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
    HumanReviewEvent,
    LlmCall,
    QcReport,
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
from novel_system.services.scene_run_preflight import SceneRunPreflightService

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
    run_preflight = SceneRunPreflightService(session).build(scene, chapter_state)
    bundle = session.get(SceneBundle, state.current_bundle_id) if state.current_bundle_id else None
    neutral = session.get(SceneDraft, state.current_neutral_draft_row_id) if state.current_neutral_draft_row_id else None
    style = session.get(SceneDraft, state.current_style_draft_row_id) if state.current_style_draft_row_id else None
    final = session.get(FinalScene, state.current_final_scene_row_id) if state.current_final_scene_row_id else None
    memory = session.execute(
        select(SceneMemory).where(SceneMemory.scene_id == scene_id, SceneMemory.active_flag == 1)
    ).scalars().first()
    generation_summary = _serialize_generation_summary(_latest_generation_call(session, scene_id))
    hard_qc_summary = _serialize_qc_summary(_latest_qc_report(session, scene_id, "hard_qc"))
    soft_qc_summary = _serialize_qc_summary(_latest_qc_report(session, scene_id, "soft_qc"))
    human_review_summary = _serialize_human_review_summary(
        _latest_human_review_event(session, scene_id, state.current_human_review_event_id)
    )
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
            "run_preflight": run_preflight,
            "bundle": {
                "bundle_id": bundle.bundle_id if bundle else None,
                "bundle_snapshot_hash": bundle.bundle_snapshot_hash if bundle else None,
                "snapshot": bundle.frozen_snapshot_json if bundle else None,
            },
            "neutral_draft": {"row_id": neutral.row_id, "content": neutral.content} if neutral else None,
            "style_draft": {"row_id": style.row_id, "content": style.content} if style else None,
            "final_scene": {"row_id": final.row_id, "content": final.content} if final else None,
            "scene_memory": {"row_id": memory.row_id, "content": memory.content} if memory else None,
            "generation_summary": generation_summary,
            "hard_qc_summary": hard_qc_summary,
            "soft_qc_summary": soft_qc_summary,
            "rewrite_counters": {
                "hard_partial_rewrite_count": state.hard_partial_rewrite_count,
                "hard_full_rewrite_count": state.hard_full_rewrite_count,
                "soft_patch_count": state.soft_patch_count,
                "repeat_issue_key": state.repeat_issue_key,
                "repeat_issue_count": state.repeat_issue_count,
            },
            "human_review_summary": human_review_summary,
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


def _latest_generation_call(session: Session, scene_id: str) -> LlmCall | None:
    calls = session.execute(
        select(LlmCall)
        .where(
            LlmCall.scene_id == scene_id,
            LlmCall.step.in_(["soft_patch", "style_patch", "style_draft", "neutral_draft"]),
        )
        .order_by(LlmCall.created_at.desc(), LlmCall.llm_call_id.desc())
    ).scalars().all()
    if not calls:
        return None
    for preferred_steps in (("soft_patch", "style_patch"), ("style_draft",), ("neutral_draft",)):
        for call in calls:
            if call.step in preferred_steps:
                return call
    return calls[0]


def _serialize_generation_summary(call: LlmCall | None) -> dict | None:
    if call is None:
        return None
    return {
        "step": _display_generation_step(call.step),
        "raw_step": call.step,
        "provider": call.provider,
        "model": call.model,
        "prompt_hash": call.prompt_hash,
        "prompt_tokens": call.prompt_tokens,
        "completion_tokens": call.completion_tokens,
        "total_tokens": call.total_tokens,
        "latency_ms": call.latency_ms,
        "finish_reason": call.finish_reason,
        "error_code": call.error_code,
    }


def _display_generation_step(step: str | None) -> str | None:
    if step in {"soft_patch", "style_patch"}:
        return "soft_patch"
    return step


def _latest_qc_report(session: Session, scene_id: str, qc_type: str) -> QcReport | None:
    return session.execute(
        select(QcReport)
        .where(QcReport.scene_id == scene_id, QcReport.qc_type == qc_type)
        .order_by(QcReport.created_at.desc(), QcReport.qc_report_id.desc())
    ).scalars().first()


