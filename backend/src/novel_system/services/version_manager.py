from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    HumanReviewEvent,
    IdempotencyKey,
    OperationLog,
    ReconcileFault,
    ReindexJob,
    ReviewItem,
    StyleObservation,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
)
from novel_system.services.errors import DomainError
from novel_system.services.human_review_support import recovery_action_contract, recovery_linked_target, structured_target
from novel_system.services.vector_store import VectorStore, get_vector_store


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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

    @staticmethod
    def _alias_scope_for_row(row: StyleObservation) -> str:
        return f"style_observation:{row.scope}:{row.scope_ref_id or 'global'}"

    @staticmethod
    def _collection_family_for_scope(scope: str, scope_ref_id: str | None) -> str:
        return f"style_observation_{scope}_{scope_ref_id or 'global'}"

    @staticmethod
    def _collection_alias_for_row(collection_family: str, row_id: str) -> str:
        return f"{collection_family}__candidate__{row_id}"

    @staticmethod
    def _snapshot_version_for_row(row_id: str) -> str:
        return f"snapshot__{row_id}"

    @staticmethod
    def _embedding_version_for_row(row_id: str) -> str:
        return f"embed__{row_id}"

    @staticmethod
    def _is_due_for_activation(effective_at: str | None) -> bool:
        parsed = parse_iso_datetime(effective_at)
        if parsed is None:
            return True
        return parsed <= datetime.now(UTC)

    @staticmethod
    def _job_type_for(job: ReindexJob | VerifyJob) -> str:
        return "reindex" if isinstance(job, ReindexJob) else "verify"

    @staticmethod
    def _job_target(job_id: str, job_type: str) -> dict[str, str]:
        target_type = "reindex_job" if job_type == "reindex" else "verify_job"
        return structured_target(target_type, job_id)  # type: ignore[return-value]

    @staticmethod
    def _review_target(review_id: str) -> dict[str, str]:
        return structured_target("review_item", review_id)  # type: ignore[return-value]

    @staticmethod
    def _human_review_event_target(event_id: str) -> dict[str, str]:
        return structured_target("human_review_event", event_id)  # type: ignore[return-value]

    @staticmethod
    def _safe_identifier_fragment(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
        return normalized or "item"

    def _human_review_event_id_for_idempotency_key(self, idempotency_key: str) -> str:
        return f"human_review_idempotency_recovery_{self._safe_identifier_fragment(idempotency_key)}"

    def _latest_idempotency_context(self, idempotency_key: str) -> dict[str, str | int | None]:
        log = self.session.execute(
            select(OperationLog)
            .where(
                OperationLog.object_type == "idempotency_key",
                OperationLog.object_ref == idempotency_key,
                OperationLog.event_type == "idempotency_started",
            )
            .order_by(OperationLog.created_at.desc(), OperationLog.operation_id.desc())
        ).scalars().first()
        payload = log.payload_json if log is not None else {}
        return {
            "request_hash": payload.get("request_hash"),
            "request_method": payload.get("request_method"),
            "request_path_template": payload.get("request_path_template"),
            "request_payload": payload.get("request_payload"),
            "attempt_no": payload.get("attempt_no"),
        }

    def _record_runtime_activity(
        self,
        *,
        event_type: str,
        object_ref: str,
        actor_ref: str,
        summary: str,
        **payload: str | int | None,
    ) -> None:
        self.session.add(
            OperationLog(
                event_type=event_type,
                object_type="runtime_activity",
                object_ref=object_ref,
                payload_json={
                    "actor_ref": actor_ref,
                    "summary": summary,
                    **{key: value for key, value in payload.items() if value is not None},
                },
            )
        )

    def _reclaim_expired_jobs(self, jobs: list[ReindexJob | VerifyJob]) -> list[dict[str, str | int | None]]:
        reclaimed_job_summaries: list[dict[str, str | int | None]] = []
        now = datetime.now(UTC)
        for job in jobs:
            lease_expires_at = parse_iso_datetime(job.lease_expires_at)
            if lease_expires_at is None or lease_expires_at > now:
                continue
            reclaimed_job_summaries.append(
                {
                    "job_id": job.job_id,
                    "job_type": self._job_type_for(job),
                    "alias_scope": job.alias_scope,
                    "target": self._job_target(job.job_id, self._job_type_for(job)),
                    "previous_worker_id": job.worker_id,
                    "attempt_no": job.attempt_no,
                    "previous_lease_expires_at": job.lease_expires_at,
                }
            )
            job.status = "queued"
            job.worker_id = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            self._record_runtime_activity(
                event_type="runtime_job_reclaimed",
                object_ref=job.job_id,
                actor_ref="system/recovery_sweep",
                summary=f"reclaimed stale {self._job_type_for(job)} lease",
                job_id=job.job_id,
                job_type=self._job_type_for(job),
                alias_scope=job.alias_scope,
                previous_worker_id=reclaimed_job_summaries[-1]["previous_worker_id"],
                attempt_no=reclaimed_job_summaries[-1]["attempt_no"],
                previous_lease_expires_at=reclaimed_job_summaries[-1]["previous_lease_expires_at"],
            )
        return reclaimed_job_summaries

    def _collect_failed_job_summaries(self) -> list[dict[str, str | None]]:
        failed_jobs = [
            *self.session.execute(select(ReindexJob).where(ReindexJob.status == "failed")).scalars().all(),
            *self.session.execute(select(VerifyJob).where(VerifyJob.status == "failed")).scalars().all(),
        ]
        failed_jobs.sort(
            key=lambda job: (
                parse_iso_datetime(job.finished_at) or datetime.min.replace(tzinfo=UTC),
                job.job_id,
            ),
            reverse=True,
        )
        return [
            {
                "job_id": job.job_id,
                "job_type": self._job_type_for(job),
                "alias_scope": job.alias_scope,
                "target": self._job_target(job.job_id, self._job_type_for(job)),
                "error_text": job.error_text,
                "finished_at": job.finished_at,
            }
            for job in failed_jobs
        ]

    def _recover_stale_idempotency_keys(
        self,
    ) -> tuple[list[dict[str, str | int | None]], list[str], list[dict[str, dict[str, str] | str]]]:
        reclaimed_summaries: list[dict[str, str | int | None]] = []
        created_event_ids: list[str] = []
        created_event_targets: list[dict[str, dict[str, str] | str]] = []
        now = datetime.now(UTC)
        records = self.session.execute(
            select(IdempotencyKey)
            .where(IdempotencyKey.status == "started")
            .order_by(IdempotencyKey.created_at.asc(), IdempotencyKey.idempotency_key.asc())
        ).scalars().all()

        for record in records:
            lease_expires_at = parse_iso_datetime(record.lease_expires_at)
            if lease_expires_at is None or lease_expires_at > now:
                continue
            context = self._latest_idempotency_context(record.idempotency_key)
            previous_worker_id = record.worker_id
            previous_lease_expires_at = record.lease_expires_at
            reclaimed_summaries.append(
                {
                    "idempotency_key": record.idempotency_key,
                    "previous_worker_id": previous_worker_id,
                    "attempt_no": record.attempt_no,
                    "previous_lease_expires_at": previous_lease_expires_at,
                }
            )
            record.status = "failed"
            record.worker_id = None
            record.heartbeat_at = None
            record.lease_expires_at = None

            event_id = self._human_review_event_id_for_idempotency_key(record.idempotency_key)
            if self.session.get(HumanReviewEvent, event_id) is None:
                allowed_actions, result_status_map, default_action = recovery_action_contract(
                    context.get("request_path_template")
                )
                linked_target = recovery_linked_target(
                    context.get("request_path_template"),
                    context.get("request_payload") or {},
                )
                self.session.add(
                    HumanReviewEvent(
                        event_id=event_id,
                        object_ref=record.idempotency_key,
                        event_source="idempotency_recovery",
                        priority="high",
                        status="open",
                        allowed_actions_json=allowed_actions,
                        result_status_map_json=result_status_map,
                        details_json={
                            "idempotency_key": record.idempotency_key,
                            "request_hash": context.get("request_hash") or record.request_hash,
                            "request_method": context.get("request_method"),
                            "request_path_template": context.get("request_path_template"),
                            "request_payload": context.get("request_payload") or {},
                            "created_by_ref": "system/recovery_sweep",
                            "created_reason": "stale_idempotency_key_recovered",
                            **{key: value for key, value in linked_target.items() if value is not None},
                            "attempt_no": record.attempt_no,
                            "previous_worker_id": previous_worker_id,
                            "previous_lease_expires_at": previous_lease_expires_at,
                        },
                        default_action=default_action,
                    )
                )
                created_event_ids.append(event_id)
                created_event_targets.append(
                    {
                        "event_id": event_id,
                        "target": self._human_review_event_target(event_id),
                    }
                )
                self._record_runtime_activity(
                    event_type="runtime_recovery_event_created",
                    object_ref=event_id,
                    actor_ref="system/recovery_sweep",
                    summary="created human review event for stale idempotency key",
                    event_id=event_id,
                    idempotency_key=record.idempotency_key,
                    request_path_template=context.get("request_path_template"),
                    linked_target_ref=linked_target.get("linked_target_ref"),
                )

        return reclaimed_summaries, created_event_ids, created_event_targets

    @staticmethod
    def _fail_stale_job(job: ReindexJob | VerifyJob, alias: VectorAliasRegistry) -> None:
        message = "job target no longer matches current candidate"
        job.status = "failed"
        job.finished_at = now_iso()
        job.error_text = message
        raise DomainError(
            "INDEX_JOB_TARGET_STALE",
            message,
            status_code=409,
            details={
                "alias_scope": alias.alias_scope,
                "job_id": job.job_id,
                "job_target_snapshot_version": job.target_snapshot_version,
                "job_target_embedding_version": job.target_embedding_version,
                "current_candidate_snapshot_version": alias.candidate_snapshot_version,
                "current_candidate_embedding_version": alias.candidate_embedding_version,
            },
        )

    def _ensure_job_targets_current(self, job: ReindexJob | VerifyJob, alias: VectorAliasRegistry) -> None:
        if (
            alias.candidate_snapshot_version != job.target_snapshot_version
            or alias.candidate_embedding_version != job.target_embedding_version
        ):
            self._fail_stale_job(job, alias)

    def materialize_review(self, review_id: str) -> dict:
        review = self.session.get(ReviewItem, review_id)
        if review is None:
            raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)

        review.status = "approved"
        payload = review.candidate_payload_json
        scope = payload.get("scope", "global")
        scope_ref_id = payload.get("scope_ref_id", "global")
        lineage_key = payload.get("lineage_key", review.review_id)
        effective_at = payload.get("effective_at")
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
            runtime_eligibility_basis=(
                "future_effective"
                if effective_at
                else "manual_hold" if review.active_on_approve == 0 else "stage_blocked"
            ),
            effective_at=effective_at,
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
        collection_family = self._collection_family_for_scope(scope, scope_ref_id)
        candidate_alias = self._collection_alias_for_row(collection_family, row_id)
        candidate_snapshot_version = self._snapshot_version_for_row(row_id)
        candidate_embedding_version = self._embedding_version_for_row(row_id)
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
                candidate_snapshot_version=candidate_snapshot_version,
                active_embedding_version=None,
                candidate_embedding_version=candidate_embedding_version,
                verify_status="pending",
                sample_query_success=0,
            )
            self.session.add(alias)
        else:
            alias.candidate_alias = candidate_alias
            alias.candidate_snapshot_version = candidate_snapshot_version
            alias.candidate_embedding_version = candidate_embedding_version
            alias.verify_status = "pending"

        reindex_job = ReindexJob(
            job_id=f"reindex_{review_id}",
            review_id=review_id,
            status="queued",
            object_type="style_observation",
            alias_scope=alias_scope,
            target_snapshot_version=alias.candidate_snapshot_version or candidate_snapshot_version,
            target_embedding_version=alias.candidate_embedding_version or candidate_embedding_version,
        )
        verify_job = VerifyJob(
            job_id=f"verify_{review_id}",
            review_id=review_id,
            status="queued",
            object_type="style_observation",
            alias_scope=alias_scope,
            target_snapshot_version=alias.candidate_snapshot_version or candidate_snapshot_version,
            target_embedding_version=alias.candidate_embedding_version or candidate_embedding_version,
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
        self._ensure_job_targets_current(job, alias)

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
        self._ensure_job_targets_current(job, alias)
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

        if (
            review
            and review.active_on_approve == 1
            and self._is_due_for_activation(approved_row.effective_at)
        ):
            self._flip_alias_for_row(approved_row, alias)
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
        self._flip_alias_for_row(approved_row, alias)
        return {"review_id": review_id, "released": True}

    def _flip_alias_for_row(self, approved_row: StyleObservation, alias: VectorAliasRegistry) -> None:
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

    def run_due_promotions(self) -> dict:
        rows = self.session.execute(
            select(StyleObservation)
            .where(
                StyleObservation.active_flag == 0,
                StyleObservation.runtime_eligible == 0,
                StyleObservation.runtime_eligibility_basis == "future_effective",
                StyleObservation.effective_at.is_not(None),
            )
            .order_by(StyleObservation.created_at.asc())
        ).scalars().all()

        due_rows_by_scope: dict[str, StyleObservation] = {}
        for row in rows:
            if not self._is_due_for_activation(row.effective_at):
                continue
            alias_scope = self._alias_scope_for_row(row)
            due_rows_by_scope[alias_scope] = row

        promoted_review_ids: list[str] = []
        promoted_review_targets: list[dict[str, dict[str, str] | str]] = []
        promoted_row_ids: list[str] = []
        promoted_alias_scopes: list[str] = []

        for alias_scope, row in due_rows_by_scope.items():
            registry = self.session.execute(
                select(VersionRegistry).where(VersionRegistry.physical_row_id == row.row_id)
            ).scalar_one_or_none()
            if registry is None or registry.verify_status != "succeeded":
                continue

            alias = self.session.get(VectorAliasRegistry, alias_scope)
            if (
                alias is None
                or alias.candidate_alias is None
                or alias.candidate_snapshot_version is None
                or alias.candidate_embedding_version is None
            ):
                continue

            self._flip_alias_for_row(row, alias)
            self._record_runtime_activity(
                event_type="runtime_due_promotion",
                object_ref=row.row_id,
                actor_ref="system/due_promotion",
                summary="promoted verified future-effective candidate",
                review_id=row.source_review_id,
                alias_scope=alias_scope,
                row_id=row.row_id,
            )
            promoted_row_ids.append(row.row_id)
            promoted_alias_scopes.append(alias_scope)
            if row.source_review_id:
                promoted_review_ids.append(row.source_review_id)
                promoted_review_targets.append(
                    {
                        "review_id": row.source_review_id,
                        "target": self._review_target(row.source_review_id),
                    }
                )

        return {
            "promoted": len(promoted_row_ids),
            "promoted_review_ids": promoted_review_ids,
            "promoted_review_targets": promoted_review_targets,
            "promoted_row_ids": promoted_row_ids,
            "promoted_alias_scopes": promoted_alias_scopes,
        }

    def recover_stuck_jobs(self) -> dict:
        running_jobs = [
            *self.session.execute(select(ReindexJob).where(ReindexJob.status == "running")).scalars().all(),
            *self.session.execute(select(VerifyJob).where(VerifyJob.status == "running")).scalars().all(),
        ]
        reclaimed_job_summaries = self._reclaim_expired_jobs(running_jobs)
        failed_job_summaries = self._collect_failed_job_summaries()
        (
            reclaimed_idempotency_key_summaries,
            created_human_review_event_ids,
            created_human_review_event_targets,
        ) = self._recover_stale_idempotency_keys()
        return {
            "reclaimed_jobs": len(reclaimed_job_summaries),
            "reclaimed_job_summaries": reclaimed_job_summaries,
            "failed_jobs": len(failed_job_summaries),
            "failed_job_summaries": failed_job_summaries,
            "reclaimed_idempotency_keys": len(reclaimed_idempotency_key_summaries),
            "failed_idempotency_keys": len(reclaimed_idempotency_key_summaries),
            "reclaimed_idempotency_key_summaries": reclaimed_idempotency_key_summaries,
            "created_human_review_events": len(created_human_review_event_ids),
            "created_human_review_event_ids": created_human_review_event_ids,
            "created_human_review_event_targets": created_human_review_event_targets,
        }
