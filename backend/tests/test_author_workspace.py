from __future__ import annotations

from sqlalchemy import select

from novel_system.db.models import ChapterState, SceneCard, SceneRunState

EMPTY_CHAPTER_WRITER_BRIEF = {
    "schema_version": "writer_brief_v2",
    "core_promise": "",
    "plot_movement": "",
    "character_shift": "",
    "chapter_question": "",
    "ending_aftertaste": "",
    "chapter_promise": "",
    "escalation_path": "",
    "relationship_delta": "",
    "reveal_or_reversal": "",
    "payoff_target": "",
    "ending_question": "",
}

EMPTY_SCENE_WRITER_BRIEF = {
    "schema_version": "writer_brief_v2",
    "character_desire": "",
    "obstacle": "",
    "stakes": "",
    "secret_or_misunderstanding": "",
    "subtext": "",
    "irreversible_change": "",
    "reader_question": "",
    "choice_under_pressure": "",
    "power_shift": "",
    "new_information": "",
    "emotional_turn": "",
    "image_anchor": "",
    "reader_aftertaste": "",
}


def _create_chapter(client, chapter_id: str, *, goal: str = "Author a chapter") -> None:
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
    scene_seq: int | None = None,
    is_chapter_last: int = 0,
    location: str = "Archive room",
) -> None:
    payload = {
        "scene_id": scene_id,
        "chapter_id": chapter_id,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_B"],
        "location": location,
        "scene_goal": f"goal for {scene_id}",
        "beats_json": [f"beat-{scene_id}-1", f"beat-{scene_id}-2"],
        "must_include_text": f"must include {scene_id}",
        "forbidden_text": f"forbidden {scene_id}",
        "exit_change": f"exit {scene_id}",
        "hook": f"hook {scene_id}",
        "target_length_band": "medium",
        "scene_type": "reunion",
        "is_chapter_last": is_chapter_last,
    }
    if scene_seq is not None:
        payload["scene_seq"] = scene_seq
    response = client.post(
        "/api/v1/scenes",
        json=payload,
        headers={"X-Idempotency-Key": f"create-{scene_id}"},
    )
    assert response.status_code == 200


