from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.writer_review import WriterReviewService

router = APIRouter(tags=["writer-review"])


@router.get("/api/v1/scenes/{scene_id}/writer-review")
def get_scene_writer_review(scene_id: str, request: Request, session: Session = Depends(get_session)):
    payload = WriterReviewService(session).scene_review(scene_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/scenes/{scene_id}/writer-review/run")
def run_scene_writer_review(scene_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    payload = WriterReviewService(session).run_scene_review(scene_id, actor_ref=actor_ref)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/scenes/{scene_id}/writer-review")
def run_scene_writer_review_alias(scene_id: str, request: Request, session: Session = Depends(get_session)):
    return run_scene_writer_review(scene_id, request, session)


@router.get("/api/v1/chapters/{chapter_id}/writer-review")
def get_chapter_writer_review(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    payload = WriterReviewService(session).chapter_review(chapter_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/chapters/{chapter_id}/writer-review/run")
def run_chapter_writer_review(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    payload = WriterReviewService(session).run_chapter_review(chapter_id, actor_ref=actor_ref)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/chapters/{chapter_id}/writer-review")
def run_chapter_writer_review_alias(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    return run_chapter_writer_review(chapter_id, request, session)


@router.post("/api/v1/revision-candidates/{revision_id}/accept")
def accept_revision_candidate(revision_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    result = WriterReviewService(session).accept_revision(revision_id, note=payload.get("note"))
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/revision-candidates/{revision_id}/reject")
def reject_revision_candidate(revision_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    result = WriterReviewService(session).reject_revision(revision_id, note=payload.get("note"))
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))
