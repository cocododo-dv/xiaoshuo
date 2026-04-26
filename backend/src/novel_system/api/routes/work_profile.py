from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.work_profile import WorkProfileService

router = APIRouter(tags=["work-profile"])


@router.get("/api/v1/work-profile/chapter/{chapter_id}")
def get_chapter_work_profile(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    payload = {"profile": WorkProfileService(session).for_chapter(chapter_id)}
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/work-profile")
def save_work_profile(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = WorkProfileService(session).upsert(payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))
