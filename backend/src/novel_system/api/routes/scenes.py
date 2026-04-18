from __future__ import annotations

from typing import Any

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
from novel_system.services.style_profile import StyleScoreService

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


@router.get("/api/v1/scenes/{scene_id}/generation-history")
def scene_generation_history(scene_id: str, request: Request, session: Session = Depends(get_session)):
    AuthorLifecycleService(session).require_active_scene(scene_id)
    attempts = session.execute(
        select(AttemptTracker).where(AttemptTracker.scene_id == scene_id).order_by(AttemptTracker.attempt_id.asc())
    ).scalars().all()
    return ok(
        {
            "scene_id": scene_id,
            "items": [
                _serialize_generation_history_item(session, item, attempt_order=index + 1)
                for index, item in enumerate(attempts)
            ],
        },
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
            "generation_summary": _serialize_generation_summary(session, scene_id, state),
            "hard_qc_summary": _serialize_qc_summary(_latest_qc_report(session, scene_id, state, "hard_qc")),
            "soft_qc_summary": _serialize_qc_summary(_latest_qc_report(session, scene_id, state, "soft_qc")),
            "rewrite_counters": {
                "hard_partial_rewrite_count": state.hard_partial_rewrite_count,
                "hard_full_rewrite_count": state.hard_full_rewrite_count,
                "soft_patch_count": state.soft_patch_count,
                "repeat_issue_key": state.repeat_issue_key,
                "repeat_issue_count": state.repeat_issue_count,
            },
            "human_review_summary": _serialize_human_review_summary(_resolve_human_review_event(session, scene_id, state)),
            "attempts": [_serialize_attempt(item) for item in attempts],
        },
        req_id=getattr(request.state, "request_id", None),
    )
    session.commit()
    return response


def _serialize_generation_summary(session: Session, scene_id: str, state: SceneRunState) -> dict | None:
    llm_call = _resolve_generation_llm_call(session, scene_id, state)
    if llm_call is None:
        return None
    summary = {
        "llm_call_id": llm_call.llm_call_id,
        "step": _display_generation_step(llm_call.step),
        "raw_step": llm_call.step,
        "provider": llm_call.provider,
        "model": llm_call.model,
        "prompt_hash": llm_call.prompt_hash,
        "prompt_tokens": llm_call.prompt_tokens,
        "completion_tokens": llm_call.completion_tokens,
        "total_tokens": llm_call.total_tokens,
        "latency_ms": llm_call.latency_ms,
        "finish_reason": llm_call.finish_reason,
        "error_code": llm_call.error_code,
        "created_at": llm_call.created_at,
    }
    style_summary = _style_score_summary_for_scene(session, scene_id, state)
    if style_summary is not None:
        summary["style_score_summary"] = style_summary
    return summary


def _resolve_generation_llm_call(session: Session, scene_id: str, state: SceneRunState) -> LlmCall | None:
    if state.current_final_scene_row_id:
        final_scene = session.get(FinalScene, state.current_final_scene_row_id)
        if final_scene is not None and final_scene.scene_id == scene_id and final_scene.generation_llm_call_id:
            llm_call = session.get(LlmCall, final_scene.generation_llm_call_id)
            if llm_call is not None:
                return llm_call

    for row_id in (state.current_style_draft_row_id, state.current_neutral_draft_row_id):
        if not row_id:
            continue
        draft = session.get(SceneDraft, row_id)
        if draft is None or draft.scene_id != scene_id or not draft.generation_llm_call_id:
            continue
        llm_call = session.get(LlmCall, draft.generation_llm_call_id)
        if llm_call is not None:
            return llm_call
    return None


def _display_generation_step(raw_step: str | None) -> str | None:
    return {
        "soft_patch": "style_patch",
        "style_draft": "style_draft",
        "neutral_draft": "neutral_draft",
    }.get(raw_step, raw_step)


def _latest_qc_report(session: Session, scene_id: str, state: SceneRunState, qc_type: str) -> QcReport | None:
    if state.current_qc_report_id:
        current_report = session.get(QcReport, state.current_qc_report_id)
        if current_report is not None and current_report.scene_id == scene_id:
            if current_report.qc_type == qc_type:
                return current_report
            if current_report.source_bundle_id:
                return _latest_qc_report_for_bundle(session, scene_id, current_report.source_bundle_id, qc_type)

    current_bundle_id = _resolve_current_run_bundle_id(session, scene_id, state)
    if not current_bundle_id:
        return None
    return _latest_qc_report_for_bundle(session, scene_id, current_bundle_id, qc_type)


def _latest_qc_report_for_bundle(session: Session, scene_id: str, bundle_id: str, qc_type: str) -> QcReport | None:
    return session.execute(
        select(QcReport)
        .where(
            QcReport.scene_id == scene_id,
            QcReport.qc_type == qc_type,
            QcReport.source_bundle_id == bundle_id,
        )
        .order_by(QcReport.created_at.desc(), QcReport.qc_report_id.desc())
    ).scalars().first()


