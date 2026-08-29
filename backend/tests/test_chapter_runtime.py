from __future__ import annotations

from sqlalchemy import select, text

from novel_system.db.models import ChapterMemory, ChapterState, FinalScene, ForeshadowTracker, ReviewItem, SceneCard, SceneMemory, SceneRunState


MARKER_ID = "F200"
MARKER_TEXT = "旧信寄件人线索"
MARKER_TOKEN = '{{backfill id=F200 text="旧信寄件人线索"}}'
CHAPTER_ID = "CH200"
SCENE_ID = "CH200_SC01"


def _create_chapter_and_scene(client, *, idempotency_suffix: str = "") -> None:
    chapter_response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": CHAPTER_ID,
            "planned_scene_count": 1,
            "chapter_goal": "补齐章节运行治理闭环",
            "main_plot_push": "把 backfill 和 final aggregate 跑通",
            "emotional_target": "让卡住的线索可追踪",
            "ending_effect": "形成章节终版摘要",
        },
        headers={"X-Idempotency-Key": f"chapter-runtime-create{idempotency_suffix}"},
    )
    assert chapter_response.status_code == 200

    scene_response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": SCENE_ID,
            "chapter_id": CHAPTER_ID,
            "scene_seq": 1,
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A", "CHAR_B"],
            "location": "旧城门洞",
            "scene_goal": "让重逢里的旧信线索进入治理流程",
            "beats_json": ["重逢", "试探", "收束"],
            "must_include_text": MARKER_TOKEN,
            "target_length_band": "short",
            "scene_type": "reunion",
            "is_chapter_last": 1,
        },
        headers={"X-Idempotency-Key": f"chapter-runtime-scene-create{idempotency_suffix}"},
    )
    assert scene_response.status_code == 200


def _seed_runtime_rows(session, *, include_old_final: bool = False) -> None:
    final_scene = FinalScene(
        row_id="final_scene_CH200_SC01_seed",
        scene_id=SCENE_ID,
        chapter_id=CHAPTER_ID,
        content=f"归档里仍然保留 {MARKER_TOKEN}",
        status="approved",
        source_bundle_id="bundle_seed",
        source_bundle_hash="hash_seed",
    )
    scene_memory = SceneMemory(
        row_id="scene_memory_CH200_SC01_seed",
        scene_id=SCENE_ID,
        chapter_id=CHAPTER_ID,
        content=f"场景记忆仍然写着 {MARKER_TOKEN}",
        carry_notes_json=[],
        source_bundle_id="bundle_seed",
        final_scene_row_id=final_scene.row_id,
        source_review_id=None,
        active_flag=1,
        runtime_eligible=1,
        runtime_eligibility_basis="direct_read",
    )
    pending_review = ReviewItem(
        review_id="review_chapter_runtime_pending",
        scene_id=SCENE_ID,
        chapter_id=CHAPTER_ID,
        item_type="scene_summary",
        status="pending",
        candidate_text=f"待审摘要仍然引用 {MARKER_TOKEN}",
        candidate_payload_json={"lineage_key": SCENE_ID, "scene_id": SCENE_ID, "text": f"待审摘要仍然引用 {MARKER_TOKEN}"},
        active_on_approve=1,
    )
    scene_state = session.get(SceneRunState, SCENE_ID)
    assert scene_state is not None
    scene_state.scene_status = "archived"
    scene_state.current_final_scene_row_id = final_scene.row_id
    session.add_all([final_scene, scene_memory, pending_review])

    if include_old_final:
        chapter_state = session.get(ChapterState, CHAPTER_ID)
        assert chapter_state is not None
        previous_final = ChapterMemory(
            row_id="chapter_memory_final_CH200_v1",
            chapter_id=CHAPTER_ID,
            aggregate_stage="final",
            content="旧的章节终版摘要",
            source_review_id=None,
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="direct_read",
        )
        session.add(previous_final)
        chapter_state.last_final_memory_row_id = previous_final.row_id

    session.commit()


def _stage_rows(session) -> list[dict]:
    return list(
        session.execute(
            text(
                """
                SELECT stage_id, chapter_id, scene_id, marker_id, marker_text, marker_token,
                       status, linked_tracker_row_id, last_strategy
                FROM staged_backfill
                ORDER BY stage_id
                """
            )
        ).mappings()
    )


def _latest_tracker(session) -> ForeshadowTracker:
    tracker = session.execute(
        select(ForeshadowTracker)
        .where(ForeshadowTracker.foreshadow_id == MARKER_ID)
        .order_by(ForeshadowTracker.version.desc(), ForeshadowTracker.row_id.desc())
    ).scalars().first()
    assert tracker is not None
    return tracker


