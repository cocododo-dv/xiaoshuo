from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.api.deps import get_session
from novel_system.api.response import ok
from novel_system.db.models import (
    AttemptTracker,
    AuthorDraft,
    ChapterGoal,
    FinalScene,
    HumanReviewEvent,
    LlmCall,
    QcReport,
    RevisionCandidate,
    SceneBundle,
    SceneCard,
    SceneDraft,
    SceneMemory,
    SceneRunState,
    WriterEvaluation,
)
from novel_system.services.archiver import Archiver
from novel_system.services.author_lifecycle import AuthorLifecycleService
from novel_system.services.author_state import compute_author_state
from novel_system.services.chapter_runtime import ChapterRuntimeService, clean_backfill_markers
from novel_system.services.errors import DomainError
from novel_system.services.idempotency import execute_with_idempotency
from novel_system.services.literary_quality import LiteraryQualityService
from novel_system.services.orchestrator import Orchestrator
from novel_system.services.near_final import NEAR_FINAL_REWRITE_TYPE, NEAR_FINAL_RUBRIC_ID
from novel_system.services.pagination import paginate_items, resolve_pagination_request
from novel_system.services.projects import ProjectService
from novel_system.services.scene_blueprint import SceneBlueprintService
from novel_system.services.scene_execution import SceneExecutionContractService, SceneTriageService
from novel_system.services.scene_quality import SceneAutoRewriteService, SceneQualityService
from novel_system.services.scene_run_jobs import SceneRunJobService, start_scene_run_job_worker
from novel_system.services.scene_run_preflight import SceneRunPreflightService
from novel_system.services.source_safety import scan_source_safety, source_profile_ids_from_snapshot
from novel_system.services.style_profile import StyleScoreService
from novel_system.services.text_validation import validate_user_text_payload
from novel_system.services.writer_review import WriterReviewService, normalize_scene_writer_brief

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
    validate_user_text_payload(payload, field_prefix="scene")
    payload = {
        **payload,
        "writer_brief_json": normalize_scene_writer_brief(payload.get("writer_brief_json")),
    }
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
def run_scene(scene_id: str, request: Request, session: Session = Depends(get_session), payload: dict | None = Body(default=None)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_scene(scene_id)
    # FE-ALIGN G3：作者改写指令随请求下发（注入风格生成提示词；幂等键随 note 变化）
    author_note = str((payload or {}).get("author_note") or "").strip()[:500] or None
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/run/full",
        payload={"scene_id": scene_id, **({"author_note": author_note} if author_note else {})},
        action=lambda: Orchestrator(session).run_scene(scene_id, author_note=author_note),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/scenes/{scene_id}/execution-contract")
def get_scene_execution_contract(scene_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_scene(scene_id)
    contract = SceneExecutionContractService(session).get_or_create(scene_id, actor_ref=actor_ref)
    session.commit()
    return ok(
        {"contract": SceneExecutionContractService(session).serialize(contract)},
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/scenes/{scene_id}/preflight/create-cards")
def create_scene_preflight_cards(scene_id: str, request: Request, session: Session = Depends(get_session)):
    """确定性建出当前场景缺失的最小 voice/relation 卡(active)，解阻 run 预检。

    这是 create_minimal_voice_card / create_minimal_relation_card 预检动作的真实执行落点
    （此前该动作只是提示、无可执行端点，是死胡同）。幂等：已有 active 卡则跳过。
    """
    scene = AuthorLifecycleService(session).require_active_scene(scene_id)
    result = SceneRunPreflightService(session).create_missing_cards(scene)
    session.commit()
    return ok(result, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/scenes/{scene_id}/execution-contract")
def generate_scene_execution_contract(scene_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_scene(scene_id)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/execution-contract",
        payload={"scene_id": scene_id},
        action=lambda: {
            "contract": SceneExecutionContractService(session).serialize(
                SceneExecutionContractService(session).generate(scene_id, actor_ref=actor_ref)
            )
        },
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/scenes/{scene_id}/triage")
def triage_scene(scene_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_scene(scene_id)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/triage",
        payload={"scene_id": scene_id},
        action=lambda: {"triage": SceneTriageService(session).evaluate(scene_id, actor_ref=actor_ref, mutate=True)},
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/scenes/{scene_id}/literary-blueprint")
def generate_scene_literary_blueprint(scene_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_scene(scene_id)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/literary-blueprint",
        payload={"scene_id": scene_id},
        action=lambda: SceneBlueprintService(session).serialize(
            SceneBlueprintService(session).generate(scene_id, actor_ref=actor_ref)
        ),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/scenes/{scene_id}/quality-contract")
def generate_scene_quality_contract(scene_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    AuthorLifecycleService(session).require_active_scene(scene_id)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/quality-contract",
        payload={"scene_id": scene_id},
        action=lambda: SceneQualityService(session).generate_contract(scene_id, actor_ref=actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/scenes/{scene_id}/quality-state")
def get_scene_quality_state(scene_id: str, request: Request, session: Session = Depends(get_session)):
    AuthorLifecycleService(session).require_active_scene(scene_id)
    return ok(
        SceneQualityService(session).quality_state(scene_id),
        req_id=getattr(request.state, "request_id", None),
    )


@router.post("/api/v1/scenes/{scene_id}/auto-rewrite")
def run_scene_auto_rewrite(scene_id: str, request: Request, payload: dict | None = None, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    request_payload = payload or {}
    AuthorLifecycleService(session).require_active_scene(scene_id)
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/auto-rewrite",
        payload={"scene_id": scene_id, **request_payload},
        action=lambda: SceneAutoRewriteService(session).run(
            scene_id,
            mode=str(request_payload.get("mode") or "auto"),
            actor_ref=actor_ref,
        ),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/auto-rewrite-runs/{run_id}/promote")
def promote_auto_rewrite_run(run_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/auto-rewrite-runs/{run_id}/promote",
        payload={"run_id": run_id},
        action=lambda: SceneAutoRewriteService(session).promote(run_id, actor_ref=actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/auto-rewrite-runs/{run_id}/rollback")
def rollback_auto_rewrite_run(run_id: str, request: Request, session: Session = Depends(get_session)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/auto-rewrite-runs/{run_id}/rollback",
        payload={"run_id": run_id},
        action=lambda: SceneAutoRewriteService(session).rollback(run_id, actor_ref=actor_ref),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.post("/api/v1/scenes/{scene_id}/run/jobs")
def create_scene_run_job(scene_id: str, request: Request, start: bool = True, session: Session = Depends(get_session), payload: dict | None = Body(default=None)):
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"
    service = SceneRunJobService(session)
    job = service.create_job(scene_id, actor_ref=actor_ref, author_note=(payload or {}).get("author_note"))
    payload = service.serialize_job(job)
    session.commit()
    if start and job.status == "queued":
        start_scene_run_job_worker(job.job_id)
    return ok(payload, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/run-jobs/{job_id}")
def get_run_job(job_id: str, request: Request, session: Session = Depends(get_session)):
    service = SceneRunJobService(session)
    job = service.get_job(job_id)
    return ok(service.serialize_job(job), req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/scene-run-states")
def list_scene_run_states(project_id: str, request: Request, session: Session = Depends(get_session)):
    """项目内全部场景运行态（管线真相）。

    起草台队列成员的后端派生源：换浏览器后 FE 据此恢复「哪些场进过管线」，
    localStorage 队列退化为这份真相的读缓存（贯通轮遗留项 ①）。
    只返回有运行态行且离开过 ready 的场——ready/无行 = 从未进管线，不参与恢复。
    """
    ProjectService(session).require_project(project_id)
    rows = session.execute(
        select(SceneRunState, SceneCard)
        .join(SceneCard, SceneCard.scene_id == SceneRunState.scene_id)
        .where(SceneCard.project_id == project_id, SceneCard.trashed_flag == 0)
        .order_by(SceneRunState.updated_at.desc())
    ).all()
    items = [
        {
            "scene_id": state.scene_id,
            "chapter_id": card.chapter_id,
            "scene_status": state.scene_status,
            # 治理 §5.3：列表恢复面也带作者可见态（枚举），FE 不再从 scene_status 猜
            "author_state": compute_author_state(session, state.scene_id, state)["author_state"],
            "total_attempt_count": state.total_attempt_count,
            "updated_at": state.updated_at,
        }
        for state, card in rows
        if state.scene_status != "ready"
    ]
    return ok({"items": items, "count": len(items)}, req_id=getattr(request.state, "request_id", None))


@router.get("/api/v1/scenes/{scene_id}/status")
def scene_status(scene_id: str, request: Request, session: Session = Depends(get_session)):
    AuthorLifecycleService(session).require_active_scene(scene_id)
    state = session.get(SceneRunState, scene_id)
    if state is None:
        # 经目录新建、从未 run/未打开 workbench 的有效场景没有运行态行——
        # 返回与「刚物化、ready」一致的空态，而非对 None 取属性抛 500（对齐 workbench 自动补建语义）。
        return ok(
            {
                "scene_status": "ready",
                "current_bundle_id": None,
                "current_bundle_hash": None,
                "current_neutral_draft_row_id": None,
                "current_style_draft_row_id": None,
                "current_final_scene_row_id": None,
                "repeat_issue_key": None,
                "repeat_issue_count": 0,
                # 治理 §5.3：作者可见状态投影（React 只消费这层字段）
                **compute_author_state(session, scene_id, None),
            },
            req_id=getattr(request.state, "request_id", None),
        )
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
            # 治理 §5.3：作者可见状态投影（React 只消费这层字段）
            **compute_author_state(session, scene_id, state),
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


@router.get("/api/v1/scenes/{scene_id}/style-candidates")
def get_scene_style_candidates(scene_id: str, request: Request, session: Session = Depends(get_session)):
    """Blueprint §6/§14: retrieve all Best-of-N style draft candidates for human terminal selection.

    Returns all style draft candidates with their adversarial quality scores,
    allowing the author to pick 'the one with life' from the available options.
    """
    AuthorLifecycleService(session).require_active_scene(scene_id)
    from novel_system.services.literary_quality import adversarial_rank_score
    drafts = list(session.execute(
        select(SceneDraft)
        .where(
            SceneDraft.scene_id == scene_id,
            SceneDraft.stage == "style_draft",
        )
        .order_by(SceneDraft.created_at.desc())
    ).scalars().all())
    state = session.get(SceneRunState, scene_id)
    selected_row_id = state.current_style_draft_row_id if state else None
    candidates = []
    for idx, d in enumerate(drafts):
        score = adversarial_rank_score(d.content) if d.content else 0.0
        candidates.append({
            "row_id": d.row_id,
            "adversarial_score": round(score, 3),
            "content_preview": (d.content or "")[:500],
            "content": d.content,
            "selected": d.row_id == selected_row_id,
            "created_at": str(d.created_at) if d.created_at else None,
        })
    candidates.sort(key=lambda c: c["adversarial_score"], reverse=True)
    # §6 Defect D: surface dispersion and criticality as author-facing quality signals
    dispersion_score = state.candidate_dispersion_score if state else None
    criticality_info = None
    if state and state.criticality_level:
        criticality_info = {
            "level": state.criticality_level,
            "reasons": state.criticality_reasons_json or [],
        }
    return ok(
        {
            "scene_id": scene_id,
            "candidates": candidates,
            "total": len(candidates),
            "dispersion_score": dispersion_score,
            "dispersion_signal": (
                "low" if dispersion_score is not None and dispersion_score < 0.15
                else "adequate" if dispersion_score is not None
                else None
            ),
            "criticality": criticality_info,
        },
        req_id=getattr(request.state, "request_id", None),
    )


@router.get("/api/v1/scenes/{scene_id}/orchestration-signals")
def get_scene_orchestration_signals(scene_id: str, request: Request, session: Session = Depends(get_session)):
    """§0: surface orchestration-layer decisions at the right resolution.

    Aggregates the author-facing quality signals the engine computes but normally
    keeps internal: Best-of-N dispersion + scene criticality (§6), foreshadow debt
    health (§5), theme expression budget (§12), and active style-drift correction (§9).
    One read for the workbench to render its "编排信号" panel.
    """
    scene = session.get(SceneCard, scene_id)
    if scene is None:
        return ok({"scene_id": scene_id, "available": False}, req_id=getattr(request.state, "request_id", None))

    project_id = (
        scene.project_id
        or (scene.chapter_id.rsplit("_", 1)[0] if "_" in scene.chapter_id else scene.chapter_id)
    )
    state = session.get(SceneRunState, scene_id)

    # §6 dispersion + criticality
    dispersion_score = state.candidate_dispersion_score if state else None
    signals: dict[str, Any] = {
        "scene_id": scene_id,
        "available": True,
        "dispersion": {
            "score": dispersion_score,
            "signal": (
                "low" if dispersion_score is not None and dispersion_score < 0.15
                else "adequate" if dispersion_score is not None else None
            ),
        },
        "criticality": (
            {"level": state.criticality_level, "reasons": state.criticality_reasons_json or []}
            if state and state.criticality_level else None
        ),
    }

    # 审计 P-11：最近一次 bundle 的降级注入槽（辅助注入失效不再沉默）
    try:
        from novel_system.db.models import SceneBundle as _SceneBundle
        latest_bundle = session.execute(
            select(_SceneBundle)
            .where(_SceneBundle.scene_id == scene_id)
            .order_by(_SceneBundle.created_at.desc(), _SceneBundle.bundle_id.desc())
        ).scalars().first()
        signals["degraded_slots"] = (
            (latest_bundle.frozen_snapshot_json or {}).get("degraded_slots") or []
            if latest_bundle is not None else []
        )
    except Exception:
        signals["degraded_slots"] = None

    # §5 foreshadow debt health (best-effort — never fail the whole panel)
    try:
        from novel_system.services.foreshadow_lifecycle import ForeshadowLifecycleService
        health = ForeshadowLifecycleService(session).project_health_report(project_id)
        signals["foreshadow_health"] = {
            "total_open": health.total_open,
            "with_planned_reinforcement": health.with_planned_reinforcement,
            "without_planned_reinforcement": health.without_planned_reinforcement,
            "overdue_count": len(health.overdue),
            "overdue_ids": health.overdue,
        }
    except Exception:
        signals["foreshadow_health"] = None

    # §12 theme expression budget
    try:
        from novel_system.services.theme_anchor import ThemeAnchorService
        signals["theme_budget"] = ThemeAnchorService(session).check_expression_budget(project_id)
    except Exception:
        signals["theme_budget"] = None

    # §9 active style-drift correction for this chapter
    try:
        from novel_system.db.models import LongformStructureGuidance as _LSG
        drift_rows = list(session.execute(
            select(_LSG).where(
                _LSG.scope_type.in_(("chapter", "global")),
                _LSG.scope_ref_id.in_((scene.chapter_id, "global")),
                _LSG.guidance_id.like("drift_%"),
                _LSG.status == "approved",
            )
        ).scalars().all())
        drift_dims: list[str] = []
        for row in drift_rows:
            rec = row.recommendation_json or {}
            for d in (rec.get("drift_dimensions") or []):
                if isinstance(d, dict) and d.get("dimension"):
                    drift_dims.append(d["dimension"])
        signals["style_drift"] = {
            "active": bool(drift_rows),
            "drifted_dimensions": drift_dims,
        }
    except Exception:
        signals["style_drift"] = None

    return ok(signals, req_id=getattr(request.state, "request_id", None))


@router.post("/api/v1/scenes/{scene_id}/style-candidates/{row_id}/select")
def select_style_candidate(
    scene_id: str,
    row_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Blueprint §6/§14: human terminal selection — author picks a candidate.

    Sets the selected candidate as the current style draft, so subsequent
    auto-critique / soft QC / archival will operate on the human-chosen version.
    """
    def _select(session: Session) -> dict[str, Any]:
        AuthorLifecycleService(session).require_active_scene(scene_id)
        draft = session.get(SceneDraft, row_id)
        if draft is None or draft.scene_id != scene_id:
            raise DomainError(
                "CANDIDATE_NOT_FOUND",
                f"Style draft candidate {row_id} not found for scene {scene_id}",
                status_code=404,
            )
        state = session.get(SceneRunState, scene_id)
        if state is None:
            raise DomainError("SCENE_STATE_NOT_FOUND", "Scene run state not found", status_code=404)
        state.current_style_draft_row_id = row_id
        # 治理 §4.3：候选选择也是「最近有效正文」的维护点
        state.latest_valid_draft_row_id = row_id
        session.flush()
        return {"scene_id": scene_id, "selected_row_id": row_id, "message": "Candidate selected for human terminal review"}

    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/style-candidates/{row_id}/select",
        payload={"scene_id": scene_id, "row_id": row_id},
        action=lambda: _select(session),
        actor_ref=getattr(request.state, "operator_ref", None) or "operator",
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


def _author_draft_plain_text(html: str | None) -> str:
    """author-draft 存 HTML（<p> 分段）；归档正文按段落还原为纯文本。"""
    import re

    if not html:
        return ""
    text = re.sub(r"</p\s*>|<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


@router.post("/api/v1/scenes/{scene_id}/adopt-current")
def adopt_current_scene(
    scene_id: str,
    request: Request,
    session: Session = Depends(get_session),
    payload: dict | None = Body(default=None),
):
    """治理 §5.2：作者采纳归档的单一服务入口。

    前端「归档/置 done」动作必须打到这里——FinalScene 只由服务端归档事务
    创建或提升（复用 Archiver，不建第二实现）。内容源优先级：未归档的
    current_final_scene → 管线草稿（latest_valid > style > neutral）→
    author-draft 人工稿兜底。守卫：无任何有效稿 409 NO_VALID_DRAFT；
    确定性来源安全扫描命中 409 SOURCE_SAFETY_BLOCKED（草稿保留可重试，
    设计红线 8：来源安全未通过可保存草稿但不能标记为已安全归档）。
    """
    actor_ref = getattr(request.state, "operator_ref", None) or "operator"

    def _adopt(session: Session) -> dict[str, Any]:
        from uuid import uuid4

        scene = AuthorLifecycleService(session).require_active_scene(scene_id)
        state = session.get(SceneRunState, scene_id)
        if state is None:
            state = SceneRunState(scene_id=scene_id, scene_status="ready")
            session.add(state)
            session.flush()

        # 已归档：幂等返回现状，不重复归档
        if state.scene_status == "archived" and state.current_final_scene_row_id:
            return {
                "scene_id": scene_id,
                "scene_status": "archived",
                "final_scene_row_id": state.current_final_scene_row_id,
                "already_archived": True,
                "author_state": compute_author_state(session, scene_id, state),
            }

        # 1) 内容源解析
        final: FinalScene | None = None
        if state.current_final_scene_row_id:
            row = session.get(FinalScene, state.current_final_scene_row_id)
            if row is not None and (row.content or "").strip():
                final = row
        source_draft_row_id: str | None = None
        content: str | None = None
        source_bundle_id: str | None = None
        source_bundle_hash: str | None = None
        if final is None:
            for row_id in (
                state.latest_valid_draft_row_id,
                state.current_style_draft_row_id,
                state.current_neutral_draft_row_id,
            ):
                if not row_id:
                    continue
                draft = session.get(SceneDraft, row_id)
                if draft is not None and (draft.content or "").strip():
                    source_draft_row_id = row_id
                    content = draft.content
                    source_bundle_id = draft.source_bundle_id
                    source_bundle_hash = draft.source_bundle_hash
                    break
            if content is None:
                author_draft = session.execute(
                    select(AuthorDraft).where(
                        AuthorDraft.object_type == "scene",
                        AuthorDraft.object_id == scene_id,
                        AuthorDraft.status == "current",
                    )
                ).scalars().first()
                text = _author_draft_plain_text(author_draft.content) if author_draft else ""
                if text.strip():
                    content = text
                    source_bundle_id = f"author_draft:{author_draft.draft_id}"
                    source_bundle_hash = f"author_draft_rev_{author_draft.revision_no}"
            if content is None:
                raise DomainError(
                    "NO_VALID_DRAFT",
                    "no valid draft content to adopt — generate or write the scene first",
                    status_code=409,
                    details={"scene_id": scene_id},
                )

        # 2) 确定性来源安全守卫（Q0 红线；Q0–Q3 分级阻断策略随 Wave 2 落地）
        target_content = final.content if final is not None else (content or "")
        bundle = session.get(SceneBundle, state.current_bundle_id) if state.current_bundle_id else None
        scan = scan_source_safety(
            target_content,
            source_profile_ids=source_profile_ids_from_snapshot(
                bundle.frozen_snapshot_json if bundle else None
            ),
        )
        if not scan.get("safe", True):
            raise DomainError(
                "SOURCE_SAFETY_BLOCKED",
                "source-safety scan blocked adoption — draft is kept and can be revised",
                status_code=409,
                details={"scene_id": scene_id, "blocked_terms": scan.get("blocked_terms") or []},
            )

        # 3) FinalScene 建行或提升，经归档事务统一置权威态
        if final is None:
            final = FinalScene(
                row_id=f"final_scene_{scene_id}_adopt_{uuid4().hex[:10]}",
                scene_id=scene_id,
                chapter_id=scene.chapter_id,
                content=content or "",
                source_bundle_id=source_bundle_id or "author_adopt",
                source_bundle_hash=source_bundle_hash or "author_adopt",
            )
            session.add(final)
            session.flush()
        state.current_final_scene_row_id = final.row_id
        if source_draft_row_id:
            state.latest_valid_draft_row_id = source_draft_row_id

        archive_result = Archiver(session).archive_final_scene(
            scene_id,
            final.row_id,
            carry_notes_json=[{"kind": "author_adoption", "actor_ref": actor_ref}],
        )
        return {
            "scene_id": scene_id,
            "scene_status": archive_result["scene_status"],
            "final_scene_row_id": final.row_id,
            "scene_memory_row_id": archive_result["scene_memory_row_id"],
            "source_safety_scan": scan,
            "author_state": compute_author_state(session, scene_id, state),
        }

    result, status = execute_with_idempotency(
        session,
        idempotency_key=request.headers.get("X-Idempotency-Key"),
        method="POST",
        path_template="/api/v1/scenes/{scene_id}/adopt-current",
        payload={"scene_id": scene_id, **(payload or {})},
        action=lambda: _adopt(session),
        actor_ref=actor_ref,
    )
    headers = {"X-Idempotency-Status": status} if status else {}
    return ok(result, req_id=getattr(request.state, "request_id", None), headers=headers)


@router.get("/api/v1/scenes/{scene_id}/workbench")
def scene_workbench(scene_id: str, request: Request, session: Session = Depends(get_session)):
    scene = AuthorLifecycleService(session).require_active_scene(scene_id)
    chapter = session.get(ChapterGoal, scene.chapter_id)
    state = session.get(SceneRunState, scene_id)
    if state is None:
        # FE 目录直接建的场景没有运行时状态行：按 scenes POST 的约定补建
        state = SceneRunState(scene_id=scene_id, scene_status="ready")
        session.add(state)
        session.flush()
    runtime_service = ChapterRuntimeService(session)
    chapter_state = runtime_service.chapter_state_payload(scene.chapter_id)
    run_preflight = SceneRunPreflightService(session).build(scene, chapter_state)
    bundle = session.get(SceneBundle, state.current_bundle_id) if state.current_bundle_id else None
    neutral = session.get(SceneDraft, state.current_neutral_draft_row_id) if state.current_neutral_draft_row_id else None
    style = session.get(SceneDraft, state.current_style_draft_row_id) if state.current_style_draft_row_id else None
    final = session.get(FinalScene, state.current_final_scene_row_id) if state.current_final_scene_row_id else None
    source_safety_scan = scan_source_safety(
        final.content if final else "",
        source_profile_ids=source_profile_ids_from_snapshot(bundle.frozen_snapshot_json if bundle else None),
    )
    memory = session.execute(
        select(SceneMemory).where(SceneMemory.scene_id == scene_id, SceneMemory.active_flag == 1)
    ).scalars().first()
    attempts = session.execute(
        select(AttemptTracker).where(AttemptTracker.scene_id == scene_id).order_by(AttemptTracker.attempt_id.asc())
    ).scalars().all()
    blueprint_service = SceneBlueprintService(session)
    contract_service = SceneExecutionContractService(session)
    execution_contract = contract_service.latest(scene_id)
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
            # 治理 §5.3：作者可见状态投影块（完整契约字段）
            "author_state": compute_author_state(session, scene_id, state),
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
            "source_safety_scan": source_safety_scan,
            "anti_template_quality_summary": _serialize_anti_template_quality_summary(session, final),
            "literary_blueprint": blueprint_service.latest_payload(scene_id),
            "execution_contract": contract_service.serialize(execution_contract),
            "scene_memory": {"row_id": memory.row_id, "content": memory.content} if memory else None,
            "generation_summary": _serialize_generation_summary(session, scene_id, state),
            "near_final_summary": _serialize_near_final_summary(session, scene_id),
            "hard_qc_summary": _serialize_qc_summary(_latest_qc_report(session, scene_id, state, "hard_qc")),
            "soft_qc_summary": _serialize_qc_summary(_latest_qc_report(session, scene_id, state, "soft_qc")),
            "triage_preview": SceneTriageService(session).evaluate(scene_id, actor_ref="preview", mutate=False),
            "rewrite_counters": {
                "hard_partial_rewrite_count": state.hard_partial_rewrite_count,
                "hard_full_rewrite_count": state.hard_full_rewrite_count,
                "soft_patch_count": state.soft_patch_count,
                "repeat_issue_key": state.repeat_issue_key,
                "repeat_issue_count": state.repeat_issue_count,
            },
            "human_review_summary": _serialize_human_review_summary(_resolve_human_review_event(session, scene_id, state)),
            "writer_review_summary": WriterReviewService(session).scene_summary(scene_id),
            "attempts": [_serialize_attempt(item) for item in attempts],
        },
        req_id=getattr(request.state, "request_id", None),
    )
    session.commit()
    return response


def _serialize_anti_template_quality_summary(session: Session, final: FinalScene | None) -> dict | None:
    if final is None or not (final.content or "").strip():
        return None
    return LiteraryQualityService(session).analyze_text(
        {
            "content": final.content or "",
            "object_type": "scene",
            "object_id": final.scene_id,
            "chapter_id": final.chapter_id,
            "scene_id": final.scene_id,
            "source_ref": f"final_scene:{final.row_id}",
        }
    )


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
        "scene_literary_rewrite": "literary_rewrite",
        "soft_patch": "style_patch",
        "style_draft": "style_draft",
        "neutral_draft": "neutral_draft",
    }.get(raw_step, raw_step)


def _serialize_near_final_summary(session: Session, scene_id: str) -> dict | None:
    latest_attempt = session.execute(
        select(AttemptTracker)
        .where(AttemptTracker.scene_id == scene_id, AttemptTracker.step == "near_final_acceptance_review")
        .order_by(AttemptTracker.attempt_id.desc())
    ).scalars().first()
    latest_evaluation = session.execute(
        select(WriterEvaluation)
        .where(
            WriterEvaluation.object_type == "scene",
            WriterEvaluation.object_id == scene_id,
            WriterEvaluation.rubric_id == NEAR_FINAL_RUBRIC_ID,
        )
        .order_by(WriterEvaluation.created_at.desc(), WriterEvaluation.evaluation_id.desc())
    ).scalars().first()
    if latest_attempt is None and latest_evaluation is None:
        return None
    details = dict(latest_attempt.details_json or {}) if latest_attempt is not None else {}
    revision_candidate = None
    candidate_id = details.get("revision_candidate_id")
    if isinstance(candidate_id, str) and candidate_id.strip():
        revision_candidate = session.get(RevisionCandidate, candidate_id)
    if revision_candidate is None:
        revision_candidate = session.execute(
            select(RevisionCandidate)
            .where(
                RevisionCandidate.object_type == "scene",
                RevisionCandidate.object_id == scene_id,
                RevisionCandidate.revision_type == NEAR_FINAL_REWRITE_TYPE,
            )
            .order_by(RevisionCandidate.created_at.desc(), RevisionCandidate.revision_id.desc())
        ).scalars().first()
    near_final_status = latest_attempt.status if latest_attempt is not None else None
    if near_final_status is None and latest_evaluation is not None:
        near_final_status = "human_review_required" if latest_evaluation.requires_human_review else "revision_required"
    failure_class = details.get("failure_class") or (latest_evaluation.failure_class if latest_evaluation is not None else None)
    return {
        "rubric_id": NEAR_FINAL_RUBRIC_ID,
        "near_final_status": near_final_status,
        "pipeline_stage": _near_final_pipeline_stage(near_final_status),
        "failure_class": failure_class,
        "failure_reason": _near_final_failure_label(failure_class),
        "auto_rewrite_eligible": (
            bool(latest_evaluation.auto_rewrite_eligible)
            if latest_evaluation is not None and latest_evaluation.auto_rewrite_eligible is not None
            else None
        ),
        "contract_field_refs": latest_evaluation.contract_field_refs_json if latest_evaluation is not None else {},
        "promotion_blockers": latest_evaluation.promotion_blockers_json if latest_evaluation is not None else [],
        "evaluation_id": latest_evaluation.evaluation_id if latest_evaluation is not None else details.get("evaluation_id"),
        "revision_candidate_id": revision_candidate.revision_id if revision_candidate is not None else None,
        "revision_candidate_status": revision_candidate.status if revision_candidate is not None else None,
        "overall_score": latest_evaluation.overall_score if latest_evaluation is not None else None,
        "requires_human_review": bool(latest_evaluation.requires_human_review) if latest_evaluation is not None else False,
        "findings": latest_evaluation.findings_json if latest_evaluation is not None else [],
        "revision_brief": latest_evaluation.revision_brief_json if latest_evaluation is not None else [],
        "stage_order": ["Planning", "Drafting", "Rewriting", "Acceptance Review", "Near-final"],
        "created_at": latest_evaluation.created_at if latest_evaluation is not None else latest_attempt.created_at,
    }


def _near_final_pipeline_stage(status: str | None) -> str:
    return {
        "near_final_ready": "Near-final",
        "revision_required": "Acceptance Review",
        "human_review_required": "Acceptance Review",
    }.get(status or "", "Planning")


def _near_final_failure_label(failure_class: Any) -> str | None:
    if not isinstance(failure_class, str) or not failure_class:
        return None
    return {
        "fact_blocker": "fact",
        "scene_structure_failure": "structure",
        "character_flatness": "character",
        "prose_model_voice": "prose",
        "ending_weakness": "prose",
        "chapter_payoff_gap": "chapter",
        "reference_safety": "safety",
    }.get(failure_class, failure_class)


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
    if report.issues_json:
        summary["issues"] = report.issues_json
    evidence_spans = _extract_evidence_spans(report.issues_json or [])
    if evidence_spans:
        summary["evidence_spans"] = evidence_spans
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


def _extract_evidence_spans(entries: list[dict]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_spans = entry.get("evidence_spans")
        if isinstance(entry_spans, list):
            spans.extend(span for span in entry_spans if isinstance(span, dict))
    return spans


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