def _resolve_current_run_bundle_id(session: Session, scene_id: str, state: SceneRunState) -> str | None:
    if state.current_bundle_id:
        return state.current_bundle_id

    if state.current_final_scene_row_id:
        final_scene = session.get(FinalScene, state.current_final_scene_row_id)
        if final_scene is not None and final_scene.scene_id == scene_id and final_scene.source_bundle_id:
            return final_scene.source_bundle_id

    for row_id in (state.current_style_draft_row_id, state.current_neutral_draft_row_id):
        if not row_id:
            continue
        draft = session.get(SceneDraft, row_id)
        if draft is not None and draft.scene_id == scene_id and draft.source_bundle_id:
            return draft.source_bundle_id

    return None


def _serialize_qc_summary(report: QcReport | None) -> dict | None:
    if report is None:
        return None
    summary = {
        "qc_report_id": report.qc_report_id,
        "qc_type": report.qc_type,
        "pass_flag": None if report.pass_flag is None else bool(report.pass_flag),
        "resolution_code": report.resolution_code,
        "issue_keys": _extract_issue_keys(report.issues_json or []),
        "next_action": report.next_action,
        "rewrite_brief": _extract_rewrite_brief(report.rewrite_brief_json or []),
        "created_at": report.created_at,
    }
    style_summary = StyleScoreService.summary_from_rewrite_brief(report.rewrite_brief_json or [])
    if style_summary is not None:
        summary.update(style_summary)
    return summary


def _style_score_summary_for_scene(session: Session, scene_id: str, state: SceneRunState) -> dict[str, Any] | None:
    report = _latest_qc_report(session, scene_id, state, "soft_qc")
    if report is None:
        return None
    return StyleScoreService.summary_from_rewrite_brief(report.rewrite_brief_json or [])


def _extract_issue_keys(entries: list[dict]) -> list[str]:
    issue_keys: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        issue_key = entry.get("issue_key")
        if isinstance(issue_key, str) and issue_key.strip():
            issue_keys.append(issue_key.strip())
    return issue_keys


def _extract_rewrite_brief(entries: list[dict]) -> list[str]:
    rewrite_brief: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        instruction = entry.get("instruction")
        if isinstance(instruction, str) and instruction.strip():
            rewrite_brief.append(instruction.strip())
            continue
        carry_note_text = entry.get("carry_note_text")
        if isinstance(carry_note_text, str) and carry_note_text.strip():
            rewrite_brief.append(carry_note_text.strip())
    return rewrite_brief


def _resolve_human_review_event(session: Session, scene_id: str, state: SceneRunState) -> HumanReviewEvent | None:
    if not state.current_human_review_event_id:
        return None
    event = session.get(HumanReviewEvent, state.current_human_review_event_id)
    if event is not None and event.scene_id == scene_id:
        return event
    return None


def _serialize_human_review_summary(event: HumanReviewEvent | None) -> dict | None:
    if event is None:
        return None
    details = dict(event.details_json or {})
    return {
        "event_id": event.event_id,
        "status": event.status,
        "event_source": event.event_source,
        "priority": event.priority,
        "trigger_reason": details.get("trigger_reason"),
        "failure_reason": details.get("failure_reason"),
        "recommended_action": details.get("recommended_action"),
        "linked_target_ref": details.get("linked_target_ref"),
        "created_at": event.created_at,
    }


def _serialize_generation_history_item(session: Session, item: AttemptTracker, *, attempt_order: int) -> dict:
    details = dict(item.details_json or {})
    llm_call = _resolve_attempt_llm_call(session, item, details)
    qc_report = _resolve_attempt_qc_report(session, item, details)
    source_qc_report = _resolve_scene_scoped_qc_report(session, item.scene_id, _detail_str(details, "source_qc_report_id"))
    human_review_event = _resolve_attempt_human_review_event(session, item, details)
    return {
        "attempt_order": attempt_order,
        "attempt": _serialize_attempt(item),
        "reference_ids": {
            "source_bundle_id": item.source_bundle_id,
            "row_id": _detail_str(details, "row_id"),
            "source_draft_row_id": _detail_str(details, "source_draft_row_id"),
            "source_style_draft_row_id": _detail_str(details, "source_style_draft_row_id"),
            "final_scene_row_id": _detail_str(details, "final_scene_row_id"),
            "llm_call_id": llm_call.llm_call_id if llm_call is not None else _detail_str(details, "llm_call_id"),
            "qc_report_id": qc_report.qc_report_id if qc_report is not None else None,
            "source_qc_report_id": source_qc_report.qc_report_id if source_qc_report is not None else None,
            "human_review_event_id": human_review_event.event_id if human_review_event is not None else None,
            "final_generation_llm_call_id": _detail_str(details, "final_generation_llm_call_id"),
        },
        "llm_call": _serialize_llm_call_detail(llm_call),
        "qc_report": _serialize_qc_report_detail(qc_report),
        "human_review_event": _serialize_human_review_event_detail(human_review_event),
    }