def _chapter_state_via_workbench(client) -> dict:
    workbench_response = client.get(f"/api/v1/scenes/{SCENE_ID}/workbench")
    assert workbench_response.status_code == 200
    return workbench_response.json()["data"]["chapter_state"]


def test_workbench_projects_template_markers_without_writing_on_get(client, session) -> None:
    _create_chapter_and_scene(client)

    workbench_response = client.get(f"/api/v1/scenes/{SCENE_ID}/workbench")

    assert workbench_response.status_code == 200
    workbench_data = workbench_response.json()["data"]
    assert workbench_data["scene_card"]["must_include_text"] == MARKER_TEXT
    chapter_state = workbench_data["chapter_state"]
    assert chapter_state["chapter_backfill_pending_count"] == 1
    assert chapter_state["aggregate_block_reason"] == "blocked_waiting_backfill"
    assert chapter_state["manual_hold_reason"] is None
    assert chapter_state["last_interim_memory_row_id"] is None
    assert chapter_state["last_final_memory_row_id"] is None
    assert chapter_state["staged_backfill_items"] == [
        {
            "stage_id": chapter_state["staged_backfill_items"][0]["stage_id"],
            "chapter_id": CHAPTER_ID,
            "scene_id": SCENE_ID,
            "marker_id": MARKER_ID,
            "marker_text": MARKER_TEXT,
            "marker_token": MARKER_TOKEN,
            "status": "pending",
            "linked_tracker_row_id": None,
            "last_strategy": None,
        }
    ]
    assert _stage_rows(session) == []


def test_run_backfill_again_requires_existing_tracker_and_reopens_it(client, session) -> None:
    _create_chapter_and_scene(client, idempotency_suffix="-defer")
    stage_id = _chapter_state_via_workbench(client)["staged_backfill_items"][0]["stage_id"]

    missing_tracker = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/backfill/{stage_id}",
        json={"strategy": "run_backfill_again"},
        headers={"X-Idempotency-Key": "chapter-backfill-missing-tracker"},
    )

    assert missing_tracker.status_code == 409
    assert missing_tracker.json()["error"]["code"] == "BACKFILL_TRACKER_MISSING"

    session.add(
        ForeshadowTracker(
            row_id="foreshadow_F200_v1",
            foreshadow_id=MARKER_ID,
            version=1,
            chapter_id=CHAPTER_ID,
            scene_id=SCENE_ID,
            text=MARKER_TEXT,
            tracker_status="deferred",
            source_review_id=None,
            active_flag=1,
            runtime_eligible=0,
            runtime_eligibility_basis="manual_hold",
        )
    )
    session.commit()

    success = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/backfill/{stage_id}",
        json={"strategy": "run_backfill_again"},
        headers={"X-Idempotency-Key": "chapter-backfill-run-again"},
    )

    assert success.status_code == 200
    assert success.json()["data"]["chapter_state"]["chapter_backfill_pending_count"] == 0
    assert success.json()["data"]["chapter_state"]["aggregate_block_reason"] == "none"
    assert success.json()["data"]["chapter_state"]["staged_backfill_items"][0]["status"] == "completed"
    tracker = _latest_tracker(session)
    assert tracker.tracker_status == "open"


def test_backfill_strategies_update_tracker_remove_marker_and_rewrite_runtime_texts(client, session) -> None:
    _create_chapter_and_scene(client)
    _seed_runtime_rows(session)
    stage_id = _chapter_state_via_workbench(client)["staged_backfill_items"][0]["stage_id"]

    create_now = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/backfill/{stage_id}",
        json={"strategy": "create_tracker_now"},
        headers={"X-Idempotency-Key": "chapter-backfill-create-now"},
    )

    assert create_now.status_code == 200
    create_data = create_now.json()["data"]
    assert create_data["chapter_state"]["chapter_backfill_pending_count"] == 0
    assert create_data["chapter_state"]["aggregate_block_reason"] == "none"
    assert create_data["chapter_state"]["staged_backfill_items"][0]["status"] == "completed"
    assert create_data["chapter_state"]["staged_backfill_items"][0]["last_strategy"] == "create_tracker_now"

    session.expire_all()
    scene = session.get(SceneCard, SCENE_ID)
    final_scene = session.get(FinalScene, "final_scene_CH200_SC01_seed")
    scene_memory = session.get(SceneMemory, "scene_memory_CH200_SC01_seed")
    pending_review = session.get(ReviewItem, "review_chapter_runtime_pending")
    assert scene is not None
    assert final_scene is not None
    assert scene_memory is not None
    assert pending_review is not None
    assert scene.must_include_text == MARKER_TEXT
    assert final_scene.content == f"归档里仍然保留 {MARKER_TEXT}"
    assert scene_memory.content == f"场景记忆仍然写着 {MARKER_TEXT}"
    assert pending_review.candidate_text == f"待审摘要仍然引用 {MARKER_TEXT}"
    assert _latest_tracker(session).tracker_status == "open"

    _create_chapter_and_scene(client, idempotency_suffix="-defer")
    stage_id = _chapter_state_via_workbench(client)["staged_backfill_items"][0]["stage_id"]

    defer_result = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/backfill/{stage_id}",
        json={"strategy": "explicit_defer_with_tracker"},
        headers={"X-Idempotency-Key": "chapter-backfill-defer"},
    )

    assert defer_result.status_code == 200
    assert defer_result.json()["data"]["chapter_state"]["staged_backfill_items"][0]["status"] == "deferred"
    assert _latest_tracker(session).tracker_status == "deferred"

    _create_chapter_and_scene(client, idempotency_suffix="-abandon")
    stage_id = _chapter_state_via_workbench(client)["staged_backfill_items"][0]["stage_id"]

    abandon_result = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/backfill/{stage_id}",
        json={"strategy": "mark_staged_abandoned"},
        headers={"X-Idempotency-Key": "chapter-backfill-abandon"},
    )

    assert abandon_result.status_code == 200
    assert abandon_result.json()["data"]["chapter_state"]["staged_backfill_items"][0]["status"] == "abandoned"
    assert _latest_tracker(session).tracker_status == "abandoned"


