from __future__ import annotations

from typing import Any

from novel_system.db.models import ReindexJob, ReviewItem, VerifyJob, VersionRegistry
from novel_system.services.errors import DomainError
from novel_system.services.knowledge_registry import descriptor_for_item_type
from novel_system.services.versioning.base import VersioningServiceBase
from novel_system.services.versioning.shared import now_iso


class ReviewMaterializationService(VersioningServiceBase):
    def materialize_review(self, review_id: str) -> dict[str, Any]:
        review = self.session.get(ReviewItem, review_id)
        if review is None:
            raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)
        if review.status == "approved":
            # 同一幂等 key 的重放由幂等层回放,走不到这里;能到这里的是换了 key 的二次批准。
            # 向量类型再物化一次会以固定 id(reindex_/verify_{review_id})再 INSERT 一对 job,
            # 在 flush 时撞 UNIQUE → IntegrityError 裸 500;直接以冲突回绝并回显既有物化结果。
            raise DomainError(
                "REVIEW_ALREADY_APPROVED",
                f"review {review_id} is already approved",
                status_code=409,
                details={
                    "review_id": review_id,
                    "materialize_status": review.materialize_status,
                    "approved_item_row_id": review.approved_item_row_id,
                    "approved_item_id": review.approved_item_id,
                },
            )

        try:
            descriptor = descriptor_for_item_type(review.item_type)
        except KeyError as exc:
            # 注册表外的 item_type(历史遗留行 / 卡片行 fe_card)没有物化落点:
            # 作者可见的 409,而不是 KeyError 500。
            raise DomainError(
                "REVIEW_ITEM_TYPE_UNSUPPORTED",
                f"review item type {review.item_type!r} has no materialization target",
                status_code=409,
                details={"review_id": review_id, "item_type": review.item_type},
            ) from exc
        if descriptor.storage_kind == "vector":
            # 同一 review 的索引 job id 是固定的(见 base._create_vector_jobs);候选被拒后再批准
            # 会在 v2 行之后再 INSERT 同 id 的 job,同样撞 UNIQUE。向量候选目前不支持二次批准:
            # 在改动任何行之前就以 409 回绝,提示作者提交新候选。
            existing_job_ids = [
                job_id
                for job_id, model_cls in (
                    (f"reindex_{review_id}", ReindexJob),
                    (f"verify_{review_id}", VerifyJob),
                )
                if self.session.get(model_cls, job_id) is not None
            ]
            if existing_job_ids:
                raise DomainError(
                    "REVIEW_REAPPROVE_UNSUPPORTED",
                    f"review {review_id} was already materialized once; a rejected vector candidate "
                    "cannot be approved again — submit a new candidate instead",
                    status_code=409,
                    details={
                        "review_id": review_id,
                        "status": review.status,
                        "materialize_status": review.materialize_status,
                        "existing_job_ids": existing_job_ids,
                    },
                )
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
