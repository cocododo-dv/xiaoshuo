from __future__ import annotations

from novel_system.db.models import QcReport


def _create_chapter_and_scene(client) -> None:
    chapter_response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": "CHJOB",
            "planned_scene_count": 1,
            "chapter_goal": "Run scene through background job",
            "main_plot_push": "Exercise job API",
            "emotional_target": "Keep operator unblocked",
            "ending_effect": "Pollable status",
        },
        headers={"X-Idempotency-Key": "chapter-job-create"},
    )
    assert chapter_response.status_code == 200
    scene_response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "CHJOB_SC01",
            "chapter_id": "CHJOB",
            "scene_seq": 1,
            "pov_character_id": "",
            "onstage_chars_json": [],
            "location": "Control room",
            "scene_goal": "Start a pollable run",
            "beats_json": ["start", "poll"],
            "target_length_band": "short",
            "scene_type": "test",
            "is_chapter_last": 1,
        },
        headers={"X-Idempotency-Key": "scene-job-create"},
    )
    assert scene_response.status_code == 200


def test_scene_run_job_api_creates_pollable_nonblocking_job(client) -> None:
    _create_chapter_and_scene(client)

    response = client.post("/api/v1/scenes/CHJOB_SC01/run/jobs?start=false")

    assert response.status_code == 200
    job = response.json()["data"]
    assert job["scene_id"] == "CHJOB_SC01"
    assert job["chapter_id"] == "CHJOB"
    assert job["job_type"] == "scene_run_full"
    assert job["status"] == "queued"
    assert job["current_step"] == "queued"
    assert job["elapsed_ms"] >= 0
    assert job["stage_order"] == [
        "planning_running",
        "bundle_built",
        "neutral_running",
        "hard_qc_running",
        "style_running",
        "soft_qc_running",
        "rewrite_running",
        "acceptance_review_running",
        "near_final",
        "archived",
    ]

    poll = client.get(f"/api/v1/run-jobs/{job['job_id']}")

    assert poll.status_code == 200
    assert poll.json()["data"]["job_id"] == job["job_id"]
    assert poll.json()["data"]["scene_id"] == "CHJOB_SC01"


def test_scene_run_job_returns_preflight_blocker_before_starting_worker(client) -> None:
    chapter_response = client.post(
        "/api/v1/chapters",
        json={
            "chapter_id": "CHJOB_BLOCK",
            "planned_scene_count": 1,
            "chapter_goal": "Run scene preflight blocker",
            "main_plot_push": "Expose blocker before worker start",
            "emotional_target": "Keep operator informed",
            "ending_effect": "Pollable blocked state",
        },
        headers={"X-Idempotency-Key": "chapter-job-block-create"},
    )
    assert chapter_response.status_code == 200
    scene_response = client.post(
        "/api/v1/scenes",
        json={
            "scene_id": "CHJOB_BLOCK_SC01",
            "chapter_id": "CHJOB_BLOCK",
            "scene_seq": 1,
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A"],
            "location": "Control room",
            "scene_goal": "Expose a missing voice card before drafting",
            "beats_json": ["start", "block"],
            "target_length_band": "short",
            "scene_type": "test",
            "is_chapter_last": 1,
        },
        headers={"X-Idempotency-Key": "scene-job-preflight-block"},
    )
    assert scene_response.status_code == 200

    response = client.post("/api/v1/scenes/CHJOB_BLOCK_SC01/run/jobs")

    assert response.status_code == 200
    job = response.json()["data"]
    assert job["status"] == "blocked"
    assert job["current_step"] == "preflight_blocked"
    assert job["error_code"] == "VOICE_PROFILE_MISSING"
    assert job["run_preflight"]["can_run"] is False
    assert job["result_summary"]["next_action"].startswith("Create or release missing knowledge cards")


def test_scene_run_job_latest_qc_exposes_issue_keys_for_operator_next_action(client, session) -> None:
    _create_chapter_and_scene(client)
    session.add(
        QcReport(
            qc_report_id="qc_CHJOB_SC01_hard_v1",
            scene_id="CHJOB_SC01",
            chapter_id="CHJOB",
            qc_type="hard",
            resolution_code="hard_fail_partial",
            pass_flag=0,
            next_action="partial_rewrite",
            issues_json=[
                {
                    "issue_key": "missing_relationship_turn",
                    "message": "关系转折没有出现在动作层。",
                }
            ],
        )
    )
    session.commit()

    response = client.post("/api/v1/scenes/CHJOB_SC01/run/jobs?start=false")

    assert response.status_code == 200
    job = response.json()["data"]
    assert job["latest_qc"]["issue_keys"] == ["missing_relationship_turn"]
    assert job["latest_qc"]["primary_issue_key"] == "missing_relationship_turn"
    assert job["latest_qc"]["next_action"] == "partial_rewrite"


def test_scene_run_job_not_found_uses_structured_error(client) -> None:
    response = client.get("/api/v1/run-jobs/missing-job")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_JOB_NOT_FOUND"
