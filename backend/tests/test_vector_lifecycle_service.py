from __future__ import annotations

import pytest
from sqlalchemy import select

from novel_system.db.models import (
    HumanReviewEvent,
    IdempotencyKey,
    ReconcileFault,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
)
from novel_system.services.errors import DomainError
from novel_system.services.versioning import VectorLifecycleService
from novel_system.services.vector_store import get_vector_store
from tests.test_review_release import (
    approve_review,
    expected_global_collection_alias,
    get_alias_scope,
    import_style_review,
    job_ids_for_review,
    promote_active_alias,
    verify_review,
)


def test_run_reindex_rejects_stale_job_target_after_new_candidate_claim(client, session) -> None:
    promote_active_alias(client)

    review_id_old = import_style_review(
        client,
        review_id="review_style_old_reindex_service",
        lineage_key="STY_OLD_REINDEX_SERVICE",
        candidate_text="old reindex should not overwrite the new collection",
        active_on_approve=1,
    )
    approve_review(client, review_id_old, idempotency_key="approve-review-style-old-reindex-service")
    old_jobs = job_ids_for_review(client, review_id_old)

    review_id_new = import_style_review(
        client,
        review_id="review_style_new_reindex_service",
        lineage_key="STY_NEW_REINDEX_SERVICE",
        candidate_text="new reindex owns the current candidate collection",
        active_on_approve=1,
    )
    new_row_id = approve_review(client, review_id_new, idempotency_key="approve-review-style-new-reindex-service")

    alias_before = get_alias_scope(client, "style_observation:global:global")
    assert alias_before["candidate_alias"] == expected_global_collection_alias(new_row_id)
    documents_before = get_vector_store().load_collection(alias_before["candidate_alias"])
    indexed_ids_before = {item["id"] for item in documents_before}
    assert new_row_id in indexed_ids_before

    with pytest.raises(DomainError) as exc_info:
        VectorLifecycleService(session).run_reindex(old_jobs["reindex"])

    assert exc_info.value.code == "INDEX_JOB_TARGET_STALE"

    alias_after = get_alias_scope(client, "style_observation:global:global")
    documents_after = get_vector_store().load_collection(alias_after["candidate_alias"])
    indexed_ids_after = {item["id"] for item in documents_after}

    assert alias_after == alias_before
    assert indexed_ids_after == indexed_ids_before


