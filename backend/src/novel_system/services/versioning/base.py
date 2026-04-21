from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    BannedRuleCluster,
    CalibrationLine,
    ChapterMemory,
    ForeshadowTracker,
    HumanReviewEvent,
    IdempotencyKey,
    NarrativePattern,
    OperationLog,
    ReconcileFault,
    ReindexJob,
    RelationProfile,
    ReviewItem,
    SceneMemory,
    StyleObservation,
    StyleRule,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
    VoiceProfile,
    WorldRule,
)
from novel_system.services.errors import DomainError
from novel_system.services.human_review_support import recovery_action_contract, recovery_linked_target, structured_target
from novel_system.services.knowledge_registry import KnowledgeDescriptor
from novel_system.services.vector_store import VectorStore, get_vector_store
from novel_system.services.versioning.shared import now_iso, parse_iso_datetime


class VersioningServiceBase:
    def __init__(self, session: Session, vector_store: VectorStore | None = None) -> None:
        self.session = session
        self.vector_store = vector_store or get_vector_store()

    def _vector_document(self, descriptor: KnowledgeDescriptor, row: Any) -> dict[str, str | None]:
        document = {
            "id": row.row_id,
            "text": getattr(row, descriptor.text_field),
            "lineage_key": getattr(row, descriptor.lineage_field),
        }
        if hasattr(row, "scope"):
            document["scope"] = row.scope
        if hasattr(row, "scope_ref_id"):
            document["scope_ref_id"] = row.scope_ref_id
        return document

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
    def _collection_family_for_scope(object_type: str, scope: str, scope_ref_id: str | None) -> str:
        return f"{object_type}_{scope}_{scope_ref_id or 'global'}"

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

    @staticmethod
    def _payload_scope(payload: dict[str, Any]) -> tuple[str, str]:
        return str(payload.get("scope") or "global"), str(payload.get("scope_ref_id") or "global")

    def _alias_scope_for_payload(self, descriptor: KnowledgeDescriptor, payload: dict[str, Any]) -> str:
        scope, scope_ref_id = self._payload_scope(payload)
        return f"{descriptor.object_type}:{scope}:{scope_ref_id}"

    def _alias_scope_for_row(self, descriptor: KnowledgeDescriptor, row: Any) -> str:
        scope = getattr(row, "scope", "global")
        scope_ref_id = getattr(row, "scope_ref_id", None) or "global"
        return f"{descriptor.object_type}:{scope}:{scope_ref_id}"

    def _next_version(self, descriptor: KnowledgeDescriptor, lineage_key: str) -> int:
        return (
            self.session.execute(
                select(func.max(VersionRegistry.version)).where(
                    VersionRegistry.object_type == descriptor.object_type,
                    VersionRegistry.lineage_key == lineage_key,
                )
            ).scalar_one_or_none()
            or 0
        ) + 1

    @staticmethod
    def _row_id_for(descriptor: KnowledgeDescriptor, lineage_key: str, version: int) -> str:
        return f"{descriptor.row_prefix}_{lineage_key}_v{version}"

    @staticmethod
    def _required_string(value: Any, *, field: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise DomainError("REVIEW_PAYLOAD_INVALID", f"missing {field}", status_code=400)

    def _lineage_key_for_review(self, review: ReviewItem, descriptor: KnowledgeDescriptor) -> str:
        payload = review.candidate_payload_json or {}
        if payload.get("lineage_key"):
            return self._required_string(payload.get("lineage_key"), field="candidate_payload_json.lineage_key")
        if descriptor.scope_kind == "scene":
            return self._required_string(payload.get("scene_id") or review.scene_id, field="scene_id")
        if descriptor.scope_kind == "chapter":
            return self._required_string(payload.get("chapter_id") or review.chapter_id, field="chapter_id")
        return review.review_id

    def _pending_runtime_basis(self, review: ReviewItem, *, effective_at: str | None, storage_kind: str) -> str:
        if effective_at and not self._is_due_for_activation(effective_at):
            return "future_effective"
        if review.active_on_approve == 0:
            return "manual_hold"
        if storage_kind == "vector":
            return "stage_blocked"
        return "pending_activation"

    def _create_materialized_row(
        self,
        descriptor: KnowledgeDescriptor,
        review: ReviewItem,
        *,
        lineage_key: str,
        version: int,
        row_id: str,
    ) -> Any:
        payload = dict(review.candidate_payload_json or {})
        effective_at = payload.get("effective_at")
        pending_basis = self._pending_runtime_basis(review, effective_at=effective_at, storage_kind=descriptor.storage_kind)
        text_value = payload.get("text", review.candidate_text)

        if descriptor.object_type == "style_observation":
            scope, scope_ref_id = self._payload_scope(payload)
            return StyleObservation(
                row_id=row_id,
                style_observation_id=lineage_key,
                version=version,
                scope=scope,
                scope_ref_id=scope_ref_id,
                text=text_value,
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
            )

        if descriptor.object_type == "style_rule":
            scope, scope_ref_id = self._payload_scope(payload)
            return StyleRule(
                row_id=row_id,
                style_rule_set_id=lineage_key,
                version=version,
                scope=scope,
                scope_ref_id=scope_ref_id,
                content=text_value,
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
            )

        if descriptor.object_type == "banned_rule_cluster":
            scope, scope_ref_id = self._payload_scope(payload)
            return descriptor.model_cls(
                row_id=row_id,
                banned_cluster_id=lineage_key,
                version=version,
                scope=scope,
                scope_ref_id=scope_ref_id,
                content=text_value,
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
            )

        if descriptor.object_type == "narrative_pattern":
            scope, scope_ref_id = self._payload_scope(payload)
            return NarrativePattern(
                row_id=row_id,
                narrative_pattern_id=lineage_key,
                version=version,
                scope=scope,
                scope_ref_id=scope_ref_id,
                content=text_value,
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
            )

        if descriptor.object_type == "voice_card":
            character_id = self._required_string(
                payload.get("character_id"),
                field="candidate_payload_json.character_id",
            )
            return VoiceProfile(
                row_id=row_id,
                voice_profile_id=lineage_key,
                version=version,
                character_id=character_id,
                content=self._append_voice_contract_metadata(text_value, payload),
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
                source_review_id=review.review_id,
            )

        if descriptor.object_type == "relation_card":
            left_character_id = self._required_string(
                payload.get("left_character_id"),
                field="candidate_payload_json.left_character_id",
            )
            right_character_id = self._required_string(
                payload.get("right_character_id"),
                field="candidate_payload_json.right_character_id",
            )
            return descriptor.model_cls(
                row_id=row_id,
                relation_profile_id=lineage_key,
                left_character_id=left_character_id,
                right_character_id=right_character_id,
                version=version,
                content=text_value,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
                source_review_id=review.review_id,
            )

        if descriptor.object_type == "world_rule":
            scope, scope_ref_id = self._payload_scope(payload)
            return WorldRule(
                row_id=row_id,
                world_rule_id=lineage_key,
                version=version,
                scope=scope,
                scope_ref_id=scope_ref_id,
                rule_tier=str(payload.get("rule_tier") or "normal"),
                content=text_value,
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
                expires_at=payload.get("expires_at"),
            )

        if descriptor.object_type == "calibration_line":
            scope, scope_ref_id = self._payload_scope(payload)
            return CalibrationLine(
                row_id=row_id,
                calibration_line_id=lineage_key,
                version=version,
                scope=scope,
                scope_ref_id=scope_ref_id,
                text=text_value,
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
            )

        if descriptor.object_type == "foreshadow":
            chapter_id = self._required_string(payload.get("chapter_id") or review.chapter_id, field="chapter_id")
            scene_id = payload.get("scene_id") or review.scene_id
            tracker_status = {
                "foreshadow_open": "open",
                "foreshadow_touch": "open",
                "foreshadow_resolve": "resolved",
            }.get(review.item_type, "open")
            return ForeshadowTracker(
                row_id=row_id,
                foreshadow_id=lineage_key,
                version=version,
                chapter_id=chapter_id,
                scene_id=scene_id,
                text=text_value,
                tracker_status=tracker_status,
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
            )

        if descriptor.object_type == "scene_summary":
            scene_id = self._required_string(payload.get("scene_id") or review.scene_id, field="scene_id")
            chapter_id = self._required_string(payload.get("chapter_id") or review.chapter_id, field="chapter_id")
            return SceneMemory(
                row_id=row_id,
                scene_id=scene_id,
                chapter_id=chapter_id,
                content=text_value,
                carry_notes_json=[],
                source_bundle_id=f"review:{review.review_id}",
                final_scene_row_id=f"review:{review.review_id}",
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
            )

        if descriptor.object_type == "chapter_summary":
            chapter_id = self._required_string(payload.get("chapter_id") or review.chapter_id, field="chapter_id")
            return ChapterMemory(
                row_id=row_id,
                chapter_id=chapter_id,
                aggregate_stage="summary",
                content=text_value,
                source_review_id=review.review_id,
                active_flag=0,
                runtime_eligible=0,
                runtime_eligibility_basis=pending_basis,
                effective_at=effective_at,
            )

        raise DomainError("REVIEW_ITEM_TYPE_UNSUPPORTED", f"unsupported item type {review.item_type}", status_code=400)

    @staticmethod
    def _append_voice_contract_metadata(text_value: Any, payload: dict[str, Any]) -> str:
        base_text = str(text_value or "").strip()
        metadata_lines: list[str] = []
        display_name = payload.get("display_name")
        if isinstance(display_name, str) and display_name.strip():
            metadata_lines.append(f"角色名：{display_name.strip()}")
        pronouns = payload.get("pronouns")
        if isinstance(pronouns, str) and pronouns.strip():
            metadata_lines.append(f"代词：{pronouns.strip()}")
        elif isinstance(pronouns, list):
            normalized_pronouns = [str(item).strip() for item in pronouns if str(item).strip()]
            if normalized_pronouns:
                metadata_lines.append(f"代词：{'、'.join(normalized_pronouns)}")
        role = payload.get("role")
        if isinstance(role, str) and role.strip():
            metadata_lines.append(f"角色职责：{role.strip()}")
        aliases = payload.get("aliases")
        if isinstance(aliases, str) and aliases.strip():
            metadata_lines.append(f"别名：{aliases.strip()}")
        elif isinstance(aliases, list):
            normalized_aliases = [str(item).strip() for item in aliases if str(item).strip()]
            if normalized_aliases:
                metadata_lines.append(f"别名：{'、'.join(normalized_aliases)}")
        if not metadata_lines:
            return base_text
        return "\n".join([base_text, *metadata_lines]) if base_text else "\n".join(metadata_lines)

    def _registry_for_row(self, row_id: str) -> VersionRegistry | None:
        return self.session.execute(
            select(VersionRegistry).where(VersionRegistry.physical_row_id == row_id)
        ).scalar_one_or_none()

    def _deactivate_same_lineage_rows(self, descriptor: KnowledgeDescriptor, row: Any) -> None:
        lineage_value = getattr(row, descriptor.lineage_field)
        lineage_column = getattr(descriptor.model_cls, descriptor.lineage_field)
        rows = self.session.execute(
            select(descriptor.model_cls).where(lineage_column == lineage_value)
        ).scalars().all()
        for existing in rows:
            if existing.row_id == row.row_id:
                continue
            if hasattr(existing, "active_flag"):
                existing.active_flag = 0
            if hasattr(existing, "runtime_eligible"):
                existing.runtime_eligible = 0
            if hasattr(existing, "runtime_eligibility_basis") and existing.runtime_eligibility_basis != "expired":
                existing.runtime_eligibility_basis = "superseded"

    def _activate_direct_row(self, descriptor: KnowledgeDescriptor, row: Any) -> None:
        self._deactivate_same_lineage_rows(descriptor, row)
        row.active_flag = 1
        if descriptor.object_type == "foreshadow":
            if row.tracker_status == "open":
                row.runtime_eligible = 1
                row.runtime_eligibility_basis = "foreshadow_open"
            else:
                row.runtime_eligible = 0
                row.runtime_eligibility_basis = "resolved"
        elif descriptor.object_type == "world_rule":
            expires_at = parse_iso_datetime(getattr(row, "expires_at", None))
            if expires_at is not None and expires_at <= datetime.now(UTC):
                row.runtime_eligible = 0
                row.runtime_eligibility_basis = "expired"
            else:
                row.runtime_eligible = 1
                row.runtime_eligibility_basis = "direct_read"
        else:
            row.runtime_eligible = 1
            row.runtime_eligibility_basis = "direct_read"
        registry = self._registry_for_row(row.row_id)
        if registry is not None:
            registry.activated_at = now_iso()
            registry.verify_status = "not_required"
            registry.reindex_status = "not_required"

    def _create_vector_jobs(
        self,
        descriptor: KnowledgeDescriptor,
        review: ReviewItem,
        *,
        row_id: str,
        alias_scope: str,
        scope: str,
        scope_ref_id: str,
    ) -> tuple[ReindexJob, VerifyJob]:
        alias = self.session.get(VectorAliasRegistry, alias_scope)
        collection_family = self._collection_family_for_scope(descriptor.object_type, scope, scope_ref_id)
        candidate_alias = self._collection_alias_for_row(collection_family, row_id)
        candidate_snapshot_version = self._snapshot_version_for_row(row_id)
        candidate_embedding_version = self._embedding_version_for_row(row_id)
        if alias is None:
            alias = VectorAliasRegistry(
                alias_scope=alias_scope,
                object_type=descriptor.object_type,
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
            alias.object_type = descriptor.object_type
            alias.scope = scope
            alias.scope_ref_id = scope_ref_id
            alias.collection_family = collection_family
            alias.candidate_alias = candidate_alias
            alias.candidate_snapshot_version = candidate_snapshot_version
            alias.candidate_embedding_version = candidate_embedding_version
            alias.verify_status = "pending"

        reindex_job = ReindexJob(
            job_id=f"reindex_{review.review_id}",
            review_id=review.review_id,
            status="queued",
            object_type=descriptor.object_type,
            alias_scope=alias_scope,
            target_snapshot_version=candidate_snapshot_version,
            target_embedding_version=candidate_embedding_version,
        )
        verify_job = VerifyJob(
            job_id=f"verify_{review.review_id}",
            review_id=review.review_id,
            status="queued",
            object_type=descriptor.object_type,
            alias_scope=alias_scope,
            target_snapshot_version=candidate_snapshot_version,
            target_embedding_version=candidate_embedding_version,
        )
        self.session.add(reindex_job)
        self.session.add(verify_job)
        return reindex_job, verify_job

    def _flip_alias_for_row(self, descriptor: KnowledgeDescriptor, approved_row: Any, alias: VectorAliasRegistry) -> None:
        self._deactivate_same_lineage_rows(descriptor, approved_row)
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
        registry = self._registry_for_row(approved_row.row_id)
        if registry is not None:
            registry.activated_at = now_iso()
            registry.verify_status = "succeeded"

    def _expire_world_rules(self) -> None:
        rows = self.session.execute(
            select(WorldRule).where(
                WorldRule.active_flag == 1,
                WorldRule.expires_at.is_not(None),
            )
        ).scalars().all()
        now = datetime.now(UTC)
        for row in rows:
            expires_at = parse_iso_datetime(row.expires_at)
            if expires_at is None or expires_at > now:
                continue
            row.runtime_eligible = 0
            row.runtime_eligibility_basis = "expired"

