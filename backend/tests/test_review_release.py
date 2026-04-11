from __future__ import annotations

import pytest
from sqlalchemy import select

from novel_system.db.models import OperationLog, StyleObservation
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
    effective_at: str | None = None,
) -> str:
    candidate_payload = {
        "scope": scope,
        "scope_ref_id": scope_ref_id,
        "lineage_key": lineage_key,
        "text": candidate_text,
    }
    if effective_at is not None:
        candidate_payload["effective_at"] = effective_at

    response = client.post(
        "/api/v1/review-items/import-demo",
        json={
            "review_id": review_id,
            "scene_id": "CH001_SC01",
            "chapter_id": "CH001",
            "item_type": "style_observation",
            "candidate_text": candidate_text,
            "candidate_payload_json": candidate_payload,
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


def promote_active_alias(client) -> str:
    review_id = import_style_review(
        client,
        review_id="review_style_active_alias",
        lineage_key="STY_ACTIVE_ALIAS",
        candidate_text="keep the currently active note serving the runtime lane",
        active_on_approve=1,
    )
    approve_review(client, review_id, idempotency_key="approve-review-style-active-alias")
    verify_review(client, review_id, idempotency_key="verify-review-style-active-alias")
    alias = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]
    return alias["active_alias"]


def expected_global_collection_alias(approved_row_id: str) -> str:
    return f"style_observation_global_global__candidate__{approved_row_id}"


def expected_snapshot_version(approved_row_id: str) -> str:
    return f"snapshot__{approved_row_id}"


def expected_embedding_version(approved_row_id: str) -> str:
    return f"embed__{approved_row_id}"


def job_ids_for_review(client, review_id: str) -> dict[str, str]:
    jobs = client.get("/api/v1/index/jobs").json()["data"]["items"]
    result: dict[str, str] = {}
    for job in jobs:
        if job["review_id"] == review_id:
            result[job["job_type"]] = job["job_id"]
    return result


def test_release_promotes_verified_candidate(client) -> None:
    review_id = import_style_review(
        client,
        review_id="review_style_release",
        lineage_key="STY_RELEASE",
        candidate_text="leave the final beat hanging at the door",
    )
    approved_row_id = approve_review(client, review_id, idempotency_key="approve-review-style-release")
    verify_review(client, review_id, idempotency_key="verify-review-style-release")

    released = client.post(
        f"/api/v1/review-items/{review_id}/release",
        headers={"X-Idempotency-Key": "release-review-style-release"},
    )
    assert released.status_code == 200

    detail = client.get("/api/v1/index/alias-scopes/style_observation:global:global")
    data = detail.json()["data"]
    assert data["active_alias"] == expected_global_collection_alias(approved_row_id)
    assert data["candidate_alias"] is None
    assert data["active_snapshot_version"] == expected_snapshot_version(approved_row_id)
    assert data["active_embedding_version"] == expected_embedding_version(approved_row_id)
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


def test_verify_future_effective_candidate_keeps_old_alias_until_due_promotion(client, session) -> None:
    active_alias_before = promote_active_alias(client)
    review_id = import_style_review(
        client,
        review_id="review_style_future_effective",
        lineage_key="STY_FUTURE_EFFECTIVE",
        candidate_text="this note should land on the next publishing window",
        active_on_approve=1,
        effective_at="2099-01-01T00:00:00+00:00",
    )
    approved_row_id = approve_review(
        client,
        review_id,
        idempotency_key="approve-review-style-future-effective",
    )
    verify_review(client, review_id, idempotency_key="verify-review-style-future-effective")

    alias = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]
    session.expire_all()
    approved_row = session.get(StyleObservation, approved_row_id)

    assert alias["active_alias"] == active_alias_before
    assert alias["candidate_alias"] == expected_global_collection_alias(approved_row_id)
    assert alias["candidate_alias"] != active_alias_before
    assert alias["candidate_snapshot_version"] == expected_snapshot_version(approved_row_id)
    assert alias["candidate_embedding_version"] == expected_embedding_version(approved_row_id)
    assert alias["active_snapshot_version"] != alias["candidate_snapshot_version"]
    assert alias["active_embedding_version"] != alias["candidate_embedding_version"]
    assert alias["verify_status"] == "succeeded"
    assert approved_row is not None
    assert approved_row.active_flag == 0
    assert approved_row.runtime_eligible == 0
    assert approved_row.runtime_eligibility_basis == "future_effective"
    assert approved_row.effective_at == "2099-01-01T00:00:00+00:00"


