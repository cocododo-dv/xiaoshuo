from __future__ import annotations

import pytest

from novel_system.services.llm_task_runner import LLMNodeRunner
from tests.real_llm_fakes import ScenePipelineOnlineFake

from .test_orchestrator_flow import seed_story

pytestmark = pytest.mark.chroma_integration


@pytest.fixture(autouse=True)
def _online_pipeline(monkeypatch) -> None:
    """假生成已退役：验收冒烟的整链场景运行注入在线记账测试替身。"""
    monkeypatch.setattr(
        "novel_system.services.orchestrator.LLMNodeRunner",
        lambda session: LLMNodeRunner(session, llm_client=ScenePipelineOnlineFake()),
    )


def test_l3_acceptance_smoke(client, session) -> None:
    seed_story(client, session=session)
    run_scene = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "acceptance-scene-1"},
    )
    assert run_scene.status_code == 200
    bundle_id = run_scene.json()["data"]["current_bundle_id"]

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

    worksheet = client.get(f"/api/v1/interop/export/bundle-worksheet/{bundle_id}")
    alias = client.get(
        "/api/v1/index/alias-scopes",
        params={"object_type": "style_observation", "scope": "global", "scope_ref_id": "global"},
    )
    assert worksheet.status_code == 200
    assert alias.status_code == 200
    alias_items = alias.json()["data"]["items"]
    assert len(alias_items) == 1
    assert alias_items[0]["verify_status"] == "succeeded"
