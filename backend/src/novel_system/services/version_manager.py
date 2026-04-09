from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ReconcileFault,
    ReindexJob,
    ReviewItem,
    StyleObservation,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
)
from novel_system.services.errors import DomainError
from novel_system.services.vector_store import VectorStore, get_vector_store


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class VersionManager:
    def __init__(self, session: Session, vector_store: VectorStore | None = None) -> None:
        self.session = session
        self.vector_store = vector_store or get_vector_store()

    @staticmethod
    def _style_observation_document(row: StyleObservation) -> dict[str, str | None]:
        return {
            "id": row.row_id,
            "text": row.text,
            "scope": row.scope,
            "lineage_key": row.style_observation_id,
            "scope_ref_id": row.scope_ref_id,
        }

    def _mark_verify_failed(
        self,
        job: VerifyJob,
        alias: VectorAliasRegistry,
        registry: VersionRegistry,
        *,
        approved_row_id: str,
    ) -> None:
        job.status = "failed"
        job.finished_at = now_iso()
        alias.verify_status = "failed"
        alias.sample_query_success = 0
        registry.verify_status = "failed"
        registry.sample_query_success = 0
        self.session.add(
            ReconcileFault(
                fault_scope="alias_mismatch",
                severity="blocking",
                object_ref=alias.alias_scope,
                details_json={
                    "candidate_alias": alias.candidate_alias,
                    "approved_row_id": approved_row_id,
                },
            )
        )

    def materialize_review(self, review_id: str) -> dict:
        review = self.session.get(ReviewItem, review_id)
        if review is None:
            raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)

        review.status = "approved"
        payload = review.candidate_payload_json
        scope = payload.get("scope", "global")
        scope_ref_id = payload.get("scope_ref_id", "global")
        lineage_key = payload.get("lineage_key", review.review_id)
        alias_scope = f"style_observation:{scope}:{scope_ref_id or 'global'}"
        version = (
            self.session.execute(
                select(func.max(StyleObservation.version)).where(
                    StyleObservation.style_observation_id == lineage_key
                )
            ).scalar_one_or_none()
            or 0
        ) + 1
        row_id = f"style_observation_{lineage_key}_v{version}"
        item = StyleObservation(
            row_id=row_id,
            style_observation_id=lineage_key,
            version=version,
            scope=scope,
            scope_ref_id=scope_ref_id,
            text=payload.get("text", review.candidate_text),
            source_review_id=review_id,
            active_flag=0,
            runtime_eligible=0,
            runtime_eligibility_basis="manual_hold" if review.active_on_approve == 0 else "stage_blocked",
        )
        self.session.add(item)

        registry = VersionRegistry(
            object_type="style_observation",
            lineage_key=lineage_key,
            version=version,
            physical_row_id=row_id,
            alias_scope=alias_scope,
            materialize_status="succeeded",
            reindex_status="queued",
            verify_status="pending",
            approved_at=now_iso(),
            materialized_at=now_iso(),
        )
        self.session.add(registry)

        alias = self.session.get(VectorAliasRegistry, alias_scope)
        collection_family = f"style_observation_{scope}_{scope_ref_id or 'global'}"
        candidate_alias = f"{collection_family}_candidate_v{version}"
        if alias is None:
            alias = VectorAliasRegistry(
                alias_scope=alias_scope,
                object_type="style_observation",
                scope=scope,
                scope_ref_id=scope_ref_id,
                collection_family=collection_family,
                active_alias=None,
                candidate_alias=candidate_alias,
                active_snapshot_version=None,
                candidate_snapshot_version=f"snapshot_v{version}",
                active_embedding_version=None,
                candidate_embedding_version=f"embed_v{version}",
                verify_status="pending",
                sample_query_success=0,
            )
            self.session.add(alias)
        else:
            alias.candidate_alias = candidate_alias
            alias.candidate_snapshot_version = f"snapshot_v{version}"
            alias.candidate_embedding_version = f"embed_v{version}"
            alias.verify_status = "pending"

        reindex_job = ReindexJob(
            job_id=f"reindex_{review_id}",
            review_id=review_id,
            status="queued",
            object_type="style_observation",
            alias_scope=alias_scope,
            target_snapshot_version=alias.candidate_snapshot_version or f"snapshot_v{version}",
            target_embedding_version=alias.candidate_embedding_version or f"embed_v{version}",
        )
        verify_job = VerifyJob(
            job_id=f"verify_{review_id}",
            review_id=review_id,
            status="queued",
            object_type="style_observation",
            alias_scope=alias_scope,
            target_snapshot_version=alias.candidate_snapshot_version or f"snapshot_v{version}",
            target_embedding_version=alias.candidate_embedding_version or f"embed_v{version}",
        )
        self.session.add(reindex_job)
        self.session.add(verify_job)

        review.materialize_status = "succeeded"
        review.approved_item_row_id = row_id
        review.approved_item_id = lineage_key

        self.session.flush()
        self._run_reindex(reindex_job.job_id)
        return {"review_id": review_id, "materialize_status": review.materialize_status, "approved_item_row_id": row_id}

    def _run_reindex(self, job_id: str) -> dict:
        job = self.session.get(ReindexJob, job_id)
        review = self.session.get(ReviewItem, job.review_id) if job.review_id else None
        alias = self.session.get(VectorAliasRegistry, job.alias_scope)
        job.status = "running"
        job.worker_id = "reindex-worker"
        job.attempt_no += 1
        job.started_at = now_iso()
        job.heartbeat_at = now_iso()
        job.lease_expires_at = (datetime.now(UTC) + timedelta(seconds=180)).isoformat()

        approved_row = self.session.get(StyleObservation, review.approved_item_row_id) if review else None
        active_rows = self.session.execute(
            select(StyleObservation).where(
                StyleObservation.active_flag == 1,
                StyleObservation.runtime_eligible == 1,
                StyleObservation.scope == alias.scope,
                StyleObservation.scope_ref_id == alias.scope_ref_id,
            )
        ).scalars().all()
        documents = [self._style_observation_document(row) for row in active_rows]
        if approved_row is not None:
            documents.append(self._style_observation_document(approved_row))
        self.vector_store.write_collection(alias.candidate_alias, documents)
        job.status = "succeeded"
        job.finished_at = now_iso()
        registry = self.session.execute(
            select(VersionRegistry).where(VersionRegistry.physical_row_id == approved_row.row_id)
        ).scalar_one()
        registry.reindex_status = "succeeded"
        registry.reindexed_at = now_iso()
        return {"job_id": job_id, "status": "succeeded"}

    def run_verify(self, job_id: str) -> dict:
        job = self.session.get(VerifyJob, job_id)
        if job is None:
            raise DomainError("VERIFY_JOB_NOT_FOUND", f"job {job_id} not found", status_code=404)
        job.status = "running"
        job.worker_id = "verify-worker"
        job.attempt_no += 1
        job.started_at = now_iso()
        job.heartbeat_at = now_iso()
        job.lease_expires_at = (datetime.now(UTC) + timedelta(seconds=180)).isoformat()

        review = self.session.get(ReviewItem, job.review_id) if job.review_id else None
        alias = self.session.get(VectorAliasRegistry, job.alias_scope)
        approved_row = self.session.get(StyleObservation, review.approved_item_row_id) if review else None
        probe_text = approved_row.text if approved_row else ""
        candidate_documents = self.vector_store.load_collection(alias.candidate_alias) if alias.candidate_alias else []
        results = self.vector_store.query(
            alias.candidate_alias,
            probe_text,
            top_k=max(3, len(candidate_documents)),
        )
        registry = self.session.execute(
            select(VersionRegistry).where(VersionRegistry.physical_row_id == approved_row.row_id)
        ).scalar_one()

        result_ids = {item.get("id") for item in results}
        if not results or approved_row.row_id not in result_ids:
            self._mark_verify_failed(job, alias, registry, approved_row_id=approved_row.row_id)
            raise DomainError("VECTOR_VERIFY_FAILED", "candidate alias verify failed", status_code=409)

        alias.verify_status = "succeeded"
        alias.sample_query_success = 1
        registry.verify_status = "succeeded"
        registry.sample_query_success = 1
        registry.reindexed_at = registry.reindexed_at or now_iso()
        job.status = "succeeded"
        job.finished_at = now_iso()

        if review and review.active_on_approve == 1:
            self._flip_alias_for_review(review, alias)

        return {"job_id": job_id, "status": "succeeded", "alias_scope": alias.alias_scope}

    def release_review(self, review_id: str) -> dict:
        review = self.session.get(ReviewItem, review_id)
        if review is None:
            raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)
        if review.status != "approved" or review.materialize_status != "succeeded" or not review.approved_item_row_id:
            raise DomainError("RELEASE_PRECONDITION_FAILED", "review is not ready for release", status_code=409)

        approved_row = self.session.get(StyleObservation, review.approved_item_row_id)
        registry = self.session.execute(
            select(VersionRegistry).where(VersionRegistry.physical_row_id == approved_row.row_id)
        ).scalar_one()
        if registry.verify_status != "succeeded":
            raise DomainError("RELEASE_PRECONDITION_FAILED", "candidate is not verified", status_code=409)

        alias = self.session.get(
            VectorAliasRegistry, f"style_observation:{approved_row.scope}:{approved_row.scope_ref_id or 'global'}"
        )
        if (
            alias.candidate_alias is None
            or alias.candidate_snapshot_version is None
            or alias.candidate_embedding_version is None
        ):
            raise DomainError("RELEASE_PRECONDITION_FAILED", "candidate is not ready for release", status_code=409)
        self._flip_alias_for_review(review, alias)
        return {"review_id": review_id, "released": True}

    def _flip_alias_for_review(self, review: ReviewItem, alias: VectorAliasRegistry) -> None:
        approved_row = self.session.get(StyleObservation, review.approved_item_row_id)
        old_rows = self.session.execute(
            select(StyleObservation).where(StyleObservation.style_observation_id == approved_row.style_observation_id)
        ).scalars().all()
        for row in old_rows:
            row.active_flag = 0
            row.runtime_eligible = 0
        approved_row.active_flag = 1
        approved_row.runtime_eligible = 1
        approved_row.runtime_eligibility_basis = "vector_ready"
        if (
            alias.candidate_alias is None
            or alias.candidate_snapshot_version is None
            or alias.candidate_embedding_version is None
        ):
            raise DomainError(
                "ALIAS_FLIP_PRECONDITION_FAILED",
                "candidate alias is not ready for activation",
                status_code=409,
            )
        alias.active_alias = alias.candidate_alias
        alias.candidate_alias = None
        alias.active_snapshot_version = alias.candidate_snapshot_version
        alias.candidate_snapshot_version = None
        alias.active_embedding_version = alias.candidate_embedding_version
        alias.candidate_embedding_version = None
        alias.verify_status = "succeeded"
        registry = self.session.execute(
            select(VersionRegistry).where(VersionRegistry.physical_row_id == approved_row.row_id)
        ).scalar_one()
        registry.activated_at = now_iso()
        registry.verify_status = "succeeded"

    def recover_stuck_jobs(self) -> dict:
        reclaimed_jobs = 0
        for job in self.session.execute(select(VerifyJob).where(VerifyJob.status == "running")).scalars().all():
            if job.lease_expires_at and job.lease_expires_at <= now_iso():
                job.status = "queued"
                job.worker_id = None
                job.heartbeat_at = None
                job.lease_expires_at = None
                reclaimed_jobs += 1
        return {
            "reclaimed_jobs": reclaimed_jobs,
            "failed_jobs": 0,
            "reclaimed_idempotency_keys": 0,
            "failed_idempotency_keys": 0,
            "created_human_review_events": 0,
        }
