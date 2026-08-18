from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.mutations import optional_idempotent_response
from novel_system.api.request_types import BoundedJsonObject, StrictRequestModel
from novel_system.api.response import ok
from novel_system.services.work_profile import WorkProfileService

router = APIRouter(tags=["work-profile"])


class WorkProfileUpsertRequest(StrictRequestModel):
    # The domain service owns scope/profile fallback semantics.
    scope_type: str | None = Field(default=None, max_length=64)
    scope_ref_id: str | None = Field(default=None, max_length=255)
    profile_key: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    profile_json: BoundedJsonObject | None = None


@router.get("/api/v1/work-profile/chapter/{chapter_id}")
def get_chapter_work_profile(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    payload = {"profile": WorkProfileService(session).for_chapter(chapter_id)}
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/work-profile")
def save_work_profile(
    payload: WorkProfileUpsertRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    body = payload.model_dump(mode="json", exclude_unset=True)
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/work-profile",
        payload=body,
        action=lambda: WorkProfileService(session).upsert(body, actor_ref=actor_ref),
    )