def _serialize_qc_summary(report: QcReport | None) -> dict | None:
    if report is None:
        return None
    issue_keys = _extract_issue_keys(report.issues_json or [])
    summary = {
        "qc_type": report.qc_type,
        "pass_flag": bool(report.pass_flag),
        "resolution_code": report.resolution_code,
        "issue_keys": issue_keys,
        "next_action": report.next_action,
        "rewrite_brief": _extract_rewrite_brief(report.rewrite_brief_json or []),
    }
    carry_note = _extract_carry_note(report.rewrite_brief_json or [])
    if carry_note is not None:
        summary.update(carry_note)
    return summary


def _extract_issue_keys(issues_json: list[dict]) -> list[str]:
    issue_keys: list[str] = []
    for issue in issues_json:
        if not isinstance(issue, dict):
            continue
        issue_key = issue.get("issue_key")
        if isinstance(issue_key, str) and issue_key and issue_key not in issue_keys:
            issue_keys.append(issue_key)
    return issue_keys


def _extract_rewrite_brief(rewrite_brief_json: list[dict]) -> list[str]:
    rewrite_brief: list[str] = []
    for entry in rewrite_brief_json:
        if not isinstance(entry, dict):
            continue
        instruction = entry.get("instruction")
        if isinstance(instruction, str) and instruction.strip():
            rewrite_brief.append(instruction.strip())
    return rewrite_brief


def _extract_carry_note(rewrite_brief_json: list[dict]) -> dict | None:
    for entry in rewrite_brief_json:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind") != "carry_forward_note":
            continue
        note_scope = entry.get("note_scope")
        carry_note_text = entry.get("carry_note_text")
        if isinstance(note_scope, str) and note_scope.strip() and isinstance(carry_note_text, str) and carry_note_text.strip():
            return {
                "carry_note_scope": note_scope.strip(),
                "carry_note_text": carry_note_text.strip(),
            }
    return None


def _latest_human_review_event(
    session: Session,
    scene_id: str,
    current_event_id: str | None,
) -> HumanReviewEvent | None:
    if current_event_id:
        current_event = session.get(HumanReviewEvent, current_event_id)
        if current_event is not None:
            return current_event
    return session.execute(
        select(HumanReviewEvent)
        .where(HumanReviewEvent.scene_id == scene_id)
        .order_by(HumanReviewEvent.created_at.desc(), HumanReviewEvent.event_id.desc())
    ).scalars().first()


def _serialize_human_review_summary(event: HumanReviewEvent | None) -> dict | None:
    if event is None:
        return None
    details = dict(event.details_json or {})
    action_history = details.get("action_history")
    action_count = len(action_history) if isinstance(action_history, list) else 0
    last_action = details.get("last_action")
    if not isinstance(last_action, str) or not last_action:
        last_action = None
        if isinstance(action_history, list) and action_history:
            last_entry = action_history[-1]
            if isinstance(last_entry, dict):
                candidate_action = last_entry.get("action")
                if isinstance(candidate_action, str) and candidate_action:
                    last_action = candidate_action
    trigger_reason = details.get("trigger_reason") if isinstance(details.get("trigger_reason"), str) else None
    recommended_action = (
        details.get("recommended_action") if isinstance(details.get("recommended_action"), str) else None
    )
    summary_parts = [part for part in [event.status, trigger_reason, recommended_action] if part]
    return {
        "event_id": event.event_id,
        "status": event.status,
        "event_source": event.event_source,
        "priority": event.priority,
        "trigger_reason": trigger_reason,
        "failure_reason": details.get("failure_reason") if isinstance(details.get("failure_reason"), str) else None,
        "recommended_action": recommended_action,
        "linked_target_ref": details.get("linked_target_ref") if isinstance(details.get("linked_target_ref"), str) else None,
        "last_action": last_action,
        "action_count": action_count,
        "summary_text": " · ".join(summary_parts) if summary_parts else event.status,
    }


def _next_scene_seq(session: Session, chapter_id: str) -> int:
    return AuthorLifecycleService(session).next_scene_append_seq(chapter_id)
