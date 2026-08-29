"""LLM 角色槽独立性（结果闭环治理设计 §5.7，Wave 6）。

§5.7 至少区分五个角色槽：writer_primary / writer_explorer / critic_independent /
judge_advisory / extractor_fast，并单列章级 ``chapter_judge_advisory``。生产审计要求
critic、场景近终稿裁判、章级裁判分别与 writer_primary 比较；任一同源即标记
``correlated_judge=true`` 并降权提示，路由不可判定则明确报告 unknown。

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


# §5.7 核心槽 + 章级裁判 → 代表节点（node_id 见 config/models.yaml task_routing）。
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
    "chapter_judge_advisory": {
        "node_id": "chapter_near_final_review",
        "label_zh": "章级咨询裁判",
        "description_zh": "章级近终稿验收裁判（只提案不硬阻断）",
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
    {
        "style_draft",
        "style_patch",
        "scene_literary_rewrite",
        "neutral_draft",
        "de_template",
    }
)
_OBSERVED_REVIEW_NODES = frozenset(
    {
        "soft_qc",
        "near_final_acceptance_review",
        "chapter_near_final_review",
        "writer_deep_review",
        "auto_critique_llm",
        "literary_eval_live",
    }
)

_OBSERVED_REVIEW_ROLE_NODES: dict[str, frozenset[str]] = {
    "critic_independent": frozenset(
        {"soft_qc", "writer_deep_review", "auto_critique_llm", "literary_eval_live"}
    ),
    "judge_advisory": frozenset({"near_final_acceptance_review"}),
    "chapter_judge_advisory": frozenset({"chapter_near_final_review"}),
}


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


def _comparison(writer: dict[str, Any], reviewer: dict[str, Any]) -> dict[str, Any]:
    writer_source = (writer.get("provider"), writer.get("model"))
    reviewer_source = (reviewer.get("provider"), reviewer.get("model"))
    if not writer.get("model") or not reviewer.get("model"):
        return {
            "status": "unknown",
            "correlated": None,
            "independent": False,
            "writer_source": writer_source,
            "reviewer_source": reviewer_source,
            "reason": "writer or reviewer route is unavailable",
        }
    correlated = _same_source(writer, reviewer)
    return {
        "status": "correlated" if correlated else "independent",
        "correlated": correlated,
        "independent": not correlated,
        "writer_source": writer_source,
        "reviewer_source": reviewer_source,
        "reason": "same provider/model" if correlated else "provider or model differs",
    }


def judge_independence(session: Session) -> dict[str, Any]:
    """按配置分别报告 critic、场景裁判与章级裁判的独立性。"""
    writer = resolve_slot(session, "writer_primary")
    critic = resolve_slot(session, "critic_independent")
    judge = resolve_slot(session, "judge_advisory")
    chapter_judge = resolve_slot(session, "chapter_judge_advisory")
    comparisons = {
        "critic_independent": _comparison(writer, critic),
        "judge_advisory": _comparison(writer, judge),
        "chapter_judge_advisory": _comparison(writer, chapter_judge),
    }
    correlated_roles = sorted(
        role for role, result in comparisons.items() if result["correlated"] is True
    )
    unknown_roles = sorted(
        role for role, result in comparisons.items() if result["status"] == "unknown"
    )
    status = "correlated" if correlated_roles else "unknown" if unknown_roles else "independent"
    reason = (
        f"咨询角色与 writer 同源：{', '.join(correlated_roles)}"
        if correlated_roles
        else f"咨询角色路由不可判定：{', '.join(unknown_roles)}"
        if unknown_roles
        else "critic、场景近终稿裁判和章级裁判均与 writer 异源"
    )
    return {
        "correlated_judge": bool(correlated_roles),
        "independent": status == "independent",
        "independence_status": status,
        "writer": writer,
        "critic": critic,
        "judge": judge,
        "chapter_judge": chapter_judge,
        "comparisons": comparisons,
        "correlated_roles": correlated_roles,
        "unknown_roles": unknown_roles,
        "weight_hint": (
            "downweight" if correlated_roles else "unavailable" if unknown_roles else "full"
        ),
        "reason": reason,
        "basis": "config_routing",
    }


def observed_correlated_judge(
    session: Session,
    scene_id: str | None,
    *,
    chapter_id: str | None = None,
) -> dict[str, Any] | None:
    """Observed independence evidence for one scene or one whole chapter.

    无 writer 调用或无评审调用 → 返回 None（无法观测）。
    """
    if not scene_id and not chapter_id:
        return None
    scope_type = "scene" if scene_id else "chapter"
    scope_id = scene_id or chapter_id
    scope_filter = (
        LlmCall.scene_id == scene_id
        if scene_id
        else LlmCall.chapter_id == chapter_id
    )
    rows = list(
        session.execute(select(LlmCall).where(scope_filter)).scalars().all()
    )
    writer_models = {
        (r.provider, r.model) for r in rows if r.node_id in _OBSERVED_WRITER_NODES and r.model
    }
    writer_node_ids = sorted(
        {r.node_id for r in rows if r.node_id in _OBSERVED_WRITER_NODES and r.model}
    )
    writer_sources_by_node = {
        node_id: sorted(
            {
                f"{row.provider or '?'}/{row.model}"
                for row in rows
                if row.node_id == node_id and row.model
            }
        )
        for node_id in writer_node_ids
    }
    review_models = {
        (r.provider, r.model) for r in rows if r.node_id in _OBSERVED_REVIEW_NODES and r.model
    }
    if not writer_models or not review_models:
        return None
    role_evidence: dict[str, dict[str, Any]] = {}
    for role, node_ids in _OBSERVED_REVIEW_ROLE_NODES.items():
        observed_node_ids = sorted(
            {
                row.node_id
                for row in rows
                if row.node_id in node_ids and row.model
            }
        )
        role_models = {
            (row.provider, row.model)
            for row in rows
            if row.node_id in node_ids and row.model
        }
        if not role_models:
            continue
        overlap = writer_models & role_models
        role_evidence[role] = {
            "status": "correlated" if overlap else "independent",
            "correlated": bool(overlap),
            "review_models": sorted(f"{provider or '?'}/{model}" for provider, model in role_models),
            "shared_sources": sorted(f"{provider or '?'}/{model}" for provider, model in overlap),
            "node_ids": observed_node_ids,
        }
    correlated_roles = sorted(
        role for role, evidence in role_evidence.items() if evidence["correlated"]
    )
    missing_roles = sorted(set(_OBSERVED_REVIEW_ROLE_NODES) - set(role_evidence))
    correlated = bool(correlated_roles)
    return {
        "correlated_judge": correlated,
        "independent": not correlated and not missing_roles,
        "independence_status": "correlated" if correlated else (
            "independent_observed_partial" if missing_roles else "independent"
        ),
        "writer_models": sorted(f"{p or '?'}/{m}" for p, m in writer_models),
        "writer_node_ids": writer_node_ids,
        "writer_sources_by_node": writer_sources_by_node,
        "review_models": sorted(f"{p or '?'}/{m}" for p, m in review_models),
        "role_evidence": role_evidence,
        "correlated_roles": correlated_roles,
        "observed_roles": sorted(role_evidence),
        "missing_roles": missing_roles,
        "coverage_complete": not missing_roles,
        "weight_hint": (
            "downweight" if correlated else "unavailable" if missing_roles else "full"
        ),
        "scope_type": scope_type,
        "scope_id": scope_id,
        "basis": "observed_calls",
    }
