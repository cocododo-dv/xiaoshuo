"""LLM 角色槽独立性（结果闭环治理设计 §5.7，Wave 6）。

§5.7 至少区分五个角色槽：writer_primary / writer_explorer / critic_independent /
judge_advisory / extractor_fast。生产默认要求 critic_independent 与 writer_primary
至少在模型或提供商之一不同；同源时标记 ``correlated_judge=true`` 并降权提示。

纪律（§5.4/§5.7）：判定**只影响咨询建议的权重与展示**，不改阻断权——LLM 评审在任何
模型组合下都只提案，Q0/Q1 须经确定性复核。这里不做任何阻断决策，只输出可解释信号。

本模块**不改**既有 ``ROLE_SLOTS``（drafting/review/extraction，供「设置→AI模型」分工 UI）——
那是另一层抽象。这里是独立性判定专用的角色→代表节点映射。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import LlmCall
from novel_system.services.llm_node_registry import get_llm_node_spec

_LOGGER = logging.getLogger(__name__)


# §5.7 五槽 → 代表节点（node_id 见 config/models.yaml task_routing）。
# critic_independent 落 soft_qc——§8 独立 LLM 批判 auto_critique_llm 实际路由到此
# （llm_task_runner._AD_HOC_ROUTE_ALIASES）。
INDEPENDENCE_SLOTS: dict[str, dict[str, str]] = {
    "writer_primary": {
        "node_id": "style_draft",
        "label_zh": "主力写作",
        "description_zh": "关键场景正文风格化生成",
    },
    "writer_explorer": {
        "node_id": "neutral_draft",
        "label_zh": "探索写作",
        "description_zh": "中性初稿 / Best-of-N 多样性来源",
    },
    "critic_independent": {
        "node_id": "soft_qc",
        "label_zh": "独立批评",
        "description_zh": "独立 LLM 编辑批判（须与主力写作异源）",
    },
    "judge_advisory": {
        "node_id": "near_final_acceptance_review",
        "label_zh": "咨询裁判",
        "description_zh": "近终稿验收裁决（只提案不硬阻断）",
    },
    "extractor_fast": {
        "node_id": "style_profile_extract",
        "label_zh": "快速提炼",
        "description_zh": "画像 / 资料抽取（低成本模型）",
    },
}

# observed 口径：从已记录 LlmCall 判定 writer vs **咨询评审** 实际是否同模型。
# 刻意不含 hard_qc——§5.7「确定性规则和来源安全是唯一可以不依赖异源模型的硬门」：
# 硬事实门本就不受独立性约束，把它计入会误报 correlated_judge。
_OBSERVED_WRITER_NODES = frozenset(
    {"style_draft", "neutral_draft", "long_form_continuation", "de_template"}
)
_OBSERVED_REVIEW_NODES = frozenset(
    {
        "soft_qc",
        "near_final_acceptance_review",
        "chapter_near_final_review",
        "writer_deep_review",
        "auto_critique_llm",
        "chapter_audit_adjudicate",
        "literary_eval_live",
    }
)


def _node_route(session: Session, node_id: str) -> dict[str, Any]:
    """解析节点当前路由到的 (provider, model)；失败降级到注册表默认，绝不抛。"""
    try:
        from novel_system.services.llm_task_runner import LLMNodeRunner

        cfg = LLMNodeRunner(session).task_config(node_id)
        provider = getattr(cfg, "provider", None)
        model = getattr(cfg, "model", None)
        if model:
            return {"provider": provider, "model": model, "degraded": False}
    except Exception:
        _LOGGER.debug("task_config failed for %s; falling back to registry", node_id, exc_info=True)
    spec = get_llm_node_spec(node_id)
    if spec is not None:
        return {"provider": spec.provider, "model": spec.model, "degraded": True}
    return {"provider": None, "model": None, "degraded": True}


def resolve_slot(session: Session, slot_id: str) -> dict[str, Any]:
    meta = INDEPENDENCE_SLOTS.get(slot_id)
    if meta is None:
        raise KeyError(slot_id)
    route = _node_route(session, meta["node_id"])
    return {
        "slot_id": slot_id,
        "node_id": meta["node_id"],
        "label_zh": meta["label_zh"],
        "provider": route["provider"],
        "model": route["model"],
        "degraded": route["degraded"],
    }


def _same_source(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        a.get("model") is not None
        and a.get("model") == b.get("model")
        and a.get("provider") == b.get("provider")
    )


def judge_independence(session: Session) -> dict[str, Any]:
    """config 口径：按当前路由判定 critic 与 writer 是否同源（§5.7）。"""
    writer = resolve_slot(session, "writer_primary")
    critic = resolve_slot(session, "critic_independent")
    judge = resolve_slot(session, "judge_advisory")
    correlated = _same_source(writer, critic)
    reason = (
        f"critic({critic['model']}) 与 writer({writer['model']}) 同源——咨询意见降权"
        if correlated
        else f"critic({critic['model']}) 与 writer({writer['model']}) 异源——独立"
    )
    return {
        "correlated_judge": correlated,
        "independent": not correlated,
        "writer": writer,
        "critic": critic,
        "judge": judge,
        "weight_hint": "downweight" if correlated else "full",
        "reason": reason,
        "basis": "config_routing",
    }


def observed_correlated_judge(session: Session, scene_id: str) -> dict[str, Any] | None:
    """observed 口径：从该场景已记录 LlmCall 判定 writer 与评审是否实际同模型。

    无 writer 调用或无评审调用 → 返回 None（无法观测）。
    """
    if not scene_id:
        return None
    rows = list(
        session.execute(select(LlmCall).where(LlmCall.scene_id == scene_id)).scalars().all()
    )
    writer_models = {
        (r.provider, r.model) for r in rows if r.node_id in _OBSERVED_WRITER_NODES and r.model
    }
    review_models = {
        (r.provider, r.model) for r in rows if r.node_id in _OBSERVED_REVIEW_NODES and r.model
    }
    if not writer_models or not review_models:
        return None
    correlated = bool(writer_models & review_models)
    return {
        "correlated_judge": correlated,
        "independent": not correlated,
        "writer_models": sorted(f"{p or '?'}/{m}" for p, m in writer_models),
        "review_models": sorted(f"{p or '?'}/{m}" for p, m in review_models),
        "basis": "observed_calls",
    }
