from __future__ import annotations

from typing import Any

from novel_system.db.models import ReviewItem, VersionRegistry
from novel_system.services.errors import DomainError
from novel_system.services.knowledge_registry import descriptor_for_item_type
from novel_system.services.versioning.base import VersioningServiceBase
from novel_system.services.versioning.shared import now_iso


class ReviewMaterializationService(VersioningServiceBase):
    def materialize_review(self, review_id: str) -> dict[str, Any]:
        review = self.session.get(ReviewItem, review_id)
        if review is None:
            raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)

        descriptor = descriptor_for_item_type(review.item_type)
        payload = dict(review.candidate_payload_json or {})
        review.status = "approved"

        lineage_key = self._lineage_key_for_review(review, descriptor)
        version = self._next_version(descriptor, lineage_key)
        row_id = self._row_id_for(descriptor, lineage_key, version)
        item = self._create_materialized_row(
            descriptor,
            review,
            lineage_key=lineage_key,
            version=version,
            row_id=row_id,
        )
        self.session.add(item)

        alias_scope = self._alias_scope_for_payload(descriptor, payload) if descriptor.storage_kind == "vector" else None
        registry = VersionRegistry(
            object_type=descriptor.object_type,
            lineage_key=lineage_key,
            version=version,
            physical_row_id=row_id,
            alias_scope=alias_scope,
            materialize_status="succeeded",
            reindex_status="queued" if descriptor.storage_kind == "vector" else "not_required",
            verify_status="pending" if descriptor.storage_kind == "vector" else "not_required",
            approved_at=now_iso(),
            materialized_at=now_iso(),
        )
        self.session.add(registry)

        review.materialize_status = "succeeded"
        review.approved_item_row_id = row_id
        review.approved_item_id = lineage_key

        result: dict[str, Any] = {
            "review_id": review_id,
            "materialize_status": review.materialize_status,
            "approved_item_row_id": row_id,
            "approved_item_id": lineage_key,
        }

        if descriptor.storage_kind == "vector":
            scope, scope_ref_id = self._payload_scope(payload)
            reindex_job, verify_job = self._create_vector_jobs(
                descriptor,
                review,
                row_id=row_id,
                alias_scope=alias_scope or self._alias_scope_for_payload(descriptor, payload),
                scope=scope,
                scope_ref_id=scope_ref_id,
            )
            self.session.flush()
            from novel_system.services.versioning.vector_lifecycle import VectorLifecycleService

            VectorLifecycleService(self.session, vector_store=self.vector_store).run_reindex(reindex_job.job_id)
            result["job_ids"] = [reindex_job.job_id, verify_job.job_id]
            result["alias_scope"] = alias_scope
            result["released"] = False
            return result

        effective_at = getattr(item, "effective_at", None)
        if review.active_on_approve == 1 and self._is_due_for_activation(effective_at):
            self._activate_direct_row(descriptor, item)
            result["released"] = True
        else:
            result["released"] = False

        self.session.flush()
        return result
