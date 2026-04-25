from __future__ import annotations


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
            "pov_character_id": "CHAR_A",
            "onstage_chars_json": ["CHAR_A"],
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


def test_scene_run_job_not_found_uses_structured_error(client) -> None:
    response = client.get("/api/v1/run-jobs/missing-job")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RUN_JOB_NOT_FOUND"
