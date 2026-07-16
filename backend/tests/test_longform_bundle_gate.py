from __future__ import annotations

import json

import pytest

from novel_system.contracts.bundle import BundleSnapshotHashProjection
from novel_system.db.models import (
    AttemptTracker,
    ChapterContract,
    ChapterGoal,
    FinalScene,
    LongformAnchor,
    SceneBundle,
    SceneCard,
    SceneRunState,
    StoryProject,
)
from novel_system.services.archiver import Archiver
from novel_system.services.bundle_builder import BundleBuilder
from novel_system.services.context_budget import collect_prompt_sections
from novel_system.services.errors import DomainError
from novel_system.services.final_text_gate import FinalTextGateService
from novel_system.services.hash_engine import compute_bundle_hash_projection
from novel_system.services.longform_tower import LongformTowerService


def _seed_longform_scene(session):
    project = StoryProject(
        project_id="longform_bundle_project",
        title="长篇冻结测试",
        outline_text="一场雨中的交接。",
        planning_mode="snowflake",
    )
    chapter = ChapterGoal(
        chapter_id="longform_bundle_chapter",
        project_id=project.project_id,
        chapter_goal="完成交接",
        display_order=1,
    )
    scene = SceneCard(
        scene_id="longform_bundle_scene",
        chapter_id=chapter.chapter_id,
        project_id=project.project_id,
        scene_seq=1,
        scene_goal="主角带着证据离开",
    )
    pinned = LongformAnchor(
        anchor_id="anchor_pinned",
        project_id=project.project_id,
        kind="fact",
        text="证据装在蓝色信封里",
        source_ref="bible:fact:7",
        status="pinned",
    )
    referenced_faded = LongformAnchor(
        anchor_id="anchor_referenced_faded",
        project_id=project.project_id,
        kind="timeline",
        text="这一天持续下雨",
        source_ref="timeline:day:3",
        status="faded",
    )
    unreferenced_faded = LongformAnchor(
        anchor_id="anchor_unreferenced_faded",
        project_id=project.project_id,
        kind="fact",
        text="不应进入运行时的旧锚点",
        status="faded",
    )
    unreferenced_story_thread = LongformAnchor(
        anchor_id="anchor_unreferenced_thread",
        project_id=project.project_id,
        kind="thread",
        text="未由本章契约选择的远期故事线",
        status="pinned",
    )
    contract = ChapterContract(
        contract_id="contract_dispatched",
        project_id=project.project_id,
        chapter_id=chapter.chapter_id,
        status="dispatched",
        dispatched_at="2026-07-16T00:00:00+00:00",
        constraints_json=[
            {
                "constraint_id": "must_carry_umbrella",
                "text": "本场必须出现雨伞",
                "anchor_id": referenced_faded.anchor_id,
                "scene_id": scene.scene_id,
                "kind": "required_text",
                "enforcement": "blocking",
                "check_terms": ["雨伞"],
                "match_mode": "all",
                "waived": False,
                "waiver_reason": None,
            },
            {
                "constraint_id": "waived_bell",
                "text": "原计划出现钟声",
                "anchor_id": None,
                "scene_id": scene.scene_id,
                "kind": "required_text",
                "enforcement": "blocking",
                "check_terms": ["钟声"],
                "match_mode": "any",
                "waived": True,
                "waiver_reason": "作者改为无声交接",
                "waiver_actor_ref": "author:seed",
                "waived_at": "2026-07-16T00:01:00+00:00",
            },
            {
                "constraint_id": "human_only_subtext",
                "text": "交接必须保留怀疑的潜台词",
                "anchor_id": pinned.anchor_id,
                "scene_id": scene.scene_id,
                "kind": "constraint",
                "enforcement": "advisory",
                "check_terms": [],
                "match_mode": "any",
                "waived": False,
                "waiver_reason": None,
            },
        ],
    )
    session.add_all(
        [
            project,
            chapter,
            scene,
            SceneRunState(scene_id=scene.scene_id),
            pinned,
            referenced_faded,
            unreferenced_faded,
            unreferenced_story_thread,
            contract,
        ]
    )
    session.flush()
    return scene, pinned, contract


