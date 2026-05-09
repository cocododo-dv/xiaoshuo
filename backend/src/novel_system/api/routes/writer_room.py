from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.writer_room import WriterRoomService

router = APIRouter(tags=["writer-room"])


@router.get("/api/v1/writer-room/{object_type}/{object_id}")
def get_writer_room(object_type: str, object_id: str, request: Request, session: Session = Depends(get_session)):
    payload = WriterRoomService(session).room(object_type, object_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))