def test_final_aggregate_is_blocked_by_pending_and_manual_hold_then_versions_final_memory(client, session) -> None:
    _create_chapter_and_scene(client)
    _seed_runtime_rows(session, include_old_final=True)
    stage_id = _chapter_state_via_workbench(client)["staged_backfill_items"][0]["stage_id"]

    blocked_pending = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/aggregate/final",
        headers={"X-Idempotency-Key": "chapter-final-aggregate-pending"},
    )

    assert blocked_pending.status_code == 409
    assert blocked_pending.json()["error"]["code"] == "BACKFILL_PENDING_BLOCKS_FINAL_AGGREGATE"

    hold_result = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/manual-hold",
        json={"reason": "等待作者确认 backfill 处理策略"},
        headers={"X-Idempotency-Key": "chapter-manual-hold-set"},
    )

    assert hold_result.status_code == 200
    assert hold_result.json()["data"]["chapter_state"]["aggregate_block_reason"] == "manual_hold"
    assert hold_result.json()["data"]["chapter_state"]["manual_hold_reason"] == "等待作者确认 backfill 处理策略"

    blocked_hold = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/aggregate/final",
        headers={"X-Idempotency-Key": "chapter-final-aggregate-hold"},
    )

    assert blocked_hold.status_code == 409
    assert blocked_hold.json()["error"]["code"] == "CHAPTER_MANUAL_HOLD_ACTIVE"

    clear_result = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/manual-hold/clear",
        headers={"X-Idempotency-Key": "chapter-manual-hold-clear"},
    )

    assert clear_result.status_code == 200
    assert clear_result.json()["data"]["chapter_state"]["aggregate_block_reason"] == "blocked_waiting_backfill"
    assert clear_result.json()["data"]["chapter_state"]["manual_hold_reason"] is None

    resolve_backfill = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/backfill/{stage_id}",
        json={"strategy": "create_tracker_now"},
        headers={"X-Idempotency-Key": "chapter-backfill-before-final-aggregate"},
    )

    assert resolve_backfill.status_code == 200
    assert resolve_backfill.json()["data"]["chapter_state"]["chapter_backfill_pending_count"] == 0

    aggregate_result = client.post(
        f"/api/v1/chapters/{CHAPTER_ID}/runtime/aggregate/final",
        headers={"X-Idempotency-Key": "chapter-final-aggregate-success"},
    )

    assert aggregate_result.status_code == 200
    aggregate_data = aggregate_result.json()["data"]
    assert aggregate_data["chapter_state"]["aggregate_block_reason"] == "none"
    assert aggregate_data["chapter_state"]["last_final_memory_row_id"] != "chapter_memory_final_CH200_v1"

    session.expire_all()
    finals = session.execute(
        select(ChapterMemory)
        .where(ChapterMemory.chapter_id == CHAPTER_ID, ChapterMemory.aggregate_stage == "final")
        .order_by(ChapterMemory.created_at.asc(), ChapterMemory.row_id.asc())
    ).scalars().all()

    assert len(finals) == 2
    assert finals[0].row_id == "chapter_memory_final_CH200_v1"
    assert finals[0].active_flag == 0
    assert finals[0].runtime_eligible == 0
    assert finals[1].row_id == aggregate_data["chapter_state"]["last_final_memory_row_id"]
    assert finals[1].active_flag == 1
    assert finals[1].runtime_eligible == 1
    assert finals[1].content == f"场景记忆仍然写着 {MARKER_TEXT}"
