"""场景 token 预算（结果闭环治理 §4.6/§5.5/§5.8/§7.12，Wave 3）。

单发基线（§4.6）：对同一冻结 Bundle、同一 writer 路由执行一次 N=1 正文生成，
再执行一次确定性 Q0/Q1 与来源安全检查（本地，0 token）。生产预算按生成调用
的**估算输入上限 + 配置输出上限**计算。关键场景端到端上限 = 5 × 基线。

硬行为（§5.8）：
- 预算耗尽后停止**新**调用，返回已有最佳稿——基线必经调用不拦但照常计数；
  可选支出（补候选 / LLM 批判 / 补丁 / near-final 重写）过 ``can_spend`` 闸。
- 预算按场景生命周期累计；自动流程不得重置（§7.12），扩容唯一入口是作者
  显式 topup（路由层留 OperationLog 审计）。
- token 口径：本 Wave 落「实际 usage 累计 + 估算判定」最小闭环；估算/实际/
  计费三口径与跨 provider 分槽归 Wave 6 成本聚合。
- 顺序管线内「先预留后发起」退化为逐次前置检查（无并发候选生成）。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from novel_system.accounting_contract import (
    DEFAULT_PROVIDER_ATTEMPT_BUDGET,
    PROVIDER_ATTEMPT_BUDGET_CONFIG_KEY,
)
from novel_system.db.models import LlmCall, OperationLog, SceneRunState

_LOGGER = logging.getLogger(__name__)

BUDGET_MULTIPLIER = 5
# PromptBuilder / task_config 不可得时的保守回退（≈短场景输入 + stylize 输出上限）
FALLBACK_INPUT_TOKENS = 4000
FALLBACK_OUTPUT_TOKENS = 2400
BASELINE_WRITER_NODE = "style_draft"


def _insert_scene_run_state_if_missing(session: Session, scene_id: str) -> None:
    values = {"scene_id": scene_id, "scene_status": "ready"}
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

        statement = dialect_insert(SceneRunState).values(**values).on_conflict_do_nothing(
            index_elements=[SceneRunState.scene_id]
        )
        session.execute(statement)
        session.commit()
        return
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

        statement = dialect_insert(SceneRunState).values(**values).on_conflict_do_nothing(
            index_elements=[SceneRunState.scene_id]
        )
        session.execute(statement)
        session.commit()
        return
    try:
        with session.begin_nested():
            session.execute(insert(SceneRunState).values(**values))
        session.commit()
    except IntegrityError:
        session.rollback()


def ensure_scene_budget_initialized(
    session: Session,
    scene_id: str,
) -> SceneRunState:
    """Atomically establish and validate the immutable scene lifecycle budget.

    The estimate and provider-attempt limit are deliberately resolved here so
    callers cannot initialize the same scene with competing budget candidates.
    """
    if not str(scene_id or "").strip():
        raise ValueError("scene budget initialization requires scene_id")
    session.commit()
    # SessionLocal intentionally keeps identities across commits. Canonical
    # validation must nevertheless observe topups committed by another request.
    session.expire_all()
    _insert_scene_run_state_if_missing(session, scene_id)
    session.expire_all()

    state = session.get(SceneRunState, scene_id)
    if state is None:
        raise RuntimeError(f"scene run state disappeared during budget initialization: {scene_id}")

    if state.scene_budget_basis_json is not None:
        basis_budget = _basis_scene_token_budget(state.scene_budget_basis_json)
        if state.scene_token_budget is None:
            effective_budget = audited_scene_budget_prefixes(session, state)[-1]
            _validate_scene_budget_state(session, state, effective_budget=effective_budget)
            session.execute(
                update(SceneRunState)
                .where(
                    SceneRunState.scene_id == scene_id,
                    SceneRunState.scene_token_budget.is_(None),
                )
                .values(scene_token_budget=effective_budget)
            )
            session.commit()
            session.expire_all()
            state = session.get(SceneRunState, scene_id)
            assert state is not None
        _validate_scene_budget_state(session, state)
        return state

    if state.scene_token_budget is not None:
        _validate_scene_budget_state(session, state)
        existing_budget = int(state.scene_token_budget)
        existing_provider_budget = int(state.provider_attempt_budget)
        basis = {
            "basis_type": "legacy_existing_scene_token_budget",
            "scene_token_budget": existing_budget,
            "topup_audit_cutoff_operation_id": _current_operation_id(session),
            "token_budget_basis": {
                "reconstructable": False,
                "reason": "legacy_scene_token_budget_without_basis",
            },
            "provider_attempt_budget": {
                "config_key": PROVIDER_ATTEMPT_BUDGET_CONFIG_KEY,
                "value": existing_provider_budget,
            },
        }
        session.execute(
            update(SceneRunState)
            .where(
                SceneRunState.scene_id == scene_id,
                SceneRunState.scene_budget_basis_json.is_(None),
            )
            .values(scene_budget_basis_json=basis)
        )
    else:
        _validate_uninitialized_scene_budget_state(state)
        effective_baseline, effective_provider_budget = _canonical_budget_candidate(session)
        scene_budget = BUDGET_MULTIPLIER * effective_baseline
        basis = {
            "baseline_tokens": effective_baseline,
            "budget_multiplier": BUDGET_MULTIPLIER,
            "scene_token_budget": scene_budget,
            "topup_audit_cutoff_operation_id": _current_operation_id(session),
            "provider_attempt_budget": {
                "config_key": PROVIDER_ATTEMPT_BUDGET_CONFIG_KEY,
                "value": effective_provider_budget,
            },
        }
        session.execute(
            update(SceneRunState)
            .where(
                SceneRunState.scene_id == scene_id,
                SceneRunState.scene_budget_basis_json.is_(None),
                SceneRunState.scene_token_budget.is_(None),
                SceneRunState.scene_tokens_used == 0,
                SceneRunState.scene_tokens_reserved == 0,
                SceneRunState.provider_attempts_used == 0,
                SceneRunState.total_attempt_count == 0,
            )
            .values(
                scene_token_budget=scene_budget,
                scene_budget_basis_json=basis,
                provider_attempt_budget=effective_provider_budget,
            )
        )
    session.commit()
    session.expire_all()
    state = session.get(SceneRunState, scene_id)
    assert state is not None
    if state.scene_budget_basis_json is None or state.scene_token_budget is None:
        raise RuntimeError(f"scene budget initialization lost its CAS: {scene_id}")
    _validate_scene_budget_state(session, state)
    return state


def _current_operation_id(session: Session) -> int:
    value = session.execute(select(func.max(OperationLog.operation_id))).scalar_one()
    return int(value or 0)


def audited_scene_budget_prefixes(
    session: Session,
    state: SceneRunState,
) -> tuple[int, ...]:
    """Return every legal effective budget represented by the immutable basis + audit."""

    basis = state.scene_budget_basis_json
    basis_budget = _basis_scene_token_budget(basis)
    assert isinstance(basis, dict)
    cutoff = basis.get("topup_audit_cutoff_operation_id", 0)
    if not isinstance(cutoff, int) or isinstance(cutoff, bool) or cutoff < 0:
        raise _corrupt_budget_state("topup audit cutoff must be a non-negative integer")
    prefixes = [basis_budget]
    topups = session.execute(
        select(OperationLog)
        .where(
            OperationLog.operation_id > cutoff,
            OperationLog.event_type == "scene_budget_topup",
            OperationLog.object_type == "scene",
            OperationLog.object_ref == state.scene_id,
        )
        .order_by(OperationLog.operation_id.asc())
    ).scalars().all()
    for topup in topups:
        payload = topup.payload_json
        if not isinstance(payload, dict):
            raise _corrupt_budget_state("topup audit payload must be an object")
        extra = payload.get("extra_tokens")
        reported_budget = payload.get("scene_token_budget")
        if not isinstance(extra, int) or isinstance(extra, bool) or extra <= 0:
            raise _corrupt_budget_state("topup audit extra_tokens must be positive")
        effective = prefixes[-1] + extra
        if (
            not isinstance(reported_budget, int)
            or isinstance(reported_budget, bool)
            or reported_budget != effective
        ):
            raise _corrupt_budget_state("topup audit scene_token_budget prefix is invalid")
        prefixes.append(effective)
    return tuple(prefixes)


def _canonical_budget_candidate(session: Session) -> tuple[int, int]:
    from novel_system.services.llm_client import load_model_routing_config

    baseline = max(
        estimate_baseline_tokens(session, {}),
        FALLBACK_INPUT_TOKENS + FALLBACK_OUTPUT_TOKENS,
    )
    routing = load_model_routing_config()
    retry_budget = getattr(routing, "retry_budget", {})
    configured_attempts = (
        retry_budget.get("provider_attempt_budget", DEFAULT_PROVIDER_ATTEMPT_BUDGET)
        if isinstance(retry_budget, dict)
        else DEFAULT_PROVIDER_ATTEMPT_BUDGET
    )
    return int(baseline), max(1, int(configured_attempts))


def _basis_scene_token_budget(basis: object) -> int:
    if not isinstance(basis, dict):
        raise _corrupt_budget_state("scene_budget_basis_json must be an object")
    budget = basis.get("scene_token_budget")
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0:
        raise _corrupt_budget_state("basis scene_token_budget must be a positive integer")
    return budget


def _basis_provider_attempt_budget(basis: object) -> int:
    if not isinstance(basis, dict):
        raise _corrupt_budget_state("scene_budget_basis_json must be an object")
    provider_basis = basis.get("provider_attempt_budget")
    if not isinstance(provider_basis, dict):
        raise _corrupt_budget_state("basis provider_attempt_budget must be an object")
    value = provider_basis.get("value")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise _corrupt_budget_state("basis provider_attempt_budget.value must be a positive integer")
    return value


def _counter(value: object, field: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _corrupt_budget_state(f"{field} must be an integer")
    if value < (1 if positive else 0):
        qualifier = "positive" if positive else "non-negative"
        raise _corrupt_budget_state(f"{field} must be {qualifier}")
    return value


def _validate_scene_budget_state(
    session: Session,
    state: SceneRunState,
    *,
    effective_budget: int | None = None,
) -> None:
    budget = effective_budget
    if budget is None:
        budget = _counter(state.scene_token_budget, "scene_token_budget", positive=True)
    if state.scene_budget_basis_json is not None:
        effective = audited_scene_budget_prefixes(session, state)[-1]
        if effective != budget:
            raise _corrupt_budget_state("audited effective budget does not match scene_token_budget")
    used = _counter(state.scene_tokens_used, "scene_tokens_used")
    reserved = _counter(state.scene_tokens_reserved, "scene_tokens_reserved")
    if used + reserved > budget:
        usage_overage_tombstone = session.scalar(
                select(LlmCall.llm_call_id).where(
                    LlmCall.scene_id == state.scene_id,
                    LlmCall.accounting_status == "usage_exceeds_reservation",
                    LlmCall.request_dispatched_at.is_not(None),
                ).limit(1)
            ) is not None
        integrity_tombstone = session.scalar(
            select(LlmCall.llm_call_id).where(
                LlmCall.scene_id == state.scene_id,
                LlmCall.request_dispatched_at.is_not(None),
                LlmCall.error_code.in_(
                    {
                        "LLM_ACCOUNTING_HOOK_NOT_INVOKED",
                        "LLM_ACCOUNTING_UNKNOWN_DISPATCH",
                        "LLM_ACCOUNTING_LIFECYCLE_INCOMPLETE",
                    }
                ),
            ).limit(1)
        ) is not None
        known_blocked_overage = reserved == 0 and (
            (
                state.run_execution_status == "usage_exceeds_reservation"
                and usage_overage_tombstone
            )
            or (
                state.run_execution_status == "accounting_integrity_blocked"
                and integrity_tombstone
            )
        )
        if not known_blocked_overage:
            raise _corrupt_budget_state("used plus reserved exceeds scene_token_budget")
    provider_used = _counter(state.provider_attempts_used, "provider_attempts_used")
    provider_budget = _counter(
        state.provider_attempt_budget,
        "provider_attempt_budget",
        positive=True,
    )
    if state.scene_budget_basis_json is not None:
        basis_provider_budget = _basis_provider_attempt_budget(state.scene_budget_basis_json)
        if basis_provider_budget != provider_budget:
            raise _corrupt_budget_state(
                "basis provider_attempt_budget.value does not match provider_attempt_budget"
            )
    if provider_used > provider_budget:
        raise _corrupt_budget_state("provider attempts used exceeds its lifecycle budget")
    total_attempts = _counter(state.total_attempt_count, "total_attempt_count")
    attempt_budget = _counter(state.attempt_budget, "attempt_budget", positive=True)
    if total_attempts > attempt_budget:
        raise _corrupt_budget_state("total attempts used exceeds its business attempt budget")


def _validate_uninitialized_scene_budget_state(state: SceneRunState) -> None:
    used = _counter(state.scene_tokens_used, "scene_tokens_used")
    reserved = _counter(state.scene_tokens_reserved, "scene_tokens_reserved")
    provider_used = _counter(state.provider_attempts_used, "provider_attempts_used")
    _counter(state.provider_attempt_budget, "provider_attempt_budget", positive=True)
    total_attempts = _counter(state.total_attempt_count, "total_attempt_count")
    _counter(state.attempt_budget, "attempt_budget", positive=True)
    if used or reserved or provider_used or total_attempts:
        raise _corrupt_budget_state(
            "budget and basis are absent after lifecycle accounting has already started"
        )


def _corrupt_budget_state(reason: str) -> ValueError:
    return ValueError(f"scene budget state is corrupt: {reason}")


def estimate_baseline_tokens(session: Session, snapshot: dict[str, Any]) -> int:
    """确定性估算单发基线：writer 路由的估算输入 + 配置输出上限。"""
    input_tokens = FALLBACK_INPUT_TOKENS
    output_tokens = FALLBACK_OUTPUT_TOKENS
    try:
        from novel_system.services.prompt_builder import PromptBuilder

        prompt = PromptBuilder().build(snapshot, BASELINE_WRITER_NODE)
        estimated = (prompt.get("token_budget") or {}).get("estimated_input_tokens")
        if isinstance(estimated, (int, float)) and estimated > 0:
            input_tokens = int(estimated)
    except Exception:
        _LOGGER.debug("baseline input estimation degraded; using fallback", exc_info=True)
    try:
        from novel_system.services.llm_task_runner import LLMNodeRunner

        task_config = LLMNodeRunner(session).task_config(BASELINE_WRITER_NODE)
        cap = getattr(task_config, "max_output_tokens", None)
        if isinstance(cap, (int, float)) and cap > 0:
            output_tokens = int(cap)
    except Exception:
        _LOGGER.debug("baseline output cap lookup degraded; using fallback", exc_info=True)
    return input_tokens + output_tokens


def ensure_budget(
    state: SceneRunState,
    baseline_tokens: int,
    *,
    provider_attempt_budget: int = DEFAULT_PROVIDER_ATTEMPT_BUDGET,
) -> None:
    """一次性初始化预算依据；补全 legacy provenance；非空依据不可覆盖。"""
    if state.scene_budget_basis_json:
        if state.scene_token_budget is None:
            basis = state.scene_budget_basis_json
            recovered_budget = (
                basis.get("scene_token_budget") if isinstance(basis, dict) else None
            )
            if (
                not isinstance(recovered_budget, int)
                or isinstance(recovered_budget, bool)
                or recovered_budget <= 0
            ):
                raise ValueError("immutable scene budget basis has no positive token budget")
            state.scene_token_budget = recovered_budget
        return

    effective_provider_budget = max(1, int(provider_attempt_budget))
    if state.scene_token_budget is not None:
        state.provider_attempt_budget = effective_provider_budget
        state.scene_budget_basis_json = {
            "basis_type": "legacy_existing_scene_token_budget",
            "scene_token_budget": int(state.scene_token_budget),
            "token_budget_basis": {
                "reconstructable": False,
                "reason": "legacy_scene_token_budget_without_basis",
            },
            "provider_attempt_budget": {
                "config_key": PROVIDER_ATTEMPT_BUDGET_CONFIG_KEY,
                "value": effective_provider_budget,
            },
        }
        return

    if baseline_tokens <= 0:
        return
    baseline = int(baseline_tokens)
    scene_budget = BUDGET_MULTIPLIER * baseline
    state.scene_token_budget = scene_budget
    state.provider_attempt_budget = effective_provider_budget
    state.scene_budget_basis_json = {
        "baseline_tokens": baseline,
        "budget_multiplier": BUDGET_MULTIPLIER,
        "scene_token_budget": scene_budget,
        "provider_attempt_budget": {
            "config_key": PROVIDER_ATTEMPT_BUDGET_CONFIG_KEY,
            "value": effective_provider_budget,
        },
    }


def budget_unit(state: SceneRunState) -> int:
    """一个「生成调用当量」的估算值 = 基线（预算/5）；未初始化回退常量。"""
    if state.scene_token_budget:
        return max(1, int(state.scene_token_budget) // BUDGET_MULTIPLIER)
    return FALLBACK_INPUT_TOKENS + FALLBACK_OUTPUT_TOKENS


def can_spend(state: SceneRunState | None, estimated_tokens: int) -> bool:
    """可选支出的前置预留检查；预算未初始化不拦（渐进迁移）。"""
    if state is None or state.scene_token_budget is None:
        return True
    used = int(state.scene_tokens_used or 0)
    return used + max(0, int(estimated_tokens)) <= int(state.scene_token_budget)
