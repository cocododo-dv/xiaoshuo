from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import ChapterGoal, ChapterState, SceneCard, SceneRunState
from novel_system.services.chapter_runtime import ChapterRuntimeService
from novel_system.services.errors import DomainError
from novel_system.services.idempotency import execute_with_idempotency

router = APIRouter(tags=["chapters"])


@router.get("/api/v1/chapters")
def list_chapters(request: Request, session: Session = Depends(get_session)):
    chapters = session.execute(select(ChapterGoal).order_by(ChapterGoal.chapter_id.asc())).scalars().all()
    return ok(
        {"items": [_serialize_chapter_summary(session, chapter) for chapter in chapters]},
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/chapters")
def create_chapter(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters",
        payload=payload,
        action=lambda: _create_chapter(session, payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


def _create_chapter(session: Session, payload: dict) -> dict:
    chapter = session.get(ChapterGoal, payload["chapter_id"])
    if chapter is None:
        chapter = ChapterGoal(**payload)
        session.add(chapter)
    else:
        for key, value in payload.items():
            setattr(chapter, key, value)

    state = session.get(ChapterState, payload["chapter_id"])
    if state is None:
        state = ChapterState(
            chapter_id=payload["chapter_id"],
            current_phase="drafting",
            mid_aggregate_enabled_effective=0,
            aggregate_block_reason="none",
        )
        session.add(state)
    session.flush()
    return {"chapter_id": chapter.chapter_id}


@router.get("/api/v1/chapters/{chapter_id}/status")
def chapter_status(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    payload = ChapterRuntimeService(session).chapter_state_payload(chapter_id)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/chapters/{chapter_id}/author-workspace")
def author_workspace(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    chapter = session.get(ChapterGoal, chapter_id)
    if chapter is None:
        raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)

    chapter_state = session.get(ChapterState, chapter_id)
    scenes = session.execute(
        select(SceneCard).where(SceneCard.chapter_id == chapter_id).order_by(SceneCard.scene_seq.asc(), SceneCard.scene_id.asc())
    ).scalars().all()
    scene_states = {
        state.scene_id: state
        for state in session.execute(
            select(SceneRunState).where(SceneRunState.scene_id.in_([scene.scene_id for scene in scenes]))
        ).scalars().all()
    }
    return ok(
        {
            "chapter": _serialize_chapter(chapter),
            "chapter_state": _serialize_chapter_state(chapter_state, chapter_id),
            "scenes": [_serialize_author_scene(scene, scene_states.get(scene.scene_id)) for scene in scenes],
        },
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/chapters/{chapter_id}/runtime/backfill/{stage_id}")
def chapter_runtime_backfill(
    chapter_id: str,
    stage_id: str,
    payload: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/{chapter_id}/runtime/backfill/{stage_id}",
        payload={"chapter_id": chapter_id, "stage_id": stage_id, **payload},
        action=lambda: ChapterRuntimeService(session).run_backfill(chapter_id, stage_id, payload.get("strategy", "")),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/chapters/{chapter_id}/runtime/aggregate/final")
def chapter_runtime_final_aggregate(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/{chapter_id}/runtime/aggregate/final",
        payload={"chapter_id": chapter_id},
        action=lambda: ChapterRuntimeService(session).run_final_aggregate(chapter_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/chapters/{chapter_id}/runtime/manual-hold")
def chapter_runtime_manual_hold(
    chapter_id: str,
    payload: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/{chapter_id}/runtime/manual-hold",
        payload={"chapter_id": chapter_id, **payload},
        action=lambda: ChapterRuntimeService(session).set_manual_hold(chapter_id, payload.get("reason", "")),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/chapters/{chapter_id}/runtime/manual-hold/clear")
def chapter_runtime_manual_hold_clear(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/{chapter_id}/runtime/manual-hold/clear",
        payload={"chapter_id": chapter_id},
        action=lambda: ChapterRuntimeService(session).clear_manual_hold(chapter_id),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/chapters/{chapter_id}/scene-order")
def reorder_chapter_scenes(
    chapter_id: str,
    payload: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/{chapter_id}/scene-order",
        payload={"chapter_id": chapter_id, **payload},
        action=lambda: _reorder_chapter_scenes(session, chapter_id, payload),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


def _serialize_chapter_summary(session: Session, chapter: ChapterGoal) -> dict:
    chapter_state = session.get(ChapterState, chapter.chapter_id)
    return {
        "chapter_id": chapter.chapter_id,
        "planned_scene_count": chapter.planned_scene_count,
        "chapter_goal": chapter.chapter_goal,
        "main_plot_push": chapter.main_plot_push,
        "emotional_target": chapter.emotional_target,
        "ending_effect": chapter.ending_effect,
        "must_not": chapter.must_not,
        "notes": chapter.notes,
        "current_phase": chapter_state.current_phase if chapter_state else "planning",
        "chapter_passed_scene_count": chapter_state.chapter_passed_scene_count if chapter_state else 0,
        "chapter_backfill_pending_count": chapter_state.chapter_backfill_pending_count if chapter_state else 0,
    }


def _serialize_chapter(chapter: ChapterGoal) -> dict:
    return {
        "chapter_id": chapter.chapter_id,
        "planned_scene_count": chapter.planned_scene_count,
        "mid_aggregate_enabled": chapter.mid_aggregate_enabled,
        "chapter_goal": chapter.chapter_goal,
        "main_plot_push": chapter.main_plot_push,
        "emotional_target": chapter.emotional_target,
        "ending_effect": chapter.ending_effect,
        "must_not": chapter.must_not,
        "notes": chapter.notes,
    }


def _serialize_chapter_state(chapter_state: ChapterState | None, chapter_id: str) -> dict:
    if chapter_state is None:
        return {
            "chapter_id": chapter_id,
            "current_phase": "planning",
            "chapter_passed_scene_count": 0,
            "chapter_backfill_pending_count": 0,
        }
    return {
        "chapter_id": chapter_state.chapter_id,
        "current_phase": chapter_state.current_phase,
        "chapter_passed_scene_count": chapter_state.chapter_passed_scene_count,
        "chapter_backfill_pending_count": chapter_state.chapter_backfill_pending_count,
    }


def _serialize_author_scene(scene: SceneCard, scene_state: SceneRunState | None) -> dict:
    return {
        "scene_id": scene.scene_id,
        "chapter_id": scene.chapter_id,
        "scene_seq": scene.scene_seq,
        "pov_character_id": scene.pov_character_id,
        "onstage_chars_json": scene.onstage_chars_json,
        "resolved_relation_id": scene.resolved_relation_id,
        "location": scene.location,
        "scene_goal": scene.scene_goal,
        "beats_json": scene.beats_json,
        "must_include_text": scene.must_include_text,
        "forbidden_text": scene.forbidden_text,
        "exit_change": scene.exit_change,
        "hook": scene.hook,
        "target_length_band": scene.target_length_band,
        "scene_type": scene.scene_type,
        "is_chapter_last": scene.is_chapter_last,
        "scene_status": scene_state.scene_status if scene_state else "ready",
        "current_bundle_id": scene_state.current_bundle_id if scene_state else None,
        "current_final_scene_row_id": scene_state.current_final_scene_row_id if scene_state else None,
    }


def _reorder_chapter_scenes(session: Session, chapter_id: str, payload: dict) -> dict:
    chapter = session.get(ChapterGoal, chapter_id)
    if chapter is None:
        raise DomainError("CHAPTER_NOT_FOUND", "chapter not found", status_code=404)

    scene_ids = payload.get("scene_ids")
    if not isinstance(scene_ids, list) or not scene_ids or not all(isinstance(scene_id, str) and scene_id for scene_id in scene_ids):
        raise DomainError("SCENE_ORDER_INVALID", "scene_ids must be a non-empty list", status_code=400)

    last_scene_id = payload.get("last_scene_id")
    if not isinstance(last_scene_id, str) or last_scene_id not in scene_ids:
        raise DomainError("SCENE_ORDER_LAST_SCENE_INVALID", "last_scene_id must be present in scene_ids", status_code=400)

    chapter_scenes = session.execute(select(SceneCard).where(SceneCard.chapter_id == chapter_id)).scalars().all()
    chapter_scene_map = {scene.scene_id: scene for scene in chapter_scenes}
    other_chapter_scenes = {
        scene.scene_id
        for scene in session.execute(select(SceneCard).where(SceneCard.scene_id.in_(scene_ids))).scalars().all()
        if scene.chapter_id != chapter_id
    }
    if other_chapter_scenes:
        raise DomainError("SCENE_ORDER_CHAPTER_MISMATCH", "scene_ids must belong to the same chapter")

    if set(scene_ids) != set(chapter_scene_map):
        raise DomainError("SCENE_ORDER_INCOMPLETE", "scene_ids must include every scene in the chapter", status_code=409)

    ordered_scenes = [chapter_scene_map[scene_id] for scene_id in scene_ids]
    for index, scene in enumerate(ordered_scenes, start=1):
        scene.scene_seq = index
        scene.is_chapter_last = 1 if scene.scene_id == last_scene_id else 0
    session.flush()
    return {
        "chapter_id": chapter_id,
        "scenes": [
            {"scene_id": scene.scene_id, "scene_seq": scene.scene_seq, "is_chapter_last": scene.is_chapter_last}
            for scene in ordered_scenes
        ],
    }
