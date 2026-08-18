from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.mutations import optional_idempotent_response
from novel_system.api.request_types import EmptyRequest
from novel_system.api.response import ok
from novel_system.services.longform_editor import LongformEditorService

router = APIRouter(tags=["longform-editor"])


class CardActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["resolve", "dismiss", "reopen"]
    note: str | None = Field(default=None, max_length=4_000)


class PublishGuidanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scope_type: Literal["global", "chapter", "scene", "character"]
    scope_ref_id: str | None = Field(default=None, max_length=255)
    content: str = Field(min_length=1, max_length=100_000)


@router.get("/api/v1/longform-editor/overview")
def get_longform_editor_overview(request: Request, session: Session = Depends(get_session)):
    payload = LongformEditorService(session).overview()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/longform-editor/diagnose")
def diagnose_longform_editor(
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/longform-editor/diagnose",
        payload={},
        action=lambda: LongformEditorService(session).diagnose(),
    )


@router.get("/api/v1/longform-editor/cards")
def list_longform_editor_cards(
    request: Request,
    session: Session = Depends(get_session),
    status: str | None = None,
    card_type: str | None = None,
    chapter_id: str | None = None,
    scene_id: str | None = None,
):
    payload = LongformEditorService(session).list_cards(
        status=status,
        card_type=card_type,
        chapter_id=chapter_id,
        scene_id=scene_id,
    )
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/longform-editor/cards/{card_id}/actions")
def longform_editor_card_action(
    card_id: str,
    payload: CardActionRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/longform-editor/cards/{card_id}/actions",
        payload={"card_id": card_id, "body": body},
        action=lambda: LongformEditorService(session).card_action(card_id, **body),
    )


@router.post("/api/v1/longform-editor/cards/{card_id}/publish-guidance")
def publish_longform_guidance(
    card_id: str,
    payload: PublishGuidanceRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json")
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/longform-editor/cards/{card_id}/publish-guidance",
        payload={"card_id": card_id, "body": body},
        action=lambda: LongformEditorService(session).publish_guidance(card_id, **body),
    )
