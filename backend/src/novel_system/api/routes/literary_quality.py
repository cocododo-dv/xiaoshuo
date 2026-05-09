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
    chapter_id: str | None = None,
    risk_type: str | None = None,
    min_severity: str | None = None,
    session: Session = Depends(get_session),
):
    payload = LiteraryQualityService(session).overview(
        text_layer=text_layer,
        chapter_id=chapter_id,
        risk_type=risk_type,
        min_severity=min_severity,
    )
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/literary-quality/analyze-text")
def literary_quality_analyze_text(
    payload: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    payload = LiteraryQualityService(session).analyze_text(payload)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/literary-quality/chapter-set-review")
def literary_quality_chapter_set_review(
    payload: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    payload = LiteraryQualityService(session).chapter_set_review(payload)
    return ok(payload, req_id=getattr(request.state, "request_id", None))
