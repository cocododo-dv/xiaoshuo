from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.mutations import idempotent_response, optional_idempotent_response
from novel_system.api.request_types import BoundedJsonObject, EmptyRequest, StrictRequestModel
from novel_system.api.response import ok
from novel_system.db.models import (
    AuthorPreferenceProfile,
    HumanReviewEvent,
    LongformDiagnosticCard,
    LongformStructureGuidance,
    ReviewItem,
    VectorAliasRegistry,
    VerifyJob,
    VersionRegistry,
)
from novel_system.services.errors import DomainError
from novel_system.services.human_review_manager import HumanReviewManager
from novel_system.services.human_review_support import (
    human_review_followup_target,
    human_review_linked_target,
    structured_target_from_replay_result,
)
from novel_system.services.knowledge_registry import all_descriptors, descriptor_for_item_type
from novel_system.services.pagination import paginate_select, resolve_pagination_request
from novel_system.services.review_cards import ReviewCardService
from novel_system.services.versioning import (
    PromotionService,
    ReviewMaterializationService,
    VectorLifecycleService,
)
from novel_system.settings import get_settings

router = APIRouter(tags=["review"])

Identifier = Annotated[str, Field(min_length=1, max_length=255)]
OptionalIdentifier = Annotated[str, Field(max_length=255)]
CardListItem = Annotated[str, Field(max_length=4000)]

# 由本路由直接落库、不经知识注册表物化的两种候选类型(见 _approve_review_with_style_profile_gate)。
_ROUTE_HANDLED_ITEM_TYPES = ("author_preference_profile", "longform_structure_guidance")
# legacy 候选创建只接受批准时有落点的 item_type:注册表之外的值批准时会 KeyError,
# 与其留下永远批不了的行,不如在创建边界就回绝。
SUPPORTED_REVIEW_ITEM_TYPES: tuple[str, ...] = tuple(
    sorted(
        {
            *(item_type for descriptor in all_descriptors() for item_type in descriptor.item_types),
            *_ROUTE_HANDLED_ITEM_TYPES,
        }
    )
)


class ReviewCardCreateRequest(StrictRequestModel):
    project_id: OptionalIdentifier | None = None
    scene_id: OptionalIdentifier | None = None
    chapter_id: OptionalIdentifier | None = None
    # Values remain domain-validated for REVIEW_CARD_KIND_INVALID.
    kind: str = Field(max_length=64)
    priority: int | None = Field(default=None, ge=1, le=10)
    title: str | None = Field(default=None, max_length=10_000)
    source: str | None = Field(default=None, max_length=255)
    where: str | None = Field(default=None, max_length=1000)
    occurred_at: str | None = Field(default=None, max_length=128)
    detail: str | None = Field(default=None, max_length=100_000)
    preview: str | None = Field(default=None, max_length=100_000)
    checklist: list[CardListItem] | None = Field(default=None, max_length=500)
    options: list[CardListItem] | None = Field(default=None, max_length=500)
    actions: list[BoundedJsonObject] | None = Field(default=None, max_length=100)
    dedupe_key: str | None = Field(default=None, max_length=512)


class ReviewCandidateCreateRequest(StrictRequestModel):
    # review_id remains optional so the established REVIEW_ID_REQUIRED domain
    # response is retained for an omitted identifier.
    review_id: OptionalIdentifier | None = None
    scene_id: OptionalIdentifier | None = None
    chapter_id: OptionalIdentifier | None = None
    item_type: str = Field(min_length=1, max_length=128)
    candidate_text: str = Field(max_length=2_000_000)
    candidate_payload_json: BoundedJsonObject = Field(default_factory=dict)
    active_on_approve: int = Field(default=1, ge=0, le=1)


class ReviewDemoImportRequest(StrictRequestModel):
    """Fixture import boundary without writable lifecycle/derived columns."""

    review_id: Identifier
    scene_id: OptionalIdentifier | None = None
    chapter_id: OptionalIdentifier | None = None
    item_type: str = Field(min_length=1, max_length=128)
    candidate_text: str = Field(max_length=2_000_000)
    candidate_payload_json: BoundedJsonObject = Field(default_factory=dict)
    active_on_approve: int = Field(default=1, ge=0, le=1)


class ReviewCardResolveRequest(StrictRequestModel):
    action_index: int | None = Field(default=None, ge=0, le=10_000)
    project_id: OptionalIdentifier | None = None


