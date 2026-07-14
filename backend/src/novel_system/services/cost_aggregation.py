"""token/费用聚合（结果闭环治理设计 §5.8/§10，Wave 6）。

基于现有 ``LlmCall``（token/延迟）+ ``SceneRunState``（5× 预算）建立聚合，
**不复制调用日志、不新增列**。价格层在 ``services/pricing.py``。

完成门：任意场景可解释——
- 总成本 + 币种（跨 provider 汇总以**费用**为准，§5.8）；
- 各阶段占比（候选生成 / QC / 修订 / 评审）；
- 是否超预算（5× 上限使用率，源自 SceneRunState）；
- 评审是否独立（observed → config 回退，见 model_independence）。

口径纪律（§5.8）：
- 跨 provider 的 token 不直接相加（分词器不同）——``tokens_by_provider`` 分列；
- 三口径 estimate / provider_actual / budget_charged，父调用只汇总一次；
- 额外成本可归因（失败重试 / 重复 QC / 低分散补候选）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    FinalScene,
    LlmCall,
    LlmCallAttempt,
    SceneCard,
    SceneRunState,
)
from novel_system.services import model_independence, pricing

_LOGGER = logging.getLogger(__name__)

BUDGET_MULTIPLIER = 5

PHASE_CANDIDATE = "candidate_generation"
PHASE_QC = "quality_check"
PHASE_REVISION = "revision"
PHASE_REVIEW = "review"
PHASE_OTHER = "other"
_PHASES = (PHASE_CANDIDATE, PHASE_QC, PHASE_REVISION, PHASE_REVIEW, PHASE_OTHER)

# criticality → Best-of-N 初始候选数（与 scene_criticality 语义一致；超出即补候选）
_INITIAL_CANDIDATES = {"critical": 3, "standard": 2, "transition": 1}


def classify_phase(node_id: str | None, step: str | None = None) -> str:
    """把一次 LLM 调用归入四阶段之一（§5.8 候选生成/QC/修订/评审）+ other。"""
    key = (node_id or step or "").lower()
    if not key:
        return PHASE_OTHER
    # revision 优先于 candidate：`scene_auto_rewrite`/`style_patch` 含 draft 语义但属修订
    if any(t in key for t in ("patch", "rewrite", "revision")):
        return PHASE_REVISION
    if any(
        t in key
        for t in ("qc", "near_final", "quality_contract", "validate")
    ):
        return PHASE_QC
    if any(
        t in key
        for t in ("deep_review", "diagnosis", "adjudicate", "critique", "literary_eval")
    ):
        return PHASE_REVIEW
    if any(
        t in key
        for t in ("draft", "blueprint", "continuation", "de_template", "architecture", "running")
    ):
        return PHASE_CANDIDATE
    return PHASE_OTHER


def _call_cost(call: LlmCall) -> dict[str, Any]:
    return pricing.compute_cost(
        call.provider,
        call.model,
        call.prompt_tokens,
        call.completion_tokens,
        at=call.created_at,
    )


def _attempt_cost(call: LlmCall, attempt: LlmCallAttempt) -> dict[str, Any]:
    return pricing.compute_cost(
        call.provider,
        call.model,
        attempt.prompt_tokens,
        attempt.completion_tokens,
        at=call.created_at,
    )


def _empty_phase_breakdown() -> dict[str, dict[str, Any]]:
    return {p: {"tokens": 0, "cost": 0.0, "share": 0.0, "call_count": 0} for p in _PHASES}


def _aggregate_calls(session: Session, calls: list[LlmCall]) -> dict[str, Any]:
    """把一组 LlmCall 折算为费用/阶段/provider 维度的通用聚合（scene/chapter/project 复用）。"""
    total_cost = 0.0
    total_tokens = 0
    is_estimate = False
    currency: str | None = None
    phase = _empty_phase_breakdown()
    tokens_by_provider: dict[str, int] = {}
    cost_by_provider: dict[str, float] = {}
    attempts_by_call: dict[str, list[LlmCallAttempt]] = {}
    if calls:
        attempts = session.execute(
            select(LlmCallAttempt)
            .where(LlmCallAttempt.llm_call_id.in_([call.llm_call_id for call in calls]))
            .order_by(
                LlmCallAttempt.llm_call_id.asc(),
                LlmCallAttempt.provider_attempt_no.asc(),
            )
        ).scalars().all()
        for attempt in attempts:
            attempts_by_call.setdefault(attempt.llm_call_id, []).append(attempt)

    estimated_tokens = 0
    provider_actual_tokens = 0
    budget_charged_tokens = 0
    attempt_row_count = 0
    physical_attempt_count = 0
    pre_dispatch_attempt_count = 0
    usage_estimate_count = 0
    exception_count = 0
    retry_attempt_count = 0
    transport_retry_attempt_count = 0
    response_parse_retry_attempt_count = 0
    degrade_attempt_count = 0
    legacy_parent_without_attempt_count = 0
    legacy_unreconstructable_tokens = 0
    for call in calls:
        cost = _call_cost(call)
        tokens = int(call.total_tokens or 0)
        total_cost += cost["cost"]
        total_tokens += tokens
        is_estimate = (
            is_estimate
            or bool(cost["is_estimate"])
            or bool(call.usage_is_estimate)
        )
        currency = currency or cost["currency"]
        ph = classify_phase(call.node_id, call.step)
        phase[ph]["tokens"] += tokens
        phase[ph]["cost"] += cost["cost"]
        phase[ph]["call_count"] += 1
        prov = call.provider or "unknown"
        tokens_by_provider[prov] = tokens_by_provider.get(prov, 0) + tokens
        cost_by_provider[prov] = cost_by_provider.get(prov, 0.0) + cost["cost"]

        call_attempts = attempts_by_call.get(call.llm_call_id, [])
        if call_attempts:
            # 父调用是唯一逻辑/报表层；它的账目字段已是物理尝试之和。
            estimated_tokens += int(call.estimated_tokens or 0)
            budget_charged_tokens += int(call.budget_charged_tokens or 0)
            attempt_row_count += len(call_attempts)
            for attempt in call_attempts:
                dispatched = attempt.request_dispatched_at is not None
                if dispatched:
                    physical_attempt_count += 1
                else:
                    pre_dispatch_attempt_count += 1
                if dispatched and bool(attempt.usage_is_estimate):
                    usage_estimate_count += 1
                elif dispatched:
                    provider_actual_tokens += int(attempt.total_tokens or 0)
                if attempt.error_code:
                    exception_count += 1
                if dispatched and int(attempt.provider_attempt_no or 0) > 0:
                    retry_attempt_count += 1
                if dispatched and attempt.dispatch_kind == "transport_retry":
                    # transport_retry 同时承载普通重试和连接能力降级，不能猜测拆分。
                    transport_retry_attempt_count += 1
                if dispatched and attempt.dispatch_kind == "response_parse_retry":
                    response_parse_retry_attempt_count += 1
                if dispatched and attempt.dispatch_kind in {
                    "api_mode_degrade",
                    "structured_output_degrade",
                    "missing_text_degrade",
                }:
                    degrade_attempt_count += 1
            continue

        request_summary = call.request_payload_summary or {}
        is_legacy_parent = "_accounting_provider_execution_mode" not in request_summary
        if is_legacy_parent:
            # 0064 前的父调用没有物理尝试行和新账目字段；显式兼容读取。
            legacy_parent_without_attempt_count += 1
            legacy_unreconstructable_tokens += tokens
            estimated_tokens += int(call.estimated_tokens or tokens)
            if call.usage_is_estimate is False:
                provider_actual_tokens += tokens
            # 0065 将 legacy charge 明确回填为 0；零值不能回退成 total。
            budget_charged_tokens += int(call.budget_charged_tokens or 0)
            usage_estimate_count += int(bool(call.usage_is_estimate))
            exception_count += int(bool(call.error_code))
        else:
            estimated_tokens += int(call.estimated_tokens or 0)
            budget_charged_tokens += int(call.budget_charged_tokens or 0)
    for ph in phase.values():
        ph["share"] = (ph["cost"] / total_cost) if total_cost > 0 else 0.0
    estimate_legacy_suffix = (
        "_with_legacy_total_tokens_fallback"
        if legacy_parent_without_attempt_count
        else ""
    )
    actual_legacy_suffix = (
        "_with_legacy_parent_usage_fallback"
        if legacy_parent_without_attempt_count
        else ""
    )
    return {
        "total_cost": total_cost,
        "total_tokens": total_tokens,
        "currency": currency or "USD",
        "is_estimate": is_estimate,
        "cross_provider": len(tokens_by_provider) > 1,
        "tokens_by_provider": tokens_by_provider,
        "cost_by_provider": cost_by_provider,
        "phase_breakdown": phase,
        "call_count": len(calls),
        "calibers": {
            "estimate": {
                "tokens": estimated_tokens,
                "source": f"llm_calls.estimated_tokens{estimate_legacy_suffix}",
            },
            "provider_actual": {
                "tokens": provider_actual_tokens,
                "source": (
                    "llm_call_attempts.total_tokens_with_provider_usage"
                    f"{actual_legacy_suffix}"
                ),
            },
            "budget_charged": {
                "tokens": budget_charged_tokens,
                "source": "llm_calls.budget_charged_tokens",
            },
        },
        "attempt_observability": {
            "attempt_row_count": attempt_row_count,
            "physical_attempt_count": physical_attempt_count,
            "pre_dispatch_attempt_count": pre_dispatch_attempt_count,
            "usage_estimate_count": usage_estimate_count,
            "exception_count": exception_count,
            "retry_attempt_count": retry_attempt_count,
            "transport_retry_attempt_count": transport_retry_attempt_count,
            "response_parse_retry_attempt_count": response_parse_retry_attempt_count,
            "degrade_attempt_count": degrade_attempt_count,
            "legacy_parent_without_attempt_count": legacy_parent_without_attempt_count,
            "legacy_unreconstructable_tokens": legacy_unreconstructable_tokens,
        },
    }


def _budget_view(state: SceneRunState | None) -> dict[str, Any]:
    if state is None or state.scene_token_budget is None:
        return {
            "budget": None,
            "used": int(getattr(state, "scene_tokens_used", 0) or 0) if state else 0,
            "remaining": None,
            "over_budget": False,
            "usage_ratio": None,
            "baseline": None,
            "multiplier_used": None,
            "run_policy": getattr(state, "run_policy", None) if state else None,
        }
    budget = int(state.scene_token_budget)
    used = int(state.scene_tokens_used or 0)
    baseline = max(1, budget // BUDGET_MULTIPLIER)
    return {
        "budget": budget,
        "used": used,
        "remaining": max(0, budget - used),
        "over_budget": used > budget,
        "usage_ratio": round(used / budget, 4) if budget else None,
        "baseline": baseline,
        "multiplier_used": round(used / baseline, 4),
        "run_policy": state.run_policy,
    }


def _extra_cost(session: Session, scene_id: str, calls: list[LlmCall], total_cost: float,
                state: SceneRunState | None) -> dict[str, Any]:
    """额外成本归因（§5.8：低分散补候选 / 失败重试 / 重复 QC）。启发式、口径已注释。"""
    ordered = sorted(calls, key=lambda c: (c.created_at or "", c.llm_call_id))
    attempts_by_call: dict[str, list[LlmCallAttempt]] = {}
    if ordered:
        attempts = session.execute(
            select(LlmCallAttempt).where(
                LlmCallAttempt.llm_call_id.in_([call.llm_call_id for call in ordered])
            )
        ).scalars().all()
        for attempt in attempts:
            attempts_by_call.setdefault(attempt.llm_call_id, []).append(attempt)
    # 新账本按失败物理尝试归因；legacy 无子账时回退父 error_code。
    failed_cost = 0.0
    for call in ordered:
        call_attempts = attempts_by_call.get(call.llm_call_id, [])
        if call_attempts:
            failed_cost += sum(
                _attempt_cost(call, attempt)["cost"]
                for attempt in call_attempts
                if attempt.request_dispatched_at is not None
                and (
                    attempt.error_code
                    or attempt.accounting_status
                    in {"failed", "usage_exceeds_reservation"}
                )
            )
        elif call.error_code:
            failed_cost += _call_cost(call)["cost"]
    # 重复 QC：QC 阶段第 2 次起
    qc_calls = [c for c in ordered if classify_phase(c.node_id, c.step) == PHASE_QC]
    repeat_qc_cost = sum(_call_cost(c)["cost"] for c in qc_calls[1:])
    # 低分散补候选：候选阶段超出 criticality 初始 N 的部分
    cand_calls = [c for c in ordered if classify_phase(c.node_id, c.step) == PHASE_CANDIDATE]
    initial = _INITIAL_CANDIDATES.get((state.criticality_level or "").lower(), 1) if state else 1
    topup_cost = sum(_call_cost(c)["cost"] for c in cand_calls[initial:])
    total = failed_cost + repeat_qc_cost + topup_cost
    return {
        "failed_call_cost": failed_cost,
        "repeat_qc_cost": repeat_qc_cost,
        "low_dispersion_topup_cost": topup_cost,
        "total": total,
        "retry_cost_ratio": round(total / total_cost, 4) if total_cost > 0 else 0.0,
    }


def scene_cost(session: Session, scene_id: str) -> dict[str, Any]:
    calls = list(
        session.execute(select(LlmCall).where(LlmCall.scene_id == scene_id)).scalars().all()
    )
    state = session.get(SceneRunState, scene_id)
    agg = _aggregate_calls(session, calls)
    budget = _budget_view(state)
    # 评审独立性：observed（本场实际）优先，无评审调用时回退 config 口径
    judge = model_independence.observed_correlated_judge(session, scene_id)
    if judge is None:
        judge = model_independence.judge_independence(session)
    result = {
        "scene_id": scene_id,
        "total_cost": agg["total_cost"],
        "currency": agg["currency"],
        "is_estimate": agg["is_estimate"],
        "total_tokens": agg["total_tokens"],
        "cross_provider": agg["cross_provider"],
        "tokens_by_provider": agg["tokens_by_provider"],
        "cost_by_provider": agg["cost_by_provider"],
        "phase_breakdown": agg["phase_breakdown"],
        "call_count": agg["call_count"],
        "budget": budget,
        "calibers": agg["calibers"],
        "attempt_observability": agg["attempt_observability"],
        "extra_cost": _extra_cost(session, scene_id, calls, agg["total_cost"], state),
        "judge_independence": judge,
    }
    return result


def _archived_scene_ids(session: Session, *, chapter_id: str | None = None,
                        scene_ids: set[str] | None = None) -> set[str]:
    stmt = select(FinalScene.scene_id).where(FinalScene.status == "archived")
    if chapter_id is not None:
        stmt = stmt.where(FinalScene.chapter_id == chapter_id)
    rows = set(session.execute(stmt).scalars().all())
    if scene_ids is not None:
        rows &= scene_ids
    return rows


def chapter_cost(session: Session, chapter_id: str) -> dict[str, Any]:
    calls = list(
        session.execute(select(LlmCall).where(LlmCall.chapter_id == chapter_id)).scalars().all()
    )
    agg = _aggregate_calls(session, calls)
    archived = _archived_scene_ids(session, chapter_id=chapter_id)
    archived_count = len(archived)
    return {
        "chapter_id": chapter_id,
        "total_cost": agg["total_cost"],
        "currency": agg["currency"],
        "is_estimate": agg["is_estimate"],
        "total_tokens": agg["total_tokens"],
        "cross_provider": agg["cross_provider"],
        "tokens_by_provider": agg["tokens_by_provider"],
        "cost_by_provider": agg["cost_by_provider"],
        "phase_breakdown": agg["phase_breakdown"],
        "call_count": agg["call_count"],
        "calibers": agg["calibers"],
        "attempt_observability": agg["attempt_observability"],
        "archived_scene_count": archived_count,
        "tokens_per_archived_scene": (
            round(agg["total_tokens"] / archived_count) if archived_count else None
        ),
        "cost_per_archived_chapter": agg["total_cost"] if archived_count else None,
    }


def project_cost(session: Session, project_id: str) -> dict[str, Any]:
    scene_ids = set(
        session.execute(
            select(SceneCard.scene_id).where(SceneCard.project_id == project_id)
        ).scalars().all()
    )
    chapter_ids = set(
        session.execute(
            select(SceneCard.chapter_id).where(SceneCard.project_id == project_id)
        ).scalars().all()
    )
    # 调用命中：project_id 直接命中 或 scene_id ∈ 项目场景（LlmCall.project_id 可能为空）
    calls = list(
        session.execute(select(LlmCall).where(LlmCall.project_id == project_id)).scalars().all()
    )
    seen = {c.llm_call_id for c in calls}
    if scene_ids:
        for call in session.execute(
            select(LlmCall).where(LlmCall.scene_id.in_(scene_ids))
        ).scalars().all():
            if call.llm_call_id not in seen:
                calls.append(call)
                seen.add(call.llm_call_id)
    agg = _aggregate_calls(session, calls)
    archived = _archived_scene_ids(session, scene_ids=scene_ids) if scene_ids else set()
    archived_count = len(archived)
    archived_chapters = {
        cid for cid in chapter_ids
        if _archived_scene_ids(session, chapter_id=cid)
    }
    return {
        "project_id": project_id,
        "total_cost": agg["total_cost"],
        "currency": agg["currency"],
        "is_estimate": agg["is_estimate"],
        "total_tokens": agg["total_tokens"],
        "cross_provider": agg["cross_provider"],
        "tokens_by_provider": agg["tokens_by_provider"],
        "cost_by_provider": agg["cost_by_provider"],
        "phase_breakdown": agg["phase_breakdown"],
        "call_count": agg["call_count"],
        "calibers": agg["calibers"],
        "attempt_observability": agg["attempt_observability"],
        "chapter_count": len(chapter_ids),
        "scene_count": len(scene_ids),
        "archived_scene_count": archived_count,
        "archived_chapter_count": len(archived_chapters),
        "tokens_per_archived_scene": (
            round(agg["total_tokens"] / archived_count) if archived_count else None
        ),
        "cost_per_archived_chapter": (
            round(agg["total_cost"] / len(archived_chapters), 6) if archived_chapters else None
        ),
        "judge_independence": model_independence.judge_independence(session),
    }
