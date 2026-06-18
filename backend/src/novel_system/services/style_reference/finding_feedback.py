"""立项 B — finding 用户反馈(👍/👎)聚合 → confidence 持续校准。

设计:docs/style-reference-phase3-backlog.md「立项 B」。
- 一人(operator_ref)一票,改向投票即更新(repository.upsert_finding_feedback 保证)。
- 聚合 net = #up − #down(去重用户)。
- 以 finding **合成基线** base_confidence 为基准,按 config/style_reference/feedback.yaml
  的 promote_net / demote_net 阈值 ±1 档(low/medium/high),写回 finding.confidence。
  base_confidence 在首次反馈时由当时 confidence 回填(此前 confidence 即合成基线),
  保留不变 → net 回到阈值内时 confidence 可逆回基线;profile 重合成产生新 finding(新基线)。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from novel_system.services.errors import DomainError
from novel_system.services.style_reference.config_loader import load_yaml_config
from novel_system.services.style_reference.repository import StyleReferenceRepository

logger = logging.getLogger(__name__)

# 置信度档位由低到高(索引即档位等级)
_LEVELS = ("low", "medium", "high")
_DEFAULT_THRESHOLDS = {"promote_net": 2, "demote_net": -2}
_VALID_VOTES = {"up", "down"}


def _load_thresholds() -> dict[str, int]:
    try:
        raw = load_yaml_config("feedback")
    except FileNotFoundError:
        return dict(_DEFAULT_THRESHOLDS)
    merged = dict(_DEFAULT_THRESHOLDS)
    if isinstance(raw, dict):
        for key in _DEFAULT_THRESHOLDS:
            if key in raw:
                merged[key] = int(raw[key])
    # 健壮性:promote_net 必须 > demote_net,否则 shift 的 if/elif 退化为静默 no-op
    # (配置笔误难察觉)。检测到非法配置 → 告警并回退安全默认,不阻断生成。
    if merged["promote_net"] <= merged["demote_net"]:
        logger.warning(
            "invalid feedback thresholds promote_net=%s <= demote_net=%s; using defaults %s",
            merged["promote_net"], merged["demote_net"], _DEFAULT_THRESHOLDS,
        )
        return dict(_DEFAULT_THRESHOLDS)
    return merged


def shift_confidence(base: str | None, net: int, *, promote_net: int, demote_net: int) -> str:
    """以 base 档为基准,net 达阈值则 ±1 档,clamp 到 [low, high]。纯函数,确定性。"""
    base_level = base if base in _LEVELS else "medium"
    idx = _LEVELS.index(base_level)
    if net >= promote_net:
        idx += 1
    elif net <= demote_net:
        idx -= 1
    idx = max(0, min(len(_LEVELS) - 1, idx))
    return _LEVELS[idx]


def apply_feedback(
    session: Session, finding_id: str, *, operator_ref: str, vote: str
) -> dict[str, Any]:
    """记录一票 → 聚合 → 在 base_confidence 基础上重算 finding.confidence。

    返回 {finding_id, vote, operator_ref, net, up, down, base_confidence, confidence}。
    finding 不存在 → DomainError 404。vote 非法 → DomainError 400。
    session flush 不 commit(由 route/调用方提交)。
    """
    if vote not in _VALID_VOTES:
        raise DomainError(
            "STYLE_REFERENCE_FEEDBACK_VOTE_INVALID",
            f"vote must be one of {sorted(_VALID_VOTES)}, got {vote!r}",
            status_code=400,
        )
    repo = StyleReferenceRepository(session)
    finding = repo.get_finding(finding_id)
    if finding is None:
        raise DomainError(
            "STYLE_REFERENCE_FINDING_NOT_FOUND",
            f"finding {finding_id!r} not found",
            status_code=404,
        )

    # 首次反馈:把当时(=合成)confidence 固化为 base,后续调档以此为基准且可逆。
    base = finding.base_confidence or finding.confidence

    repo.upsert_finding_feedback(finding_id, operator_ref, vote)
    agg = repo.aggregate_finding_feedback(finding_id)

    thresholds = _load_thresholds()
    new_confidence = shift_confidence(
        base, agg["net"],
        promote_net=thresholds["promote_net"], demote_net=thresholds["demote_net"],
    )
    repo.update_finding(finding_id, base_confidence=base, confidence=new_confidence)

    return {
        "finding_id": finding_id,
        "vote": vote,
        "operator_ref": operator_ref,
        "net": agg["net"],
        "up": agg["up"],
        "down": agg["down"],
        "base_confidence": base,
        "confidence": new_confidence,
    }
