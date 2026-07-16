"""Evidence-bound genre × scene-function quality strategy resolution.

Configuration may fall back through wildcard scopes.  Evidence never does:
Best-of-N is enabled only when the exact requested genre/function cell has its
own completed hidden-run artifacts, human blind votes, and human value metrics.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    EvaluationExperiment,
    EvaluationPair,
    QualityBenchmarkManifest,
    QualityBenchmarkResult,
    QualityBenchmarkRun,
    QualityStrategyPolicy,
    SceneCard,
    StoryProject,
    utcnow,
)
from novel_system.services.best_of_n_blind_eval import binomial_two_sided_p
from novel_system.services.errors import DomainError
from novel_system.services.evaluation_experiment import EvaluationExperimentService
from novel_system.services.literary_quality import DIMENSION_WEIGHTS, QUALITY_DIMENSIONS
from novel_system.services.quality_evidence import QualityEvidenceService
from novel_system.services.tension_curve import FUNCTION_TAGS, get_scene_function_tag


DEFAULT_QUALITY_THRESHOLDS: dict[str, Any] = {
    "min_blind_non_tie_n": 30,
    "min_treatment_wins": 21,
    "max_p_value": 0.05,
    "min_human_value_n": 30,
    "max_human_edit_distance_ratio": 0.35,
    "min_first_usable_rate": 0.70,
    "min_follow_read_intent": 3.5,
    "max_token_multiplier": 5.0,
    "max_average_latency_ms": 120_000.0,
    "require_cost_tokens": True,
    "require_latency": True,
    "require_monetary_cost": True,
}

_THRESHOLD_KEYS = frozenset(DEFAULT_QUALITY_THRESHOLDS)


@dataclass(frozen=True, slots=True)
class ResolvedQualityStrategy:
    genre: str
    scene_function: str
    matched_policy_id: str | None
    matched_scope: tuple[str, str] | None
    fallback_level: str
    weights: dict[str, float]
    thresholds: dict[str, Any]
    best_of_n_requested: bool
    best_of_n_enabled: bool
    best_of_n_n: int
    blockers: tuple[str, ...]
    evidence: dict[str, Any]

    def public_summary(self) -> dict[str, Any]:
        return {
            "genre": self.genre,
            "scene_function": self.scene_function,
            "matched_policy_id": self.matched_policy_id,
            "matched_scope": list(self.matched_scope) if self.matched_scope else None,
            "fallback_level": self.fallback_level,
            "weights": dict(self.weights),
            "thresholds": dict(self.thresholds),
            "best_of_n_requested": self.best_of_n_requested,
            "best_of_n_enabled": self.best_of_n_enabled,
            "best_of_n_n": self.best_of_n_n,
            "blockers": list(self.blockers),
            "evidence": dict(self.evidence),
        }


class QualityStrategyService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_policy(
        self,
        *,
        genre: str = "*",
        scene_function: str = "*",
        weights: dict[str, Any] | None = None,
        thresholds: dict[str, Any] | None = None,
        best_of_n_requested: bool = False,
        best_of_n_n: int = 1,
        evidence_experiment_id: str | None = None,
        benchmark_manifest_id: str | None = None,
        policy_version: int = 1,
        created_by: str = "operator",
        policy_id: str | None = None,
    ) -> QualityStrategyPolicy:
        normalized_genre = str(genre or "").strip()
        normalized_function = str(scene_function or "").strip()
        if not normalized_genre:
            raise DomainError("QUALITY_POLICY_GENRE_REQUIRED", "genre or * is required", 422)
        if normalized_function != "*" and normalized_function not in FUNCTION_TAGS:
            raise DomainError(
                "QUALITY_POLICY_SCENE_FUNCTION_INVALID",
                f"scene_function must be * or one of {FUNCTION_TAGS}",
                422,
            )
        if isinstance(best_of_n_requested, bool) is False:
            raise DomainError("QUALITY_POLICY_BEST_OF_N_INVALID", "best_of_n_requested must be boolean", 422)
        if (
            not isinstance(best_of_n_n, int)
            or isinstance(best_of_n_n, bool)
            or not 1 <= best_of_n_n <= 5
        ):
            raise DomainError("QUALITY_POLICY_BEST_OF_N_INVALID", "best_of_n_n must be 1..5", 422)
        if (
            not isinstance(policy_version, int)
            or isinstance(policy_version, bool)
            or policy_version < 1
        ):
            raise DomainError("QUALITY_POLICY_VERSION_INVALID", "policy_version must be positive", 422)

        effective_weights = _normalize_weights(weights)
        effective_thresholds = _normalize_thresholds(thresholds)
        self._validate_evidence_references(
            evidence_experiment_id=evidence_experiment_id,
            benchmark_manifest_id=benchmark_manifest_id,
        )
        row = QualityStrategyPolicy(
            policy_id=policy_id or f"qpolicy_{uuid.uuid4().hex[:16]}",
            policy_version=int(policy_version),
            genre=normalized_genre,
            scene_function=normalized_function,
            weights_json=effective_weights,
            thresholds_json=effective_thresholds,
            best_of_n_requested=best_of_n_requested,
            best_of_n_n=int(best_of_n_n),
            evidence_experiment_id=evidence_experiment_id,
            benchmark_manifest_id=benchmark_manifest_id,
            status="active",
            created_by=str(created_by or "operator").strip() or "operator",
        )
        self.session.add(row)
        self.session.flush()
        return row

    def bind_evidence(
        self,
        policy_id: str,
        *,
        evidence_experiment_id: str,
        benchmark_manifest_id: str,
    ) -> QualityStrategyPolicy:
        row = self.session.get(QualityStrategyPolicy, policy_id)
        if row is None or row.status != "active":
            raise DomainError("QUALITY_POLICY_NOT_FOUND", "active quality policy not found", 404)
        self._validate_evidence_references(
            evidence_experiment_id=evidence_experiment_id,
            benchmark_manifest_id=benchmark_manifest_id,
        )
        experiment = self.session.get(EvaluationExperiment, evidence_experiment_id)
        if experiment is None or experiment.benchmark_manifest_id != benchmark_manifest_id:
            raise DomainError(
                "QUALITY_POLICY_EVIDENCE_MISMATCH",
                "experiment and policy must reference the same hidden manifest",
                409,
            )
        row.evidence_experiment_id = evidence_experiment_id
        row.benchmark_manifest_id = benchmark_manifest_id
        row.updated_at = utcnow()
        self.session.flush()
        return row

    def retire_policy(self, policy_id: str) -> QualityStrategyPolicy:
        row = self.session.get(QualityStrategyPolicy, policy_id)
        if row is None:
            raise DomainError("QUALITY_POLICY_NOT_FOUND", "quality policy not found", 404)
        row.status = "retired"
        row.updated_at = utcnow()
        self.session.flush()
        return row

    def _validate_evidence_references(
        self,
        *,
        evidence_experiment_id: str | None,
        benchmark_manifest_id: str | None,
    ) -> None:
        if benchmark_manifest_id is not None:
            manifest = self.session.get(QualityBenchmarkManifest, benchmark_manifest_id)
            if manifest is None or manifest.status != "frozen" or manifest.split_kind != "hidden":
                raise DomainError(
                    "QUALITY_POLICY_MANIFEST_NOT_FROZEN",
                    "benchmark_manifest_id must reference a frozen hidden manifest",
                    409,
                )
        if evidence_experiment_id is not None:
            experiment = self.session.get(EvaluationExperiment, evidence_experiment_id)
            if experiment is None:
                raise DomainError("QUALITY_POLICY_EXPERIMENT_NOT_FOUND", "evidence experiment not found", 404)
            if benchmark_manifest_id is None or experiment.benchmark_manifest_id != benchmark_manifest_id:
                raise DomainError(
                    "QUALITY_POLICY_EVIDENCE_MISMATCH",
                    "evidence experiment must be bound to the same manifest",
                    409,
                )


class QualityStrategyResolver:
    """Resolve configuration by wildcard priority, but prove the exact cell."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve(self, genre: str | None, scene_function: str | None) -> ResolvedQualityStrategy:
        normalized_genre = str(genre or "").strip()
        normalized_function = str(scene_function or "").strip()
        if not normalized_genre or normalized_function not in FUNCTION_TAGS:
            blockers = []
            if not normalized_genre:
                blockers.append("genre_unlabeled")
            if normalized_function not in FUNCTION_TAGS:
                blockers.append("scene_function_unlabeled_or_invalid")
            return self._builtin_result(
                normalized_genre or "unlabeled",
                normalized_function or "unlabeled",
                blockers=blockers,
            )

        policy, level = self._resolve_policy_row(normalized_genre, normalized_function)
        if policy is None:
            return self._builtin_result(
                normalized_genre,
                normalized_function,
                blockers=["no_active_quality_policy"],
            )

        weights = _normalize_weights(policy.weights_json or {})
        thresholds = _normalize_thresholds(policy.thresholds_json or {})
        blockers: list[str] = []
        evidence: dict[str, Any] = {
            "experiment_id": policy.evidence_experiment_id,
            "benchmark_manifest_id": policy.benchmark_manifest_id,
            "target_cell_only": True,
        }
        if not policy.best_of_n_requested:
            blockers.append("best_of_n_not_requested")
        if (
            isinstance(policy.best_of_n_n, bool)
            or not isinstance(policy.best_of_n_n, int)
            or not 1 <= policy.best_of_n_n <= 5
        ):
            blockers.append("best_of_n_policy_n_invalid")
        if (
            isinstance(policy.policy_version, bool)
            or not isinstance(policy.policy_version, int)
            or policy.policy_version < 1
        ):
            blockers.append("quality_policy_version_invalid")
        if not policy.evidence_experiment_id or not policy.benchmark_manifest_id:
            blockers.append("evidence_references_missing")
        else:
            self._evaluate_evidence(
                policy,
                genre=normalized_genre,
                scene_function=normalized_function,
                thresholds=thresholds,
                blockers=blockers,
                evidence=evidence,
            )
        enabled = bool(policy.best_of_n_requested and not blockers)
        return ResolvedQualityStrategy(
            genre=normalized_genre,
            scene_function=normalized_function,
            matched_policy_id=policy.policy_id,
            matched_scope=(policy.genre, policy.scene_function),
            fallback_level=level,
            weights=weights,
            thresholds=thresholds,
            best_of_n_requested=bool(policy.best_of_n_requested),
            best_of_n_enabled=enabled,
            best_of_n_n=int(policy.best_of_n_n) if enabled else 1,
            blockers=tuple(dict.fromkeys(blockers)),
            evidence=evidence,
        )

    def resolve_for_scene(self, scene: SceneCard | str) -> ResolvedQualityStrategy:
        row = self.session.get(SceneCard, scene) if isinstance(scene, str) else scene
        if row is None:
            return self._builtin_result("unlabeled", "unlabeled", blockers=["scene_not_found"])
        project = self.session.get(StoryProject, row.project_id) if row.project_id else None
        return self.resolve(project.genre if project else None, get_scene_function_tag(row))

    def _resolve_policy_row(
        self,
        genre: str,
        scene_function: str,
    ) -> tuple[QualityStrategyPolicy | None, str]:
        rows = list(
            self.session.execute(
                select(QualityStrategyPolicy).where(
                    QualityStrategyPolicy.status == "active",
                    QualityStrategyPolicy.genre.in_((genre, "*")),
                    QualityStrategyPolicy.scene_function.in_((scene_function, "*")),
                )
            ).scalars().all()
        )
        priority = {
            (genre, scene_function): (0, "exact"),
            (genre, "*"): (1, "genre_default"),
            ("*", scene_function): (2, "scene_function_default"),
            ("*", "*"): (3, "global_default"),
        }
        rows.sort(
            key=lambda row: (
                priority[(row.genre, row.scene_function)][0],
                -int(row.policy_version),
                row.policy_id,
            )
        )
        if not rows:
            return None, "builtin_default"
        row = rows[0]
        return row, priority[(row.genre, row.scene_function)][1]

    def _evaluate_evidence(
        self,
        policy: QualityStrategyPolicy,
        *,
        genre: str,
        scene_function: str,
        thresholds: dict[str, Any],
        blockers: list[str],
        evidence: dict[str, Any],
    ) -> None:
        experiment = self.session.get(EvaluationExperiment, policy.evidence_experiment_id)
        manifest = self.session.get(QualityBenchmarkManifest, policy.benchmark_manifest_id)
        if (
            experiment is None
            or manifest is None
            or experiment.benchmark_manifest_id != manifest.manifest_id
            or experiment.benchmark_manifest_hash != manifest.manifest_hash
            or experiment.hidden_rubric_hash != manifest.rubric_hash
        ):
            blockers.append("evidence_manifest_binding_invalid")
            return
        report = EvaluationExperimentService(self.session).build_report(experiment.experiment_id)
        evidence["blind_report_base_eligible"] = bool(report.get("policy_evidence_base_eligible"))
        evidence["blind_report_base_reasons"] = list(report.get("policy_evidence_base_reasons") or [])
        if not report.get("policy_evidence_base_eligible"):
            blockers.append("blind_experiment_not_eligible")
        if not report.get("policy_evidence_eligible"):
            blockers.append("blind_experiment_global_outcome_gate_failed")
        if report.get("requires_fresh_replication"):
            blockers.append("fresh_human_replication_required")
        if report.get("decision") != "upgrade_to_default":
            blockers.append("blind_experiment_not_approved_for_upgrade")

        cell = next(
            (
                item
                for item in report.get("strategy_cells") or []
                if item.get("genre") == genre and item.get("scene_function") == scene_function
            ),
            None,
        )
        evidence["blind_cell"] = cell
        if cell is None:
            blockers.append("blind_exact_cell_missing")
            return
        non_tie_n = int(cell.get("non_tie_n") or 0)
        treatment_wins = int(cell.get("treatment_wins") or 0)
        p_value = binomial_two_sided_p(treatment_wins, non_tie_n, 0.5)
        if non_tie_n < int(thresholds["min_blind_non_tie_n"]):
            blockers.append("blind_cell_sample_insufficient")
        if treatment_wins < int(thresholds["min_treatment_wins"]):
            blockers.append("blind_cell_treatment_wins_insufficient")
        if treatment_wins <= int(cell.get("control_wins") or 0) or p_value >= float(
            thresholds["max_p_value"]
        ):
            blockers.append("blind_cell_not_significant")
        token_multiplier = cell.get("token_multiplier")
        if token_multiplier is None or float(token_multiplier) > float(thresholds["max_token_multiplier"]):
            blockers.append("blind_cell_token_cost_unacceptable_or_missing")

        target_pairs = list(
            self.session.execute(
                select(EvaluationPair).where(
                    EvaluationPair.experiment_id == experiment.experiment_id,
                    EvaluationPair.genre == genre,
                    EvaluationPair.scene_function == scene_function,
                )
            ).scalars().all()
        )
        treatment_result_ids = [pair.treatment_benchmark_result_id for pair in target_pairs]
        if not treatment_result_ids or any(result_id is None for result_id in treatment_result_ids):
            blockers.append("treatment_result_bindings_missing")
            return
        treatment_results = list(
            self.session.execute(
                select(QualityBenchmarkResult).where(
                    QualityBenchmarkResult.result_id.in_(treatment_result_ids)
                )
            ).scalars().all()
        )
        treatment_runs = {
            result.run_id: self.session.get(QualityBenchmarkRun, result.run_id)
            for result in treatment_results
        }
        if len(treatment_results) != len(treatment_result_ids) or any(
            run is None
            or run.status != "completed"
            or run.policy_id != policy.policy_id
            or run.manifest_id != manifest.manifest_id
            for run in treatment_runs.values()
        ):
            blockers.append("treatment_policy_run_binding_invalid")
            return

        summary = QualityEvidenceService(self.session).summarize_value_metrics(
            manifest.manifest_id,
            genre=genre,
            scene_function=scene_function,
            result_ids=[str(result_id) for result_id in treatment_result_ids],
        )
        evidence["human_value"] = summary
        required_n = int(thresholds["min_human_value_n"])
        _require_metric(
            summary["human_edit_distance"],
            required_n=required_n,
            missing_blocker="human_edit_distance_sample_insufficient",
            blockers=blockers,
        )
        _require_metric(
            summary["first_usable"],
            required_n=required_n,
            missing_blocker="first_usable_sample_insufficient",
            blockers=blockers,
        )
        _require_metric(
            summary["follow_read_intent"],
            required_n=required_n,
            missing_blocker="follow_read_intent_sample_insufficient",
            blockers=blockers,
        )
        if summary["human_edit_distance"].get("mean") is None or float(
            summary["human_edit_distance"]["mean"] or 0
        ) > float(thresholds["max_human_edit_distance_ratio"]):
            blockers.append("human_edit_distance_too_high")
        if summary["first_usable"].get("rate") is None or float(
            summary["first_usable"]["rate"] or 0
        ) < float(thresholds["min_first_usable_rate"]):
            blockers.append("first_usable_rate_too_low")
        if summary["follow_read_intent"].get("mean") is None or float(
            summary["follow_read_intent"]["mean"] or 0
        ) < float(thresholds["min_follow_read_intent"]):
            blockers.append("follow_read_intent_too_low")
        if thresholds["require_cost_tokens"]:
            _require_metric(
                summary["cost_tokens"],
                required_n=required_n,
                missing_blocker="cost_token_sample_insufficient",
                blockers=blockers,
            )
        if thresholds["require_latency"]:
            _require_metric(
                summary["latency_ms"],
                required_n=required_n,
                missing_blocker="latency_sample_insufficient",
                blockers=blockers,
            )
            latency_mean = summary["latency_ms"].get("mean")
            if latency_mean is None or float(latency_mean) > float(thresholds["max_average_latency_ms"]):
                blockers.append("average_latency_too_high")
        if thresholds["require_monetary_cost"]:
            _require_metric(
                summary["monetary_cost"],
                required_n=required_n,
                missing_blocker="monetary_cost_sample_insufficient",
                blockers=blockers,
            )

    def _builtin_result(
        self,
        genre: str,
        scene_function: str,
        *,
        blockers: list[str],
    ) -> ResolvedQualityStrategy:
        return ResolvedQualityStrategy(
            genre=genre,
            scene_function=scene_function,
            matched_policy_id=None,
            matched_scope=None,
            fallback_level="builtin_default",
            weights=dict(DIMENSION_WEIGHTS),
            thresholds=dict(DEFAULT_QUALITY_THRESHOLDS),
            best_of_n_requested=False,
            best_of_n_enabled=False,
            best_of_n_n=1,
            blockers=tuple(blockers),
            evidence={"target_cell_only": True},
        )


