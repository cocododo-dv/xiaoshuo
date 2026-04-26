from __future__ import annotations

from sqlalchemy import select

from novel_system.db.models import (
    AuthorDraft,
    ChapterGoal,
    ChapterMemory,
    ChapterState,
    FinalScene,
    HumanReviewEvent,
    SceneCard,
    SceneRunState,
)
from novel_system.services.literary_quality import analyze_literary_quality


def _seed_quality_scene(session, *, chapter_id: str = "LQ100", scene_id: str = "LQ100_SC01") -> str:
    final_row_id = f"final_scene_{scene_id}_v1"
    session.add(
        ChapterGoal(
            chapter_id=chapter_id,
            planned_scene_count=1,
            chapter_goal="A quiet meeting must turn into a costly decision.",
        )
    )
    session.add(ChapterState(chapter_id=chapter_id, current_phase="drafting"))
    session.add(
        SceneCard(
            scene_id=scene_id,
            chapter_id=chapter_id,
            scene_seq=1,
            scene_goal="A witness asks for protection and forces the lead to choose.",
            beats_json=["witness arrives", "lead chooses", "door opens"],
            exit_change="The lead has crossed a line.",
            hook="A key scrapes under the door.",
        )
    )
    session.add(
        SceneRunState(
            scene_id=scene_id,
            scene_status="archived",
            current_final_scene_row_id=final_row_id,
            current_bundle_id="bundle_quality",
            current_bundle_hash="hash_quality",
        )
    )
    session.add(
        FinalScene(
            row_id=final_row_id,
            scene_id=scene_id,
            chapter_id=chapter_id,
            content=(
                "The witness held the key. The lead had to choose the archive or the child. "
                "She opened the door before the bell stopped."
            ),
            status="approved",
            source_bundle_id="bundle_quality",
            source_bundle_hash="hash_quality",
        )
    )
    session.commit()
    return final_row_id


def _item(payload: dict, object_type: str, object_id: str) -> dict:
    return next(
        row
        for row in payload["items"]
        if row["object_type"] == object_type and row["object_id"] == object_id
    )


def test_literary_quality_overview_prefers_author_drafts_and_does_not_mutate_runtime(client, session) -> None:
    final_row_id = _seed_quality_scene(session)
    scene_draft = AuthorDraft(
        draft_id="author_draft_scene_LQ100_SC01_current",
        object_type="scene",
        object_id="LQ100_SC01",
        source_text_ref=f"final_scene:{final_row_id}",
        content=(
            '"Because you know the truth, I explain everything now," he said. '
            "She suddenly realized the moon was somehow meaningful. "
            "The moon watched the moonlit room; moon, moon. "
            "He turned, turned, turned, then turned again. "
            "In the end, everything changed forever."
        ),
        revision_no=3,
        status="current",
    )
    chapter_draft = AuthorDraft(
        draft_id="author_draft_chapter_LQ100_current",
        object_type="chapter",
        object_id="LQ100",
        source_text_ref="chapter_assembled:LQ100",
        content="Chapter author draft with a forced choice: choose the archive or save the child.",
        revision_no=1,
        status="current",
    )
    session.add_all([scene_draft, chapter_draft])
    session.commit()

    before_state = session.get(SceneRunState, "LQ100_SC01").scene_status
    response = client.get("/api/v1/literary-quality/overview")

    assert response.status_code == 200
    payload = response.json()["data"]
    scene_item = _item(payload, "scene", "LQ100_SC01")
    chapter_item = _item(payload, "chapter", "LQ100")

    assert scene_item["text_layer"] == "author_draft"
    assert scene_item["source_ref"] == f"author_draft:{scene_draft.draft_id}"
    assert chapter_item["text_layer"] == "author_draft"
    assert chapter_item["source_ref"] == f"author_draft:{chapter_draft.draft_id}"
    assert payload["summary"]["object_count"] >= 2
    assert payload["summary"]["model_voice_count"] >= 1
    assert scene_item["score"] < 0.75
    assert scene_item["signals"]["model_voice"]["risk"] is True
    assert scene_item["signals"]["image_homogeneity"]["risk"] is True
    assert scene_item["signals"]["repetitive_action"]["risk"] is True
    assert scene_item["signals"]["expository_dialogue"]["risk"] is True
    assert scene_item["signals"]["no_choice_scene"]["risk"] is True
    assert scene_item["signals"]["summary_ending"]["risk"] is True
    assert {"dimension", "severity", "issue", "evidence_excerpt", "recommendation"} <= set(scene_item["findings"][0])

    session.expire_all()
    assert session.get(FinalScene, final_row_id).content.startswith("The witness held the key.")
    assert session.get(SceneRunState, "LQ100_SC01").scene_status == before_state
    assert session.execute(select(HumanReviewEvent)).scalars().all() == []


