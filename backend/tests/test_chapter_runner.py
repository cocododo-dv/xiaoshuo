from __future__ import annotations

from novel_system.db.models import ChapterRunJob, HumanReviewEvent, SceneCard, SceneRunState
from novel_system.services.chapter_runner import ChapterRunnerService


def _create_chapter(client, chapter_id: str) -> None:
    response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": chapter_id,
            "planned_scene_count": 3,
            "chapter_goal": f"goal {chapter_id}",
            "main_plot_push": f"push {chapter_id}",
            "emotional_target": f"emotion {chapter_id}",
            "ending_effect": f"ending {chapter_id}",
        },
        headers={"X-Idempotency-Key": f"create-chapter-{chapter_id}"},
    )
    assert response.status_code == 200


def _create_scene(client, chapter_id: str, scene_id: str, scene_seq: int, *, is_chapter_last: int = 0) -> None:
    response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": scene_id,
            "chapter_id": chapter_id,
            "scene_seq": scene_seq,
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A"],
            "location": f"location {scene_id}",
            "scene_goal": f"goal {scene_id}",
            "beats_json": [f"beat {scene_id}"],
            "must_include_text": f"must {scene_id}",
            "target_length_band": "short",
            "scene_type": "bridge",
            "is_chapter_last": is_chapter_last,
        },
        headers={"X-Idempotency-Key": f"create-scene-{scene_id}"},
    )
    assert response.status_code == 200


def _install_fake_runner(monkeypatch, *, blocked_scene: str | None = None, block_kind: str | None = None):
    shared = {
        "calls": [],
        "gate": {
            "chapter_id": "CH900",
            "chapter_passed_scene_count": 0,
            "chapter_backfill_pending_count": 0,
            "mid_aggregate_enabled_effective": 0,
            "aggregate_block_reason": "none",
            "manual_hold_reason": None,
            "last_interim_memory_row_id": None,
            "last_final_memory_row_id": None,
            "staged_backfill_items": [],
        },
    }

    class FakeOrchestrator:
        def __init__(self, session) -> None:
            self.session = session

        def run_scene(self, scene_id: str) -> dict:
            shared["calls"].append(scene_id)
            state = self.session.get(SceneRunState, scene_id)
            assert state is not None
            if blocked_scene == scene_id and block_kind == "human_review":
                state.scene_status = "human_review_required"
                state.current_human_review_event_id = f"review_{scene_id}"
                self.session.flush()
                return {
                    "scene_status": "human_review_required",
                    "current_human_review_event_id": state.current_human_review_event_id,
                }
            if blocked_scene == scene_id and block_kind == "partial_rewrite":
                state.scene_status = "hard_qc_partial_rewrite_required"
                state.current_human_review_event_id = None
                state.current_final_scene_row_id = None
                self.session.flush()
                return {
                    "scene_status": "hard_qc_partial_rewrite_required",
                    "current_human_review_event_id": None,
                    "current_final_scene_row_id": None,
                }

            state.scene_status = "archived"
            state.current_human_review_event_id = None
            state.current_final_scene_row_id = f"final_scene_{scene_id}"
            self.session.flush()

            if blocked_scene == scene_id and block_kind == "backfill":
                shared["gate"] = {
                    **shared["gate"],
                    "chapter_backfill_pending_count": 1,
                    "aggregate_block_reason": "blocked_waiting_backfill",
                    "staged_backfill_items": [
                        {
                            "stage_id": f"stage_{scene_id}",
                            "chapter_id": "CH900",
                            "scene_id": scene_id,
                            "marker_id": "F001",
                            "marker_text": "marker text",
                            "marker_token": '{{backfill id=F001 text="marker text"}}',
                            "status": "pending",
                            "linked_tracker_row_id": None,
                            "last_strategy": None,
                        }
                    ],
                }
            return {
                "scene_status": "archived",
                "current_human_review_event_id": None,
                "current_final_scene_row_id": state.current_final_scene_row_id,
            }

    class FakeChapterRuntimeService:
        def __init__(self, session) -> None:
            self.session = session

        def chapter_state_payload(self, chapter_id: str) -> dict:
            return {**shared["gate"], "chapter_id": chapter_id}

    monkeypatch.setattr("novel_system.services.chapter_runner.Orchestrator", FakeOrchestrator)
    monkeypatch.setattr("novel_system.services.chapter_runner.ChapterRuntimeService", FakeChapterRuntimeService)
    return shared


