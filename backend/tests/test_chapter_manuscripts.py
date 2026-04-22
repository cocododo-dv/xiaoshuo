from __future__ import annotations

from novel_system.db.models import ChapterMemory, ChapterState, FinalScene, SceneRunState


def _create_chapter(client, chapter_id: str, *, goal: str = "Draft a chapter") -> None:
    response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": chapter_id,
            "planned_scene_count": 3,
            "chapter_goal": goal,
            "main_plot_push": f"push {chapter_id}",
            "emotional_target": f"emotion {chapter_id}",
            "ending_effect": f"ending {chapter_id}",
            "must_not": f"avoid {chapter_id}",
            "notes": f"notes {chapter_id}",
        },
        headers={"X-Idempotency-Key": f"create-{chapter_id}"},
    )
    assert response.status_code == 200


def _create_scene(
    client,
    scene_id: str,
    *,
    chapter_id: str,
    scene_seq: int,
    is_chapter_last: int = 0,
) -> None:
    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": scene_id,
            "chapter_id": chapter_id,
            "scene_seq": scene_seq,
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A"],
            "location": f"Location {scene_id}",
            "scene_goal": f"goal for {scene_id}",
            "beats_json": [f"beat {scene_id}"],
            "must_include_text": "",
            "forbidden_text": "",
            "exit_change": "",
            "hook": "",
            "target_length_band": "medium",
            "scene_type": "reunion",
            "is_chapter_last": is_chapter_last,
        },
        headers={"X-Idempotency-Key": f"create-{scene_id}"},
    )
    assert response.status_code == 200


def _finalize_scene(session, scene_id: str, chapter_id: str, content: str, *, suffix: str = "v1") -> str:
    row_id = f"final_scene_{scene_id}_{suffix}"
    final = FinalScene(
        row_id=row_id,
        scene_id=scene_id,
        chapter_id=chapter_id,
        content=content,
        status="approved",
        source_bundle_id=f"bundle_{scene_id}",
        source_bundle_hash=f"hash_{scene_id}",
    )
    state = session.get(SceneRunState, scene_id)
    assert state is not None
    state.scene_status = "archived"
    state.current_final_scene_row_id = row_id
    session.add(final)
    session.commit()
    return row_id


def _set_final_aggregate(session, chapter_id: str, content: str, *, row_id: str | None = None) -> str:
    memory_row_id = row_id or f"chapter_memory_final_{chapter_id}_v1"
    memory = ChapterMemory(
        row_id=memory_row_id,
        chapter_id=chapter_id,
        aggregate_stage="final",
        content=content,
        active_flag=1,
        runtime_eligible=1,
        runtime_eligibility_basis="direct_read",
    )
    state = session.get(ChapterState, chapter_id)
    assert state is not None
    state.last_final_memory_row_id = memory_row_id
    session.add(memory)
    session.commit()
    return memory_row_id


def test_chapter_manuscript_detail_assembles_current_final_scenes_and_marks_missing(client, session) -> None:
    _create_chapter(client, "CHM100", goal="Read the current manuscript")
    _create_scene(client, "CHM100_SC02", chapter_id="CHM100", scene_seq=2, is_chapter_last=1)
    _create_scene(client, "CHM100_SC01", chapter_id="CHM100", scene_seq=1)
    _create_scene(client, "CHM100_SC03", chapter_id="CHM100", scene_seq=3)
    _finalize_scene(session, "CHM100_SC02", "CHM100", "second scene text")
    _finalize_scene(session, "CHM100_SC01", "CHM100", "first scene text")

    response = client.get("/api/v1/chapter-manuscripts/CHM100")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["chapter"]["chapter_id"] == "CHM100"
    assert data["completion_status"] == "partial"
    assert data["comparison_status"] == "aggregate_missing"
    assert data["assembled"] == {
        "content": "first scene text\nsecond scene text",
        "char_count": len("first scene text\nsecond scene text"),
        "scene_count": 3,
        "generated_scene_count": 2,
        "missing_scene_ids": ["CHM100_SC03"],
    }
    assert data["aggregate"] is None
    assert [scene["scene_id"] for scene in data["scenes"]] == ["CHM100_SC01", "CHM100_SC02", "CHM100_SC03"]
    assert data["scenes"][0]["final_scene"] == {
        "row_id": "final_scene_CHM100_SC01_v1",
        "char_count": len("first scene text"),
        "created_at": data["scenes"][0]["final_scene"]["created_at"],
    }
    assert data["scenes"][2]["final_scene"] is None


