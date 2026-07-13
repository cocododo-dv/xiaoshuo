from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import ChapterGoal, ChapterState, SceneCard, SceneRunState
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.chapter_runner import ChapterRunnerService
from novel_system.services.chapter_runtime import ChapterRuntimeService
from novel_system.services.errors import DomainError
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.text_validation import validate_user_text_payload
from novel_system.services.writer_review import normalize_chapter_writer_brief

router = APIRouter(tags=["chapters"])


@router.get("/api/v1/chapters")
def list_chapters(request: Request, session: Session = Depends(get_session)):
    return ok(
        {"items": AuthorLifecycleService(session).list_active_chapters()},
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/author-trash")
def author_trash(request: Request, session: Session = Depends(get_session)):
    return ok(
        AuthorLifecycleService(session).author_trash_payload(),
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


@router.post("/api/v1/chapters/trash")
def trash_chapters(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/trash",
        payload=payload,
        action=lambda: AuthorLifecycleService(session).trash_chapters(payload.get("chapter_ids") or [], actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/chapters/restore")
def restore_chapters(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/restore",
        payload=payload,
        action=lambda: AuthorLifecycleService(session).restore_chapters(payload.get("chapter_ids") or []),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/chapters/purge")
def purge_chapters(payload: dict, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/purge",
        payload=payload,
        action=lambda: AuthorLifecycleService(session).purge_chapters(payload.get("chapter_ids") or []),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


def _create_chapter(session: Session, payload: dict) -> dict:
    validate_user_text_payload(payload, field_prefix="chapter")
    payload = {
        **payload,
        "writer_brief_json": normalize_chapter_writer_brief(payload.get("writer_brief_json")),
    }
    chapter = session.get(ChapterGoal, payload["chapter_id"])
    if chapter is None:
        chapter = ChapterGoal(**payload)
        session.add(chapter)
    else:
        if chapter.trashed_flag == 1:
            raise DomainError("CHAPTER_TRASHED", "chapter is currently in author trash")
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
    AuthorLifecycleService(session).require_active_chapter(chapter_id)
    payload = ChapterRuntimeService(session).chapter_state_payload(chapter_id)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/chapters/{chapter_id}/author-workspace")
def author_workspace(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(
        AuthorLifecycleService(session).author_workspace_payload(chapter_id),
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/chapters/{chapter_id}/scene-draft")
def chapter_scene_draft(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    return ok(
        AuthorLifecycleService(session).scene_draft_payload(chapter_id),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/chapters/{chapter_id}/run/full")
def run_chapter_full(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_chapter(chapter_id)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/chapters/{chapter_id}/run/full",
        payload={"chapter_id": chapter_id},
        action=lambda lease: ChapterRunnerService(session).run_full(chapter_id, request_lease=lease),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/chapters/{chapter_id}/run-status")
def chapter_run_status(chapter_id: str, request: Request, session: Session = Depends(get_session)):
    AuthorLifecycleService(session).require_active_chapter(chapter_id)
    payload = ChapterRunnerService(session).run_status(chapter_id)
    session.commit()
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/chapters/{chapter_id}/runtime/backfill/{stage_id}")
def chapter_runtime_backfill(
    chapter_id: str,
    stage_id: str,
    payload: dict,
    request: Request,
    session: Session = Depends(get_session),
):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_chapter(chapter_id)
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
    AuthorLifecycleService(session).require_active_chapter(chapter_id)
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
    AuthorLifecycleService(session).require_active_chapter(chapter_id)
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
    AuthorLifecycleService(session).require_active_chapter(chapter_id)
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
    return AuthorLifecycleService(session).serialize_chapter_summary(chapter)


def _serialize_chapter(chapter: ChapterGoal) -> dict:
    return AuthorLifecycleService(None).serialize_chapter(chapter)  # type: ignore[arg-type]


def _serialize_chapter_state(chapter_state: ChapterState | None, chapter_id: str) -> dict:
    return AuthorLifecycleService(None).serialize_chapter_state(chapter_state, chapter_id)  # type: ignore[arg-type]


def _serialize_author_scene(scene: SceneCard, scene_state: SceneRunState | None) -> dict:
    return AuthorLifecycleService(None).serialize_author_scene(scene, scene_state)  # type: ignore[arg-type]


def _reorder_chapter_scenes(session: Session, chapter_id: str, payload: dict) -> dict:
    AuthorLifecycleService(session).require_active_chapter(chapter_id)

    scene_ids = payload.get("scene_ids")
    if not isinstance(scene_ids, list) or not scene_ids or not all(isinstance(scene_id, str) and scene_id for scene_id in scene_ids):
        raise DomainError("SCENE_ORDER_INVALID", "scene_ids must be a non-empty list", status_code=400)

    last_scene_id = payload.get("last_scene_id")
    if not isinstance(last_scene_id, str) or last_scene_id not in scene_ids:
        raise DomainError("SCENE_ORDER_LAST_SCENE_INVALID", "last_scene_id must be present in scene_ids", status_code=400)

    chapter_scenes = session.execute(
        select(SceneCard).where(SceneCard.chapter_id == chapter_id, SceneCard.trashed_flag == 0)
    ).scalars().all()
    chapter_scene_map = {scene.scene_id: scene for scene in chapter_scenes}
    other_chapter_scenes = {
        scene.scene_id
        for scene in session.execute(select(SceneCard).where(SceneCard.scene_id.in_(scene_ids), SceneCard.trashed_flag == 0)).scalars().all()
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
