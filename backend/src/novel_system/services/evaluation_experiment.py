"""Wave 5 — 质量实验通道服务：匿名 A/B 人类盲评的持久化编排（结果闭环治理 §6.2/§9.4）。

在 ``best_of_n_blind_eval`` 纯函数核心（盲化 + 精确二项 + 平局 + 最小胜场阈值 +
默认策略判据）之上，加数据库持久化与 §6.2 有效性约束：

- 每个 ``scene_snapshot_hash`` 至多一个有效对比对（防伪重复，破坏检验独立性）。
- ``next_pair`` 只出 ``pair_id`` + 左右纯文本；映射/策略/token/快照哈希一律不下发
  （盲化威胁模型：防无意识偏倚，非防蓄意作弊——本地读库可破盲，按此设定即可）。
- 投票后方可 reveal；报告折叠隐藏键 → treatment/control/tie，产出可复算结论。
- 实验通道**不写 FinalScene**，只写三张实验表（§5.1）；实验失败不影响生产状态。

不自动翻转任何生产默认（§11 规则 7）：报告只输出 keep/upgrade/downgrade/disable 建议；
翻默认需真实人评，另行执行。消融序列升级默认前须第二批 30 组非平局对复验（§8 项 8）。
"""
from __future__ import annotations

import hashlib
import json
import random
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    EvaluationExperiment,
    EvaluationPair,
    EvaluationVote,
    utcnow,
)
from novel_system.services.best_of_n_blind_eval import (
    BlindEvalResult,
    default_strategy_decision,
)
from novel_system.services.errors import DomainError

_VALID_CHOICES = ("left", "right", "tie")
_VALID_PROVENANCE = ("synthetic", "human")
_VALID_ISOLATION_MODES = ("seed_project", "time_isolated")


