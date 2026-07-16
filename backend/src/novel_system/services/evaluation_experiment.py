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
import math
import random
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    EvaluationExperiment,
    EvaluationPair,
    EvaluationVote,
    QualityBenchmarkManifest,
    QualityBenchmarkResult,
    QualityBenchmarkRun,
    utcnow,
)
from novel_system.services.best_of_n_blind_eval import (
    BlindEvalResult,
    default_strategy_decision,
)
from novel_system.services.errors import DomainError

_VALID_CHOICES = ("left", "right", "tie")
_VALID_PROVENANCE = ("synthetic", "human")
_VALID_ISOLATION_MODES = ("seed_project", "time_isolated", "external_holdout")
_AUTOMATED_REVIEWER_PREFIXES = ("model:", "llm:", "ai:", "bot:", "auto:", "synthetic:")


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
        benchmark_manifest_id: str | None = None,
        experiment_id: str | None = None,
    ) -> EvaluationExperiment:
        evidence_provenance = str(evidence_provenance or "synthetic").strip().lower()
        if evidence_provenance not in _VALID_PROVENANCE:
            raise DomainError(
                "INVALID_EVIDENCE_PROVENANCE",
                f"evidence_provenance must be one of {_VALID_PROVENANCE}",
                status_code=422,
            )
        benchmark_manifest = None
        if benchmark_manifest_id:
            benchmark_manifest = self.session.get(QualityBenchmarkManifest, benchmark_manifest_id)
            if benchmark_manifest is None or benchmark_manifest.status != "frozen":
                raise DomainError(
                    "HIDDEN_BENCHMARK_MANIFEST_NOT_FROZEN",
                    "evaluation experiment requires an existing frozen hidden manifest",
                    status_code=409,
                )
            if isolation_mode is None:
                isolation_mode = benchmark_manifest.isolation_mode
            elif isolation_mode != benchmark_manifest.isolation_mode:
                raise DomainError(
                    "HIDDEN_BENCHMARK_ISOLATION_MISMATCH",
                    "experiment isolation_mode must match the frozen hidden manifest",
                    status_code=409,
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
            benchmark_manifest_id=(benchmark_manifest.manifest_id if benchmark_manifest else None),
            benchmark_manifest_hash=(benchmark_manifest.manifest_hash if benchmark_manifest else None),
            hidden_rubric_hash=(benchmark_manifest.rubric_hash if benchmark_manifest else None),
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
        genre: str | None = None,
        scene_function: str | None = None,
        treatment_benchmark_result_id: str | None = None,
        control_benchmark_result_id: str | None = None,
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

        normalized_scene_function = str(scene_function or "").strip() or None
        if normalized_scene_function is not None:
            from novel_system.services.tension_curve import FUNCTION_TAGS

            if normalized_scene_function not in FUNCTION_TAGS:
                raise DomainError(
                    "EVALUATION_SCENE_FUNCTION_INVALID",
                    f"scene_function must be one of {FUNCTION_TAGS}",
                    status_code=422,
                )
        benchmark_binding = self._validate_benchmark_pair_binding(
            experiment,
            treatment_result_id=treatment_benchmark_result_id,
            control_result_id=control_benchmark_result_id,
            treatment_text=treatment_text,
            control_text=control_text,
            treatment_ref=treatment_ref,
            control_ref=control_ref,
            genre=str(genre or "").strip() or None,
            scene_function=normalized_scene_function,
        )
        if benchmark_binding is not None:
            treatment_result, control_result = benchmark_binding
            duplicate_case = self.session.execute(
                select(EvaluationPair.pair_id).where(
                    EvaluationPair.experiment_id == experiment_id,
                    EvaluationPair.benchmark_case_id_hash == treatment_result.case_id_hash,
                )
            ).first()
            if duplicate_case is not None:
                raise DomainError(
                    "BENCHMARK_CASE_ALREADY_USED",
                    "each hidden benchmark case may appear only once in an experiment",
                    409,
                )
            treatment_ref = treatment_result.artifact_ref
            control_ref = control_result.artifact_ref
            scene_snapshot_hash = treatment_result.generation_input_hash
            token_cost = {
                "treatment": treatment_result.cost_tokens,
                "control": control_result.cost_tokens,
                "source": "quality_benchmark_results",
            }
            normalized_scene_function = treatment_result.scene_function
            genre = treatment_result.genre
            if slot == "left":
                left_ref, right_ref = treatment_ref, control_ref
            else:
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
            genre=str(genre or "").strip() or None,
            scene_function=normalized_scene_function,
            treatment_benchmark_result_id=(
                benchmark_binding[0].result_id if benchmark_binding is not None else None
            ),
            control_benchmark_result_id=(
                benchmark_binding[1].result_id if benchmark_binding is not None else None
            ),
            benchmark_case_id_hash=(
                benchmark_binding[0].case_id_hash if benchmark_binding is not None else None
            ),
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
                    "human evidence requires seed_project/time_isolated/external_holdout and a snapshot_source_ref",
                    status_code=422,
                )
        if experiment.benchmark_manifest_id:
            binding_errors = self._benchmark_binding_errors(experiment, pairs)
            if binding_errors:
                raise DomainError(
                    "HIDDEN_BENCHMARK_PAIR_BINDING_INVALID",
                    "every frozen hidden case must have one valid treatment/control result pair",
                    409,
                    details={"reasons": binding_errors},
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
        if duration_ms is not None and (
            not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0
        ):
            raise DomainError(
                "INVALID_VOTE_DURATION",
                "duration_ms must be a nonnegative integer or null",
                status_code=422,
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
            if reviewer_ref is None or reviewer_ref.lower().startswith(_AUTOMATED_REVIEWER_PREFIXES):
                raise DomainError(
                    "HUMAN_REVIEWER_REQUIRED",
                    "human evidence votes require a non-automated reviewer_ref",
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
        token_treatment_observed_n = 0
        token_control_observed_n = 0
        durations: list[int] = []
        snapshot_hashes: set[str] = set()
        anonymous_vote_count = 0
        by_genre: dict[str, dict[str, int]] = {}
        by_strategy_cell: dict[tuple[str, str], dict[str, Any]] = {}

        for pair in pairs:
            snapshot_hashes.add(pair.scene_snapshot_hash)
            cost = pair.token_cost_json or {}
            treatment_cost = _nonnegative_number_or_none(cost.get("treatment"))
            control_cost = _nonnegative_number_or_none(cost.get("control"))
            if treatment_cost is not None:
                token_treatment += treatment_cost
                token_treatment_observed_n += 1
            if control_cost is not None:
                token_control += control_cost
                token_control_observed_n += 1
            cell_key = (pair.genre or "unlabeled", pair.scene_function or "unlabeled")
            cell = by_strategy_cell.setdefault(
                cell_key,
                {
                    "total_pairs": 0,
                    "treatment_wins": 0,
                    "control_wins": 0,
                    "ties": 0,
                    "no_contrast": 0,
                    "unvoted": 0,
                    "treatment_tokens": 0.0,
                    "control_tokens": 0.0,
                    "treatment_token_observed_n": 0,
                    "control_token_observed_n": 0,
                },
            )
            cell["total_pairs"] += 1
            if treatment_cost is not None:
                cell["treatment_tokens"] += treatment_cost
                cell["treatment_token_observed_n"] += 1
            if control_cost is not None:
                cell["control_tokens"] += control_cost
                cell["control_token_observed_n"] += 1
            if pair.no_contrast:
                result.no_contrast += 1
                cell["no_contrast"] += 1
                continue
            vote = self._pair_outcome_vote(pair.pair_id)
            if vote is None:
                result.unvoted += 1
                cell["unvoted"] += 1
                continue
            genre_bucket = by_genre.setdefault(
                pair.genre or "unlabeled",
                {"voted_pairs": 0, "treatment_wins": 0, "control_wins": 0, "ties": 0},
            )
            genre_bucket["voted_pairs"] += 1
            if not str(vote.reviewer_ref or "").strip():
                anonymous_vote_count += 1
            if vote.duration_ms is not None:
                durations.append(vote.duration_ms)
            if vote.choice == "tie":
                result.ties += 1
                genre_bucket["ties"] += 1
                cell["ties"] += 1
                continue
            treatment_slot = (pair.blind_mapping_json or {}).get("treatment_slot")
            if vote.choice == treatment_slot:
                result.treatment_wins += 1
                genre_bucket["treatment_wins"] += 1
                cell["treatment_wins"] += 1
            else:
                result.control_wins += 1
                genre_bucket["control_wins"] += 1
                cell["control_wins"] += 1

        is_ablation = bool((exp.treatment_policy_json or {}).get("ablation") or (exp.control_policy_json or {}).get("ablation"))
        decision = default_strategy_decision(result, is_ablation=is_ablation)

        total_pairs = len(pairs)
        decisive = result.decisive
        token_cost_complete = (
            token_treatment_observed_n == total_pairs
            and token_control_observed_n == total_pairs
        )
        token_multiplier = (
            token_treatment / token_control
            if token_cost_complete and token_control
            else None
        )
        pseudo_replication_ok = len(snapshot_hashes) == total_pairs
        manifest_verified = bool(
            exp.status == "frozen"
            and exp.frozen_pair_manifest_hash
            and exp.frozen_pair_manifest_hash == self._pair_manifest_hash(pairs)
        )
        hidden_manifest_verified = self._hidden_manifest_verified(exp)
        hidden_pair_bindings_verified = not self._benchmark_binding_errors(exp, pairs)
        base_eligibility_reasons: list[str] = []
        if exp.evidence_provenance != "human":
            base_eligibility_reasons.append("evidence_provenance_not_human")
        if not manifest_verified:
            base_eligibility_reasons.append("frozen_manifest_not_verified")
        if not hidden_manifest_verified:
            base_eligibility_reasons.append("hidden_benchmark_manifest_not_verified")
        if not hidden_pair_bindings_verified:
            base_eligibility_reasons.append("hidden_benchmark_pair_bindings_not_verified")
        if exp.isolation_mode not in _VALID_ISOLATION_MODES or not str(exp.snapshot_source_ref or "").strip():
            base_eligibility_reasons.append("evaluation_isolation_not_verified")
        if not pseudo_replication_ok:
            base_eligibility_reasons.append("snapshot_pseudo_replication_detected")
        if anonymous_vote_count:
            base_eligibility_reasons.append("anonymous_vote_provenance_present")
        base_evidence_eligible = not base_eligibility_reasons
        eligibility_reasons = list(base_eligibility_reasons)
        if decisive < 30:
            eligibility_reasons.append("fewer_than_30_non_tie_votes")
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
            "benchmark_manifest_id": exp.benchmark_manifest_id,
            "benchmark_manifest_hash": exp.benchmark_manifest_hash,
            "hidden_rubric_hash": exp.hidden_rubric_hash,
            "hidden_benchmark_manifest_verified": hidden_manifest_verified,
            "hidden_benchmark_pair_bindings_verified": hidden_pair_bindings_verified,
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
            # 95% Wilson 区间（非平局票上的 treatment 偏好率）；分题材拆分供审计。
            "preference_ci95": _wilson_ci95(result.treatment_wins, decisive),
            "by_genre": {
                genre: {
                    **tally,
                    "non_tie_n": tally["treatment_wins"] + tally["control_wins"],
                    "preference_rate": (
                        round(tally["treatment_wins"] / (tally["treatment_wins"] + tally["control_wins"]), 4)
                        if (tally["treatment_wins"] + tally["control_wins"])
                        else None
                    ),
                }
                for genre, tally in sorted(by_genre.items())
            },
            "strategy_cells": [
                _strategy_cell_report(genre, scene_function, tally)
                for (genre, scene_function), tally in sorted(by_strategy_cell.items())
            ],
            "tie_rate": round(result.ties / total_pairs, 4) if total_pairs else 0.0,
            "no_contrast_rate": round(result.no_contrast / total_pairs, 4) if total_pairs else 0.0,
            "p_value": decision.p_value,
            "min_wins_threshold": decision.min_wins,
            "significant": decision.significant,
            "statistical_decision": decision.decision,
            "policy_evidence_base_eligible": base_evidence_eligible,
            "policy_evidence_base_reasons": base_eligibility_reasons,
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
                "treatment_observed_n": token_treatment_observed_n,
                "control_observed_n": token_control_observed_n,
                "treatment_missing_n": total_pairs - token_treatment_observed_n,
                "control_missing_n": total_pairs - token_control_observed_n,
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

    def _hidden_manifest_verified(self, experiment: EvaluationExperiment) -> bool:
        if not experiment.benchmark_manifest_id:
            return False
        manifest = self.session.get(QualityBenchmarkManifest, experiment.benchmark_manifest_id)
        return bool(
            manifest is not None
            and manifest.status == "frozen"
            and manifest.split_kind == "hidden"
            and experiment.benchmark_manifest_hash == manifest.manifest_hash
            and experiment.hidden_rubric_hash == manifest.rubric_hash
            and experiment.isolation_mode == manifest.isolation_mode
        )

    def _validate_benchmark_pair_binding(
        self,
        experiment: EvaluationExperiment,
        *,
        treatment_result_id: str | None,
        control_result_id: str | None,
        treatment_text: str,
        control_text: str,
        treatment_ref: str | None,
        control_ref: str | None,
        genre: str | None,
        scene_function: str | None,
    ) -> tuple[QualityBenchmarkResult, QualityBenchmarkResult] | None:
        result_ids = (treatment_result_id, control_result_id)
        if not experiment.benchmark_manifest_id:
            if any(result_ids):
                raise DomainError(
                    "BENCHMARK_RESULT_WITHOUT_MANIFEST",
                    "benchmark result bindings require an experiment-bound hidden manifest",
                    422,
                )
            return None
        if not all(str(value or "").strip() for value in result_ids):
            raise DomainError(
                "HIDDEN_BENCHMARK_RESULT_BINDING_REQUIRED",
                "manifest-bound pairs require treatment and control benchmark result ids",
                422,
            )
        treatment = self.session.get(QualityBenchmarkResult, str(treatment_result_id))
        control = self.session.get(QualityBenchmarkResult, str(control_result_id))
        if treatment is None or control is None:
            raise DomainError("HIDDEN_BENCHMARK_RESULT_NOT_FOUND", "bound benchmark result not found", 404)
        treatment_run = self.session.get(QualityBenchmarkRun, treatment.run_id)
        control_run = self.session.get(QualityBenchmarkRun, control.run_id)
        manifest = self.session.get(QualityBenchmarkManifest, experiment.benchmark_manifest_id)
        if (
            manifest is None
            or treatment_run is None
            or control_run is None
            or treatment_run.run_id == control_run.run_id
            or treatment_run.status != "completed"
            or control_run.status != "completed"
            or treatment_run.manifest_id != experiment.benchmark_manifest_id
            or control_run.manifest_id != experiment.benchmark_manifest_id
            or treatment_run.manifest_hash != manifest.manifest_hash
            or control_run.manifest_hash != manifest.manifest_hash
            or treatment_run.rubric_hash != manifest.rubric_hash
            or control_run.rubric_hash != manifest.rubric_hash
            or experiment.benchmark_manifest_hash != manifest.manifest_hash
            or experiment.hidden_rubric_hash != manifest.rubric_hash
        ):
            raise DomainError(
                "HIDDEN_BENCHMARK_RUN_NOT_ELIGIBLE",
                "both results must belong to completed runs of the experiment manifest",
                409,
            )
        treatment_policy_hash = _policy_hash(experiment.treatment_policy_json or {})
        control_policy_hash = _policy_hash(experiment.control_policy_json or {})
        if treatment_policy_hash == control_policy_hash:
            raise DomainError(
                "HIDDEN_BENCHMARK_POLICY_ARMS_NOT_DISTINCT",
                "treatment and control generation policies must be preregistered and distinct",
                409,
            )
        if (
            treatment_run.generation_arm != "treatment"
            or control_run.generation_arm != "control"
            or treatment_run.generation_policy_hash != treatment_policy_hash
            or control_run.generation_policy_hash != control_policy_hash
        ):
            raise DomainError(
                "HIDDEN_BENCHMARK_GENERATION_POLICY_MISMATCH",
                "run arm and immutable generation policy hash must match the experiment",
                409,
            )
        declared_treatment_policy_id = str(
            (experiment.treatment_policy_json or {}).get("quality_strategy_policy_id") or ""
        ).strip()
        declared_control_policy_id = str(
            (experiment.control_policy_json or {}).get("quality_strategy_policy_id") or ""
        ).strip()
        if declared_treatment_policy_id and treatment_run.policy_id != declared_treatment_policy_id:
            raise DomainError(
                "HIDDEN_BENCHMARK_TREATMENT_POLICY_MISMATCH",
                "treatment result run is not bound to the preregistered treatment policy",
                409,
            )
        if declared_control_policy_id and control_run.policy_id != declared_control_policy_id:
            raise DomainError(
                "HIDDEN_BENCHMARK_CONTROL_POLICY_MISMATCH",
                "control result run is not bound to the preregistered control policy",
                409,
            )
        if (
            treatment.case_id_hash != control.case_id_hash
            or treatment.generation_input_hash != control.generation_input_hash
            or treatment.genre != control.genre
            or treatment.scene_function != control.scene_function
        ):
            raise DomainError(
                "HIDDEN_BENCHMARK_CASE_MISMATCH",
                "treatment and control must be the same hidden case and strategy cell",
                409,
            )
        if hashlib.sha256(str(treatment_text).encode("utf-8")).hexdigest() != treatment.output_hash or hashlib.sha256(
            str(control_text).encode("utf-8")
        ).hexdigest() != control.output_hash:
            raise DomainError(
                "HIDDEN_BENCHMARK_TEXT_MISMATCH",
                "blind-pair texts must exactly match their bound generated outputs",
                409,
            )
        if treatment_ref is not None and treatment_ref != treatment.artifact_ref:
            raise DomainError("HIDDEN_BENCHMARK_ARTIFACT_MISMATCH", "treatment artifact differs", 409)
        if control_ref is not None and control_ref != control.artifact_ref:
            raise DomainError("HIDDEN_BENCHMARK_ARTIFACT_MISMATCH", "control artifact differs", 409)
        if genre is not None and genre != treatment.genre:
            raise DomainError("HIDDEN_BENCHMARK_CELL_MISMATCH", "genre differs from benchmark result", 409)
        if scene_function is not None and scene_function != treatment.scene_function:
            raise DomainError(
                "HIDDEN_BENCHMARK_CELL_MISMATCH",
                "scene_function differs from benchmark result",
                409,
            )
        return treatment, control

    def _benchmark_binding_errors(
        self,
        experiment: EvaluationExperiment,
        pairs: list[EvaluationPair],
    ) -> list[str]:
        if not experiment.benchmark_manifest_id:
            return ["experiment_has_no_hidden_manifest"]
        manifest = self.session.get(QualityBenchmarkManifest, experiment.benchmark_manifest_id)
        if manifest is None or manifest.status != "frozen":
            return ["hidden_manifest_not_frozen"]
        errors: list[str] = []
        if (
            experiment.benchmark_manifest_hash != manifest.manifest_hash
            or experiment.hidden_rubric_hash != manifest.rubric_hash
        ):
            errors.append("experiment_manifest_hash_invalid")
        treatment_policy_hash = _policy_hash(experiment.treatment_policy_json or {})
        control_policy_hash = _policy_hash(experiment.control_policy_json or {})
        if treatment_policy_hash == control_policy_hash:
            errors.append("generation_policy_arms_not_distinct")
        seen_cases: set[str] = set()
        for pair in pairs:
            if not pair.treatment_benchmark_result_id or not pair.control_benchmark_result_id:
                errors.append(f"pair_unbound:{pair.pair_id}")
                continue
            treatment = self.session.get(QualityBenchmarkResult, pair.treatment_benchmark_result_id)
            control = self.session.get(QualityBenchmarkResult, pair.control_benchmark_result_id)
            if treatment is None or control is None:
                errors.append(f"result_missing:{pair.pair_id}")
                continue
            treatment_run = self.session.get(QualityBenchmarkRun, treatment.run_id)
            control_run = self.session.get(QualityBenchmarkRun, control.run_id)
            if (
                treatment_run is None
                or control_run is None
                or treatment_run.status != "completed"
                or control_run.status != "completed"
                or treatment_run.manifest_id != manifest.manifest_id
                or control_run.manifest_id != manifest.manifest_id
                or treatment_run.manifest_hash != manifest.manifest_hash
                or control_run.manifest_hash != manifest.manifest_hash
                or treatment_run.rubric_hash != manifest.rubric_hash
                or control_run.rubric_hash != manifest.rubric_hash
                or treatment_run.generation_arm != "treatment"
                or control_run.generation_arm != "control"
                or treatment_run.generation_policy_hash != treatment_policy_hash
                or control_run.generation_policy_hash != control_policy_hash
                or treatment_run.run_id == control_run.run_id
            ):
                errors.append(f"run_invalid:{pair.pair_id}")
            declared_treatment_policy_id = str(
                (experiment.treatment_policy_json or {}).get("quality_strategy_policy_id") or ""
            ).strip()
            declared_control_policy_id = str(
                (experiment.control_policy_json or {}).get("quality_strategy_policy_id") or ""
            ).strip()
            if declared_treatment_policy_id and (
                treatment_run is None or treatment_run.policy_id != declared_treatment_policy_id
            ):
                errors.append(f"treatment_policy_invalid:{pair.pair_id}")
            if declared_control_policy_id and (
                control_run is None or control_run.policy_id != declared_control_policy_id
            ):
                errors.append(f"control_policy_invalid:{pair.pair_id}")
            if (
                treatment.case_id_hash != control.case_id_hash
                or treatment.case_id_hash != pair.benchmark_case_id_hash
                or treatment.generation_input_hash != control.generation_input_hash
                or treatment.generation_input_hash != pair.scene_snapshot_hash
                or treatment.genre != control.genre
                or treatment.genre != pair.genre
                or treatment.scene_function != control.scene_function
                or treatment.scene_function != pair.scene_function
                or treatment.artifact_ref != (
                    pair.left_artifact_ref
                    if (pair.blind_mapping_json or {}).get("treatment_slot") == "left"
                    else pair.right_artifact_ref
                )
                or control.artifact_ref != (
                    pair.right_artifact_ref
                    if (pair.blind_mapping_json or {}).get("treatment_slot") == "left"
                    else pair.left_artifact_ref
                )
                or (pair.token_cost_json or {}).get("treatment") != treatment.cost_tokens
                or (pair.token_cost_json or {}).get("control") != control.cost_tokens
                or (pair.token_cost_json or {}).get("source") != "quality_benchmark_results"
            ):
                errors.append(f"pair_mapping_invalid:{pair.pair_id}")
            treatment_text = (
                pair.left_text if (pair.blind_mapping_json or {}).get("treatment_slot") == "left" else pair.right_text
            )
            control_text = (
                pair.right_text if (pair.blind_mapping_json or {}).get("treatment_slot") == "left" else pair.left_text
            )
            if (
                hashlib.sha256((treatment_text or "").encode("utf-8")).hexdigest() != treatment.output_hash
                or hashlib.sha256((control_text or "").encode("utf-8")).hexdigest() != control.output_hash
            ):
                errors.append(f"pair_text_invalid:{pair.pair_id}")
            if treatment.case_id_hash in seen_cases:
                errors.append(f"duplicate_case:{treatment.case_id_hash}")
            seen_cases.add(treatment.case_id_hash)
        if len(seen_cases) != manifest.case_count:
            errors.append(f"manifest_coverage:{len(seen_cases)}/{manifest.case_count}")
        return errors

    @staticmethod
    def _pair_manifest_hash(pairs: list[EvaluationPair]) -> str:
        payload = [
            {
                "pair_id": pair.pair_id,
                "scene_snapshot_hash": pair.scene_snapshot_hash,
                "left_text_sha256": hashlib.sha256((pair.left_text or "").encode("utf-8")).hexdigest(),
                "right_text_sha256": hashlib.sha256((pair.right_text or "").encode("utf-8")).hexdigest(),
                "blind_mapping": pair.blind_mapping_json or {},
                "left_artifact_ref": pair.left_artifact_ref,
                "right_artifact_ref": pair.right_artifact_ref,
                "token_cost": pair.token_cost_json or {},
                "no_contrast": int(pair.no_contrast or 0),
                "genre": pair.genre,
                "scene_function": pair.scene_function,
                "treatment_benchmark_result_id": pair.treatment_benchmark_result_id,
                "control_benchmark_result_id": pair.control_benchmark_result_id,
                "benchmark_case_id_hash": pair.benchmark_case_id_hash,
            }
            for pair in pairs
        ]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _policy_hash(policy: dict[str, Any]) -> str:
    canonical = json.dumps(policy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _strategy_cell_report(
    genre: str,
    scene_function: str,
    tally: dict[str, Any],
) -> dict[str, Any]:
    result = BlindEvalResult(
        treatment_wins=int(tally["treatment_wins"]),
        control_wins=int(tally["control_wins"]),
        ties=int(tally["ties"]),
        no_contrast=int(tally["no_contrast"]),
        unvoted=int(tally["unvoted"]),
    )
    decision = default_strategy_decision(result, is_ablation=False)
    control_tokens = float(tally["control_tokens"])
    cost_complete = (
        int(tally["treatment_token_observed_n"]) == int(tally["total_pairs"])
        and int(tally["control_token_observed_n"]) == int(tally["total_pairs"])
    )
    multiplier = (
        float(tally["treatment_tokens"]) / control_tokens
        if cost_complete and control_tokens
        else None
    )
    return {
        "genre": genre,
        "scene_function": scene_function,
        "total_pairs": int(tally["total_pairs"]),
        "treatment_wins": result.treatment_wins,
        "control_wins": result.control_wins,
        "ties": result.ties,
        "no_contrast": result.no_contrast,
        "unvoted": result.unvoted,
        "non_tie_n": result.decisive,
        "preference_rate": decision.preference_rate,
        "p_value": decision.p_value,
        "significant": decision.significant,
        "statistical_decision": decision.decision,
        "token_multiplier": round(multiplier, 4) if multiplier is not None else None,
        "treatment_token_observed_n": int(tally["treatment_token_observed_n"]),
        "control_token_observed_n": int(tally["control_token_observed_n"]),
        "treatment_token_missing_n": int(tally["total_pairs"] - tally["treatment_token_observed_n"]),
        "control_token_missing_n": int(tally["total_pairs"] - tally["control_token_observed_n"]),
    }


def _nonnegative_number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _wilson_ci95(successes: int, n: int) -> dict[str, float] | None:
    """非平局票上 treatment 偏好率的 95% Wilson 置信区间。"""
    if n <= 0:
        return None
    z = 1.959963984540054
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"low": round(max(0.0, center - margin), 4), "high": round(min(1.0, center + margin), 4)}


def _module_conclusion(decision: str) -> str:
    return {
        "upgrade_to_default": "keep",     # 值得——保留并可升级默认（需复验）
        "keep_optional": "downgrade",     # 未证增益——降级为可选（§8 项 7）
        "disable": "disable",             # 显著更差——关闭
        "need_more_samples": "pending",
        "not_eligible_for_policy": "pending",
        "replication_required": "pending",
    }.get(decision, "pending")