def test_chapter_list_and_author_workspace_include_author_and_runtime_state(client, session) -> None:
    _create_chapter(client, "CH100", goal="Close the archive loop")
    _create_chapter(client, "CH200", goal="Open the next conflict")
    _create_scene(client, "CH100_SC01", chapter_id="CH100", scene_seq=1)
    _create_scene(client, "CH100_SC02", chapter_id="CH100", scene_seq=2, is_chapter_last=1)
    _create_scene(client, "CH200_SC01", chapter_id="CH200", scene_seq=1, is_chapter_last=1)

    chapter_state = session.get(ChapterState, "CH100")
    assert chapter_state is not None
    chapter_state.current_phase = "drafting"
    chapter_state.chapter_passed_scene_count = 1
    chapter_state.chapter_backfill_pending_count = 2

    scene_state = session.get(SceneRunState, "CH100_SC02")
    assert scene_state is not None
    scene_state.scene_status = "archived"
    scene_state.current_bundle_id = "bundle_ch100_sc02"
    scene_state.current_final_scene_row_id = "final_scene_ch100_sc02"
    session.commit()

    chapters_response = client.get("/api/v1/chapters")

    assert chapters_response.status_code == 200
    assert chapters_response.json()["data"]["items"] == [
        {
            "chapter_id": "CH100",
            "planned_scene_count": 3,
            "chapter_goal": "Close the archive loop",
            "main_plot_push": "push CH100",
            "emotional_target": "emotion CH100",
            "ending_effect": "ending CH100",
            "must_not": "avoid CH100",
            "notes": "notes CH100",
            "current_phase": "drafting",
            "chapter_passed_scene_count": 1,
            "chapter_backfill_pending_count": 2,
            "active_scene_count": 2,
            "trashed_scene_count": 0,
            "trash_allowed": 1,
            "trash_block_reason": None,
        },
        {
            "chapter_id": "CH200",
            "planned_scene_count": 3,
            "chapter_goal": "Open the next conflict",
            "main_plot_push": "push CH200",
            "emotional_target": "emotion CH200",
            "ending_effect": "ending CH200",
            "must_not": "avoid CH200",
            "notes": "notes CH200",
            "current_phase": "drafting",
            "chapter_passed_scene_count": 0,
            "chapter_backfill_pending_count": 0,
            "active_scene_count": 1,
            "trashed_scene_count": 0,
            "trash_allowed": 1,
            "trash_block_reason": None,
        },
    ]

    workspace_response = client.get("/api/v1/chapters/CH100/author-workspace")

    assert workspace_response.status_code == 200
    assert workspace_response.json()["data"] == {
        "chapter": {
            "chapter_id": "CH100",
            "planned_scene_count": 3,
            "mid_aggregate_enabled": 0,
            "chapter_goal": "Close the archive loop",
            "main_plot_push": "push CH100",
            "emotional_target": "emotion CH100",
            "ending_effect": "ending CH100",
            "must_not": "avoid CH100",
            "notes": "notes CH100",
            "writer_brief_json": EMPTY_CHAPTER_WRITER_BRIEF,
        },
        "chapter_state": {
            "chapter_id": "CH100",
            "current_phase": "drafting",
            "chapter_passed_scene_count": 1,
            "chapter_backfill_pending_count": 2,
        },
        "scenes": [
            {
                "scene_id": "CH100_SC01",
                "chapter_id": "CH100",
                "scene_seq": 1,
                "pov_character_id": "CHAR_A",
                "onstage_chars_json": ["CHAR_A", "CHAR_B"],
                "resolved_relation_id": None,
                "location": "Archive room",
                "scene_goal": "goal for CH100_SC01",
                "beats_json": ["beat-CH100_SC01-1", "beat-CH100_SC01-2"],
                "must_include_text": "must include CH100_SC01",
                "forbidden_text": "forbidden CH100_SC01",
                "exit_change": "exit CH100_SC01",
                "hook": "hook CH100_SC01",
                "writer_brief_json": EMPTY_SCENE_WRITER_BRIEF,
                "target_length_band": "medium",
                "scene_type": "reunion",
                "is_chapter_last": 0,
                "scene_status": "ready",
                "current_bundle_id": None,
                "current_final_scene_row_id": None,
            },
            {
                "scene_id": "CH100_SC02",
                "chapter_id": "CH100",
                "scene_seq": 2,
                "pov_character_id": "CHAR_A",
                "onstage_chars_json": ["CHAR_A", "CHAR_B"],
                "resolved_relation_id": None,
                "location": "Archive room",
                "scene_goal": "goal for CH100_SC02",
                "beats_json": ["beat-CH100_SC02-1", "beat-CH100_SC02-2"],
                "must_include_text": "must include CH100_SC02",
                "forbidden_text": "forbidden CH100_SC02",
                "exit_change": "exit CH100_SC02",
                "hook": "hook CH100_SC02",
                "writer_brief_json": EMPTY_SCENE_WRITER_BRIEF,
                "target_length_band": "medium",
                "scene_type": "reunion",
                "is_chapter_last": 1,
                "scene_status": "archived",
                "current_bundle_id": "bundle_ch100_sc02",
                "current_final_scene_row_id": "final_scene_ch100_sc02",
            },
        ],
    }


def test_scene_upsert_appends_to_end_when_scene_seq_is_omitted(client, session) -> None:
    _create_chapter(client, "CH300", goal="Append scenes")
    _create_scene(client, "CH300_SC01", chapter_id="CH300", scene_seq=1)

    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "CH300_SC02",
            "chapter_id": "CH300",
            "pov_character_id": "CHAR_B",
            "onstage_chars_json": ["CHAR_B"],
            "location": "Bridge",
            "scene_goal": "Append automatically",
            "beats_json": ["append", "verify"],
            "must_include_text": "a handoff clue",
            "target_length_band": "short",
            "scene_type": "bridge",
        },
        headers={"X-Idempotency-Key": "create-ch300-sc02"},
    )

    assert response.status_code == 200
    scene = session.get(SceneCard, "CH300_SC02")
    scene_state = session.get(SceneRunState, "CH300_SC02")
    assert scene is not None
    assert scene.scene_seq == 2
    assert scene.is_chapter_last == 0
    assert scene_state is not None
    assert scene_state.scene_status == "ready"


