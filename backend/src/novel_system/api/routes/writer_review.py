from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.mutations import optional_idempotent_response
from novel_system.api.request_types import EmptyRequest, StrictRequestModel
from novel_system.api.response import ok
from novel_system.services.writer_review import WriterReviewService

router = APIRouter(tags=["writer-review"])


class RevisionDecisionRequest(StrictRequestModel):
    note: str | None = Field(default=None, max_length=4000)


@router.get("/api/v1/scenes/{scene_id}/writer-review")
def get_scene_writer_review(scene_id: str, request: Request, session: Session = Depends(get_session)):
    payload = WriterReviewService(session).scene_review(scene_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/scenes/{scene_id}/writer-review/run")
def run_scene_writer_review(
    scene_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/writer-review/run",
        payload={"scene_id": scene_id},
        action=lambda: WriterReviewService(session).run_scene_review(scene_id, actor_ref=actor_ref),
    )


@router.post("/api/v1/scenes/{scene_id}/writer-review")
def run_scene_writer_review_alias(
    scene_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/writer-review",
        payload={"scene_id": scene_id},
        action=lambda: WriterReviewService(session).run_scene_review(scene_id, actor_ref=actor_ref),
    )


@router.get("/api/v1/chapters/{chapter_id}/writer-review")
def get_chapter_writer_review(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    payload = WriterReviewService(session).chapter_review(chapter_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/chapters/{chapter_id}/writer-review/run")
def run_chapter_writer_review(
    chapter_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/chapters/{chapter_id}/writer-review/run",
        payload={"chapter_id": chapter_id},
        action=lambda: WriterReviewService(session).run_chapter_review(chapter_id, actor_ref=actor_ref),
    )


@router.post("/api/v1/chapters/{chapter_id}/writer-review")
def run_chapter_writer_review_alias(
    chapter_id: str,
    request: Request,
    payload: EmptyRequest | None = None,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/chapters/{chapter_id}/writer-review",
        payload={"chapter_id": chapter_id},
        action=lambda: WriterReviewService(session).run_chapter_review(chapter_id, actor_ref=actor_ref),
    )


@router.post("/api/v1/revision-candidates/{revision_id}/accept")
def accept_revision_candidate(
    revision_id: str,
    request: Request,
    payload: RevisionDecisionRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/revision-candidates/{revision_id}/accept",
        payload={"revision_id": revision_id, "body": body},
        action=lambda: WriterReviewService(session).accept_revision(revision_id, note=body.get("note")),
    )


@router.post("/api/v1/revision-candidates/{revision_id}/reject")
def reject_revision_candidate(
    revision_id: str,
    request: Request,
    payload: RevisionDecisionRequest | None = None,
    session: Session = Depends(get_session),
):
    body = payload.model_dump(mode="json", exclude_unset=True) if payload is not None else {}
    return optional_idempotent_response(
        request,
        session,
        method="POST",
        path_template="/api/v1/revision-candidates/{revision_id}/reject",
        payload={"revision_id": revision_id, "body": body},
        action=lambda: WriterReviewService(session).reject_revision(revision_id, note=body.get("note")),
    )
