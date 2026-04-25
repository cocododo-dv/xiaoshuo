from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.author_drafts import AuthorDraftService

router = APIRouter(tags=["author-drafts"])


@router.get("/api/v1/author-drafts/{object_type}/{object_id}/current")
def get_current_author_draft(object_type: str, object_id: str, request: Request, session: Session = Depends(get_session)):
    payload = AuthorDraftService(session).current(object_type, object_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{object_type}/{object_id}/ensure")
def ensure_author_draft(object_type: str, object_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    payload = AuthorDraftService(session).ensure(object_type, object_id, actor_ref=actor_ref)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.patch("/api/v1/author-drafts/{draft_id}")
def save_author_draft(draft_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).save(draft_id, payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/author-drafts/{draft_id}/candidate-events")
def record_author_draft_candidate_event(draft_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = AuthorDraftService(session).record_candidate_event(draft_id, payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))