def test_scene_upsert_rejects_missing_chapter(client) -> None:
    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "ORPHAN_SC01",
            "chapter_id": "CH404",
            "scene_seq": 1,
            "scene_goal": "Should fail",
            "beats_json": [],
        },
        headers={"X-Idempotency-Key": "create-orphan-scene"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHAPTER_NOT_FOUND"


def test_scene_draft_uses_chapter_context_when_no_active_scene_exists(client) -> None:
    _create_chapter(client, "CH350", goal="Draft the next scene")

    response = client.get("/api/v1/chapters/CH350/scene-draft")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "scene_id": "CH350_SC01",
        "chapter_id": "CH350",
        "scene_seq": 1,
        "pov_character_id": "",
        "onstage_chars_json": [],
        "location": "",
        "scene_goal": "推进本章目标：push CH350",
        "beats_json": [],
        "must_include_text": "",
        "forbidden_text": "avoid CH350",
        "exit_change": "",
        "hook": "朝向本章结尾效果：ending CH350",
        "target_length_band": "medium",
        "scene_type": "reunion",
        "is_chapter_last": 0,
    }


def test_scene_draft_inherits_from_previous_active_scene_and_chapter_context(client) -> None:
    _create_chapter(client, "CH351", goal="Draft the next scene")
    _create_scene(client, "CH351_SC01", chapter_id="CH351", scene_seq=1, location="Bridge approach")

    response = client.get("/api/v1/chapters/CH351/scene-draft")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "scene_id": "CH351_SC02",
        "chapter_id": "CH351",
        "scene_seq": 2,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_B"],
        "location": "Bridge approach",
        "scene_goal": "承接上一场景变化：exit CH351_SC01；推进本章目标：push CH351",
        "beats_json": [],
        "must_include_text": "",
        "forbidden_text": "avoid CH351",
        "exit_change": "",
        "hook": "朝向本章结尾效果：ending CH351",
        "target_length_band": "medium",
        "scene_type": "reunion",
        "is_chapter_last": 0,
    }


def test_scene_draft_ignores_trashed_scene_for_prefill_but_keeps_global_append_sequence(client) -> None:
    _create_chapter(client, "CH352", goal="Draft after trash")
    _create_scene(client, "CH352_SC01", chapter_id="CH352", scene_seq=1, location="North gate")
    _create_scene(client, "CH352_SC02", chapter_id="CH352", scene_seq=2, location="Hidden vault")

    trash_response = client.post(
        "/api/v1/scenes/trash",
        json={"scene_ids": ["CH352_SC02"]},
        headers={"X-Idempotency-Key": "trash-ch352-sc02"},
    )
    assert trash_response.status_code == 200

    response = client.get("/api/v1/chapters/CH352/scene-draft")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "scene_id": "CH352_SC03",
        "chapter_id": "CH352",
        "scene_seq": 3,
        "pov_character_id": "CHAR_A",
        "onstage_chars_json": ["CHAR_A", "CHAR_B"],
        "location": "North gate",
        "scene_goal": "承接上一场景变化：exit CH352_SC01；推进本章目标：push CH352",
        "beats_json": [],
        "must_include_text": "",
        "forbidden_text": "avoid CH352",
        "exit_change": "",
        "hook": "朝向本章结尾效果：ending CH352",
        "target_length_band": "medium",
        "scene_type": "reunion",
        "is_chapter_last": 0,
    }


