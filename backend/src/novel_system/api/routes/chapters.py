from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import ChapterGoal, ChapterState
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
    state = session.get(ChapterState, chapter_id)
    return ok(
        {
            "chapter_id": chapter_id,
            "chapter_passed_scene_count": state.chapter_passed_scene_count,
            "chapter_backfill_pending_count": state.chapter_backfill_pending_count,
            "mid_aggregate_enabled_effective": state.mid_aggregate_enabled_effective,
            "aggregate_block_reason": state.aggregate_block_reason,
            "last_final_memory_row_id": state.last_final_memory_row_id,
        },
        req_id=getattr(request.state, "request_id", None),
    )