def test_chapter_manuscript_detail_compares_aggregate_with_current_assembled_text(client, session) -> None:
    _create_chapter(client, "CHM200", goal="Compare final aggregate")
    _create_scene(client, "CHM200_SC01", chapter_id="CHM200", scene_seq=1)
    _create_scene(client, "CHM200_SC02", chapter_id="CHM200", scene_seq=2, is_chapter_last=1)
    _finalize_scene(session, "CHM200_SC01", "CHM200", "alpha")
    _finalize_scene(session, "CHM200_SC02", "CHM200", "beta")
    aggregate_row_id = _set_final_aggregate(session, "CHM200", "alpha\nbeta")

    response = client.get("/api/v1/chapter-manuscripts/CHM200")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["completion_status"] == "complete"
    assert data["comparison_status"] == "aggregate_matches_current"
    assert data["aggregate"] == {
        "row_id": aggregate_row_id,
        "content": "alpha\nbeta",
        "char_count": len("alpha\nbeta"),
        "created_at": data["aggregate"]["created_at"],
    }

    session.get(FinalScene, "final_scene_CHM200_SC02_v1").content = "beta changed"
    session.commit()
    response = client.get("/api/v1/chapter-manuscripts/CHM200")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assembled"]["content"] == "alpha\nbeta changed"
    assert data["comparison_status"] == "aggregate_differs_current"


def test_chapter_manuscript_list_reports_statuses_and_excludes_trashed_records(client, session) -> None:
    _create_chapter(client, "CHM300", goal="Visible chapter")
    _create_scene(client, "CHM300_SC01", chapter_id="CHM300", scene_seq=1)
    _create_scene(client, "CHM300_SC02", chapter_id="CHM300", scene_seq=2, is_chapter_last=1)
    _finalize_scene(session, "CHM300_SC01", "CHM300", "visible text")

    _create_chapter(client, "CHM301", goal="Trashed chapter")
    _create_scene(client, "CHM301_SC01", chapter_id="CHM301", scene_seq=1, is_chapter_last=1)
    trash_chapter = client.post(
        "/api/v1/chapters/trash",
        json={"chapter_ids": ["CHM301"]},
        headers={"X-Idempotency-Key": "trash-chm301"},
    )
    assert trash_chapter.status_code == 200

    _create_scene(client, "CHM300_SC03", chapter_id="CHM300", scene_seq=3)
    trash_scene = client.post(
        "/api/v1/scenes/trash",
        json={"scene_ids": ["CHM300_SC03"]},
        headers={"X-Idempotency-Key": "trash-chm300-sc03"},
    )
    assert trash_scene.status_code == 200

    state = session.get(ChapterState, "CHM300")
    assert state is not None
    state.chapter_backfill_pending_count = 2
    session.commit()

    response = client.get("/api/v1/chapter-manuscripts")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert [item["chapter_id"] for item in items] == ["CHM300"]
    assert items[0]["scene_count"] == 2
    assert items[0]["generated_scene_count"] == 1
    assert items[0]["missing_scene_ids"] == ["CHM300_SC02"]
    assert items[0]["completion_status"] == "partial"
    assert items[0]["comparison_status"] == "aggregate_missing"
    assert items[0]["chapter_backfill_pending_count"] == 2


def test_chapter_manuscript_empty_chapter_and_active_aggregate_fallback(client, session) -> None:
    _create_chapter(client, "CHM400", goal="No scenes yet")
    _set_final_aggregate(session, "CHM400", "legacy aggregate", row_id="chapter_memory_final_CHM400_v2")
    state = session.get(ChapterState, "CHM400")
    assert state is not None
    state.last_final_memory_row_id = None
    session.commit()

    response = client.get("/api/v1/chapter-manuscripts/CHM400")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["completion_status"] == "empty"
    assert data["comparison_status"] == "aggregate_differs_current"
    assert data["assembled"]["scene_count"] == 0
    assert data["assembled"]["content"] == ""
    assert data["aggregate"]["row_id"] == "chapter_memory_final_CHM400_v2"
