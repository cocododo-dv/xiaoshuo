from __future__ import annotations

import pytest

from novel_system.db.models import StyleObservation
from novel_system.services.vector_store import get_vector_store
from novel_system.settings import get_settings

pytestmark = pytest.mark.chroma_integration


def import_style_review(
    client,
    *,
    review_id: str,
    lineage_key: str,
    candidate_text: str,
    scope: str = "global",
    scope_ref_id: str = "global",
    active_on_approve: int = 0,
) -> str:
    response = client.post(
        "/api/v1/review-items/import-demo",
        json={
            "review_id": review_id,
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "item_type": "style_observation",
            "candidate_text": candidate_text,
            "candidate_payload_json": {
                "scope": scope,
                "scope_ref_id": scope_ref_id,
                "lineage_key": lineage_key,
                "text": candidate_text,
            },
            "active_on_approve": active_on_approve,
        },
        headers={"X-Idempotency-Key": f"import-{review_id}"},
    )
    assert response.status_code == 200
    return review_id


def approve_review(client, review_id: str, *, idempotency_key: str) -> str:
    approved = client.post(
        f"/api/v1/review-items/{review_id}/approve",
        headers={"X-Idempotency-Key": idempotency_key},
    )
    assert approved.status_code == 200
    return approved.json()["data"]["approved_item_row_id"]


def verify_review(client, review_id: str, *, idempotency_key: str) -> None:
    jobs = client.get("/api/v1/index/jobs").json()["data"]["items"]
    verify_job_id = next(job["job_id"] for job in jobs if job["review_id"] == review_id and job["job_type"] == "verify")
    retried = client.post(
        f"/api/v1/index/verify/{verify_job_id}/retry",
        headers={"X-Idempotency-Key": idempotency_key},
    )
    assert retried.status_code == 200


def test_release_promotes_verified_candidate(client) -> None:
    review_id = import_style_review(
        client,
        review_id="review_style_release",
        lineage_key="STY_RELEASE",
        candidate_text="leave the final beat hanging at the door",
    )
    approve_review(client, review_id, idempotency_key="approve-review-style-release")
    verify_review(client, review_id, idempotency_key="verify-review-style-release")

    released = client.post(
        f"/api/v1/review-items/{review_id}/release",
        headers={"X-Idempotency-Key": "release-review-style-release"},
    )
    assert released.status_code == 200

    detail = client.get("/api/v1/index/alias-scopes/style_observation:global:global")
    data = detail.json()["data"]
    assert data["active_alias"]
    assert data["candidate_alias"] is None
    assert get_settings().vector_backend == "chroma"


def test_release_rejects_already_promoted_candidate(client) -> None:
    review_id = import_style_review(
        client,
        review_id="review_style_release_twice",
        lineage_key="STY_RELEASE_TWICE",
        candidate_text="keep the subtext under the spoken line",
    )
    approve_review(client, review_id, idempotency_key="approve-review-style-release-twice")
    verify_review(client, review_id, idempotency_key="verify-review-style-release-twice")

    first_release = client.post(
        f"/api/v1/review-items/{review_id}/release",
        headers={"X-Idempotency-Key": "release-review-style-release-twice-1"},
    )
    assert first_release.status_code == 200
    alias_before = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]

    second_release = client.post(
        f"/api/v1/review-items/{review_id}/release",
        headers={"X-Idempotency-Key": "release-review-style-release-twice-2"},
    )
    assert second_release.status_code == 409
    assert second_release.json()["error"]["code"] == "RELEASE_PRECONDITION_FAILED"

    alias_after = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]
    assert alias_after["active_alias"] == alias_before["active_alias"]
    assert alias_after["candidate_alias"] is None
    assert alias_after["active_snapshot_version"] == alias_before["active_snapshot_version"]
    assert alias_after["active_embedding_version"] == alias_before["active_embedding_version"]


def test_reindex_only_includes_runtime_rows_for_same_alias_scope(client, session) -> None:
    session.add(
        StyleObservation(
            row_id="style_observation_other_scene_v1",
            style_observation_id="STY_OTHER_SCENE",
            version=1,
            scope="scene",
            scope_ref_id="CH001_SC99",
            text="runtime text from another scene scope",
            active_flag=1,
            runtime_eligible=1,
            runtime_eligibility_basis="vector_ready",
        )
    )
    session.commit()

    review_id = import_style_review(
        client,
        review_id="review_style_scene_scope",
        lineage_key="STY_SCENE_SCOPE",
        candidate_text="only this scene scope should be indexed",
        scope="scene",
        scope_ref_id="CH001_SC01",
    )
    approved_row_id = approve_review(
        client,
        review_id,
        idempotency_key="approve-review-style-scene-scope",
    )

    alias = client.get("/api/v1/index/alias-scopes/style_observation:scene:CH001_SC01").json()["data"]
    documents = get_vector_store().load_collection(alias["candidate_alias"])
    indexed_ids = {item["id"] for item in documents}

    assert approved_row_id in indexed_ids
    assert "style_observation_other_scene_v1" not in indexed_ids