def test_verify_failure_is_published_with_owned_cas_and_keeps_active_alias(client, session) -> None:
    active_alias_before = promote_active_alias(client)
    review_id = import_style_review(
        client,
        review_id="review_style_owned_verify_failure",
        lineage_key="STY_OWNED_VERIFY_FAILURE",
        candidate_text="",
        active_on_approve=1,
    )
    approved_row_id = approve_review(
        client,
        review_id,
        idempotency_key="approve-review-style-owned-verify-failure",
    )
    verify_job_id = job_ids_for_review(client, review_id)["verify"]

    response = client.post(
        f"/api/v1/index/verify/{verify_job_id}/retry",
        headers={"X-Idempotency-Key": "verify-review-style-owned-failure"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VECTOR_VERIFY_FAILED"
    session.expire_all()
    job = session.get(VerifyJob, verify_job_id)
    alias = session.get(VectorAliasRegistry, "style_observation:global:global")
    registry = session.execute(
        select(VersionRegistry).where(VersionRegistry.physical_row_id == approved_row_id)
    ).scalar_one()
    fault = session.execute(
        select(ReconcileFault)
        .where(
            ReconcileFault.fault_scope == "alias_mismatch",
            ReconcileFault.object_ref == "style_observation:global:global",
        )
        .order_by(ReconcileFault.fault_id.desc())
    ).scalars().first()
    idempotency = session.get(IdempotencyKey, "verify-review-style-owned-failure")

    assert job is not None
    assert alias is not None
    assert fault is not None
    assert idempotency is not None
    assert job.status == "failed"
    assert job.worker_id == "verify-worker"
    assert job.attempt_no == 1
    assert job.error_text == "candidate alias verify failed"
    assert alias.active_alias == active_alias_before
    assert alias.candidate_alias is not None
    assert alias.verify_status == "failed"
    assert alias.sample_query_success == 0
    assert registry.verify_status == "failed"
    assert registry.sample_query_success == 0
    assert fault.details_json["candidate_alias"] == alias.candidate_alias
    assert fault.details_json["approved_row_id"] == approved_row_id
    assert idempotency.status == "failed"


def test_verify_failure_publisher_does_not_downgrade_a_superseding_candidate(client, session) -> None:
    active_alias_before = promote_active_alias(client)
    old_review_id = import_style_review(
        client,
        review_id="review_style_old_failure_intent",
        lineage_key="STY_OLD_FAILURE_INTENT",
        candidate_text="old candidate that later loses the alias claim",
        active_on_approve=1,
    )
    old_row_id = approve_review(
        client,
        old_review_id,
        idempotency_key="approve-review-style-old-failure-intent",
    )
    old_job_id = job_ids_for_review(client, old_review_id)["verify"]
    session.expire_all()
    old_job = session.get(VerifyJob, old_job_id)
    old_alias = session.get(VectorAliasRegistry, "style_observation:global:global")
    assert old_job is not None
    assert old_alias is not None
    stale_error = DomainError(
        "VECTOR_VERIFY_FAILED",
        "candidate alias verify failed",
        status_code=409,
        details={
            "job_id": old_job.job_id,
            "alias_scope": old_alias.alias_scope,
            "approved_row_id": old_row_id,
            "candidate_alias": old_alias.candidate_alias,
            "target_snapshot_version": old_job.target_snapshot_version,
            "target_embedding_version": old_job.target_embedding_version,
            "expected_job_status": old_job.status,
            "expected_job_attempt_no": old_job.attempt_no,
            "failed_job_worker_id": "verify-worker",
            "failed_job_attempt_no": old_job.attempt_no + 1,
            "failed_job_started_at": "2026-07-16T00:00:00+00:00",
            "failed_job_heartbeat_at": "2026-07-16T00:00:00+00:00",
            "failed_job_lease_expires_at": "2026-07-16T00:03:00+00:00",
            "expected_alias_verify_status": old_alias.verify_status,
            "expected_alias_sample_query_success": old_alias.sample_query_success,
            "expected_registry_verify_status": "pending",
            "expected_registry_sample_query_success": 0,
        },
    )

    new_review_id = import_style_review(
        client,
        review_id="review_style_new_failure_intent",
        lineage_key="STY_NEW_FAILURE_INTENT",
        candidate_text="new candidate now owns the alias claim",
        active_on_approve=1,
    )
    new_row_id = approve_review(
        client,
        new_review_id,
        idempotency_key="approve-review-style-new-failure-intent",
    )
    session.expire_all()

    published = VectorLifecycleService.publish_owned_verify_failure(session, stale_error)
    session.commit()
    session.expire_all()

    alias = session.get(VectorAliasRegistry, "style_observation:global:global")
    old_job = session.get(VerifyJob, old_job_id)
    old_registry = session.execute(
        select(VersionRegistry).where(VersionRegistry.physical_row_id == old_row_id)
    ).scalar_one()
    faults = session.execute(
        select(ReconcileFault).where(
            ReconcileFault.fault_scope == "alias_mismatch",
            ReconcileFault.object_ref == "style_observation:global:global",
        )
    ).scalars().all()

    assert published is False
    assert alias is not None
    assert old_job is not None
    assert alias.active_alias == active_alias_before
    assert alias.candidate_alias == expected_global_collection_alias(new_row_id)
    assert alias.verify_status == "pending"
    assert old_job.status == "queued"
    assert old_registry.verify_status == "pending"
    assert faults == []


def test_human_review_verify_retry_uses_the_same_owned_failure_publisher(client, session) -> None:
    active_alias_before = promote_active_alias(client)
    review_id = import_style_review(
        client,
        review_id="review_style_human_retry_failure",
        lineage_key="STY_HUMAN_RETRY_FAILURE",
        candidate_text="",
        active_on_approve=1,
    )
    approved_row_id = approve_review(
        client,
        review_id,
        idempotency_key="approve-review-style-human-retry-failure",
    )
    verify_job_id = job_ids_for_review(client, review_id)["verify"]
    event_id = "human_review_verify_failure_publish"
    session.add(
        HumanReviewEvent(
            event_id=event_id,
            object_ref=verify_job_id,
            event_source="idempotency_recovery",
            priority="high",
            status="needs_followup",
            allowed_actions_json=["retry_verify"],
            result_status_map_json={"retry_verify": "needs_followup"},
            details_json={
                "followup_action": "retry_verify",
                "followup_target_type": "verify_job",
                "followup_target_id": verify_job_id,
                "followup_target_ref": f"verify_job:{verify_job_id}",
            },
            default_action="retry_verify",
        )
    )
    session.commit()

    response = client.post(
        f"/api/v1/human-review-events/{event_id}/actions",
        json={"action": "retry_verify"},
        headers={"X-Idempotency-Key": "human-review-verify-failure-publish"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VECTOR_VERIFY_FAILED"
    session.expire_all()
    event = session.get(HumanReviewEvent, event_id)
    job = session.get(VerifyJob, verify_job_id)
    alias = session.get(VectorAliasRegistry, "style_observation:global:global")
    registry = session.execute(
        select(VersionRegistry).where(VersionRegistry.physical_row_id == approved_row_id)
    ).scalar_one()
    fault = session.execute(
        select(ReconcileFault).where(
            ReconcileFault.fault_scope == "alias_mismatch",
            ReconcileFault.object_ref == "style_observation:global:global",
        )
    ).scalars().first()

    assert event is not None
    assert job is not None
    assert alias is not None
    assert fault is not None
    assert event.status == "needs_followup"
    assert job.status == "failed"
    assert alias.active_alias == active_alias_before
    assert alias.verify_status == "failed"
    assert registry.verify_status == "failed"


def test_later_reverify_failure_can_downgrade_the_same_previously_verified_candidate(client, session) -> None:
    active_alias_before = promote_active_alias(client)
    review_id = import_style_review(
        client,
        review_id="review_style_reverify_failure",
        lineage_key="STY_REVERIFY_FAILURE",
        candidate_text="candidate remains staged until its future effective window",
        active_on_approve=1,
        effective_at="2099-01-01T00:00:00+00:00",
    )
    approved_row_id = approve_review(
        client,
        review_id,
        idempotency_key="approve-review-style-reverify-failure",
    )
    verify_review(
        client,
        review_id,
        idempotency_key="verify-review-style-reverify-success",
    )
    verify_job_id = job_ids_for_review(client, review_id)["verify"]
    alias_before = get_alias_scope(client, "style_observation:global:global")
    assert alias_before["active_alias"] == active_alias_before
    assert alias_before["verify_status"] == "succeeded"
    get_vector_store().write_collection(alias_before["candidate_alias"], [])

    response = client.post(
        f"/api/v1/index/verify/{verify_job_id}/retry",
        headers={"X-Idempotency-Key": "verify-review-style-reverify-failure"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VECTOR_VERIFY_FAILED"
    session.expire_all()
    job = session.get(VerifyJob, verify_job_id)
    alias = session.get(VectorAliasRegistry, "style_observation:global:global")
    registry = session.execute(
        select(VersionRegistry).where(VersionRegistry.physical_row_id == approved_row_id)
    ).scalar_one()
    assert job is not None
    assert alias is not None
    assert job.status == "failed"
    assert job.attempt_no == 2
    assert alias.active_alias == active_alias_before
    assert alias.candidate_alias == alias_before["candidate_alias"]
    assert alias.verify_status == "failed"
    assert registry.verify_status == "failed"
