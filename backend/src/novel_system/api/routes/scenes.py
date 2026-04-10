from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import AttemptTracker, ChapterGoal, ChapterState, FinalScene, SceneBundle, SceneCard, SceneDraft, SceneMemory, SceneRunState
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.orchestrator import Orchestrator

router = APIRouter(tags=["scenes"])


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
    scene = session.get(SceneCard, payload["scene_id"])
    if scene is None:
        scene = SceneCard(**payload)
        session.add(scene)
    else:
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
def scene_attempts(scene_id: str, request: Request, session: Session = Depends(get_session)):
    items = session.execute(
        select(AttemptTracker).where(AttemptTracker.scene_id == scene_id).order_by(AttemptTracker.attempt_id.desc())
    ).scalars().all()
    return ok(
        {"items": [_serialize_attempt(item) for item in items]},
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/scenes/{scene_id}/workbench")
def scene_workbench(scene_id: str, request: Request, session: Session = Depends(get_session)):
    scene = session.get(SceneCard, scene_id)
    chapter = session.get(ChapterGoal, scene.chapter_id)
    state = session.get(SceneRunState, scene_id)
    chapter_state = session.get(ChapterState, scene.chapter_id)
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
    return ok(
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
                "must_include_text": scene.must_include_text,
                "location": scene.location,
            },
            "scene_run_state": {
                "scene_status": state.scene_status,
                "current_bundle_id": state.current_bundle_id,
                "current_bundle_hash": state.current_bundle_hash,
                "current_final_scene_row_id": state.current_final_scene_row_id,
            },
            "chapter_state": {
                "chapter_backfill_pending_count": chapter_state.chapter_backfill_pending_count,
                "aggregate_block_reason": chapter_state.aggregate_block_reason,
                "mid_aggregate_enabled_effective": chapter_state.mid_aggregate_enabled_effective,
            },
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


def _serialize_attempt(item: AttemptTracker) -> dict:
    return {
        "attempt_id": item.attempt_id,
        "step": item.step,
        "status": item.status,
        "source_bundle_id": item.source_bundle_id,
        "details_json": item.details_json,
        "created_at": item.created_at,
    }
