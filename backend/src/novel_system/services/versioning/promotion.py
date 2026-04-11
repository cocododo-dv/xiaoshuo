from __future__ import annotations

from typing import Any

from sqlalchemy import select

from novel_system.db.models import (
    BannedRuleCluster,
    CalibrationLine,
    ChapterMemory,
    ForeshadowTracker,
    RelationProfile,
    ReviewItem,
    SceneMemory,
    StyleObservation,
    StyleRule,
    VectorAliasRegistry,
    VoiceProfile,
    WorldRule,
)
from novel_system.services.errors import DomainError
from novel_system.services.knowledge_registry import descriptor_for_item_type, descriptor_for_object_type
from novel_system.services.versioning.base import VersioningServiceBase


class PromotionService(VersioningServiceBase):
    def release_review(self, review_id: str) -> dict[str, Any]:
        review = self.session.get(ReviewItem, review_id)
        if review is None:
            raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)
        if review.status != "approved" or review.materialize_status != "succeeded" or not review.approved_item_row_id:
            raise DomainError("RELEASE_PRECONDITION_FAILED", "review is not ready for release", status_code=409)

        descriptor = descriptor_for_item_type(review.item_type)
        approved_row = self.session.get(descriptor.model_cls, review.approved_item_row_id)
        if approved_row is None:
            raise DomainError("APPROVED_ROW_NOT_FOUND", f"row {review.approved_item_row_id} not found", status_code=404)
        if getattr(approved_row, "active_flag", 0) == 1:
            raise DomainError("RELEASE_PRECONDITION_FAILED", "candidate is already active", status_code=409)
        if not self._is_due_for_activation(getattr(approved_row, "effective_at", None)):
            raise DomainError("RELEASE_PRECONDITION_FAILED", "candidate is not due for release", status_code=409)

        if descriptor.storage_kind == "vector":
            registry = self._registry_for_row(approved_row.row_id)
            if registry is None or registry.verify_status != "succeeded":
                raise DomainError("RELEASE_PRECONDITION_FAILED", "candidate is not verified", status_code=409)
            alias = self.session.get(VectorAliasRegistry, self._alias_scope_for_row(descriptor, approved_row))
            if (
                alias is None
                or alias.candidate_alias is None
                or alias.candidate_snapshot_version is None
                or alias.candidate_embedding_version is None
            ):
                raise DomainError("RELEASE_PRECONDITION_FAILED", "candidate is not ready for release", status_code=409)
            self._flip_alias_for_row(descriptor, approved_row, alias)
            return {"review_id": review_id, "released": True}

        self._activate_direct_row(descriptor, approved_row)
        return {"review_id": review_id, "released": True}

    def run_due_promotions(self) -> dict[str, Any]:
        self._expire_world_rules()

        promoted_review_ids: list[str] = []
        promoted_review_targets: list[dict[str, dict[str, str] | str]] = []
        promoted_row_ids: list[str] = []
        promoted_alias_scopes: list[str] = []

        vector_models = (
            (descriptor_for_object_type("style_observation"), StyleObservation),
            (descriptor_for_object_type("calibration_line"), CalibrationLine),
        )
        for descriptor, model_cls in vector_models:
            rows = self.session.execute(
                select(model_cls)
                .where(
                    model_cls.active_flag == 0,
                    model_cls.runtime_eligible == 0,
                    model_cls.runtime_eligibility_basis == "future_effective",
                    model_cls.effective_at.is_not(None),
                )
                .order_by(model_cls.created_at.asc())
            ).scalars().all()

            due_rows_by_scope: dict[str, Any] = {}
            for row in rows:
                if not self._is_due_for_activation(row.effective_at):
                    continue
                due_rows_by_scope[self._alias_scope_for_row(descriptor, row)] = row

            for alias_scope, row in due_rows_by_scope.items():
                registry = self._registry_for_row(row.row_id)
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

                self._flip_alias_for_row(descriptor, row, alias)
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

        direct_models = (
            (descriptor_for_object_type("style_rule"), StyleRule),
            (descriptor_for_object_type("banned_rule_cluster"), BannedRuleCluster),
            (descriptor_for_object_type("voice_card"), VoiceProfile),
            (descriptor_for_object_type("relation_card"), RelationProfile),
            (descriptor_for_object_type("world_rule"), WorldRule),
            (descriptor_for_object_type("foreshadow"), ForeshadowTracker),
            (descriptor_for_object_type("scene_summary"), SceneMemory),
            (descriptor_for_object_type("chapter_summary"), ChapterMemory),
        )
        for descriptor, model_cls in direct_models:
            rows = self.session.execute(
                select(model_cls)
                .where(
                    model_cls.active_flag == 0,
                    model_cls.runtime_eligible == 0,
                    model_cls.runtime_eligibility_basis == "future_effective",
                    model_cls.effective_at.is_not(None),
                )
                .order_by(model_cls.created_at.asc())
            ).scalars().all()
            due_rows_by_lineage: dict[str, Any] = {}
            for row in rows:
                if not self._is_due_for_activation(row.effective_at):
                    continue
                due_rows_by_lineage[getattr(row, descriptor.lineage_field)] = row

            for row in due_rows_by_lineage.values():
                self._activate_direct_row(descriptor, row)
                self._record_runtime_activity(
                    event_type="runtime_due_promotion",
                    object_ref=row.row_id,
                    actor_ref="system/due_promotion",
                    summary="activated future-effective direct-read candidate",
                    review_id=row.source_review_id,
                    row_id=row.row_id,
                )
                promoted_row_ids.append(row.row_id)
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
