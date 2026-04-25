from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.services.writer_deep_review import WriterDeepReviewService

router = APIRouter(tags=["writer-deep-review"])


@router.get("/api/v1/scenes/{scene_id}/deep-review")
def get_scene_deep_review(scene_id: str, request: Request, session: Session = Depends(get_session)):
    payload = WriterDeepReviewService(session).scene_summary(scene_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/scenes/{scene_id}/deep-review")
def run_scene_deep_review(scene_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    payload = WriterDeepReviewService(session).run_scene_review(scene_id, actor_ref=actor_ref)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/chapters/{chapter_id}/deep-review")
def get_chapter_deep_review(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    payload = WriterDeepReviewService(session).chapter_summary(chapter_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/chapters/{chapter_id}/deep-review")
def run_chapter_deep_review(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    payload = WriterDeepReviewService(session).run_chapter_review(chapter_id, actor_ref=actor_ref)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/passages/patch-candidates")
def create_passage_patch_candidate(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = WriterDeepReviewService(session).create_patch_candidate(payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/passage-patch-candidates/{patch_id}/accept")
def accept_passage_patch_candidate(patch_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = WriterDeepReviewService(session).accept_patch_candidate(patch_id, payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/passage-patch-candidates/{patch_id}/reject")
def reject_passage_patch_candidate(patch_id: str, payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result = WriterDeepReviewService(session).reject_patch_candidate(patch_id, payload, actor_ref=actor_ref)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/author-preference-profile")
def get_author_preference_profile(request: Request, session: Session = Depends(get_session)):
    payload = WriterDeepReviewService(session).author_preference_profile()
    return ok(payload, req_id=getattr(request.state, "request_id", None))