class ReviewCardProjectRequest(StrictRequestModel):
    project_id: OptionalIdentifier | None = None


class ReviewRiskConfirmationRequest(StrictRequestModel):
    acknowledged: StrictBool = False
    reason: str | None = Field(default=None, max_length=4000)
    severity: str | None = Field(default=None, max_length=64)


class ReviewApproveRequest(StrictRequestModel):
    risk_confirmation: ReviewRiskConfirmationRequest | None = None


class ReviewRejectRequest(StrictRequestModel):
    reason: str | None = Field(default=None, max_length=4000)


class HumanReviewActionRequest(StrictRequestModel):
    # Missing/invalid action vocabulary remains owned by HumanReviewManager.
    action: str | None = Field(default=None, max_length=128)
    reason: str | None = Field(default=None, max_length=4000)


@router.get("/api/v1/review-items")
def list_review_items(
    request: Request,
    session: Session = Depends(get_session),
    status: str | None = None,
    item_type: str | None = None,
    target_collection: str | None = None,
    scene_id: str | None = None,
    chapter_id: str | None = None,
    state: str | None = None,
    project_id: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
):
    # FE-ALIGN P5 卡片模式：?state=open|snoozed&project_id=… → 持久卡 ∪ 派生卡（统一形状）
    if state is not None:
        if not project_id:
            raise DomainError("REVIEW_PROJECT_REQUIRED", "project_id is required with state filter", status_code=400)
        result = ReviewCardService(session).list_cards(project_id, state=state)
        return ok(result, req_id=getattr(request.state, "request_id", None))
    query = select(ReviewItem)
    if status:
        query = query.where(ReviewItem.status == status)
    if item_type:
        query = query.where(ReviewItem.item_type == item_type)
    if target_collection:
        query = query.where(ReviewItem.target_collection == target_collection)
    if scene_id:
        query = query.where(ReviewItem.scene_id == scene_id)
    if chapter_id:
        query = query.where(ReviewItem.chapter_id == chapter_id)
    page_items, pagination = paginate_select(
        session,
        query,
        request=resolve_pagination_request(page=page, page_size=page_size, cursor=cursor, limit=limit),
        order_columns=(
            (ReviewItem.created_at, "desc"),
            (ReviewItem.review_id, "desc"),
        ),
        cursor_values=lambda item: [item.created_at, item.review_id],
    )
    return ok(
        {"items": [_serialize_review(item, session=session) for item in page_items], "pagination": pagination},
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/review-items/badge")
def review_badge(project_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(ReviewCardService(session).badge(project_id), req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/review-items/{review_id}")
def review_detail(review_id: str, request: Request, session: Session = Depends(get_session)):
    item = session.get(ReviewItem, review_id)
    if item is None:
        raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)
    return ok(_serialize_review(item, session=session), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/review-items")
def create_review_item(
    payload: ReviewCardCreateRequest | ReviewCandidateCreateRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    # FE-ALIGN P5：带 kind 的载荷走卡片创建（dedupe_key 去重）；legacy 载荷保持原 upsert 流
    is_card = "kind" in body and "review_id" not in body
    action = (
        (lambda: ReviewCardService(session).create_card(body, actor_ref=actor_ref))
        if is_card
        else (lambda: _upsert_review_item(session, body))
    )
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items",
        payload=body,
        action=action,
    )


# ---------------------------------------------------------------------------
# FE-ALIGN P5：卡片状态流转（resolve 在同一事务执行 effect — D4）
# ---------------------------------------------------------------------------


@router.post("/api/v1/review-items/{review_id}/resolve")
def resolve_review_card(
    review_id: str,
    request: Request,
    payload: ReviewCardResolveRequest | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items/{review_id}/resolve",
        payload={"review_id": review_id, **body},
        action=lambda: ReviewCardService(session).resolve(
            review_id,
            action_index=body.get("action_index"),
            project_id=body.get("project_id"),
            actor_ref=actor_ref,
        ),
    )


@router.post("/api/v1/review-items/{review_id}/unresolve")
def unresolve_review_card(
    review_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items/{review_id}/unresolve",
        payload={"review_id": review_id},
        action=lambda: ReviewCardService(session).unresolve(review_id),
    )


@router.post("/api/v1/review-items/{review_id}/snooze")
def snooze_review_card(
    review_id: str,
    request: Request,
    payload: ReviewCardProjectRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items/{review_id}/snooze",
        payload={"review_id": review_id, **body},
        action=lambda: ReviewCardService(session).snooze(review_id, project_id=body.get("project_id")),
    )


@router.post("/api/v1/review-items/{review_id}/unsnooze")
def unsnooze_review_card(
    review_id: str,
    request: Request,
    payload: ReviewCardProjectRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items/{review_id}/unsnooze",
        payload={"review_id": review_id, **body},
        action=lambda: ReviewCardService(session).unsnooze(review_id, project_id=body.get("project_id")),
    )


@router.post("/api/v1/review-items/import-demo", include_in_schema=False)
def import_demo_review(
    payload: ReviewDemoImportRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    if not get_settings(include_runtime_config=False).fixture_import_enabled:
        raise DomainError("FIXTURE_IMPORT_DISABLED", "fixture import is disabled", status_code=404)
    body = payload.model_dump(mode="json", exclude_unset=True)
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items/import-demo",
        payload=body,
        action=lambda: _import_review(session, body),
    )


def _import_review(session: Session, payload: dict) -> dict:
    item = session.get(ReviewItem, payload["review_id"])
    if item is None:
        item = ReviewItem(**payload)
        session.add(item)
    else:
        for key, value in payload.items():
            setattr(item, key, value)
    session.flush()
    return {"review_id": item.review_id}


def _upsert_review_item(session: Session, payload: dict) -> dict:
    review_id = payload.get("review_id")
    if not isinstance(review_id, str) or not review_id:
        raise DomainError("REVIEW_ID_REQUIRED", "missing review_id", status_code=400)
    item_type = payload.get("item_type")
    if item_type not in SUPPORTED_REVIEW_ITEM_TYPES:
        raise DomainError(
            "REVIEW_ITEM_TYPE_INVALID",
            f"item_type {item_type!r} has no approval target; expected one of {list(SUPPORTED_REVIEW_ITEM_TYPES)}",
            status_code=400,
            details={"item_type": item_type, "supported_item_types": list(SUPPORTED_REVIEW_ITEM_TYPES)},
        )

    item = session.get(ReviewItem, review_id)
    if item is None:
        item = ReviewItem(**payload)
        session.add(item)
    else:
        for key, value in payload.items():
            setattr(item, key, value)
    session.flush()
    session.refresh(item)
    return _serialize_review(item, session=session)


@router.post("/api/v1/review-items/{review_id}/approve")
def approve_review(
    review_id: str,
    request: Request,
    payload: ReviewApproveRequest | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    approval_payload = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    approval_payload["review_id"] = review_id
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items/{review_id}/approve",
        payload=approval_payload,
        action=lambda: _approve_review_with_style_profile_gate(session, review_id, approval_payload),
    )


def _approve_review_with_style_profile_gate(session: Session, review_id: str, payload: dict[str, Any]) -> dict:
    item = session.get(ReviewItem, review_id)
    if item is None:
        return ReviewMaterializationService(session).materialize_review(review_id)
    if item.item_type == "author_preference_profile":
        return _approve_author_preference_profile(session, item)
    if item.item_type == "longform_structure_guidance":
        return _approve_longform_structure_guidance(session, item)

    risk = _high_risk_style_profile_approval(session, item)
    if risk is None:
        return ReviewMaterializationService(session).materialize_review(review_id)

    reason = _risk_confirmation_reason(payload.get("risk_confirmation"))
    if reason is None:
        raise DomainError(
            "STYLE_PROFILE_RISK_CONFIRMATION_REQUIRED",
            "high-risk style profile approval requires acknowledgement and a confirmation reason",
            status_code=409,
            details=risk,
        )

    result = ReviewMaterializationService(session).materialize_review(review_id)
    return {
        **result,
        "risk_confirmation": {
            "acknowledged": True,
            "reason": reason,
            "severity": "high",
            "required": True,
        },
    }


def _approve_author_preference_profile(session: Session, item: ReviewItem) -> dict[str, Any]:
    payload = item.candidate_payload_json or {}
    if not isinstance(payload, dict):
        payload = {}
    profile_id = payload.get("profile_id") if isinstance(payload.get("profile_id"), str) else "author_pref_global_global"
    scope_type = str(payload.get("scope_type") or "global")
    scope_ref_id = str(payload.get("scope_ref_id") or "global").strip()
    if scope_type not in {"global", "genre", "project", "chapter"} or not scope_ref_id:
        raise DomainError(
            "AUTHOR_PREFERENCE_SCOPE_INVALID",
            "author preference profile has an invalid scope",
            status_code=400,
        )
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    source_patch_ids = payload.get("source_patch_ids") if isinstance(payload.get("source_patch_ids"), list) else []
    profile = session.get(AuthorPreferenceProfile, profile_id)
    if profile is None:
        profile = AuthorPreferenceProfile(
            profile_id=profile_id,
            scope_type=scope_type,
            scope_ref_id=scope_ref_id,
            summary_json=summary,
            source_patch_ids_json=[str(value) for value in source_patch_ids],
        )
        session.add(profile)
    else:
        profile.scope_type = scope_type
        profile.scope_ref_id = scope_ref_id
        profile.summary_json = summary
        profile.source_patch_ids_json = [str(value) for value in source_patch_ids]
    profile.status = "approved"
    profile.runtime_eligible = 1
    item.status = "approved"
    item.materialize_status = "succeeded"
    item.approved_item_row_id = profile.profile_id
    item.approved_item_id = profile.profile_id
    session.flush()
    return {
        "review_id": item.review_id,
        "materialize_status": item.materialize_status,
        "approved_item_row_id": profile.profile_id,
        "approved_item_id": profile.profile_id,
        "released": True,
    }


def _approve_longform_structure_guidance(session: Session, item: ReviewItem) -> dict[str, Any]:
    payload = item.candidate_payload_json or {}
    if not isinstance(payload, dict):
        payload = {}
    content = payload.get("content") if isinstance(payload.get("content"), str) else item.candidate_text
    if not isinstance(content, str) or not content.strip():
        raise DomainError("LONGFORM_GUIDANCE_INVALID", "longform structure guidance requires content", status_code=400)
    guidance_id = payload.get("guidance_id") if isinstance(payload.get("guidance_id"), str) else f"lfguidance_{item.review_id}"
    scope_type = payload.get("scope_type") if payload.get("scope_type") in {"global", "chapter", "scene", "character"} else "global"
    scope_ref_id = payload.get("scope_ref_id") if isinstance(payload.get("scope_ref_id"), str) and payload.get("scope_ref_id") else "global"
    guidance = session.get(LongformStructureGuidance, guidance_id)
    if guidance is None:
        guidance = LongformStructureGuidance(
            guidance_id=guidance_id,
            card_id=payload.get("card_id") if isinstance(payload.get("card_id"), str) else None,
            scope_type=scope_type,
            scope_ref_id=scope_ref_id,
            content=content.strip(),
            source_review_id=item.review_id,
            evidence_json=payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {},
            recommendation_json=payload.get("recommendation") if isinstance(payload.get("recommendation"), dict) else {},
        )
        session.add(guidance)
    else:
        guidance.card_id = payload.get("card_id") if isinstance(payload.get("card_id"), str) else guidance.card_id
        guidance.scope_type = scope_type
        guidance.scope_ref_id = scope_ref_id
        guidance.content = content.strip()
        guidance.source_review_id = item.review_id
        guidance.evidence_json = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        guidance.recommendation_json = payload.get("recommendation") if isinstance(payload.get("recommendation"), dict) else {}
    guidance.status = "approved"
    guidance.runtime_eligible = 1

    card_id = payload.get("card_id")
    card = session.get(LongformDiagnosticCard, card_id) if isinstance(card_id, str) else None
    if card is not None:
        card.status = "published_guidance"
        card.review_id = item.review_id
        card.guidance_id = guidance.guidance_id

    item.status = "approved"
    item.materialize_status = "succeeded"
    item.approved_item_row_id = guidance.guidance_id
    item.approved_item_id = guidance.guidance_id
    session.flush()
    return {
        "review_id": item.review_id,
        "materialize_status": item.materialize_status,
        "approved_item_row_id": guidance.guidance_id,
        "approved_item_id": guidance.guidance_id,
        "released": True,
    }


def _high_risk_style_profile_approval(session: Session, item: ReviewItem) -> dict[str, Any] | None:
    candidate_payload = item.candidate_payload_json or {}
    if not isinstance(candidate_payload, dict):
        return None
    candidate_profile = candidate_payload.get("style_profile")
    if not isinstance(candidate_profile, dict):
        return None

    baseline_profile = _style_profile_baseline(session, item)
    if not isinstance(baseline_profile, dict):
        return None

    baseline_features = baseline_profile.get("features")
    if not isinstance(baseline_features, dict):
        return None

    removed_features = []
    for feature_key in sorted(baseline_features):
        if _style_guidance_items(baseline_profile, feature_key) and not _style_guidance_items(
            candidate_profile,
            feature_key,
        ):
            removed_features.append(feature_key)

    if not removed_features:
        return None
    return {
        "severity": "high",
        "removed_features": removed_features,
        "review_id": item.review_id,
    }


def _style_guidance_items(profile: dict[str, Any], feature_key: str) -> list[str]:
    features = profile.get("features")
    if not isinstance(features, dict):
        return []
    feature = features.get(feature_key)
    if not isinstance(feature, dict):
        return []
    guidance = feature.get("guidance")
    if isinstance(guidance, str):
        return [guidance.strip()] if guidance.strip() else []
    if not isinstance(guidance, list):
        return []
    return [str(item).strip() for item in guidance if str(item).strip()]


def _risk_confirmation_reason(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    if value.get("acknowledged") is not True:
        return None
    reason = value.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        return None
    return reason.strip()


@router.post("/api/v1/review-items/{review_id}/release")
def release_review(
    review_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items/{review_id}/release",
        payload={"review_id": review_id},
        action=lambda: PromotionService(session).release_review(review_id),
    )


@router.post("/api/v1/review-items/{review_id}/reject")
def reject_review(
    review_id: str,
    request: Request,
    payload: ReviewRejectRequest | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    reject_payload = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    reject_payload["review_id"] = review_id
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/review-items/{review_id}/reject",
        payload=reject_payload,
        action=lambda: _reject_review(session, review_id, reject_payload),
    )


def _reject_review(session: Session, review_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = session.get(ReviewItem, review_id)
    if item is None:
        raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)
    if _review_has_released_materialized_row(session, item):
        raise DomainError("REVIEW_REJECT_PRECONDITION_FAILED", "released reviews cannot be rejected", status_code=409)
    had_materialized_candidate = (
        item.status == "approved" or item.materialize_status == "succeeded" or bool(item.approved_item_row_id)
    )
    item.status = "rejected"
    if had_materialized_candidate:
        item.materialize_status = "rejected"
        item.approved_item_row_id = None
        item.approved_item_id = None
    session.flush()
    return {
        "review_id": item.review_id,
        "status": item.status,
        "materialize_status": item.materialize_status,
        "approved_item_row_id": item.approved_item_row_id,
        "reason": payload.get("reason"),
    }


def _review_has_released_materialized_row(session: Session, item: ReviewItem) -> bool:
    if not item.approved_item_row_id:
        return False
    try:
        descriptor = descriptor_for_item_type(item.item_type)
    except (DomainError, KeyError):
        return True
    approved_row = session.get(descriptor.model_cls, item.approved_item_row_id)
    if approved_row is None:
        return False
    return getattr(approved_row, "active_flag", 0) == 1 or getattr(approved_row, "runtime_eligible", 0) == 1


def _serialize_review(item: ReviewItem, *, session: Session | None = None) -> dict:
    payload = {
        "review_id": item.review_id,
        "scene_id": item.scene_id,
        "chapter_id": item.chapter_id,
        "item_type": item.item_type,
        "target_collection": item.target_collection,
        "status": item.status,
        "candidate_text": item.candidate_text,
        "candidate_payload_json": item.candidate_payload_json,
        "active_on_approve": item.active_on_approve,
        "materialize_status": item.materialize_status,
        "approved_item_row_id": item.approved_item_row_id,
    }
    if session is not None:
        payload["release_state"] = _release_state(item, session=session)
    baseline = _style_profile_baseline(session, item)
    if baseline is not None:
        payload["style_profile_baseline"] = baseline
    return payload


def _release_state_payload(
    *,
    state: str,
    blocked_reason: str = "",
    message: str,
    recommended_action: str = "none",
    verify_job_id: str | None = None,
) -> dict[str, Any]:
    return {
        "state": state,
        "blocked_reason": blocked_reason,
        "message": message,
        "recommended_action": recommended_action,
        "verify_job_id": verify_job_id,
    }


def _latest_verify_job_id(session: Session, review_id: str) -> str | None:
    job = session.execute(
        select(VerifyJob).where(VerifyJob.review_id == review_id).order_by(VerifyJob.job_id.desc())
    ).scalars().first()
    return job.job_id if job is not None else None


def _registry_for_row(session: Session, row_id: str) -> VersionRegistry | None:
    return session.execute(select(VersionRegistry).where(VersionRegistry.physical_row_id == row_id)).scalar_one_or_none()


def _alias_scope_for_row(descriptor, row: Any) -> str:
    scope = getattr(row, "scope", "global")
    scope_ref_id = getattr(row, "scope_ref_id", None) or "global"
    return f"{descriptor.object_type}:{scope}:{scope_ref_id}"


def _release_state(item: ReviewItem, *, session: Session) -> dict[str, Any]:
    verify_job_id = _latest_verify_job_id(session, item.review_id)

    if item.status == "rejected":
        return _release_state_payload(
            state="not_applicable",
            blocked_reason="",
            message="审核项已拒绝，不进入发布链路。",
            verify_job_id=verify_job_id,
        )
    if item.status != "approved":
        return _release_state_payload(
            state="blocked",
            blocked_reason="not_approved",
            message="请先批准审核，批准会生成可发布的候选版本。",
            recommended_action="approve",
            verify_job_id=verify_job_id,
        )
    if item.materialize_status == "failed":
        return _release_state_payload(
            state="blocked",
            blocked_reason="materialize_failed",
            message="候选物化失败，请修复候选或重新批准后再发布。",
            recommended_action="retry_materialize",
            verify_job_id=verify_job_id,
        )
    if item.materialize_status != "succeeded":
        return _release_state_payload(
            state="blocked",
            blocked_reason="materialize_pending",
            message="候选尚未物化完成，物化成功后才能发布。",
            recommended_action="retry_materialize",
            verify_job_id=verify_job_id,
        )
    if not item.approved_item_row_id:
        return _release_state_payload(
            state="blocked",
            blocked_reason="missing_candidate",
            message="未找到已批准候选行，请检查物化结果后再发布。",
            recommended_action="retry_materialize",
            verify_job_id=verify_job_id,
        )

    try:
        descriptor = descriptor_for_item_type(item.item_type)
    except (DomainError, KeyError):
        return _release_state_payload(
            state="not_applicable",
            blocked_reason="",
            message="该审核项类型没有运行时发布链路。",
            verify_job_id=verify_job_id,
        )

    approved_row = session.get(descriptor.model_cls, item.approved_item_row_id)
    if approved_row is None:
        return _release_state_payload(
            state="blocked",
            blocked_reason="missing_candidate",
            message="已批准候选行不存在，请重新物化后再发布。",
            recommended_action="retry_materialize",
            verify_job_id=verify_job_id,
        )
    if getattr(approved_row, "active_flag", 0) == 1:
        return _release_state_payload(
            state="active",
            message="候选已是当前运行时生效版本，无需再次发布。",
            verify_job_id=verify_job_id,
        )
    if not PromotionService._is_due_for_activation(getattr(approved_row, "effective_at", None)):
        return _release_state_payload(
            state="blocked",
            blocked_reason="not_due",
            message="候选尚未到达生效时间，等到生效窗口后再发布。",
            recommended_action="wait_until_due",
            verify_job_id=verify_job_id,
        )

    if descriptor.storage_kind == "vector":
        registry = _registry_for_row(session, approved_row.row_id)
        if registry is None or registry.verify_status != "succeeded":
            return _release_state_payload(
                state="blocked",
                blocked_reason="not_verified",
                message="候选尚未通过索引校验，请先在索引控制台重试校验，成功后再发布。",
                recommended_action="retry_verify",
                verify_job_id=verify_job_id,
            )
        alias_scope = registry.alias_scope or _alias_scope_for_row(descriptor, approved_row)
        alias = session.get(VectorAliasRegistry, alias_scope)
        if (
            alias is None
            or alias.candidate_alias is None
            or alias.candidate_snapshot_version is None
            or alias.candidate_embedding_version is None
        ):
            return _release_state_payload(
                state="blocked",
                blocked_reason="missing_candidate",
                message="候选索引别名尚未准备好，请先重试索引校验。",
                recommended_action="retry_verify",
                verify_job_id=verify_job_id,
            )

    return _release_state_payload(
        state="ready",
        message="候选已批准、已物化且校验通过，可以发布到运行时。",
        verify_job_id=verify_job_id,
    )


def _style_profile_baseline(session: Session | None, item: ReviewItem) -> dict | None:
    if session is None:
        return None
    candidate_payload = item.candidate_payload_json or {}
    if not isinstance(candidate_payload.get("style_profile"), dict):
        return None
    lineage_key = candidate_payload.get("lineage_key")
    if not isinstance(lineage_key, str) or not lineage_key:
        return None
    try:
        descriptor = descriptor_for_item_type(item.item_type)
    except (DomainError, KeyError):
        # 注册表外的 item_type 没有基线可比(与 _release_state 的处理一致);
        # 交给物化服务以 REVIEW_ITEM_TYPE_UNSUPPORTED 回绝,而不是在风险门前 KeyError。
        return None

    registries = session.execute(
        select(VersionRegistry)
        .where(VersionRegistry.object_type == descriptor.object_type)
        .where(VersionRegistry.lineage_key == lineage_key)
        .order_by(VersionRegistry.version.desc())
    ).scalars().all()
    for registry in registries:
        row = session.get(descriptor.model_cls, registry.physical_row_id)
        if row is None or getattr(row, "active_flag", 0) != 1:
            continue
        source_review_id = getattr(row, "source_review_id", None)
        source_review = session.get(ReviewItem, source_review_id) if source_review_id else None
        source_payload = source_review.candidate_payload_json if source_review else {}
        if isinstance(source_payload, dict) and isinstance(source_payload.get("style_profile"), dict):
            return source_payload["style_profile"]
    return None


@router.get("/api/v1/human-review-events")
def list_human_review_events(
    request: Request,
    session: Session = Depends(get_session),
    status: str | None = None,
    event_source: str | None = None,
    priority: str | None = None,
    owner: str | None = None,
    scene_id: str | None = None,
    chapter_id: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
):
    query = select(HumanReviewEvent)
    if status:
        query = query.where(HumanReviewEvent.status == status)
    if event_source:
        query = query.where(HumanReviewEvent.event_source == event_source)
    if priority:
        query = query.where(HumanReviewEvent.priority == priority)
    if owner:
        query = query.where(HumanReviewEvent.owner == owner)
    if scene_id:
        query = query.where(HumanReviewEvent.scene_id == scene_id)
    if chapter_id:
        query = query.where(HumanReviewEvent.chapter_id == chapter_id)
    page_items, pagination = paginate_select(
        session,
        query,
        request=resolve_pagination_request(page=page, page_size=page_size, cursor=cursor, limit=limit),
        order_columns=(
            (HumanReviewEvent.created_at, "desc"),
            (HumanReviewEvent.event_id, "desc"),
        ),
        cursor_values=lambda item: [item.created_at, item.event_id],
    )
    return ok(
        {"items": [_serialize_event(item) for item in page_items], "pagination": pagination},
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/human-review-events/{event_id}/actions")
def human_review_event_action(
    event_id: str,
    payload: HumanReviewActionRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True)
    action_name = body.get("action")
    if not action_name:
        raise DomainError("HUMAN_REVIEW_ACTION_REQUIRED", "missing action", status_code=400)
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    return idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/human-review-events/{event_id}/actions",
        payload={"event_id": event_id, **body},
        action=lambda: HumanReviewManager(session).run_action(event_id, action_name, actor_ref=actor_ref, payload=body),
        owned_failure_callback=lambda error: VectorLifecycleService.publish_owned_verify_failure(
            session,
            error,
        ),
    )


def _serialize_event(item: HumanReviewEvent | None) -> dict:
    assert item is not None
    details = dict(item.details_json or {})
    return {
        "event_id": item.event_id,
        "scene_id": item.scene_id,
        "chapter_id": item.chapter_id,
        "object_ref": item.object_ref,
        "event_source": item.event_source,
        "priority": item.priority,
        "owner": item.owner,
        "status": item.status,
        "allowed_actions_json": item.allowed_actions_json,
        "result_status_map_json": item.result_status_map_json,
        "details_json": details,
        "linked_target": human_review_linked_target(details, item.scene_id),
        "followup_target": human_review_followup_target(details),
        "replay_target": structured_target_from_replay_result(details.get("last_replay_result")),
        "default_action": item.default_action,
    }
