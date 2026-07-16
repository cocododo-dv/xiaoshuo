from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ReindexJob,
    ReviewItem,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
)
from novel_system.services.errors import DomainError
from novel_system.services.knowledge_registry import descriptor_for_object_type
from novel_system.services.versioning.base import VersioningServiceBase
from novel_system.services.versioning.shared import now_iso


class VectorLifecycleService(VersioningServiceBase):
    def run_reindex(self, job_id: str) -> dict[str, Any]:
        job = self.session.get(ReindexJob, job_id)
        if job is None:
            raise DomainError("REINDEX_JOB_NOT_FOUND", f"job {job_id} not found", status_code=404)
        review = self.session.get(ReviewItem, job.review_id) if job.review_id else None
        if review is None or not review.approved_item_row_id:
            raise DomainError("REVIEW_NOT_FOUND", f"review {job.review_id} not found", status_code=404)
        descriptor = descriptor_for_object_type(job.object_type)
        alias = self.session.get(VectorAliasRegistry, job.alias_scope)
        if alias is None or alias.candidate_alias is None:
            raise DomainError("VECTOR_ALIAS_NOT_FOUND", f"alias {job.alias_scope} not found", status_code=404)

        job.status = "running"
        job.worker_id = "reindex-worker"
        job.attempt_no += 1
        job.started_at = now_iso()
        job.heartbeat_at = now_iso()
        job.lease_expires_at = (datetime.now(UTC) + timedelta(seconds=180)).isoformat()
        self._ensure_job_targets_current(job, alias)

        approved_row = self.session.get(descriptor.model_cls, review.approved_item_row_id)
        scope_column = getattr(descriptor.model_cls, "scope")
        scope_ref_column = getattr(descriptor.model_cls, "scope_ref_id")
        active_rows = self.session.execute(
            select(descriptor.model_cls).where(
                descriptor.model_cls.active_flag == 1,
                descriptor.model_cls.runtime_eligible == 1,
                scope_column == alias.scope,
                scope_ref_column == alias.scope_ref_id,
            )
        ).scalars().all()
        documents = [self._vector_document(descriptor, row) for row in active_rows]
        if approved_row is not None and approved_row.row_id not in {item["id"] for item in documents}:
            documents.append(self._vector_document(descriptor, approved_row))
        self.vector_store.write_collection(alias.candidate_alias, documents)
        job.status = "succeeded"
        job.finished_at = now_iso()
        registry = self._registry_for_row(approved_row.row_id)
        if registry is not None:
            registry.reindex_status = "succeeded"
            registry.reindexed_at = now_iso()
        return {"job_id": job_id, "status": "succeeded"}

    def run_verify(self, job_id: str) -> dict[str, Any]:
        job = self.session.get(VerifyJob, job_id)
        if job is None:
            raise DomainError("VERIFY_JOB_NOT_FOUND", f"job {job_id} not found", status_code=404)
        review = self.session.get(ReviewItem, job.review_id) if job.review_id else None
        if review is None or not review.approved_item_row_id:
            raise DomainError("REVIEW_NOT_FOUND", f"review {job.review_id} not found", status_code=404)
        descriptor = descriptor_for_object_type(job.object_type)

        expected_job_status = job.status
        expected_job_attempt_no = int(job.attempt_no or 0)
        job.status = "running"
        job.worker_id = "verify-worker"
        job.attempt_no += 1
        job.started_at = now_iso()
        job.heartbeat_at = now_iso()
        job.lease_expires_at = (datetime.now(UTC) + timedelta(seconds=180)).isoformat()

        alias = self.session.get(VectorAliasRegistry, job.alias_scope)
        if alias is None or alias.candidate_alias is None:
            raise DomainError("VECTOR_ALIAS_NOT_FOUND", f"alias {job.alias_scope} not found", status_code=404)
        self._ensure_job_targets_current(job, alias)

        approved_row = self.session.get(descriptor.model_cls, review.approved_item_row_id)
        if approved_row is None:
            raise DomainError("APPROVED_ROW_NOT_FOUND", f"row {review.approved_item_row_id} not found", status_code=404)

        probe_text = getattr(approved_row, descriptor.text_field)
        candidate_documents = self.vector_store.load_collection(alias.candidate_alias)
        results = self.vector_store.query(
            alias.candidate_alias,
            probe_text,
            top_k=max(3, len(candidate_documents)),
        )
        registry = self._registry_for_row(approved_row.row_id)
        if registry is None:
            raise DomainError("VERSION_REGISTRY_NOT_FOUND", f"registry missing for {approved_row.row_id}", status_code=404)

        result_ids = {item.get("id") for item in results}
        if not results or approved_row.row_id not in result_ids:
            raise DomainError(
                "VECTOR_VERIFY_FAILED",
                "candidate alias verify failed",
                status_code=409,
                details={
                    "job_id": job.job_id,
                    "alias_scope": alias.alias_scope,
                    "approved_row_id": approved_row.row_id,
                    "candidate_alias": alias.candidate_alias,
                    "target_snapshot_version": job.target_snapshot_version,
                    "target_embedding_version": job.target_embedding_version,
                    "expected_job_status": expected_job_status,
                    "expected_job_attempt_no": expected_job_attempt_no,
                    "failed_job_worker_id": job.worker_id,
                    "failed_job_attempt_no": job.attempt_no,
                    "failed_job_started_at": job.started_at,
                    "failed_job_heartbeat_at": job.heartbeat_at,
                    "failed_job_lease_expires_at": job.lease_expires_at,
                    "expected_alias_verify_status": alias.verify_status,
                    "expected_alias_sample_query_success": alias.sample_query_success,
                    "expected_registry_verify_status": registry.verify_status,
                    "expected_registry_sample_query_success": registry.sample_query_success,
                },
            )

        alias.verify_status = "succeeded"
        alias.sample_query_success = 1
        registry.verify_status = "succeeded"
        registry.sample_query_success = 1
        registry.reindexed_at = registry.reindexed_at or now_iso()
        job.status = "succeeded"
        job.finished_at = now_iso()

        if review.active_on_approve == 1 and self._is_due_for_activation(getattr(approved_row, "effective_at", None)):
            self._flip_alias_for_row(descriptor, approved_row, alias)
            self._record_runtime_activity(
                event_type="runtime_auto_promotion",
                object_ref=approved_row.row_id,
                actor_ref="system/verify_auto_promotion",
                summary="auto promoted verified active-on-approve candidate",
                review_id=review.review_id,
                job_id=job.job_id,
                alias_scope=alias.alias_scope,
                row_id=approved_row.row_id,
            )

        return {"job_id": job_id, "status": "succeeded", "alias_scope": alias.alias_scope}

    @classmethod
    def publish_owned_verify_failure(cls, session: Session, error: DomainError) -> bool:
        """Publish verify failure state after the idempotency owner CAS.

        The failed action has already been rolled back when this callback runs.
        We therefore reload and lock the exact job, alias, and registry rows
        described by the failure. A superseded candidate or already successful
        verification is left untouched. The idempotency boundary owns commit.
        """

        if error.code != "VECTOR_VERIFY_FAILED":
            return False
        details = error.details or {}
        required = {
            "job_id",
            "alias_scope",
            "approved_row_id",
            "candidate_alias",
            "target_snapshot_version",
            "target_embedding_version",
            "expected_job_status",
            "expected_job_attempt_no",
            "failed_job_worker_id",
            "failed_job_attempt_no",
            "failed_job_started_at",
            "failed_job_heartbeat_at",
            "failed_job_lease_expires_at",
            "expected_alias_verify_status",
            "expected_alias_sample_query_success",
            "expected_registry_verify_status",
            "expected_registry_sample_query_success",
        }
        if not required.issubset(details):
            return False

        job = session.execute(
            select(VerifyJob)
            .where(VerifyJob.job_id == str(details["job_id"]))
            .with_for_update()
        ).scalar_one_or_none()
        alias = session.execute(
            select(VectorAliasRegistry)
            .where(VectorAliasRegistry.alias_scope == str(details["alias_scope"]))
            .with_for_update()
        ).scalar_one_or_none()
        registry = session.execute(
            select(VersionRegistry)
            .where(VersionRegistry.physical_row_id == str(details["approved_row_id"]))
            .with_for_update()
        ).scalar_one_or_none()

        if job is None or alias is None or registry is None:
            return False
        expected_snapshot = str(details["target_snapshot_version"])
        expected_embedding = str(details["target_embedding_version"])
        if (
            job.alias_scope != str(details["alias_scope"])
            or job.target_snapshot_version != expected_snapshot
            or job.target_embedding_version != expected_embedding
            or alias.candidate_alias != str(details["candidate_alias"])
            or alias.candidate_snapshot_version != expected_snapshot
            or alias.candidate_embedding_version != expected_embedding
            or job.status != str(details["expected_job_status"])
            or int(job.attempt_no or 0) != int(details["expected_job_attempt_no"])
            or alias.verify_status != str(details["expected_alias_verify_status"])
            or alias.sample_query_success != int(details["expected_alias_sample_query_success"])
            or registry.verify_status != str(details["expected_registry_verify_status"])
            or registry.sample_query_success != int(details["expected_registry_sample_query_success"])
        ):
            return False

        service = cls(session)
        service._mark_verify_failed(
            job,
            alias,
            registry,
            approved_row_id=str(details["approved_row_id"]),
        )
        job.worker_id = str(details["failed_job_worker_id"])
        job.attempt_no = int(details["failed_job_attempt_no"])
        job.started_at = str(details["failed_job_started_at"])
        job.heartbeat_at = str(details["failed_job_heartbeat_at"])
        job.lease_expires_at = str(details["failed_job_lease_expires_at"])
        job.error_text = error.message
        return True
