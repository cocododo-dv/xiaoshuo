from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.author_desk import AuthorDeskService

router = APIRouter(tags=["author-desk"])


@router.get("/api/v1/author-desk/{object_type}/{object_id}/snapshot")
def get_author_desk_snapshot(object_type: str, object_id: str, request: Request, session: Session = Depends(get_session)):
    payload = AuthorDeskService(session).snapshot(object_type, object_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))
