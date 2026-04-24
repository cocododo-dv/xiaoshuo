from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.longform_control import LongformControlService

router = APIRouter(tags=["longform-control"])


@router.get("/api/v1/longform-control")
def get_longform_control(request: Request, session: Session = Depends(get_session)):
    payload = LongformControlService(session).dashboard()
    return ok(payload, req_id=getattr(request.state, "request_id", None))