def test_scene_draft_keeps_default_blank_copy_when_chapter_and_scene_context_are_blank(client) -> None:
    response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": "CH353",
            "planned_scene_count": 1,
            "chapter_goal": "",
            "main_plot_push": "",
            "emotional_target": "",
            "ending_effect": "",
            "must_not": "",
            "notes": "",
        },
        headers={"X-Idempotency-Key": "create-blank-ch353"},
    )
    assert response.status_code == 200

    response = client.get("/api/v1/chapters/CH353/scene-draft")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "scene_id": "CH353_SC01",
        "chapter_id": "CH353",
        "scene_seq": 1,
        "pov_character_id": "",
        "onstage_chars_json": [],
        "location": "",
        "scene_goal": "",
        "beats_json": [],
        "must_include_text": "",
        "forbidden_text": "",
        "exit_change": "",
        "hook": "",
        "target_length_band": "medium",
        "scene_type": "reunion",
        "is_chapter_last": 0,
    }


def test_scene_draft_suggests_next_available_id_and_next_append_sequence(client) -> None:
    _create_chapter(client, "CH354", goal="Draft the next scene")
    _create_scene(client, "CH354_SC01", chapter_id="CH354", scene_seq=1)
    _create_scene(client, "LEGACY_SCENE_ALPHA", chapter_id="CH354", scene_seq=5)

    response = client.get("/api/v1/chapters/CH354/scene-draft")

    assert response.status_code == 200
    assert response.json()["data"]["scene_id"] == "CH354_SC02"
    assert response.json()["data"]["scene_seq"] == 6


def test_scene_draft_rejects_missing_chapter(client) -> None:
    response = client.get("/api/v1/chapters/CH404/scene-draft")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CHAPTER_NOT_FOUND"


def test_scene_draft_rejects_trashed_chapter(client) -> None:
    _create_chapter(client, "CH360", goal="Trash before drafting")

    trash_response = client.post(
        "/api/v1/chapters/trash",
        json={"chapter_ids": ["CH360"]},
        headers={"X-Idempotency-Key": "trash-ch360"},
    )
    assert trash_response.status_code == 200

    response = client.get("/api/v1/chapters/CH360/scene-draft")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHAPTER_TRASHED"


def test_scene_order_rewrites_sequence_and_marks_single_last_scene(client, session) -> None:
    _create_chapter(client, "CH400", goal="Reorder chapter scenes")
    _create_scene(client, "CH400_SC01", chapter_id="CH400", scene_seq=1)
    _create_scene(client, "CH400_SC02", chapter_id="CH400", scene_seq=2)
    _create_scene(client, "CH400_SC03", chapter_id="CH400", scene_seq=3, is_chapter_last=1)

    response = client.post(
        "/api/v1/chapters/CH400/scene-order",
        json={
            "scene_ids": ["CH400_SC03", "CH400_SC01", "CH400_SC02"],
            "last_scene_id": "CH400_SC01",
        },
        headers={"X-Idempotency-Key": "reorder-ch400-scenes"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["scenes"] == [
        {"scene_id": "CH400_SC03", "scene_seq": 1, "is_chapter_last": 0},
        {"scene_id": "CH400_SC01", "scene_seq": 2, "is_chapter_last": 1},
        {"scene_id": "CH400_SC02", "scene_seq": 3, "is_chapter_last": 0},
    ]

    scenes = session.execute(
        select(SceneCard).where(SceneCard.chapter_id == "CH400").order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
    ).scalars().all()
    assert [(scene.scene_id, scene.scene_seq, scene.is_chapter_last) for scene in scenes] == [
        ("CH400_SC03", 1, 0),
        ("CH400_SC01", 2, 1),
        ("CH400_SC02", 3, 0),
    ]


def test_scene_order_rejects_cross_chapter_payloads(client) -> None:
    _create_chapter(client, "CH500", goal="Primary chapter")
    _create_chapter(client, "CH501", goal="Other chapter")
    _create_scene(client, "CH500_SC01", chapter_id="CH500", scene_seq=1, is_chapter_last=1)
    _create_scene(client, "CH501_SC01", chapter_id="CH501", scene_seq=1, is_chapter_last=1)

    response = client.post(
        "/api/v1/chapters/CH500/scene-order",
        json={
            "scene_ids": ["CH500_SC01", "CH501_SC01"],
            "last_scene_id": "CH500_SC01",
        },
        headers={"X-Idempotency-Key": "reorder-cross-chapter"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SCENE_ORDER_CHAPTER_MISMATCH"
