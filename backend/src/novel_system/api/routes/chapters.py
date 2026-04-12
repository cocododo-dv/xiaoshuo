from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import ChapterGoal, ChapterState
from novel_system.services.chapter_runtime import ChapterRuntimeService
from novel_system.services.idempotency import execute_with_idempotency

router = APIRouter(tags=["chapters"])


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
