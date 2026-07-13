from __future__ import annotations

from sqlalchemy import select

from novel_system.db.models import ChapterRunJob, QcReport, SceneCard, SceneRunState
from novel_system.services.scene_run_jobs import SceneRunJobService


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


def test_scene_run_job_api_creates_pollable_nonblocking_job(client, session) -> None:
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
    session.expire_all()
    assert session.get(ChapterRunJob, job["job_id"]).scene_id == "CHJOB_SC01"


def test_scene_run_job_serialization_prefers_authoritative_scene_column(session) -> None:
    job = ChapterRunJob(
        job_id="scene_run_authoritative_scope",
        chapter_id="CHJOB",
        scene_id="SCENE_COLUMN",
        status="queued",
        job_type="scene_run_full",
        payload_json={"scene_id": "STALE_PAYLOAD", "current_step": "queued"},
        result_summary_json={"scene_id": "STALE_SUMMARY"},
    )
    session.add(job)
    session.commit()

    serialized = SceneRunJobService(session).serialize_job(job)

    assert serialized["scene_id"] == "SCENE_COLUMN"


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


def test_scene_run_states_listing_backs_fe_queue_recovery(client, session) -> None:
    """贯通轮遗留 ①：GET /scene-run-states 是起草台队列成员的后端派生源——
    只返回离开过 ready 的场（进过管线），换浏览器后 FE 据此恢复队列。"""
    from novel_system.tools.seed_fe_demo_works import seed_fe_demo_works

    seed_fe_demo_works(session)
    session.commit()
    scenes = session.execute(
        select(SceneCard).where(SceneCard.project_id == "tide", SceneCard.trashed_flag == 0)
    ).scalars().all()
    assert len(scenes) >= 2
    touched, untouched = scenes[0], scenes[1]
    for scene, status in ((touched, "human_review_required"), (untouched, "ready")):
        state = session.get(SceneRunState, scene.scene_id)
        if state is None:
            state = SceneRunState(scene_id=scene.scene_id)
            session.add(state)
        state.scene_status = status
    session.commit()

    response = client.get("/api/v1/scene-run-states?project_id=tide")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    by_id = {item["scene_id"]: item for item in data["items"]}
    assert touched.scene_id in by_id
    assert by_id[touched.scene_id]["scene_status"] == "human_review_required"
    assert by_id[touched.scene_id]["chapter_id"] == touched.chapter_id
    # ready = 从未进管线，不参与队列恢复
    assert untouched.scene_id not in by_id

    missing = client.get("/api/v1/scene-run-states?project_id=no-such-project")
    assert missing.status_code == 404