def _detail_str(details: dict, key: str) -> str | None:
    value = details.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _resolve_attempt_llm_call(session: Session, item: AttemptTracker, details: dict) -> LlmCall | None:
    for llm_call_id in (_detail_str(details, "llm_call_id"), _detail_str(details, "final_generation_llm_call_id")):
        if not llm_call_id:
            continue
        llm_call = session.get(LlmCall, llm_call_id)
        if llm_call is not None and (item.scene_id is None or llm_call.scene_id == item.scene_id):
            return llm_call

    for row_key in ("row_id", "source_draft_row_id", "source_style_draft_row_id"):
        row_id = _detail_str(details, row_key)
        if not row_id:
            continue
        draft = session.get(SceneDraft, row_id)
        if draft is None or (item.scene_id is not None and draft.scene_id != item.scene_id):
            continue
        if draft.generation_llm_call_id:
            llm_call = session.get(LlmCall, draft.generation_llm_call_id)
            if llm_call is not None:
                return llm_call

    final_scene_row_id = _detail_str(details, "final_scene_row_id")
    if final_scene_row_id:
        final_scene = session.get(FinalScene, final_scene_row_id)
        if final_scene is not None and (item.scene_id is None or final_scene.scene_id == item.scene_id):
            if final_scene.generation_llm_call_id:
                llm_call = session.get(LlmCall, final_scene.generation_llm_call_id)
                if llm_call is not None:
                    return llm_call

    return None


def _resolve_scene_scoped_qc_report(session: Session, scene_id: str | None, qc_report_id: str | None) -> QcReport | None:
    if not qc_report_id:
        return None
    qc_report = session.get(QcReport, qc_report_id)
    if qc_report is None:
        return None
    if scene_id is not None and qc_report.scene_id != scene_id:
        return None
    return qc_report


def _resolve_attempt_qc_report(session: Session, item: AttemptTracker, details: dict) -> QcReport | None:
    for qc_report_id in (_detail_str(details, "qc_report_id"), _detail_str(details, "source_qc_report_id")):
        qc_report = _resolve_scene_scoped_qc_report(session, item.scene_id, qc_report_id)
        if qc_report is not None:
            return qc_report
    return None


def _resolve_attempt_human_review_event(session: Session, item: AttemptTracker, details: dict) -> HumanReviewEvent | None:
    event_id = _detail_str(details, "human_review_event_id")
    if not event_id:
        return None
    event = session.get(HumanReviewEvent, event_id)
    if event is None:
        return None
    if item.scene_id is not None and event.scene_id != item.scene_id:
        return None
    return event


def _serialize_llm_call_detail(llm_call: LlmCall | None) -> dict | None:
    if llm_call is None:
        return None
    return {
        "llm_call_id": llm_call.llm_call_id,
        "step": _display_generation_step(llm_call.step),
        "raw_step": llm_call.step,
        "provider": llm_call.provider,
        "model": llm_call.model,
        "prompt_hash": llm_call.prompt_hash,
        "request_payload_summary": llm_call.request_payload_summary,
        "response_payload_summary": llm_call.response_payload_summary,
        "prompt_tokens": llm_call.prompt_tokens,
        "completion_tokens": llm_call.completion_tokens,
        "total_tokens": llm_call.total_tokens,
        "latency_ms": llm_call.latency_ms,
        "finish_reason": llm_call.finish_reason,
        "error_code": llm_call.error_code,
        "created_at": llm_call.created_at,
    }


def _serialize_qc_report_detail(report: QcReport | None) -> dict | None:
    if report is None:
        return None
    return {
        "qc_report_id": report.qc_report_id,
        "qc_type": report.qc_type,
        "source_draft_row_id": report.source_draft_row_id,
        "source_bundle_id": report.source_bundle_id,
        "pass_flag": None if report.pass_flag is None else bool(report.pass_flag),
        "resolution_code": report.resolution_code,
        "next_action": report.next_action,
        "issues_json": report.issues_json or [],
        "rewrite_brief_json": report.rewrite_brief_json or [],
        "issue_keys": _extract_issue_keys(report.issues_json or []),
        "rewrite_brief": _extract_rewrite_brief(report.rewrite_brief_json or []),
        "created_at": report.created_at,
    }


def _serialize_human_review_event_detail(event: HumanReviewEvent | None) -> dict | None:
    if event is None:
        return None
    return {
        "event_id": event.event_id,
        "status": event.status,
        "event_source": event.event_source,
        "priority": event.priority,
        "owner": event.owner,
        "object_ref": event.object_ref,
        "allowed_actions_json": event.allowed_actions_json or [],
        "result_status_map_json": event.result_status_map_json or {},
        "default_action": event.default_action,
        "details_json": dict(event.details_json or {}),
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


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