def test_bundle_freezes_dispatched_contract_and_anchor_provenance(session):
    scene, pinned, contract = _seed_longform_scene(session)

    first = BundleBuilder(session).build(scene.scene_id)
    snapshot = first["snapshot"]
    anchor_payload = json.loads(snapshot["inline_digests"]["longform_anchors"])
    contract_payload = json.loads(snapshot["inline_digests"]["chapter_contract"])

    assert {item["anchor_id"] for item in anchor_payload} == {
        "anchor_pinned",
        "anchor_referenced_faded",
    }
    assert contract_payload["contract_id"] == contract.contract_id
    assert contract_payload["status"] == "dispatched"
    assert snapshot["source_version_refs"]["chapter_contract_id"] == contract.contract_id
    assert snapshot["source_version_refs"]["longform_anchor_ids"] == [
        "anchor_pinned",
        "anchor_referenced_faded",
    ]
    assert {section.name for section in collect_prompt_sections(snapshot)} >= {
        "longform_anchors",
        "chapter_contract",
    }

    frozen_anchor_text = anchor_payload[0]["text"]
    pinned.text = "数据库中的锚点后来被修改"
    contract.constraints_json = [
        {**contract.constraints_json[0], "check_terms": ["雨衣"]}
    ]
    session.flush()

    # The persisted first bundle remains an immutable audit snapshot.
    assert json.loads(snapshot["inline_digests"]["longform_anchors"])[0]["text"] == frozen_anchor_text
    second = BundleBuilder(session).build(scene.scene_id, force_rebuild=True)
    assert second["bundle_snapshot_hash"] != first["bundle_snapshot_hash"]


def test_contract_waiver_records_actor_reason_and_time(session):
    scene, _pinned, contract = _seed_longform_scene(session)
    contract.status = "drafting"
    session.flush()

    updated = LongformTowerService(session).update_constraints(
        scene.project_id,
        scene.chapter_id,
        {
            "constraints": [
                {
                    "text": "原计划出现钟声",
                    "kind": "required_text",
                    "enforcement": "blocking",
                    "check_terms": ["钟声"],
                    "waived": True,
                    "waiver_reason": "作者改为无声交接",
                }
            ]
        },
        actor_ref="author:test",
    )

    waiver = updated["constraints"][0]
    assert waiver["waived"] is True
    assert waiver["waiver_reason"] == "作者改为无声交接"
    assert waiver["waiver_actor_ref"] == "author:test"
    assert waiver["waived_at"]

    unchanged = LongformTowerService(session).update_constraints(
        scene.project_id,
        scene.chapter_id,
        {"constraints": [waiver]},
        actor_ref="editor:later-save",
    )["constraints"][0]
    assert unchanged["waiver_actor_ref"] == "author:test"
    assert unchanged["waived_at"] == waiver["waived_at"]


def test_contract_rejects_duplicate_constraint_ids(session):
    scene, _pinned, contract = _seed_longform_scene(session)
    contract.status = "drafting"
    session.flush()

    with pytest.raises(DomainError) as exc_info:
        LongformTowerService(session).update_constraints(
            scene.project_id,
            scene.chapter_id,
            {
                "constraints": [
                    {"constraint_id": "duplicate", "text": "第一条"},
                    {"constraint_id": "duplicate", "text": "第二条"},
                ]
            },
            actor_ref="author:test",
        )

    assert exc_info.value.code == "TOWER_CONTRACT_CONSTRAINT_ID_DUPLICATE"


def test_bundle_fails_closed_when_dispatched_contract_anchor_is_missing(session):
    scene, _pinned, contract = _seed_longform_scene(session)
    contract.constraints_json = [
        {
            "constraint_id": "missing_anchor_constraint",
            "text": "必须遵守已删除的锚点",
            "anchor_id": "anchor_does_not_exist",
            "enforcement": "blocking",
            "check_terms": ["证据"],
        }
    ]
    session.flush()

    with pytest.raises(DomainError) as exc_info:
        BundleBuilder(session).build(scene.scene_id)

    assert exc_info.value.code == "BUNDLE_SOURCE_MISSING"
    assert exc_info.value.details["missing_anchor_ids"] == ["anchor_does_not_exist"]