def test_chapter_run_full_executes_scenes_in_order_and_reports_completed_status(client, session, monkeypatch) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2)
    _create_scene(client, "CH900", "CH900_SC03", 3, is_chapter_last=1)
    shared = _install_fake_runner(monkeypatch)

    response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-complete"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["current_scene_id"] == "CH900_SC03"
    assert data["completed_scene_ids"] == ["CH900_SC01", "CH900_SC02", "CH900_SC03"]
    assert data["blocked_scene_id"] is None
    assert data["latest_error"] is None
    assert shared["calls"] == ["CH900_SC01", "CH900_SC02", "CH900_SC03"]

    status_response = client.get("/api/v1/chapters/CH900/run-status")
    assert status_response.status_code == 200
    status_payload = status_response.json()["data"]
    assert status_payload["status"] == "completed"
    assert status_payload["scene_count"] == 3
    assert status_payload["completed_count"] == 3
    assert status_payload["progress_pct"] == 100
    assert status_payload["started_at"]
    assert status_payload["finished_at"]

    job = session.query(ChapterRunJob).filter_by(chapter_id="CH900").one()
    assert job.status == "completed"
    assert job.payload_json["completed_scene_ids"] == ["CH900_SC01", "CH900_SC02", "CH900_SC03"]


def test_chapter_run_full_blocks_on_human_review_and_resume_retries_blocked_scene(client, session, monkeypatch) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2, is_chapter_last=1)
    shared = _install_fake_runner(monkeypatch, blocked_scene="CH900_SC01", block_kind="human_review")

    blocked_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-human-review"},
    )

    assert blocked_response.status_code == 200
    blocked = blocked_response.json()["data"]
    assert blocked["status"] == "blocked"
    assert blocked["current_scene_id"] == "CH900_SC01"
    assert blocked["completed_scene_ids"] == []
    assert blocked["blocked_scene_id"] == "CH900_SC01"
    assert blocked["latest_error"] == {
        "code": "CHAPTER_RUN_HUMAN_REVIEW_REQUIRED",
        "message": "scene requires human review before chapter run can continue",
    }
    session.add(
        HumanReviewEvent(
            event_id="review_CH900_SC01",
            scene_id="CH900_SC01",
            chapter_id="CH900",
            object_ref="scene_card:CH900_SC01",
            event_source="scene_generation",
            priority="high",
            status="resolved",
            allowed_actions_json=["inspect"],
            result_status_map_json={"inspect": "needs_followup"},
            details_json={},
            default_action="inspect",
        )
    )
    session.commit()

    shared["gate"] = {
        **shared["gate"],
        "aggregate_block_reason": "none",
        "chapter_backfill_pending_count": 0,
        "staged_backfill_items": [],
    }
    shared["calls"].clear()
    _install_fake_runner(monkeypatch)

    resumed_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-human-review-resume"},
    )

    assert resumed_response.status_code == 200
    resumed = resumed_response.json()["data"]
    assert resumed["status"] == "completed"
    assert resumed["completed_scene_ids"] == ["CH900_SC01", "CH900_SC02"]


def test_chapter_run_full_blocks_when_scene_finishes_without_final_scene(client, session, monkeypatch) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2, is_chapter_last=1)
    shared = _install_fake_runner(monkeypatch, blocked_scene="CH900_SC01", block_kind="partial_rewrite")

    response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-partial-rewrite-block"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "blocked"
    assert data["current_scene_id"] == "CH900_SC01"
    assert data["completed_scene_ids"] == []
    assert data["blocked_scene_id"] == "CH900_SC01"
    assert data["latest_error"] == {
        "code": "CHAPTER_RUN_SCENE_INCOMPLETE",
        "message": "scene run did not produce a final scene",
    }
    assert shared["calls"] == ["CH900_SC01"]


def test_chapter_run_full_stays_blocked_until_human_review_resolves(client, session, monkeypatch) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2, is_chapter_last=1)
    shared = _install_fake_runner(monkeypatch, blocked_scene="CH900_SC01", block_kind="human_review")

    blocked_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-human-review-stays-blocked"},
    )

    assert blocked_response.status_code == 200
    blocked = blocked_response.json()["data"]
    assert blocked["status"] == "blocked"
    assert blocked["blocked_scene_id"] == "CH900_SC01"
    session.add(
        HumanReviewEvent(
            event_id="review_CH900_SC01",
            scene_id="CH900_SC01",
            chapter_id="CH900",
            object_ref="scene_card:CH900_SC01",
            event_source="scene_generation",
            priority="high",
            status="needs_followup",
            allowed_actions_json=["inspect"],
            result_status_map_json={"inspect": "needs_followup"},
            details_json={},
            default_action="inspect",
        )
    )
    session.commit()

    shared["calls"].clear()
    _install_fake_runner(monkeypatch)

    resumed_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-human-review-unresolved"},
    )

    assert resumed_response.status_code == 200
    resumed = resumed_response.json()["data"]
    assert resumed["status"] == "blocked"
    assert resumed["blocked_scene_id"] == "CH900_SC01"
    assert resumed["latest_error"] == {
        "code": "CHAPTER_RUN_HUMAN_REVIEW_REQUIRED",
        "message": "scene requires human review before chapter run can continue",
    }
    assert resumed["completed_scene_ids"] == []
    assert shared["calls"] == []

    review_event = session.get(HumanReviewEvent, "review_CH900_SC01")
    assert review_event is not None
    review_event.status = "resolved"
    session.commit()

    resumed_after_resolution = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-human-review-resolved"},
    )

    assert resumed_after_resolution.status_code == 200
    completed = resumed_after_resolution.json()["data"]
    assert completed["status"] == "completed"
    assert completed["completed_scene_ids"] == ["CH900_SC01", "CH900_SC02"]