def _normalize_weights(raw: dict[str, Any] | None) -> dict[str, float]:
    if raw is None or not raw:
        return dict(DIMENSION_WEIGHTS)
    if not isinstance(raw, dict):
        raise DomainError("QUALITY_POLICY_WEIGHTS_INVALID", "weights must be an object", 422)
    unknown = sorted(set(raw) - set(QUALITY_DIMENSIONS))
    if unknown:
        raise DomainError(
            "QUALITY_POLICY_WEIGHTS_INVALID",
            "weights contain unknown quality dimensions",
            422,
            details={"unknown": unknown},
        )
    merged = dict(DIMENSION_WEIGHTS)
    for key, value in raw.items():
        if isinstance(value, bool):
            raise DomainError("QUALITY_POLICY_WEIGHTS_INVALID", "weights must be finite nonnegative numbers", 422)
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DomainError(
                "QUALITY_POLICY_WEIGHTS_INVALID",
                "weights must be finite nonnegative numbers",
                422,
            ) from exc
        if not math.isfinite(number) or number < 0:
            raise DomainError("QUALITY_POLICY_WEIGHTS_INVALID", "weights must be finite nonnegative numbers", 422)
        merged[key] = number
    total = sum(merged.values())
    if total <= 0:
        raise DomainError("QUALITY_POLICY_WEIGHTS_INVALID", "at least one weight must be positive", 422)
    return {key: round(value / total, 8) for key, value in merged.items()}