class EvaluationExperimentService:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # 建实验 / 加对
    # ------------------------------------------------------------------

    def create_experiment(
        self,
        *,
        name: str,
        hypothesis: str = "",
        treatment_policy: dict[str, Any] | None = None,
        control_policy: dict[str, Any] | None = None,
        isolation_mode: str | None = None,
        snapshot_source_ref: str | None = None,
        evidence_provenance: str = "synthetic",
        experiment_id: str | None = None,
    ) -> EvaluationExperiment:
        evidence_provenance = str(evidence_provenance or "synthetic").strip().lower()
        if evidence_provenance not in _VALID_PROVENANCE:
            raise DomainError(
                "INVALID_EVIDENCE_PROVENANCE",
                f"evidence_provenance must be one of {_VALID_PROVENANCE}",
                status_code=422,
            )
        exp = EvaluationExperiment(
            experiment_id=experiment_id or f"exp_{uuid.uuid4().hex[:16]}",
            name=name,
            hypothesis=hypothesis or "",
            treatment_policy_json=treatment_policy or {},
            control_policy_json=control_policy or {},
            isolation_mode=isolation_mode,
            snapshot_source_ref=snapshot_source_ref,
            evidence_provenance=evidence_provenance,
            status="collecting",
        )
        self.session.add(exp)
        self.session.flush()
        return exp

    def add_pair(
        self,
        experiment_id: str,
        *,
        scene_snapshot_hash: str,
        treatment_text: str,
        control_text: str,
        treatment_ref: str | None = None,
        control_ref: str | None = None,
        token_cost: dict[str, Any] | None = None,
        seed: int | None = None,
        pair_id: str | None = None,
    ) -> EvaluationPair:
        experiment = self.session.get(EvaluationExperiment, experiment_id)
        if experiment is None:
            raise DomainError("EXPERIMENT_NOT_FOUND", f"experiment {experiment_id} not found", status_code=404)
        if experiment.status != "collecting":
            raise DomainError(
                "EXPERIMENT_FROZEN",
                "frozen evaluation experiments cannot accept new pairs",
                status_code=409,
            )
        # §6.2：每快照至多一对，防伪重复。
        existing = self.session.execute(
            select(EvaluationPair.pair_id).where(
                EvaluationPair.experiment_id == experiment_id,
                EvaluationPair.scene_snapshot_hash == scene_snapshot_hash,
            )
        ).first()
        if existing is not None:
            raise DomainError(
                "SNAPSHOT_ALREADY_USED",
                f"snapshot {scene_snapshot_hash} already has a pair in this experiment",
                status_code=409,
            )

        rng = random.Random(seed) if seed is not None else random.Random()
        treatment_is_left = rng.random() < 0.5
        if treatment_is_left:
            left_text, right_text, slot = treatment_text, control_text, "left"
            left_ref, right_ref = treatment_ref, control_ref
        else:
            left_text, right_text, slot = control_text, treatment_text, "right"
            left_ref, right_ref = control_ref, treatment_ref

        pair = EvaluationPair(
            pair_id=pair_id or f"pair_{uuid.uuid4().hex[:16]}",
            experiment_id=experiment_id,
            scene_snapshot_hash=scene_snapshot_hash,
            left_artifact_ref=left_ref,
            right_artifact_ref=right_ref,
            left_text=left_text,
            right_text=right_text,
            blind_mapping_json={"treatment_slot": slot},
            token_cost_json=token_cost or {},
            no_contrast=1 if treatment_text == control_text else 0,
        )
        self.session.add(pair)
        self.session.flush()
        return pair

    def freeze_experiment(self, experiment_id: str) -> EvaluationExperiment:
        """冻结盲评题包并封存完整性哈希；冻结后禁止再增删对比对。"""
        experiment = self.session.get(EvaluationExperiment, experiment_id)
        if experiment is None:
            raise DomainError("EXPERIMENT_NOT_FOUND", f"experiment {experiment_id} not found", status_code=404)
        pairs = self._experiment_pairs(experiment_id)
        if experiment.status == "frozen":
            current_hash = self._pair_manifest_hash(pairs)
            if current_hash != experiment.frozen_pair_manifest_hash:
                raise DomainError(
                    "EXPERIMENT_MANIFEST_TAMPERED",
                    "the frozen evaluation pair manifest no longer matches",
                    status_code=409,
                )
            return experiment
        if experiment.status != "collecting":
            raise DomainError("EXPERIMENT_NOT_COLLECTING", "experiment cannot be frozen from its current status", 409)
        contrast_count = sum(1 for pair in pairs if not pair.no_contrast)
        if contrast_count < 30:
            raise DomainError(
                "EVALUATION_POOL_TOO_SMALL",
                "at least 30 contrastive pairs from distinct snapshots are required before freezing",
                status_code=422,
                details={"total_pairs": len(pairs), "contrastive_pairs": contrast_count, "required": 30},
            )
        if experiment.evidence_provenance == "human":
            if experiment.isolation_mode not in _VALID_ISOLATION_MODES or not str(
                experiment.snapshot_source_ref or ""
            ).strip():
                raise DomainError(
                    "HUMAN_EVIDENCE_ISOLATION_REQUIRED",
                    "human evidence requires seed_project/time_isolated and a snapshot_source_ref",
                    status_code=422,
                )
        experiment.frozen_pair_manifest_hash = self._pair_manifest_hash(pairs)
        experiment.frozen_at = utcnow()
        experiment.status = "frozen"
        self.session.flush()
        return experiment

    # ------------------------------------------------------------------
    # 盲化取对 / 投票
    # ------------------------------------------------------------------

    def next_pair(self, experiment_id: str, *, reviewer_ref: str | None = None) -> dict[str, str] | None:
        """返回下一个（该 reviewer）未投票的对——**只出 pair_id + 左右纯文本**，无任何元数据。"""
        experiment = self.session.get(EvaluationExperiment, experiment_id)
        if experiment is None:
            raise DomainError("EXPERIMENT_NOT_FOUND", f"experiment {experiment_id} not found", status_code=404)
        if experiment.evidence_provenance == "human" and experiment.status != "frozen":
            raise DomainError(
                "HUMAN_EVIDENCE_NOT_FROZEN",
                "human evaluation pairs are available only after the pool is frozen",
                status_code=409,
            )
        voted_pair_ids = set(
            self.session.execute(
                select(EvaluationVote.pair_id)
            ).scalars().all()
        )
        pairs = self.session.execute(
            select(EvaluationPair)
            .where(EvaluationPair.experiment_id == experiment_id)
            .order_by(EvaluationPair.created_at.asc(), EvaluationPair.pair_id.asc())
        ).scalars().all()
        for pair in pairs:
            if pair.pair_id in voted_pair_ids:
                continue
            return {
                "pair_id": pair.pair_id,
                "left_text": pair.left_text,
                "right_text": pair.right_text,
            }
        return None

    def record_vote(
        self,
        pair_id: str,
        *,
        choice: str,
        reviewer_ref: str | None = None,
        duration_ms: int | None = None,
        vote_id: str | None = None,
    ) -> EvaluationVote:
        choice = str(choice or "").strip().lower()
        if choice not in _VALID_CHOICES:
            raise DomainError(
                "INVALID_VOTE_CHOICE", f"choice must be one of {_VALID_CHOICES}", status_code=422,
            )
        pair = self.session.get(EvaluationPair, pair_id)
        if pair is None:
            raise DomainError("PAIR_NOT_FOUND", f"pair {pair_id} not found", status_code=404)
        experiment = self.session.get(EvaluationExperiment, pair.experiment_id)
        if experiment is None:
            raise DomainError("EXPERIMENT_NOT_FOUND", "the pair's experiment was not found", status_code=404)
        reviewer_ref = str(reviewer_ref or "").strip() or None
        if experiment.evidence_provenance == "human":
            if experiment.status != "frozen":
                raise DomainError(
                    "HUMAN_EVIDENCE_NOT_FROZEN",
                    "human votes are accepted only after the evaluation pool is frozen",
                    status_code=409,
                )
            if reviewer_ref is None:
                raise DomainError(
                    "HUMAN_REVIEWER_REQUIRED",
                    "human evidence votes require a non-empty reviewer_ref",
                    status_code=422,
                )

        existing = self.session.execute(
            select(EvaluationVote).where(EvaluationVote.pair_id == pair_id)
        ).scalars().first()
        if existing is not None:
            if existing.choice == choice and existing.reviewer_ref == reviewer_ref:
                return existing  # 幂等：同选择重复提交返回同一票，不双计
            raise DomainError(
                "VOTE_ALREADY_RECORDED",
                "this pair already has its single blind-evaluation outcome vote",
                status_code=409,
            )

        vote = EvaluationVote(
            vote_id=vote_id or f"vote_{uuid.uuid4().hex[:16]}",
            pair_id=pair_id,
            choice=choice,
            reviewer_ref=reviewer_ref,
            duration_ms=duration_ms,
        )
        self.session.add(vote)
        self.session.flush()
        return vote

    # ------------------------------------------------------------------
    # 可复算报告
    # ------------------------------------------------------------------

    def build_report(self, experiment_id: str) -> dict[str, Any]:
        exp = self.session.get(EvaluationExperiment, experiment_id)
        if exp is None:
            raise DomainError("EXPERIMENT_NOT_FOUND", f"experiment {experiment_id} not found", status_code=404)

        pairs = self._experiment_pairs(experiment_id)

        result = BlindEvalResult()
        token_treatment = 0.0
        token_control = 0.0
        durations: list[int] = []
        snapshot_hashes: set[str] = set()
        anonymous_vote_count = 0

        for pair in pairs:
            snapshot_hashes.add(pair.scene_snapshot_hash)
            cost = pair.token_cost_json or {}
            token_treatment += float(cost.get("treatment") or 0)
            token_control += float(cost.get("control") or 0)
            if pair.no_contrast:
                result.no_contrast += 1
                continue
            vote = self._pair_outcome_vote(pair.pair_id)
            if vote is None:
                result.unvoted += 1
                continue
            if not str(vote.reviewer_ref or "").strip():
                anonymous_vote_count += 1
            if vote.duration_ms is not None:
                durations.append(vote.duration_ms)
            if vote.choice == "tie":
                result.ties += 1
                continue
            treatment_slot = (pair.blind_mapping_json or {}).get("treatment_slot")
            if vote.choice == treatment_slot:
                result.treatment_wins += 1
            else:
                result.control_wins += 1

        is_ablation = bool((exp.treatment_policy_json or {}).get("ablation") or (exp.control_policy_json or {}).get("ablation"))
        decision = default_strategy_decision(result, is_ablation=is_ablation)

        total_pairs = len(pairs)
        decisive = result.decisive
        token_multiplier = (token_treatment / token_control) if token_control else None
        pseudo_replication_ok = len(snapshot_hashes) == total_pairs
        manifest_verified = bool(
            exp.status == "frozen"
            and exp.frozen_pair_manifest_hash
            and exp.frozen_pair_manifest_hash == self._pair_manifest_hash(pairs)
        )
        eligibility_reasons: list[str] = []
        if exp.evidence_provenance != "human":
            eligibility_reasons.append("evidence_provenance_not_human")
        if not manifest_verified:
            eligibility_reasons.append("frozen_manifest_not_verified")
        if exp.isolation_mode not in _VALID_ISOLATION_MODES or not str(exp.snapshot_source_ref or "").strip():
            eligibility_reasons.append("evaluation_isolation_not_verified")
        if not pseudo_replication_ok:
            eligibility_reasons.append("snapshot_pseudo_replication_detected")
        if decisive < 30:
            eligibility_reasons.append("fewer_than_30_non_tie_votes")
        if anonymous_vote_count:
            eligibility_reasons.append("anonymous_vote_provenance_present")
        policy_evidence_eligible = not eligibility_reasons
        if not policy_evidence_eligible:
            policy_decision = "not_eligible_for_policy"
            policy_rationale = "统计结果仅供诊断，不能调整生产默认：" + ", ".join(eligibility_reasons)
        elif decision.decision == "upgrade_to_default" and decision.requires_fresh_replication:
            policy_decision = "replication_required"
            policy_rationale = "统计门已通过，但消融实验在升级默认前必须用新一批 30 组非平局真人票复验。"
        else:
            policy_decision = decision.decision
            policy_rationale = decision.rationale

        return {
            "experiment_id": exp.experiment_id,
            "name": exp.name,
            "hypothesis": exp.hypothesis,
            "status": exp.status,
            "evidence_provenance": exp.evidence_provenance,
            "frozen_at": exp.frozen_at,
            "frozen_pair_manifest_hash": exp.frozen_pair_manifest_hash,
            "frozen_manifest_verified": manifest_verified,
            "isolation": {"mode": exp.isolation_mode, "source_ref": exp.snapshot_source_ref},
            "total_pairs": total_pairs,
            "distinct_snapshot_count": len(snapshot_hashes),
            # §6.2 伪重复守卫：30 组必须来自 30 个互异快照。
            "pseudo_replication_ok": pseudo_replication_ok,
            "treatment_wins": result.treatment_wins,
            "control_wins": result.control_wins,
            "ties": result.ties,
            "no_contrast": result.no_contrast,
            "unvoted": result.unvoted,
            "non_tie_n": decisive,
            "preference_rate": decision.preference_rate,
            "tie_rate": round(result.ties / total_pairs, 4) if total_pairs else 0.0,
            "no_contrast_rate": round(result.no_contrast / total_pairs, 4) if total_pairs else 0.0,
            "p_value": decision.p_value,
            "min_wins_threshold": decision.min_wins,
            "significant": decision.significant,
            "statistical_decision": decision.decision,
            "policy_evidence_eligible": policy_evidence_eligible,
            "policy_eligibility_reasons": eligibility_reasons,
            "decision": policy_decision,
            "module_conclusion": _module_conclusion(policy_decision),
            "requires_fresh_replication": decision.requires_fresh_replication,
            "statistical_rationale": decision.rationale,
            "rationale": policy_rationale,
            "recommended_production_policy": {
                "best_of_n_default_enabled": policy_decision == "upgrade_to_default",
                "actionable": policy_decision in {"upgrade_to_default", "keep_optional", "disable"},
            },
            "token_cost": {
                "treatment_total": token_treatment,
                "control_total": token_control,
                "token_multiplier": round(token_multiplier, 4) if token_multiplier is not None else None,
            },
            "vote_duration": {
                "count": len(durations),
                "avg_ms": round(sum(durations) / len(durations), 1) if durations else None,
            },
        }

    def _pair_outcome_vote(self, pair_id: str) -> EvaluationVote | None:
        """单用户盲评：每对取最早一票为该对结论，保持二项检验独立性（一对一结果）。"""
        return self.session.execute(
            select(EvaluationVote)
            .where(EvaluationVote.pair_id == pair_id)
            .order_by(EvaluationVote.created_at.asc(), EvaluationVote.vote_id.asc())
        ).scalars().first()

    def _experiment_pairs(self, experiment_id: str) -> list[EvaluationPair]:
        return self.session.execute(
            select(EvaluationPair)
            .where(EvaluationPair.experiment_id == experiment_id)
            .order_by(EvaluationPair.created_at.asc(), EvaluationPair.pair_id.asc())
        ).scalars().all()

    @staticmethod
    def _pair_manifest_hash(pairs: list[EvaluationPair]) -> str:
        payload = [
            {
                "pair_id": pair.pair_id,
                "scene_snapshot_hash": pair.scene_snapshot_hash,
                "left_text_sha256": hashlib.sha256((pair.left_text or "").encode("utf-8")).hexdigest(),
                "right_text_sha256": hashlib.sha256((pair.right_text or "").encode("utf-8")).hexdigest(),
                "blind_mapping": pair.blind_mapping_json or {},
                "no_contrast": int(pair.no_contrast or 0),
            }
            for pair in pairs
        ]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _module_conclusion(decision: str) -> str:
    return {
        "upgrade_to_default": "keep",     # 值得——保留并可升级默认（需复验）
        "keep_optional": "downgrade",     # 未证增益——降级为可选（§8 项 7）
        "disable": "disable",             # 显著更差——关闭
        "need_more_samples": "pending",
        "not_eligible_for_policy": "pending",
        "replication_required": "pending",
    }.get(decision, "pending")