def test_literary_quality_overview_falls_back_to_runtime_text_and_final_aggregate(client, session) -> None:
    final_row_id = _seed_quality_scene(session, chapter_id="LQ200", scene_id="LQ200_SC01")
    memory = ChapterMemory(
        row_id="chapter_memory_final_LQ200_v1",
        chapter_id="LQ200",
        aggregate_stage="final",
        content="Final aggregate: she must choose the witness and opens the locked room.",
        active_flag=1,
        runtime_eligible=1,
        runtime_eligibility_basis="direct_read",
    )
    session.add(memory)
    session.get(ChapterState, "LQ200").last_final_memory_row_id = memory.row_id
    session.commit()

    response = client.get("/api/v1/literary-quality/overview?text_layer=author_draft_preferred")

    assert response.status_code == 200
    payload = response.json()["data"]
    scene_item = _item(payload, "scene", "LQ200_SC01")
    chapter_item = _item(payload, "chapter", "LQ200")

    assert scene_item["text_layer"] == "runtime_final_scene"
    assert scene_item["source_ref"] == f"final_scene:{final_row_id}"
    assert chapter_item["text_layer"] == "chapter_memory_final"
    assert chapter_item["source_ref"] == f"chapter_memory:{memory.row_id}"

    runtime_response = client.get("/api/v1/literary-quality/overview?text_layer=runtime_final_scene&chapter_id=LQ200")
    assert runtime_response.status_code == 200
    runtime_items = runtime_response.json()["data"]["items"]
    assert [item["object_type"] for item in runtime_items] == ["scene"]
    assert runtime_items[0]["text_layer"] == "runtime_final_scene"

    memory_response = client.get("/api/v1/literary-quality/overview?text_layer=chapter_memory_final&chapter_id=LQ200")
    assert memory_response.status_code == 200
    memory_items = memory_response.json()["data"]["items"]
    assert [item["object_type"] for item in memory_items] == ["chapter"]
    assert memory_items[0]["text_layer"] == "chapter_memory_final"


def test_literary_quality_detects_template_reuse_and_protects_valid_ambiguity() -> None:
    text = (
        "她低头看着钥匙，沉默了片刻。\n"
        "他低头看着录音，沉默了片刻。\n"
        "她低头看着门缝，沉默了片刻。\n"
        "月光、阴影、冷风和雾气反复压下来，月光又落在她手上。\n"
        "她忽然意识到这一切都变得不同了。她知道真相必须公开。"
    )

    signals, findings = analyze_literary_quality(text)

    assert signals["template_action_reuse"]["risk"] is True
    assert signals["image_field_reuse"]["risk"] is True
    assert signals["syntax_monotony"]["risk"] is True
    assert signals["false_clarity"]["risk"] is True
    assert signals["valid_ambiguity"]["risk"] is False
    assert signals["valid_ambiguity"]["score"] == 1.0
    finding_dimensions = {finding["dimension"] for finding in findings}
    assert {
        "template_action_reuse",
        "image_field_reuse",
        "syntax_monotony",
        "false_clarity",
    } <= finding_dimensions


