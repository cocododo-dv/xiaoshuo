from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.literary_quality import LiteraryQualityService

router = APIRouter(tags=["literary_quality"])


@router.get("/api/v1/literary-quality/overview")
def literary_quality_overview(
    request: Request,
    text_layer: str = "author_draft_preferred",
    session: Session = Depends(get_session),
):
    payload = LiteraryQualityService(session).overview(text_layer=text_layer)
    return ok(payload, req_id=getattr(request.state, "request_id", None))
