from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import (
    AttemptTracker,
    ChapterGoal,
    FinalScene,
    SceneBundle,
    SceneCard,
    SceneDraft,
    SceneMemory,
    SceneRunState,
)
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.chapter_runtime import ChapterRuntimeService, clean_backfill_markers
from novel_system.services.errors import DomainError
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.pagination import paginate_items, resolve_pagination_request

router = APIRouter(tags=["scenes"])


@router.post("/api/v1/scenes/trash")
def trash_scenes(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/trash",
        payload=payload,
        action=lambda: AuthorLifecycleService(session).trash_scenes(payload.get("scene_ids") or [], actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/scenes/restore")
def restore_scenes(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/restore",
        payload=payload,
        action=lambda: AuthorLifecycleService(session).restore_scenes(payload.get("scene_ids") or []),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/scenes/purge")
def purge_scenes(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/purge",
        payload=payload,
        action=lambda: AuthorLifecycleService(session).purge_scenes(payload.get("scene_ids") or []),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/scenes")
def create_scene(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes",
        payload=payload,
        action=lambda: _create_scene(session, payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


def _create_scene(session: Session, payload: dict) -> dict:
    lifecycle = AuthorLifecycleService(session)
    chapter_id = payload.get("chapter_id")
    if not isinstance(chapter_id, str) or not chapter_id:
        raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)

    chapter = lifecycle.require_active_chapter(chapter_id)

    scene = session.get(SceneCard, payload["scene_id"])
    if scene is None:
        if payload.get("scene_seq") is None:
            payload = {
                **payload,
                "scene_seq": _next_scene_seq(session, chapter_id),
            }
        scene = SceneCard(**payload)
        session.add(scene)
    else:
        if scene.trashed_flag == 1:
            raise DomainError("SCENE_TRASHED", "scene is currently in author trash")
        if payload.get("scene_seq") is None:
            payload = {
                **payload,
                "scene_seq": scene.scene_seq,
            }
        for key, value in payload.items():
            setattr(scene, key, value)

    state = session.get(SceneRunState, payload["scene_id"])
    if state is None:
        state = SceneRunState(scene_id=payload["scene_id"], scene_status="ready")
        session.add(state)
    session.flush()
    return {"scene_id": scene.scene_id}


@router.post("/api/v1/scenes/{scene_id}/run/full")
def run_scene(scene_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_scene(scene_id)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/run/full",
        payload={"scene_id": scene_id},
        action=lambda: Orchestrator(session).run_scene(scene_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/scenes/{scene_id}/status")
def scene_status(scene_id: str, request: Request, session: Session = Depends(get_session)):
    AuthorLifecycleService(session).require_active_scene(scene_id)
    state = session.get(SceneRunState, scene_id)
    return ok(
        {
            "scene_status": state.scene_status,
            "current_bundle_id": state.current_bundle_id,
            "current_bundle_hash": state.current_bundle_hash,
            "current_neutral_draft_row_id": state.current_neutral_draft_row_id,
            "current_style_draft_row_id": state.current_style_draft_row_id,
            "current_final_scene_row_id": state.current_final_scene_row_id,
            "repeat_issue_key": state.repeat_issue_key,
            "repeat_issue_count": state.repeat_issue_count,
        },
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/scenes/{scene_id}/attempts")
def scene_attempts(
    scene_id: str,
    request: Request,
    session: Session = Depends(get_session),
    page: int | None = None,
    page_size: int | None = None,
    cursor: str | None = None,
    limit: int | None = None,
):
    AuthorLifecycleService(session).require_active_scene(scene_id)
    items = session.execute(
        select(AttemptTracker).where(AttemptTracker.scene_id == scene_id).order_by(AttemptTracker.attempt_id.desc())
    ).scalars().all()
    page_items, pagination = paginate_items(
        items,
        request=resolve_pagination_request(page=page, page_size=page_size, cursor=cursor, limit=limit),
        cursor_values=lambda item: [item.attempt_id],
    )
    return ok(
        {"items": [_serialize_attempt(item) for item in page_items], "pagination": pagination},
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/scenes/{scene_id}/workbench")
def scene_workbench(scene_id: str, request: Request, session: Session = Depends(get_session)):
    scene = AuthorLifecycleService(session).require_active_scene(scene_id)
    chapter = session.get(ChapterGoal, scene.chapter_id)
    state = session.get(SceneRunState, scene_id)
    runtime_service = ChapterRuntimeService(session)
    chapter_state = runtime_service.chapter_state_payload(scene.chapter_id)
    bundle = session.get(SceneBundle, state.current_bundle_id) if state.current_bundle_id else None
    neutral = session.get(SceneDraft, state.current_neutral_draft_row_id) if state.current_neutral_draft_row_id else None
    style = session.get(SceneDraft, state.current_style_draft_row_id) if state.current_style_draft_row_id else None
    final = session.get(FinalScene, state.current_final_scene_row_id) if state.current_final_scene_row_id else None
    memory = session.execute(
        select(SceneMemory).where(SceneMemory.scene_id == scene_id, SceneMemory.active_flag == 1)
    ).scalars().first()
    attempts = session.execute(
        select(AttemptTracker).where(AttemptTracker.scene_id == scene_id).order_by(AttemptTracker.attempt_id.asc())
    ).scalars().all()
    response = ok(
        {
            "chapter_goal": {
                "chapter_id": chapter.chapter_id,
                "chapter_goal": chapter.chapter_goal,
                "main_plot_push": chapter.main_plot_push,
                "emotional_target": chapter.emotional_target,
                "ending_effect": chapter.ending_effect,
            },
            "scene_card": {
                "scene_id": scene.scene_id,
                "scene_goal": scene.scene_goal,
                "beats_json": scene.beats_json,
                "must_include_text": clean_backfill_markers(scene.must_include_text),
                "location": scene.location,
            },
            "scene_run_state": {
                "scene_status": state.scene_status,
                "current_bundle_id": state.current_bundle_id,
                "current_bundle_hash": state.current_bundle_hash,
                "current_final_scene_row_id": state.current_final_scene_row_id,
            },
            "chapter_state": chapter_state,
            "bundle": {
                "bundle_id": bundle.bundle_id if bundle else None,
                "bundle_snapshot_hash": bundle.bundle_snapshot_hash if bundle else None,
                "snapshot": bundle.frozen_snapshot_json if bundle else None,
            },
            "neutral_draft": {"row_id": neutral.row_id, "content": neutral.content} if neutral else None,
            "style_draft": {"row_id": style.row_id, "content": style.content} if style else None,
            "final_scene": {"row_id": final.row_id, "content": final.content} if final else None,
            "scene_memory": {"row_id": memory.row_id, "content": memory.content} if memory else None,
            "attempts": [_serialize_attempt(item) for item in attempts],
        },
        req_id=getattr(request.state, "request_id", None),
    )
    session.commit()
    return response


def _serialize_attempt(item: AttemptTracker) -> dict:
    return {
        "attempt_id": item.attempt_id,
        "step": item.step,
        "status": item.status,
        "source_bundle_id": item.source_bundle_id,
        "details_json": item.details_json,
        "created_at": item.created_at,
    }


def _next_scene_seq(session: Session, chapter_id: str) -> int:
    return AuthorLifecycleService(session).next_scene_append_seq(chapter_id)