def test_prepare_full_run_restarts_resolved_blocked_job(client, session, monkeypatch) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2, is_chapter_last=1)
    _install_fake_runner(monkeypatch, blocked_scene="CH900_SC01", block_kind="human_review")

    blocked_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-prepare-blocked"},
    )
    assert blocked_response.status_code == 200
    assert blocked_response.json()["data"]["status"] == "blocked"
    session.add(
        HumanReviewEvent(
            event_id="review_CH900_SC01",
            scene_id="CH900_SC01",
            chapter_id="CH900",
            object_ref="scene_card:CH900_SC01",
            event_source="scene_generation",
            priority="high",
            status="resolved",
            allowed_actions_json=["inspect"],
            result_status_map_json={"inspect": "resolved"},
            details_json={},
            default_action="inspect",
        )
    )
    session.commit()

    prepared, should_start = ChapterRunnerService(session).prepare_full_run("CH900")

    assert should_start is True
    assert prepared["status"] == "pending"
    assert prepared["blocked_scene_id"] is None
    assert prepared["latest_error"] is None


def test_chapter_run_full_persists_completed_scenes_when_blocked_by_backfill_and_resumes_from_next_scene(
    client,
    session,
    monkeypatch,
) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2)
    _create_scene(client, "CH900", "CH900_SC03", 3, is_chapter_last=1)
    shared = _install_fake_runner(monkeypatch, blocked_scene="CH900_SC02", block_kind="backfill")

    blocked_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-backfill"},
    )

    assert blocked_response.status_code == 200
    blocked = blocked_response.json()["data"]
    assert blocked["status"] == "blocked"
    assert blocked["current_scene_id"] == "CH900_SC02"
    assert blocked["completed_scene_ids"] == ["CH900_SC01", "CH900_SC02"]
    assert blocked["blocked_scene_id"] == "CH900_SC02"
    assert blocked["latest_error"] == {
        "code": "CHAPTER_RUN_BACKFILL_PENDING",
        "message": "chapter run is blocked by pending staged backfill",
    }

    status_response = client.get("/api/v1/chapters/CH900/run-status")
    assert status_response.status_code == 200
    assert status_response.json()["data"]["completed_scene_ids"] == ["CH900_SC01", "CH900_SC02"]

    job = session.query(ChapterRunJob).filter_by(chapter_id="CH900").one()
    blocked_job_id = job.job_id
    assert job.status == "blocked"

    shared["gate"] = {
        **shared["gate"],
        "chapter_backfill_pending_count": 0,
        "aggregate_block_reason": "none",
        "staged_backfill_items": [],
    }
    shared["calls"].clear()
    _install_fake_runner(monkeypatch)

    resumed_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-backfill-resume"},
    )

    assert resumed_response.status_code == 200
    resumed = resumed_response.json()["data"]
    assert resumed["job_id"] == blocked_job_id
    assert resumed["status"] == "completed"
    assert resumed["completed_scene_ids"] == ["CH900_SC01", "CH900_SC02", "CH900_SC03"]


def test_chapter_run_full_reuses_completed_job_progress_when_new_scene_is_added(client, monkeypatch) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2, is_chapter_last=1)
    shared = _install_fake_runner(monkeypatch)

    first_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-completed-progress-initial"},
    )

    assert first_response.status_code == 200
    first_run = first_response.json()["data"]
    assert first_run["status"] == "completed"
    assert shared["calls"] == ["CH900_SC01", "CH900_SC02"]

    _create_scene(client, "CH900", "CH900_SC03", 3, is_chapter_last=1)
    shared = _install_fake_runner(monkeypatch)

    resumed_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-completed-progress-resume"},
    )

    assert resumed_response.status_code == 200
    resumed = resumed_response.json()["data"]
    assert resumed["job_id"] == first_run["job_id"]
    assert resumed["status"] == "completed"
    assert resumed["completed_scene_ids"] == ["CH900_SC01", "CH900_SC02", "CH900_SC03"]
    assert shared["calls"] == ["CH900_SC03"]