def test_final_gate_tracks_contract_hits_waivers_and_human_verification(session):
    scene, _pinned, _contract = _seed_longform_scene(session)
    bundle = BundleBuilder(session).build(scene.scene_id)
    gate = FinalTextGateService(session)

    missing = gate.evaluate(
        scene_id=scene.scene_id,
        content="她把蓝色信封递过去，转身走进雨里。",
        source_bundle_id=bundle["bundle_id"],
    )
    assert missing["safe_to_archive"] is False
    assert "longform_contract:must_carry_umbrella:missing" in missing["archive_blockers"]
    assert [item["constraint_ref"] for item in missing["longform_contract"]["waivers"]] == [
        "waived_bell"
    ]
    assert any(
        item["constraint_ref"] == "human_only_subtext"
        for item in missing["longform_contract"]["unresolved"]
    )
    with pytest.raises(DomainError) as exc_info:
        gate.raise_if_not_archivable(missing, scene_id=scene.scene_id)
    assert exc_info.value.code == "FINAL_TEXT_LONGFORM_CONTRACT_BLOCKED"

    satisfied = gate.evaluate(
        scene_id=scene.scene_id,
        content="她收起雨伞，把蓝色信封递过去，等对方先移开视线。",
        source_bundle_id=bundle["bundle_id"],
    )
    assert satisfied["safe_to_archive"] is True
    assert [item["constraint_ref"] for item in satisfied["longform_contract"]["key_hits"]] == [
        "must_carry_umbrella"
    ]
    assert satisfied["longform_contract"]["provenance"]["source_bundle_id"] == bundle["bundle_id"]


def test_final_gate_rejects_unaudited_contract_waiver(session):
    scene, _pinned, contract = _seed_longform_scene(session)
    contract.constraints_json = [
        (
            {**item, "waiver_actor_ref": None, "waived_at": None}
            if item.get("constraint_id") == "waived_bell"
            else item
        )
        for item in contract.constraints_json
    ]
    session.flush()
    bundle = BundleBuilder(session).build(scene.scene_id)

    result = FinalTextGateService(session).evaluate(
        scene_id=scene.scene_id,
        content="她撑着雨伞，把蓝色信封递了过去。",
        source_bundle_id=bundle["bundle_id"],
    )

    assert result["safe_to_archive"] is False
    assert "longform_contract:waived_bell:waiver_invalid" in result[
        "archive_blockers"
    ]
    assert result["longform_contract"]["waivers"] == []


def test_final_gate_fails_closed_when_frozen_contract_hash_changes(session):
    scene, _pinned, _contract = _seed_longform_scene(session)
    bundle = BundleBuilder(session).build(scene.scene_id)
    stored = session.get(SceneBundle, bundle["bundle_id"])
    snapshot = dict(stored.frozen_snapshot_json)
    inline = dict(snapshot["inline_digests"])
    inline["chapter_contract"] = "{not-json"
    snapshot["inline_digests"] = inline
    stored.frozen_snapshot_json = snapshot
    session.flush()

    result = FinalTextGateService(session).evaluate(
        scene_id=scene.scene_id,
        content="她撑着雨伞，把蓝色信封递了过去。",
        source_bundle_id=bundle["bundle_id"],
    )

    assert result["safe_to_archive"] is False
    assert "bundle_integrity:bundle_hash_mismatch" in result["archive_blockers"]
    assert "longform_contract:bundle_hash_mismatch" in result["archive_blockers"]


def test_archive_rejects_tampered_bundle_without_longform_contract(session):
    scene, _pinned, contract = _seed_longform_scene(session)
    session.delete(contract)
    session.flush()
    bundle = BundleBuilder(session).build(
        scene.scene_id,
        author_note="保持第一版作者指令。",
    )
    stored = session.get(SceneBundle, bundle["bundle_id"])
    snapshot = dict(stored.frozen_snapshot_json)
    inline = dict(snapshot["inline_digests"])
    assert "chapter_contract" not in inline
    inline["author_instruction"] = "持久层篡改后的作者指令。"
    snapshot["inline_digests"] = inline
    stored.frozen_snapshot_json = snapshot
    final = FinalScene(
        row_id="final_tampered_bundle_without_contract",
        scene_id=scene.scene_id,
        chapter_id=scene.chapter_id,
        content="她在门边停下，把信封收回口袋。",
        status="near_final_ready",
        source_bundle_id=bundle["bundle_id"],
        source_bundle_hash=bundle["bundle_snapshot_hash"],
        source_kind="author_draft",
        created_by="author",
    )
    session.add(final)
    session.flush()

    with pytest.raises(DomainError) as blocked:
        Archiver(session).archive_final_scene(scene.scene_id, final.row_id)

    assert blocked.value.code == "FINAL_TEXT_BUNDLE_INTEGRITY_FAILED"
    gate = blocked.value.details["final_text_gate"]
    assert gate["bundle_integrity"]["error_code"] == "bundle_hash_mismatch"
    assert "bundle_integrity:bundle_hash_mismatch" in gate["archive_blockers"]
    assert gate["longform_contract"]["available"] is False


