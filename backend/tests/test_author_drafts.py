from __future__ import annotations

from novel_system.db.models import AuthorDraft, AuthorDraftEvent, ChapterMemory, ChapterState, FinalScene, SceneRunState


def _create_chapter(client, chapter_id: str, *, planned_scene_count: int = 2) -> None:
    response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": chapter_id,
            "planned_scene_count": planned_scene_count,
            "chapter_goal": f"目标 {chapter_id}",
            "main_plot_push": "推进主线",
            "emotional_target": "情绪转折",
            "ending_effect": "留下余味",
        },
        headers={"X-Idempotency-Key": f"author-draft-chapter-{chapter_id}"},
    )
    assert response.status_code == 200


def _create_scene(client, scene_id: str, *, chapter_id: str, scene_seq: int, is_chapter_last: int = 0) -> None:
    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": scene_id,
            "chapter_id": chapter_id,
            "scene_seq": scene_seq,
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A"],
            "location": "档案室",
            "scene_goal": f"场景目标 {scene_id}",
            "beats_json": ["发现", "选择"],
            "exit_change": "关系改变",
            "hook": "尾钩",
            "target_length_band": "medium",
            "scene_type": "reunion",
            "is_chapter_last": is_chapter_last,
        },
        headers={"X-Idempotency-Key": f"author-draft-scene-{scene_id}"},
    )
    assert response.status_code == 200


def _finalize_scene(session, scene_id: str, chapter_id: str, content: str, *, suffix: str = "v1") -> str:
    row_id = f"final_scene_{scene_id}_{suffix}"
    state = session.get(SceneRunState, scene_id)
    assert state is not None
    state.scene_status = "archived"
    state.current_final_scene_row_id = row_id
    session.add(
        FinalScene(
            row_id=row_id,
            scene_id=scene_id,
            chapter_id=chapter_id,
            content=content,
            status="approved",
            source_bundle_id=f"bundle_{scene_id}",
            source_bundle_hash=f"hash_{scene_id}",
        )
    )
    session.commit()
    return row_id


def _set_final_aggregate(session, chapter_id: str, content: str) -> str:
    row_id = f"chapter_memory_final_{chapter_id}_v1"
    state = session.get(ChapterMemory, row_id)
    assert state is None
    session.add(
        ChapterMemory(
            row_id=row_id,
            chapter_id=chapter_id,
            aggregate_stage="final",
            content=content,
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="direct_read",
        )
    )
    chapter_state = session.get(ChapterState, chapter_id)
    assert chapter_state is not None
    chapter_state.last_final_memory_row_id = row_id
    session.commit()
    return row_id


def test_ensure_and_save_chapter_and_scene_author_drafts_without_overwriting_runtime_outputs(client, session) -> None:
    _create_chapter(client, "AD100")
    _create_scene(client, "AD100_SC01", chapter_id="AD100", scene_seq=1)
    _create_scene(client, "AD100_SC02", chapter_id="AD100", scene_seq=2, is_chapter_last=1)
    final_row_id = _finalize_scene(session, "AD100_SC01", "AD100", "场景运行终稿。")
    aggregate_row_id = _set_final_aggregate(session, "AD100", "章节最终聚合稿。")

    chapter_response = client.post("/api/v1/author-drafts/chapter/AD100/ensure")
    scene_response = client.post("/api/v1/author-drafts/scene/AD100_SC01/ensure")

    assert chapter_response.status_code == 200
    assert scene_response.status_code == 200
    chapter_draft = chapter_response.json()["data"]["draft"]
    scene_draft = scene_response.json()["data"]["draft"]
    assert chapter_draft["content"] == "章节最终聚合稿。"
    assert chapter_draft["source_text_ref"] == f"chapter_memory:{aggregate_row_id}"
    assert scene_draft["content"] == "场景运行终稿。"
    assert scene_draft["source_text_ref"] == f"final_scene:{final_row_id}"

    save_response = client.patch(
        f"/api/v1/author-drafts/{chapter_draft['draft_id']}",
        json={"content": "作者手工改过的章节稿。", "base_revision_no": 1},
    )

    assert save_response.status_code == 200
    saved = save_response.json()["data"]["draft"]
    assert saved["content"] == "作者手工改过的章节稿。"
    assert saved["revision_no"] == 2

    session.expire_all()
    assert session.get(ChapterMemory, aggregate_row_id).content == "章节最终聚合稿。"
    assert session.get(FinalScene, final_row_id).content == "场景运行终稿。"
    assert session.query(AuthorDraft).filter_by(object_type="chapter", object_id="AD100").count() == 1
    assert {row.event_type for row in session.query(AuthorDraftEvent).all()} >= {"created", "edited"}


def test_author_draft_save_uses_optimistic_locking(client, session) -> None:
    _create_chapter(client, "AD200", planned_scene_count=1)
    _create_scene(client, "AD200_SC01", chapter_id="AD200", scene_seq=1, is_chapter_last=1)
    _finalize_scene(session, "AD200_SC01", "AD200", "第一版。")
    draft = client.post("/api/v1/author-drafts/chapter/AD200/ensure").json()["data"]["draft"]

    first_save = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={"content": "第二版。", "base_revision_no": 1},
    )
    stale_save = client.patch(
        f"/api/v1/author-drafts/{draft['draft_id']}",
        json={"content": "过期保存。", "base_revision_no": 1},
    )

    assert first_save.status_code == 200
    assert stale_save.status_code == 409
    assert stale_save.json()["error"]["code"] == "AUTHOR_DRAFT_CONFLICT"
    assert stale_save.json()["error"]["details"]["current_revision_no"] == 2


def test_chapter_author_draft_falls_back_to_assembled_scene_text_when_no_aggregate_exists(client, session) -> None:
    _create_chapter(client, "AD300")
    _create_scene(client, "AD300_SC02", chapter_id="AD300", scene_seq=2, is_chapter_last=1)
    _create_scene(client, "AD300_SC01", chapter_id="AD300", scene_seq=1)
    _finalize_scene(session, "AD300_SC02", "AD300", "第二场。")
    _finalize_scene(session, "AD300_SC01", "AD300", "第一场。")

    response = client.post("/api/v1/author-drafts/chapter/AD300/ensure")

    assert response.status_code == 200
    draft = response.json()["data"]["draft"]
    assert draft["source_text_ref"] == "chapter_assembled:AD300"
    assert draft["content"] == "第一场。\n第二场。"


def test_candidate_event_records_without_mutating_author_draft_content(client, session) -> None:
    _create_chapter(client, "AD400", planned_scene_count=1)
    _create_scene(client, "AD400_SC01", chapter_id="AD400", scene_seq=1, is_chapter_last=1)
    _finalize_scene(session, "AD400_SC01", "AD400", "原始作者稿。")
    draft = client.post("/api/v1/author-drafts/scene/AD400_SC01/ensure").json()["data"]["draft"]

    event_response = client.post(
        f"/api/v1/author-drafts/{draft['draft_id']}/candidate-events",
        json={
            "event_type": "candidate_inserted",
            "patch_id": "patch_AD400",
            "option_id": "option_sharper",
            "note": "只记录放入稿件动作，保存由 PATCH 完成。",
        },
    )

    assert event_response.status_code == 200
    event = event_response.json()["data"]["event"]
    assert event["event_type"] == "candidate_inserted"
    assert event["patch_id"] == "patch_AD400"
    current = client.get("/api/v1/author-drafts/scene/AD400_SC01/current").json()["data"]["draft"]
    assert current["content"] == "原始作者稿。"
