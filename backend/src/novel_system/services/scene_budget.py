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

from sqlalchemy.orm import Session

from novel_system.db.models import SceneRunState

_LOGGER = logging.getLogger(__name__)

BUDGET_MULTIPLIER = 5
# PromptBuilder / task_config 不可得时的保守回退（≈短场景输入 + stylize 输出上限）
FALLBACK_INPUT_TOKENS = 4000
FALLBACK_OUTPUT_TOKENS = 2400
BASELINE_WRITER_NODE = "style_draft"


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


def ensure_budget(state: SceneRunState, baseline_tokens: int) -> None:
    """预算为空时确立为 5×基线；已设不覆盖、从不收缩（作者 topup 是唯一扩容口）。"""
    if state.scene_token_budget is None and baseline_tokens > 0:
        state.scene_token_budget = BUDGET_MULTIPLIER * int(baseline_tokens)


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


def record_usage(session: Session, scene_id: str, total_tokens: Any) -> None:
    """LLM 调用结算：凡带 scene_id 且存在运行态行的调用（成功/失败）都累计。"""
    if not scene_id:
        return
    state = session.get(SceneRunState, scene_id)
    if state is None:
        return
    try:
        tokens = int(total_tokens or 0)
    except (TypeError, ValueError):
        tokens = 0
    if tokens <= 0:
        return
    state.scene_tokens_used = int(state.scene_tokens_used or 0) + tokens