def test_final_gate_fails_closed_on_internally_hashed_malformed_contract(session):
    scene, _pinned, _contract = _seed_longform_scene(session)
    bundle = BundleBuilder(session).build(scene.scene_id)
    stored = session.get(SceneBundle, bundle["bundle_id"])
    snapshot = dict(stored.frozen_snapshot_json)
    inline = dict(snapshot["inline_digests"])
    inline["chapter_contract"] = "{not-json"
    snapshot["inline_digests"] = inline
    stored.frozen_snapshot_json = snapshot
    stored.bundle_snapshot_hash = compute_bundle_hash_projection(
        BundleSnapshotHashProjection(
            contract_version=snapshot["contract_version"],
            stage_allowlist_name=snapshot["stage_allowlist_name"],
            source_version_refs=snapshot["source_version_refs"],
            resolved_ref_ids=snapshot["resolved_ref_ids"],
            ordered_injections=snapshot["ordered_injections"],
            inline_digests=snapshot["inline_digests"],
        )
    )
    session.flush()

    result = FinalTextGateService(session).evaluate(
        scene_id=scene.scene_id,
        content="她撑着雨伞，把蓝色信封递了过去。",
        source_bundle_id=bundle["bundle_id"],
    )

    assert result["safe_to_archive"] is False
    assert "longform_contract:validation_unavailable" in result["archive_blockers"]


def test_finality_fields_separate_archive_safety_warning_and_author_confirmation(session):
    scene, _pinned, _contract = _seed_longform_scene(session)
    bundle = BundleBuilder(session).build(scene.scene_id)
    content = "她收起雨伞。她看着门。她看着灯。她看着空椅子。最后，一切都变得不同了。"
    gate = FinalTextGateService(session)

    automatic = gate.evaluate(
        scene_id=scene.scene_id,
        content=content,
        source_bundle_id=bundle["bundle_id"],
    )
    confirmed = gate.evaluate(
        scene_id=scene.scene_id,
        content=content,
        source_bundle_id=bundle["bundle_id"],
        author_confirmed_final=True,
    )

    assert automatic["safe_to_archive"] is True
    assert automatic["author_confirmed_final"] is False
    assert automatic["literary_warnings_unresolved"] is True
    assert confirmed["safe_to_archive"] is True
    assert confirmed["author_confirmed_final"] is True
    assert confirmed["literary_warnings_unresolved"] is False
    assert confirmed["archivable"] == confirmed["safe_to_archive"]


def test_author_confirmation_is_persisted_in_archive_gate_audit(session):
    scene, _pinned, _contract = _seed_longform_scene(session)
    bundle = BundleBuilder(session).build(scene.scene_id)
    final = FinalScene(
        row_id="final_author_confirmed",
        scene_id=scene.scene_id,
        chapter_id=scene.chapter_id,
        content="她收起雨伞，把蓝色信封递过去，等对方先移开视线。",
        status="near_final_ready",
        source_bundle_id=bundle["bundle_id"],
        source_bundle_hash=bundle["bundle_snapshot_hash"],
        source_kind="author_draft",
        created_by="author",
    )
    session.add(final)
    session.flush()

    automatic = Archiver(session).archive_final_scene(
        scene.scene_id,
        final.row_id,
    )
    assert automatic["author_confirmed_final"] is False

    archived = Archiver(session).archive_final_scene(
        scene.scene_id,
        final.row_id,
        author_confirmed_final=True,
    )

    assert archived["safe_to_archive"] is True
    assert archived["author_confirmed_final"] is True
    assert archived["literary_warnings_unresolved"] is False
    attempt = session.get(AttemptTracker, archived["archive_attempt_id"])
    audit = attempt.details_json["final_text_gate"]
    assert audit["safe_to_archive"] is True
    assert audit["author_confirmed_final"] is True
    assert audit["literary_warnings_unresolved"] is False
    assert audit["longform_contract"]["contract_id"] == "contract_dispatched"
    assert [
        item["constraint_ref"]
        for item in audit["longform_contract"]["key_hits"]
    ] == ["must_carry_umbrella"]
    assert [
        item["constraint_ref"]
        for item in audit["longform_contract"]["waivers"]
    ] == ["waived_bell"]
    assert audit["longform_contract"]["provenance"]["source_bundle_id"] == bundle[
        "bundle_id"
    ]
    assert audit["longform_contract"]["bundle_integrity"]["valid"] is True
    attempts = session.query(AttemptTracker).filter(
        AttemptTracker.scene_id == scene.scene_id,
        AttemptTracker.step == "archive",
    ).all()
    assert len(attempts) == 2