def _seed_cross_scene_template_reuse(session) -> None:
    chapter_id = "LQ300"
    session.add(
        ChapterGoal(
            chapter_id=chapter_id,
            planned_scene_count=2,
            chapter_goal="Two strong-type scenes should avoid repeating the same visible machinery.",
        )
    )
    session.add(ChapterState(chapter_id=chapter_id, current_phase="drafting"))
    for index, object_term in enumerate(("钥匙", "录音"), start=1):
        scene_id = f"{chapter_id}_SC0{index}"
        final_row_id = f"final_scene_{scene_id}_v1"
        session.add(
            SceneCard(
                scene_id=scene_id,
                chapter_id=chapter_id,
                scene_seq=index,
                scene_goal=f"林岑必须处理{object_term}带来的选择压力。",
            )
        )
        session.add(
            SceneRunState(
                scene_id=scene_id,
                scene_status="archived",
                current_final_scene_row_id=final_row_id,
            )
        )
        session.add(
            FinalScene(
                row_id=final_row_id,
                scene_id=scene_id,
                chapter_id=chapter_id,
                content=(
                    f"她低头看着{object_term}，沉默了片刻。"
                    f"他低头看着{object_term}，沉默了片刻。"
                    f"林岑低头看着{object_term}，沉默了片刻。"
                    "月光、阴影、冷风和雾气反复压下来。"
                    "她忽然意识到这一切都变得不同了。她知道真相必须公开。"
                ),
                status="approved",
                source_bundle_id=f"bundle_{scene_id}",
                source_bundle_hash=f"hash_{scene_id}",
            )
        )
    session.commit()


def test_literary_quality_overview_exposes_filters_clusters_fingerprints_and_reuse(client, session) -> None:
    _seed_cross_scene_template_reuse(session)

    response = client.get(
        "/api/v1/literary-quality/overview",
        params={
            "chapter_id": "LQ300",
            "risk_type": "template_action_reuse",
            "min_severity": "revision",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["filters"] == {
        "text_layer": "author_draft_preferred",
        "chapter_id": "LQ300",
        "risk_type": "template_action_reuse",
        "min_severity": "revision",
    }
    assert payload["items"]
    assert {item["chapter_id"] for item in payload["items"]} == {"LQ300"}
    assert all(item["signals"]["template_action_reuse"]["risk"] for item in payload["items"])
    assert all(item["recommended_next_action"]["action"] == "open_deepdesk_patch" for item in payload["items"])
    assert payload["risk_clusters"][0]["dimension"] == "template_action_reuse"
    assert payload["risk_clusters"][0]["count"] >= 2
    assert any(row["object_id"].startswith("LQ300_SC") for row in payload["fingerprints"])
    assert "action_templates" in payload["fingerprints"][0]["fingerprint"]
    assert any(row["cluster_type"] == "action_template" for row in payload["cross_scene_reuse"])
    assert payload["recommended_next_action"]["action"] == "open_deepdesk_patch"


def test_literary_quality_analyze_text_returns_quality_spine_without_database_mutation(client, session) -> None:
    _seed_quality_scene(session, chapter_id="LQ400", scene_id="LQ400_SC01")

    response = client.post(
        "/api/v1/literary-quality/analyze-text",
        json={
            "content": (
                "她低头看着钥匙，沉默了片刻。"
                "他低头看着录音，沉默了片刻。"
                "她低头看着门缝，沉默了片刻。"
                "她知道真相必须公开。"
            ),
            "object_type": "scene",
            "object_id": "scratch",
            "chapter_id": "scratch_chapter",
        },
    )

    assert response.status_code == 200
    payload = response.json()["data"]

    assert payload["object_type"] == "scene"
    assert payload["object_id"] == "scratch"
    assert payload["score"] < 0.75
    assert payload["fingerprint"]["action_templates"]
    assert payload["span_findings"]
    first_span = payload["span_findings"][0]
    assert {"dimension", "severity", "start", "end", "evidence", "recommended_action"} <= set(first_span)
    assert payload["content"][first_span["start"] : first_span["end"]] == first_span["evidence"]
    assert any(span["dimension"] == "template_action_reuse" for span in payload["span_findings"])
    assert payload["risk_clusters"][0]["count"] >= 1
    assert payload["recommended_next_action"]["action"] == "open_deepdesk_patch"

    session.expire_all()
    assert session.get(SceneRunState, "LQ400_SC01").scene_status == "archived"
