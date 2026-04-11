from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import HumanReviewEvent, ReviewItem
from novel_system.services.errors import DomainError
from novel_system.services.human_review_manager import HumanReviewManager
from novel_system.services.human_review_support import (
    human_review_followup_target,
    human_review_linked_target,
    structured_target_from_replay_result,
)
from novel_system.services.idempotency import execute_with_idempotency
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
    return ok(
        {"items": [_serialize_review(item) for item in items]},
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/review-items/{review_id}")
def review_detail(review_id: str, request: Request, session: Session = Depends(get_session)):
    item = session.get(ReviewItem, review_id)
    if item is None:
        raise DomainError("REVIEW_NOT_FOUND", f"review {review_id} not found", status_code=404)
    return ok(_serialize_review(item), req_id=getattr(request.state, "request_id", None))


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
    return _serialize_review(item)


@router.post("/api/v1/review-items/{review_id}/approve")
def approve_review(review_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/review-items/{review_id}/approve",
        payload={"review_id": review_id},
        action=lambda: ReviewMaterializationService(session).materialize_review(review_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


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


def _serialize_review(item: ReviewItem) -> dict:
    return {
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
    return ok(
        {"items": [_serialize_event(item) for item in items]},
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
