from __future__ import annotations

from fastapi.testclient import TestClient

from novel_system.db.models import (
    AuthorPreferenceProfile,
    ChapterGoal,
    FinalScene,
    PassagePatchCandidate,
    SceneCard,
    SceneRunState,
    WriterEvaluation,
)
from novel_system.services.writer_deep_review import LITERARY_REVISION_RUBRIC_ID


CHAPTER_ID = "DEEP_CH01"
SCENE_ID = "DEEP_CH01_SC01"
FINAL_ROW_ID = "final_DEEP_CH01_SC01"


def _seed_finished_scene(session) -> None:
    session.add(
        ChapterGoal(
            chapter_id=CHAPTER_ID,
            planned_scene_count=1,
            chapter_goal="林岑必须决定是否公开导师留下的失踪案证据。",
            main_plot_push="把旧档案线推进到公开真相的选择。",
            emotional_target="从职业克制转向道德压力。",
            ending_effect="读者知道她已经不能只做修复师。",
            writer_brief_json={
                "chapter_promise": "真相和保护幸存者不能同时满足。",
                "relationship_delta": "林岑开始不再完全信任许望的判断。",
                "ending_question": "她会把证据交给谁？",
            },
        )
    )
    session.add(
        SceneCard(
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            scene_seq=1,
            scene_goal="林岑发现关键录音，但必须决定公开还是隐藏。",
            beats_json=["修复录音", "听见幸存者编号", "决定暂缓公开"],
            exit_change="她把一半证据藏起来，准备独自核查。",
            hook="录音最后出现她自己的心跳声。",
            writer_brief_json={
                "character_desire": "确认导师留下的证据是否真实。",
                "choice_under_pressure": "公开证据或先保护幸存者。",
                "power_shift": "林岑从被动修复者变成证据持有人。",
                "reader_aftertaste": "她越冷静，越像在越界。",
            },
        )
    )
    session.add(
        SceneRunState(
            scene_id=SCENE_ID,
            scene_status="archived",
            current_final_scene_row_id=FINAL_ROW_ID,
            current_bundle_id="bundle_deep",
            current_bundle_hash="hash_deep",
        )
    )
    session.add(
        FinalScene(
            row_id=FINAL_ROW_ID,
            scene_id=SCENE_ID,
            chapter_id=CHAPTER_ID,
            content=(
                "林岑的手指在潮湿的档案盒边缘停顿。盐霜泛着幽蓝的冷光。"
                "她低声说证据还不能公开，然后又解释这是为了保护所有人。"
                "许望没有回答，录音里传来三声钟响。林岑的手指再次停顿。"
            ),
            status="approved",
            source_bundle_id="bundle_deep",
            source_bundle_hash="hash_deep",
        )
    )
    session.commit()


def test_scene_deep_review_creates_strict_literary_evaluation_and_theme_lens(client: TestClient, session) -> None:
    _seed_finished_scene(session)

    response = client.post(f"/api/v1/scenes/{SCENE_ID}/deep-review")

    assert response.status_code == 200
    payload = response.json()["data"]
    evaluation = payload["latest_evaluation"]

    assert payload["rubric_id"] == LITERARY_REVISION_RUBRIC_ID
    assert evaluation["rubric_id"] == LITERARY_REVISION_RUBRIC_ID
    assert evaluation["overall_score"] <= 0.85
    assert {"blocking", "revision", "taste"}.issubset({item["severity"] for item in evaluation["findings"]})
    assert "theme" in {item["lens"] for item in payload["lens_evaluations"]}
    assert any(item["dimension"] == "repetitive_expression" for item in evaluation["findings"])
    assert any(item["classification"] == "revision" for item in evaluation["revision_brief"])

    session.expire_all()
    aggregate_rows = session.query(WriterEvaluation).filter_by(
        object_type="scene",
        object_id=SCENE_ID,
        rubric_id=LITERARY_REVISION_RUBRIC_ID,
        parent_evaluation_id=None,
    ).all()
    assert len(aggregate_rows) == 1


def test_passage_patch_candidate_accepts_without_overwriting_final_and_records_preference(client: TestClient, session) -> None:
    _seed_finished_scene(session)
    original_final = session.get(FinalScene, FINAL_ROW_ID).content

    create_response = client.post(
        "/api/v1/passages/patch-candidates",
        json={
            "object_type": "scene",
            "object_id": SCENE_ID,
            "chapter_id": CHAPTER_ID,
            "scene_id": SCENE_ID,
            "target_text_ref": f"final_scene:{FINAL_ROW_ID}",
            "source_excerpt": "她低声说证据还不能公开，然后又解释这是为了保护所有人。",
            "issue_dimension": "dialogue_subtext",
        },
    )

    assert create_response.status_code == 200
    candidate = create_response.json()["data"]["candidate"]
    assert candidate["status"] == "candidate"
    assert candidate["manual_only"] is True
    assert len(candidate["replacement_options"]) == 3
    assert {option["tone"] for option in candidate["replacement_options"]} == {"shorter", "sharper", "subtler"}

    accept_response = client.post(
        f"/api/v1/passage-patch-candidates/{candidate['patch_id']}/accept",
        json={"selected_option_id": candidate["replacement_options"][1]["option_id"], "note": "更有刺。"},
    )

    assert accept_response.status_code == 200
    accepted = accept_response.json()["data"]["candidate"]
    assert accepted["status"] == "accepted"
    assert accepted["author_decision"] == "accepted"

    session.expire_all()
    assert session.get(FinalScene, FINAL_ROW_ID).content == original_final
    row = session.get(PassagePatchCandidate, candidate["patch_id"])
    assert row.selected_option_id == candidate["replacement_options"][1]["option_id"]

    profile_response = client.get("/api/v1/author-preference-profile")
    assert profile_response.status_code == 200
    profile = profile_response.json()["data"]["profile"]
    assert profile["status"] == "draft"
    assert profile["runtime_eligible"] is False
    assert "更锋利" in " ".join(profile["summary"]["preferred_revision_moves"])

    session.expire_all()
    db_profile = session.get(AuthorPreferenceProfile, profile["profile_id"])
    assert db_profile.status == "draft"


def test_rejecting_passage_patch_updates_candidate_but_keeps_preference_unpublished(client: TestClient, session) -> None:
    _seed_finished_scene(session)

    candidate = client.post(
        "/api/v1/passages/patch-candidates",
        json={
            "object_type": "scene",
            "object_id": SCENE_ID,
            "chapter_id": CHAPTER_ID,
            "scene_id": SCENE_ID,
            "target_text_ref": f"final_scene:{FINAL_ROW_ID}",
            "source_excerpt": "林岑的手指再次停顿。",
            "issue_dimension": "repetitive_expression",
        },
    ).json()["data"]["candidate"]

    reject_response = client.post(
        f"/api/v1/passage-patch-candidates/{candidate['patch_id']}/reject",
        json={"note": "这处重复保留为人物习惯。"},
    )

    assert reject_response.status_code == 200
    rejected = reject_response.json()["data"]["candidate"]
    assert rejected["status"] == "rejected"
    assert rejected["author_decision"] == "rejected"

    profile = client.get("/api/v1/author-preference-profile").json()["data"]["profile"]
    assert profile["runtime_eligible"] is False
    assert any("保留" in item for item in profile["summary"]["rejected_revision_moves"])
