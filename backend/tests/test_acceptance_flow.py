from __future__ import annotations

import pytest

from .test_orchestrator_flow import seed_story

pytestmark = pytest.mark.chroma_integration


def test_l3_acceptance_smoke(client) -> None:
    seed_story(client)
    run_scene = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "acceptance-scene-1"},
    )
    assert run_scene.status_code == 200

    review = client.post(
        "/api/v1/review-items/import-demo",
        json={
            "review_id": "review_acceptance",
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "item_type": "style_observation",
            "candidate_text": "以停顿收束重逢场。",
            "candidate_payload_json": {
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": "STY_ACC",
                "text": "以停顿收束重逢场。"
            },
            "active_on_approve": 0
        },
        headers={"X-Idempotency-Key": "review-acceptance-import"},
    )
    assert review.status_code == 200
    assert client.post(
        "/api/v1/review-items/review_acceptance/approve",
        headers={"X-Idempotency-Key": "review-acceptance-approve"},
    ).status_code == 200

    jobs = client.get("/api/v1/index/jobs").json()["data"]["items"]
    verify_job = next(job["job_id"] for job in jobs if job["review_id"] == "review_acceptance" and job["job_type"] == "verify")
    assert client.post(
        f"/api/v1/index/verify/{verify_job}/retry",
        headers={"X-Idempotency-Key": "review-acceptance-verify"},
    ).status_code == 200
    assert client.post(
        "/api/v1/review-items/review_acceptance/release",
        headers={"X-Idempotency-Key": "review-acceptance-release"},
    ).status_code == 200

    worksheet = client.get("/api/v1/interop/export/bundle-worksheet/bundle_CH001_SC01")
    alias = client.get("/api/v1/index/alias-scopes/style_observation:global:global")
    assert worksheet.status_code == 200
    assert alias.status_code == 200
    assert alias.json()["data"]["verify_status"] == "succeeded"