def test_chapter_run_status_reconciles_removed_blocked_scene(client, session, monkeypatch) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2, is_chapter_last=1)
    _install_fake_runner(monkeypatch, blocked_scene="CH900_SC02", block_kind="backfill")

    blocked_response = client.post(
        "/api/v1/chapters/CH900/run/full",
        headers={"X-Idempotency-Key": "chapter-run-blocked-scene-remove"},
    )

    assert blocked_response.status_code == 200
    blocked = blocked_response.json()["data"]
    assert blocked["status"] == "blocked"
    assert blocked["blocked_scene_id"] == "CH900_SC02"

    removed_scene = session.get(SceneCard, "CH900_SC02")
    assert removed_scene is not None
    removed_scene.trashed_flag = 1
    session.commit()

    status_response = client.get("/api/v1/chapters/CH900/run-status")

    assert status_response.status_code == 200
    status_payload = status_response.json()["data"]
    assert status_payload["status"] == "completed"
    assert status_payload["scene_ids"] == ["CH900_SC01"]
    assert status_payload["blocked_scene_id"] is None
    assert status_payload["current_scene_id"] == "CH900_SC01"
    assert status_payload["latest_error"] is None


def test_chapter_run_status_preserves_failed_job_visibility(client, session) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1)
    _create_scene(client, "CH900", "CH900_SC02", 2, is_chapter_last=1)
    session.add(
        ChapterRunJob(
            job_id="chapter_run_CH900_failed",
            chapter_id="CH900",
            status="failed",
            job_type="chapter_run_full",
            payload_json={
                "scene_ids": ["CH900_SC01", "CH900_SC02"],
                "completed_scene_ids": ["CH900_SC01"],
                "current_scene_id": "CH900_SC02",
                "blocked_scene_id": None,
            },
            result_summary_json={
                "scene_ids": ["CH900_SC01", "CH900_SC02"],
                "completed_scene_ids": ["CH900_SC01"],
                "current_scene_id": "CH900_SC02",
                "blocked_scene_id": None,
                "latest_error": {
                    "code": "CHAPTER_RUN_FAILED",
                    "message": "scene execution crashed",
                },
            },
            worker_id="local-process",
            attempt_no=1,
            error_code="CHAPTER_RUN_FAILED",
            error_text="scene execution crashed",
        )
    )
    session.commit()

    status_response = client.get("/api/v1/chapters/CH900/run-status")

    assert status_response.status_code == 200
    status_payload = status_response.json()["data"]
    assert status_payload["status"] == "failed"
    assert status_payload["current_scene_id"] == "CH900_SC02"
    assert status_payload["completed_scene_ids"] == ["CH900_SC01"]
    assert status_payload["latest_error"] == {
        "code": "CHAPTER_RUN_FAILED",
        "message": "scene execution crashed",
    }


def test_chapter_run_status_reconciles_external_finalized_scene_progress(client, session) -> None:
    _create_chapter(client, "CH900")
    _create_scene(client, "CH900", "CH900_SC01", 1, is_chapter_last=1)
    state = session.get(SceneRunState, "CH900_SC01")
    assert state is not None
    state.scene_status = "archived"
    state.current_final_scene_row_id = "final_scene_CH900_SC01_v1"
    session.add(
        ChapterRunJob(
            job_id="chapter_run_CH900_stale_blocked",
            chapter_id="CH900",
            status="blocked",
            job_type="chapter_run_full",
            payload_json={
                "scene_ids": ["CH900_SC01"],
                "completed_scene_ids": [],
                "current_scene_id": "CH900_SC01",
                "blocked_scene_id": "CH900_SC01",
            },
            result_summary_json={
                "scene_ids": ["CH900_SC01"],
                "completed_scene_ids": [],
                "current_scene_id": "CH900_SC01",
                "blocked_scene_id": "CH900_SC01",
                "latest_error": {
                    "code": "CHAPTER_RUN_SCENE_INCOMPLETE",
                    "message": "scene run did not produce a final scene",
                },
            },
            worker_id="local-process",
            attempt_no=1,
            error_code="CHAPTER_RUN_SCENE_INCOMPLETE",
            error_text="scene run did not produce a final scene",
        )
    )
    session.commit()

    status_response = client.get("/api/v1/chapters/CH900/run-status")

    assert status_response.status_code == 200
    status_payload = status_response.json()["data"]
    assert status_payload["status"] == "completed"
    assert status_payload["completed_scene_ids"] == ["CH900_SC01"]
    assert status_payload["blocked_scene_id"] is None
    assert status_payload["current_scene_id"] == "CH900_SC01"
    assert status_payload["latest_error"] is None