def _normalize_thresholds(raw: dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return dict(DEFAULT_QUALITY_THRESHOLDS)
    if not isinstance(raw, dict):
        raise DomainError("QUALITY_POLICY_THRESHOLDS_INVALID", "thresholds must be an object", 422)
    unknown = sorted(set(raw) - _THRESHOLD_KEYS)
    if unknown:
        raise DomainError(
            "QUALITY_POLICY_THRESHOLDS_INVALID",
            "thresholds contain unknown keys",
            422,
            details={"unknown": unknown},
        )
    merged = {**DEFAULT_QUALITY_THRESHOLDS, **raw}
    for key in ("require_cost_tokens", "require_latency", "require_monetary_cost"):
        if not isinstance(merged[key], bool):
            raise DomainError("QUALITY_POLICY_THRESHOLDS_INVALID", f"{key} must be boolean", 422)
    if not merged["require_cost_tokens"] or not merged["require_latency"] or not merged["require_monetary_cost"]:
        raise DomainError(
            "QUALITY_POLICY_THRESHOLDS_TOO_PERMISSIVE",
            "cost_tokens, monetary cost, and latency evidence are mandatory for production release",
            422,
        )
    for key in ("min_blind_non_tie_n", "min_treatment_wins", "min_human_value_n"):
        value = merged[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise DomainError("QUALITY_POLICY_THRESHOLDS_INVALID", f"{key} must be a positive integer", 422)
        merged[key] = value
        if merged[key] < int(DEFAULT_QUALITY_THRESHOLDS[key]):
            raise DomainError(
                "QUALITY_POLICY_THRESHOLDS_TOO_PERMISSIVE",
                f"{key} cannot be lower than the production baseline",
                422,
            )
    for key in (
        "max_p_value",
        "max_human_edit_distance_ratio",
        "min_first_usable_rate",
    ):
        value = merged[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1
        ):
            raise DomainError("QUALITY_POLICY_THRESHOLDS_INVALID", f"{key} must be within 0..1", 422)
        merged[key] = float(value)
    if merged["max_p_value"] > DEFAULT_QUALITY_THRESHOLDS["max_p_value"]:
        raise DomainError(
            "QUALITY_POLICY_THRESHOLDS_TOO_PERMISSIVE",
            "max_p_value cannot exceed the production baseline",
            422,
        )
    if merged["max_human_edit_distance_ratio"] > DEFAULT_QUALITY_THRESHOLDS[
        "max_human_edit_distance_ratio"
    ]:
        raise DomainError(
            "QUALITY_POLICY_THRESHOLDS_TOO_PERMISSIVE",
            "max_human_edit_distance_ratio cannot exceed the production baseline",
            422,
        )
    if merged["min_first_usable_rate"] < DEFAULT_QUALITY_THRESHOLDS["min_first_usable_rate"]:
        raise DomainError(
            "QUALITY_POLICY_THRESHOLDS_TOO_PERMISSIVE",
            "min_first_usable_rate cannot be lower than the production baseline",
            422,
        )
    follow_read_threshold = merged["min_follow_read_intent"]
    if (
        isinstance(follow_read_threshold, bool)
        or not isinstance(follow_read_threshold, (int, float))
        or not math.isfinite(float(follow_read_threshold))
        or not 1 <= float(follow_read_threshold) <= 5
    ):
        raise DomainError("QUALITY_POLICY_THRESHOLDS_INVALID", "min_follow_read_intent must be 1..5", 422)
    merged["min_follow_read_intent"] = float(follow_read_threshold)
    if merged["min_follow_read_intent"] < DEFAULT_QUALITY_THRESHOLDS["min_follow_read_intent"]:
        raise DomainError(
            "QUALITY_POLICY_THRESHOLDS_TOO_PERMISSIVE",
            "min_follow_read_intent cannot be lower than the production baseline",
            422,
        )
    for key in ("max_token_multiplier", "max_average_latency_ms"):
        value = merged[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise DomainError("QUALITY_POLICY_THRESHOLDS_INVALID", f"{key} must be positive", 422)
        merged[key] = float(value)
        if merged[key] > float(DEFAULT_QUALITY_THRESHOLDS[key]):
            raise DomainError(
                "QUALITY_POLICY_THRESHOLDS_TOO_PERMISSIVE",
                f"{key} cannot exceed the production baseline",
                422,
            )
    return merged


def _require_metric(
    metric: dict[str, Any],
    *,
    required_n: int,
    missing_blocker: str,
    blockers: list[str],
) -> None:
    if int(metric.get("observed_result_n") or 0) < required_n or int(metric.get("missing_result_n") or 0) > 0:
        blockers.append(missing_blocker)