def test_run_due_promotions_flips_verified_future_effective_candidate_when_due(client, session) -> None:
    active_alias_before = promote_active_alias(client)
    review_id = import_style_review(
        client,
        review_id="review_style_due_promotion",
        lineage_key="STY_DUE_PROMOTION",
        candidate_text="this note should activate once the due window arrives",
        active_on_approve=1,
        effective_at="2099-01-01T00:00:00+00:00",
    )
    approved_row_id = approve_review(
        client,
        review_id,
        idempotency_key="approve-review-style-due-promotion",
    )
    verify_review(client, review_id, idempotency_key="verify-review-style-due-promotion")

    session.expire_all()
    approved_row = session.get(StyleObservation, approved_row_id)
    assert approved_row is not None
    approved_row.effective_at = "2000-01-01T00:00:00+00:00"
    session.commit()

    promoted = client.post(
        "/api/v1/runtime/promotions/run-due",
        headers={
            "X-Idempotency-Key": "run-due-promotions",
            "X-Operator-Ref": "ops.duwei",
        },
    )

    assert promoted.status_code == 200
    data = promoted.json()["data"]
    assert data["actor_ref"] == "ops.duwei"
    assert data["promoted"] == 1
    assert data["promoted_review_ids"] == [review_id]
    assert data["promoted_review_targets"] == [
        {
            "review_id": review_id,
            "target": {
                "target_type": "review_item",
                "target_id": review_id,
                "target_ref": f"review_item:{review_id}",
            },
        }
    ]
    runtime_logs = session.execute(
        select(OperationLog)
        .where(OperationLog.object_type == "runtime_activity")
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    assert runtime_logs[-1].event_type == "runtime_due_promotion"
    assert runtime_logs[-1].payload_json["actor_ref"] == "system/due_promotion"
    assert runtime_logs[-1].payload_json["review_id"] == review_id

    alias = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]
    session.expire_all()
    approved_row = session.get(StyleObservation, approved_row_id)

    assert alias["active_alias"] == expected_global_collection_alias(approved_row_id)
    assert alias["active_alias"] != active_alias_before
    assert alias["candidate_alias"] is None
    assert alias["active_snapshot_version"] == expected_snapshot_version(approved_row_id)
    assert alias["active_embedding_version"] == expected_embedding_version(approved_row_id)
    assert alias["verify_status"] == "succeeded"
    assert approved_row is not None
    assert approved_row.active_flag == 1
    assert approved_row.runtime_eligible == 1
    assert approved_row.runtime_eligibility_basis == "vector_ready"


def test_verify_rejects_stale_job_target_after_new_candidate_claim(client) -> None:
    promote_active_alias(client)

    review_id_old = import_style_review(
        client,
        review_id="review_style_old_candidate",
        lineage_key="STY_OLD_CANDIDATE",
        candidate_text="old candidate text should not verify the new candidate",
        active_on_approve=1,
    )
    approve_review(client, review_id_old, idempotency_key="approve-review-style-old-candidate")
    old_jobs = job_ids_for_review(client, review_id_old)

    review_id_new = import_style_review(
        client,
        review_id="review_style_new_candidate",
        lineage_key="STY_NEW_CANDIDATE",
        candidate_text="new candidate text owns the current collection",
        active_on_approve=1,
    )
    new_row_id = approve_review(client, review_id_new, idempotency_key="approve-review-style-new-candidate")

    alias_before = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]
    assert alias_before["candidate_alias"] == expected_global_collection_alias(new_row_id)
    assert alias_before["candidate_snapshot_version"] == expected_snapshot_version(new_row_id)
    assert alias_before["candidate_embedding_version"] == expected_embedding_version(new_row_id)

    response = client.post(
        f"/api/v1/index/verify/{old_jobs['verify']}/retry",
        headers={"X-Idempotency-Key": "verify-review-style-old-candidate"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INDEX_JOB_TARGET_STALE"

    alias_after = client.get("/api/v1/index/alias-scopes/style_observation:global:global").json()["data"]
    assert alias_after == alias_before


