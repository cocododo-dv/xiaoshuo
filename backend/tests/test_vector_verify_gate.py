from __future__ import annotations

import pytest

from novel_system.services.vector_store import get_vector_store

pytestmark = pytest.mark.chroma_integration


def import_style_review(
    client,
    *,
    review_id: str,
    lineage_key: str,
    candidate_text: str,
    active_on_approve: int,
) -> None:
    response = client.post(
        "/api/v1/review-items/import-demo",
        json={
            "review_id": review_id,
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "item_type": "style_observation",
            "candidate_text": candidate_text,
            "candidate_payload_json": {
                "scope": "global",
                "scope_ref_id": "global",
                "lineage_key": lineage_key,
                "text": candidate_text,
            },
            "active_on_approve": active_on_approve,
        },
        headers={"X-Idempotency-Key": f"import-{review_id}"},
    )
    assert response.status_code == 200


def approve_review(client, review_id: str, *, idempotency_key: str) -> str:
    approved = client.post(
        f"/api/v1/review-items/{review_id}/approve",
        headers={"X-Idempotency-Key": idempotency_key},
    )
    assert approved.status_code == 200
    jobs = client.get("/api/v1/index/jobs").json()["data"]["items"]
    return next(job["job_id"] for job in jobs if job["review_id"] == review_id and job["job_type"] == "verify")


def get_alias_scope(client, alias_scope: str) -> dict:
    object_type, scope, scope_ref_id = alias_scope.split(":", 2)
    response = client.get(
        "/api/v1/index/alias-scopes",
        params={"object_type": object_type, "scope": scope, "scope_ref_id": scope_ref_id},
    )
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 1, f"expected exactly one alias scope for {alias_scope}, got {len(items)}"
    return items[0]


def promote_active_alias(client) -> str:
    import_style_review(
        client,
        review_id="review_style_good",
        lineage_key="STY_GOOD",
        candidate_text="keep the old alias serving verified text",
        active_on_approve=1,
    )
    verify_job_id = approve_review(client, "review_style_good", idempotency_key="approve-review-style-good")
    verified = client.post(
        f"/api/v1/index/verify/{verify_job_id}/retry",
        headers={"X-Idempotency-Key": "verify-review-style-good"},
    )
    assert verified.status_code == 200
    alias = get_alias_scope(client, "style_observation:global:global")
    return alias["active_alias"]


def seed_bad_candidate(client) -> str:
    import_style_review(
        client,
        review_id="review_style_bad",
        lineage_key="STY_BAD",
        candidate_text="",
        active_on_approve=1,
    )
    return approve_review(client, "review_style_bad", idempotency_key="approve-review-style-bad")


def test_verify_failure_keeps_old_alias_serving(client) -> None:
    active_alias_before = promote_active_alias(client)
    bad_verify_job_id = seed_bad_candidate(client)

    response = client.post(
        f"/api/v1/index/verify/{bad_verify_job_id}/retry",
        headers={"X-Idempotency-Key": "verify-review-style-bad"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VECTOR_VERIFY_FAILED"
    data = get_alias_scope(client, "style_observation:global:global")
    assert data["active_alias"] == active_alias_before
    assert data["candidate_alias"]
    assert data["verify_status"] == "failed"


def test_verify_requires_approved_row_to_be_returned(client) -> None:
    active_alias_before = promote_active_alias(client)
    import_style_review(
        client,
        review_id="review_style_stale_candidate",
        lineage_key="STY_STALE_CANDIDATE",
        candidate_text="target text that should map to the approved row",
        active_on_approve=1,
    )
    verify_job_id = approve_review(
        client,
        "review_style_stale_candidate",
        idempotency_key="approve-review-style-stale-candidate",
    )
    alias_before = get_alias_scope(client, "style_observation:global:global")

    get_vector_store().write_collection(
        alias_before["candidate_alias"],
        [
            {
                "id": "stale-doc-1",
                "text": "target text that should map to the approved row",
                "scope": "global",
                "lineage_key": "STY_STALE",
            }
        ],
    )

    response = client.post(
        f"/api/v1/index/verify/{verify_job_id}/retry",
        headers={"X-Idempotency-Key": "verify-review-style-stale-candidate"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VECTOR_VERIFY_FAILED"
    alias_after = get_alias_scope(client, "style_observation:global:global")
    assert alias_after["active_alias"] == active_alias_before
    assert alias_after["candidate_alias"] == alias_before["candidate_alias"]
    assert alias_after["verify_status"] == "failed"
