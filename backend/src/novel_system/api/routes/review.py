from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import HumanReviewEvent, ReviewItem, VersionRegistry
from novel_system.services.errors import DomainError
from novel_system.services.human_review_manager import HumanReviewManager
from novel_system.services.human_review_support import (
    human_review_followup_target,
    human_review_linked_target,
    structured_target_from_replay_result,
)
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.knowledge_registry import descriptor_for_item_type
from novel_system.services.pagination import paginate_items, resolve_pagination_request
from novel_system.services.versioning import PromotionService, ReviewMaterializationService

router = APIRouter(tags=["review"])


@router.get("/api/v1/review-items")
def list_review_items(
    request: Request,
    session: Session = Depends(get_session),
    status: str | None = None,
    item_type: str | None = None,
    target_collection: str | None = None,
    scene_id: str | None = None,
    chapter_id: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
):
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
    items = session.execute(query.order_by(ReviewItem.created_at.desc(), ReviewItem.review_id.desc())).scalars().all()
    page_items, pagination = paginate_items(
        items,
        request=resolve_pagination_request(page=page, page_size=page_size, cursor=cursor, limit=limit),
        cursor_values=lambda item: [item.created_at, item.review_id],
    )
    return ok(
        {"items": [_serialize_review(item, session=session) for item in page_items], "pagination": pagination},
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/review-items/{review_id}")
def review_detail(review_id: str, request: Request, session: Session = Depends(get_session)):
    item = session.get(ReviewItem, review_id)
    if item is None:
        raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)
    return ok(_serialize_review(item, session=session), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/review-items")
def create_review_item(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/review-items",
        payload=payload,
        action=lambda: _upsert_review_item(session, payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/review-items/import-demo")
def import_demo_review(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/review-items/import-demo",
        payload=payload,
        action=lambda: _import_review(session, payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


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
    payload: dict[str, Any] | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    approval_payload = dict(payload or {})
    approval_payload["review_id"] = review_id
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/review-items/{review_id}/approve",
        payload=approval_payload,
        action=lambda: _approve_review_with_style_profile_gate(session, review_id, approval_payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


def _approve_review_with_style_profile_gate(session: Session, review_id: str, payload: dict[str, Any]) -> dict:
    item = session.get(ReviewItem, review_id)
    if item is None:
        return ReviewMaterializationService(session).materialize_review(review_id)

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
def release_review(review_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/review-items/{review_id}/release",
        payload={"review_id": review_id},
        action=lambda: PromotionService(session).release_review(review_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/review-items/{review_id}/reject")
def reject_review(
    review_id: str,
    request: Request,
    payload: dict[str, Any] | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    reject_payload = dict(payload or {})
    reject_payload["review_id"] = review_id
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/review-items/{review_id}/reject",
        payload=reject_payload,
        action=lambda: _reject_review(session, review_id, reject_payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


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
    except DomainError:
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
    baseline = _style_profile_baseline(session, item)
    if baseline is not None:
        payload["style_profile_baseline"] = baseline
    return payload


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
    except DomainError:
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
    items = session.execute(query.order_by(HumanReviewEvent.created_at.desc(), HumanReviewEvent.event_id.desc())).scalars().all()
    page_items, pagination = paginate_items(
        items,
        request=resolve_pagination_request(page=page, page_size=page_size, cursor=cursor, limit=limit),
        cursor_values=lambda item: [item.created_at, item.event_id],
    )
    return ok(
        {"items": [_serialize_event(item) for item in page_items], "pagination": pagination},
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/human-review-events/{event_id}")
def human_review_event_detail(event_id: str, request: Request, session: Session = Depends(get_session)):
    item = session.get(HumanReviewEvent, event_id)
    if item is None:
        raise DomainError("HUMAN_REVIEW_EVENT_NOT_FOUND", f"human review event {event_id} not found", status_code=404)
    return ok(_serialize_event(item), req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/human-review-events/{event_id}/actions")
def human_review_event_action(event_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    action_name = payload.get("action")
    if not action_name:
        raise DomainError("HUMAN_REVIEW_ACTION_REQUIRED", "missing action", status_code=400)
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/human-review-events/{event_id}/actions",
        payload={"event_id": event_id, "action": action_name},
        action=lambda: HumanReviewManager(session).run_action(event_id, action_name, actor_ref=actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


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
