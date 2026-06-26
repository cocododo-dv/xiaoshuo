"""MaterializationService 单测(PR-4)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from novel_system.db.models import ReviewItem
from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.ingest import IngestService
from novel_system.services.style_reference.materialization import (
    MaterializationService,
    REVIEW_CALIB_PREFIX,
    REVIEW_PREFIX,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import BindingScope


SAMPLE_TEXT = """这是叙述。

他说:"行。"

我心里想着事。

记得那年。

雪飘落。
"""


def _seed_profile_with_findings(seed: str) -> str:
    """建一个完整链路 book + run + extraction + 4 类 findings + profile。"""
    with SessionLocal() as session:
        ingest = IngestService(session, llm_enabled=False)
        result = ingest.ingest_upload(
            raw_bytes=SAMPLE_TEXT.encode("utf-8"),
            file_name=f"b_{seed}.txt",
            title="t",
            author_label="a",
            cloud_policy="segments_only",
        )
        book_id = result.book.book_id
        repo = StyleReferenceRepository(session)
        run_id = f"sr_run_{seed}"
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        extraction_id = f"sr_ext_{seed}"
        repo.create_extraction(
            extraction_id=extraction_id,
            book_id=book_id,
            run_id=run_id,
            layer="language",
            sub_dimension="language.rhetoric",
            raw_payload_json={},
            status="done",
            validation_errors_json=[],
            purpose="extract",
        )
        # 4 类 findings 各 1 条
        findings_spec = [
            ("language.rhetoric", "observation", "鲁迅善用反讽"),
            ("narrative.pacing", "observation", "对话推动节奏"),
            ("language.rhetoric", "forbidden_pattern", "禁堆华丽形容词"),
            ("scene.dialogue", "observation", "对话简洁直率"),
        ]
        finding_ids = []
        for i, (sub_dim, kind, statement) in enumerate(findings_spec):
            fid = f"sr_find_{seed}_{i}"
            repo.create_finding(
                finding_id=fid,
                book_id=book_id,
                run_id=run_id,
                extraction_id=extraction_id,
                sub_dimension=sub_dim,
                finding_kind=kind,
                statement=statement,
                confidence="high",
                status="pending",
            )
            finding_ids.append(fid)
        # profile,含 calibration_guidance 2 条
        profile = repo.create_profile(
            profile_id=f"sr_profile_{seed}",
            book_id=book_id,
            run_id=run_id,
            title="t",
            status="draft",
            profile_json={
                "narrative_summary": "ns",
                "calibration_guidance": ["calib line A", "calib line B"],
            },
            coverage_json={},
            source_finding_ids_json=finding_ids,
        )
        session.commit()
        return profile.profile_id


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_apply_dispatches_findings_to_4_item_types() -> None:
    profile_id = _seed_profile_with_findings("dispatch")
    with SessionLocal() as session:
        svc = MaterializationService(session)
        result = svc.apply_profile(
            profile_id, scope=BindingScope.PROJECT, scope_ref_id="proj_x"
        )
        session.commit()

    # 期望 item_type_counts:style_rule_set 1 (language obs), narrative_pattern 2
    # (narrative.pacing obs + scene.dialogue obs), banned_rule_cluster 1 (forbid),
    # calibration_candidate 2 (2 lines)
    assert result.item_type_counts.get("style_rule_set") == 1
    assert result.item_type_counts.get("narrative_pattern") == 2
    assert result.item_type_counts.get("banned_rule_cluster") == 1
    assert result.item_type_counts.get("calibration_candidate") == 2


def test_review_id_prefix_style_ref() -> None:
    profile_id = _seed_profile_with_findings("prefix")
    with SessionLocal() as session:
        svc = MaterializationService(session)
        result = svc.apply_profile(
            profile_id, scope=BindingScope.PROJECT, scope_ref_id="proj_y"
        )
        session.commit()

    for rid in result.review_ids:
        assert rid.startswith(REVIEW_PREFIX) or rid.startswith(REVIEW_CALIB_PREFIX), (
            f"review_id {rid!r} 应以 style_ref 前缀开头"
        )


def test_apply_activates_profile_for_injection() -> None:
    """Q1 回归：apply 即把 profile 置 active。

    此前 synthesize 产 DRAFT、apply 只建 active binding 却从不激活 profile 本身，
    而注入(InjectionService / scene_execution)硬要求 profile.status=='active'，
    导致真实流程(导入→抽取→合成→应用)后风格注入恒为空(no-op)。
    """
    profile_id = _seed_profile_with_findings("activate")
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        assert repo.get_profile(profile_id).status == "draft"  # 合成态

    with SessionLocal() as session:
        svc = MaterializationService(session)
        svc.apply_profile(profile_id, scope=BindingScope.PROJECT, scope_ref_id="proj_activate")
        session.commit()

    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        assert repo.get_profile(profile_id).status == "active"  # 修复后：apply 激活 → 注入可生效


def test_apply_creates_binding_row() -> None:
    profile_id = _seed_profile_with_findings("binding")
    with SessionLocal() as session:
        svc = MaterializationService(session)
        result = svc.apply_profile(
            profile_id, scope=BindingScope.SCENE, scope_ref_id="scene_99"
        )
        session.commit()
        repo = StyleReferenceRepository(session)
        bindings = repo.list_bindings(profile_id=profile_id)

    assert result.binding_id
    assert any(b.binding_id == result.binding_id for b in bindings)
    binding = next(b for b in bindings if b.binding_id == result.binding_id)
    assert binding.scope == "scene"
    assert binding.scope_ref_id == "scene_99"
    assert binding.status == "active"


def test_apply_idempotent_same_inputs_no_extra_reviews() -> None:
    profile_id = _seed_profile_with_findings("idem")
    with SessionLocal() as session:
        svc = MaterializationService(session)
        r1 = svc.apply_profile(
            profile_id, scope=BindingScope.PROJECT, scope_ref_id="proj_z"
        )
        session.commit()
    with SessionLocal() as session:
        svc = MaterializationService(session)
        r2 = svc.apply_profile(
            profile_id, scope=BindingScope.PROJECT, scope_ref_id="proj_z"
        )
        session.commit()
    # 同 profile+scope 复用 binding,review_id 也复用(set 相等)
    assert r1.binding_id == r2.binding_id
    assert set(r1.review_ids) == set(r2.review_ids)


def test_review_items_written_with_correct_target_collection() -> None:
    """ReviewItem.target_collection(Computed 列)应路由到 4 集合命名。"""
    profile_id = _seed_profile_with_findings("target_col")
    with SessionLocal() as session:
        svc = MaterializationService(session)
        svc.apply_profile(
            profile_id, scope=BindingScope.PROJECT, scope_ref_id="proj_t"
        )
        session.commit()
    with SessionLocal() as session:
        reviews = list(
            session.execute(
                select(ReviewItem).where(ReviewItem.review_id.like(f"{REVIEW_PREFIX}%"))
            ).scalars().all()
        )
    target_collections = {r.target_collection for r in reviews}
    assert "style_rules" in target_collections
    assert "narrative_patterns" in target_collections
    assert "banned_rule_clusters" in target_collections


def test_apply_profile_not_found() -> None:
    from novel_system.services.errors import DomainError

    with SessionLocal() as session:
        svc = MaterializationService(session)
        with pytest.raises(DomainError) as exc_info:
            svc.apply_profile(
                "sr_profile_nonexistent",
                scope=BindingScope.PROJECT,
                scope_ref_id=None,
            )
        assert exc_info.value.code == "STYLE_REFERENCE_PROFILE_NOT_FOUND"
