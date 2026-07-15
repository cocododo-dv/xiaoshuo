"""Wave 5 — 质量实验盲评报告的可复算 CLI（结果闭环治理 §6.2/§9.4）。

完成门「产出可复算的 30 组投票报告」的复算入口。两种模式：

- ``--db EXPERIMENT_ID``：从数据库读实验，调 ``EvaluationExperimentService.build_report``
  （生产路径同源，确定性）。
- ``--from-json plan_votes.json``：纯离线复算——输入冻结对 + 投票，不碰数据库：

      {"pairs": [
          {"blind_mapping": {"treatment_slot": "left"}, "no_contrast": false,
           "vote": "left", "scene_snapshot_hash": "snap_000",
           "token_cost": {"treatment": 5000, "control": 1000}},
          ...
      ]}

  同输入必得同报告，可脱离运行时复算、进版本库归档。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from novel_system.services.best_of_n_blind_eval import (
    BlindEvalResult,
    default_strategy_decision,
)


def report_from_pairs(
    pairs: list[dict[str, Any]],
    *,
    is_ablation: bool = True,
    evidence_provenance: str = "synthetic",
    frozen_manifest_verified: bool = False,
    isolation_verified: bool = False,
) -> dict[str, Any]:
    """纯函数：从冻结对+投票折叠出可复算报告（不碰 DB）。"""
    result = BlindEvalResult()
    token_treatment = token_control = 0.0
    snapshot_hashes: set[str] = set()
    durations: list[int] = []
    anonymous_vote_count = 0
    for pair in pairs:
        h = pair.get("scene_snapshot_hash")
        if h is not None:
            snapshot_hashes.add(str(h))
        cost = pair.get("token_cost") or {}
        token_treatment += float(cost.get("treatment") or 0)
        token_control += float(cost.get("control") or 0)
        if pair.get("no_contrast"):
            result.no_contrast += 1
            continue
        vote = pair.get("vote")
        if vote is None:
            result.unvoted += 1
            continue
        dur = pair.get("duration_ms")
        if not str(pair.get("reviewer_ref") or "").strip():
            anonymous_vote_count += 1
        if isinstance(dur, int):
            durations.append(dur)
        vote = str(vote).strip().lower()
        if vote == "tie":
            result.ties += 1
            continue
        slot = (pair.get("blind_mapping") or {}).get("treatment_slot")
        if vote == slot:
            result.treatment_wins += 1
        elif vote in ("left", "right"):
            result.control_wins += 1
        else:
            result.invalid += 1

    decision = default_strategy_decision(result, is_ablation=is_ablation)
    total = len(pairs)
    token_multiplier = (token_treatment / token_control) if token_control else None
    pseudo_replication_ok = (len(snapshot_hashes) == total) if snapshot_hashes else False
    eligibility_reasons: list[str] = []
    if evidence_provenance != "human":
        eligibility_reasons.append("evidence_provenance_not_human")
    if not frozen_manifest_verified:
        eligibility_reasons.append("frozen_manifest_not_verified")
    if not isolation_verified:
        eligibility_reasons.append("evaluation_isolation_not_verified")
    if not pseudo_replication_ok:
        eligibility_reasons.append("snapshot_pseudo_replication_detected")
    if decision.non_tie_n < 30:
        eligibility_reasons.append("fewer_than_30_non_tie_votes")
    if anonymous_vote_count:
        eligibility_reasons.append("anonymous_vote_provenance_present")
    policy_evidence_eligible = not eligibility_reasons
    if not policy_evidence_eligible:
        policy_decision = "not_eligible_for_policy"
    elif decision.decision == "upgrade_to_default" and decision.requires_fresh_replication:
        policy_decision = "replication_required"
    else:
        policy_decision = decision.decision
    return {
        "total_pairs": total,
        "distinct_snapshot_count": len(snapshot_hashes),
        "pseudo_replication_ok": pseudo_replication_ok,
        "treatment_wins": result.treatment_wins,
        "control_wins": result.control_wins,
        "ties": result.ties,
        "no_contrast": result.no_contrast,
        "unvoted": result.unvoted,
        "non_tie_n": decision.non_tie_n,
        "preference_rate": decision.preference_rate,
        "p_value": decision.p_value,
        "min_wins_threshold": decision.min_wins,
        "significant": decision.significant,
        "statistical_decision": decision.decision,
        "evidence_provenance": evidence_provenance,
        "frozen_manifest_verified": frozen_manifest_verified,
        "isolation_verified": isolation_verified,
        "policy_evidence_eligible": policy_evidence_eligible,
        "policy_eligibility_reasons": eligibility_reasons,
        "decision": policy_decision,
        "requires_fresh_replication": decision.requires_fresh_replication,
        "statistical_rationale": decision.rationale,
        "rationale": (
            decision.rationale
            if policy_evidence_eligible
            else "统计结果仅供诊断，不能调整生产默认：" + ", ".join(eligibility_reasons)
        ),
        "token_multiplier": round(token_multiplier, 4) if token_multiplier is not None else None,
        "avg_vote_duration_ms": round(sum(durations) / len(durations), 1) if durations else None,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        "=" * 66,
        "  质量实验盲评报告（§6.2 / §9.4，可复算）",
        "=" * 66,
        f"  对比对        : {report['total_pairs']}  "
        f"(非平局 {report['non_tie_n']}, 平局 {report['ties']}, 无对比 {report['no_contrast']}, 未投 {report['unvoted']})",
        f"  互异快照      : {report['distinct_snapshot_count']}  "
        f"(伪重复守卫: {'OK' if report.get('pseudo_replication_ok') else '⚠ 非 1:1'})",
        f"  treatment 偏好: {report['treatment_wins']} / {report['non_tie_n']}  "
        f"= {report['preference_rate']:.0%}",
        f"  双侧精确二项 p: {report['p_value']:.4f}   最小胜场阈值: {report['min_wins_threshold']}   "
        f"显著: {report['significant']}",
        f"  token 倍率    : {report['token_multiplier']}   平均投票耗时: {report.get('avg_vote_duration_ms')} ms",
        "-" * 66,
        f"  决定: {report['decision'].upper()}"
        + ("   （消融序列升级默认前须第二批 30 组非平局对复验）" if report.get("requires_fresh_replication") else ""),
        f"  {report['rationale']}",
        "=" * 66,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="质量实验盲评报告可复算 CLI")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--db", metavar="EXPERIMENT_ID", help="从数据库读实验并复算报告")
    src.add_argument("--from-json", metavar="PATH", help="从 pairs+votes JSON 纯离线复算")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非文本报告")
    args = parser.parse_args(argv)

    if args.from_json:
        with open(args.from_json, encoding="utf-8") as fh:
            payload = json.load(fh)
        evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
        report = report_from_pairs(
            payload.get("pairs") or [],
            evidence_provenance=str(evidence.get("provenance") or "synthetic"),
            frozen_manifest_verified=evidence.get("frozen_manifest_verified") is True,
            isolation_verified=evidence.get("isolation_verified") is True,
            is_ablation=evidence.get("is_ablation", True) is True,
        )
    else:
        from novel_system.db.session import SessionLocal
        from novel_system.services.evaluation_experiment import EvaluationExperimentService

        session = SessionLocal()
        try:
            report = EvaluationExperimentService(session).build_report(args.db)
        finally:
            session.close()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_report(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
