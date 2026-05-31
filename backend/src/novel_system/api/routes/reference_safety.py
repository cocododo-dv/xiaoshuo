from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.reference_safety import ReferenceSafetyService

router = APIRouter(tags=["reference-safety"])


class SourceSafetyScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    source_profile_ids: list[str] | None = None
    object_ref: str | None = None


@router.get("/api/v1/reference-safety/overview")
def get_reference_safety_overview(request: Request, session: Session = Depends(get_session)):
    return ok(
        ReferenceSafetyService(session).overview(),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v2/style-reference/books/{book_id}/safety-profile/extract")
def extract_reference_safety_profile(book_id: str, request: Request, session: Session = Depends(get_session)):
    payload = ReferenceSafetyService(session).extract_profile(book_id)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/source-safety/scan")
def scan_source_safety(payload: SourceSafetyScanRequest, request: Request, session: Session = Depends(get_session)):
    result = ReferenceSafetyService(session).scan_text(**payload.model_dump(mode="json"))
    return ok(result, req_id=getattr(request.state, "request_id", None))
