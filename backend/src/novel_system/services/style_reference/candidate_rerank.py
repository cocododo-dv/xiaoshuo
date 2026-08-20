"""Deterministic, evidence-gated style scoring for scene draft candidates.

The scorer deliberately measures only observable text statistics already frozen in
``StyleReferenceProfile.profile_json.metrics_baseline``.  It does not use topic,
named entities, embeddings, author identity, or an LLM judge.  This makes the
signal explainable and keeps reference *content* out of the positive score.

Deployment is conservative:

* ``shadow`` (the repository default) records style fit and preserves the existing
  adversarial-quality order except for the independent source-copy guard;
* ``active`` is accepted only with an explicit frozen human-evidence reference;
* even in active mode, style may choose only among candidates within a bounded
  distance of the best deterministic quality score;
* verbatim overlap with the source corpus is a separate hard safety guard and can
  never improve a candidate's score.

The module is intentionally independent of ``scene_generation`` result classes so
the pure ranking functions can be calibrated and tested without a database.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from novel_system.services.hash_engine import canonical_json
from novel_system.services.style_reference.config_loader import load_yaml_config
from novel_system.services.style_reference.injection import (
    InjectionService,
    ordered_character_ids,
)
from novel_system.services.style_reference.metrics import (
    METRIC_NAMES,
    PROSE_SHAPE_METRIC_NAMES,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.runtime_contract import (
    blend_profile_metric_baselines,
    build_style_runtime_contract,
    contract_profile_objects,
    resolve_style_runtime_contract_state,
)
from novel_system.services.style_reference.validation.core import (
    _load_plagiarism_corpus,
)
from novel_system.services.style_reference.validation.plagiarism import check_plagiarism
from novel_system.services.style_reference.validation.quantitative import (
    DEFAULT_FLOOR,
    TYPE_RATIO_METRICS,
    compute_generated_metrics,
)


SCORER_VERSION = "style_candidate_rerank_v2"
_TEXT_METRICS = tuple(
    name for name in METRIC_NAMES if name not in TYPE_RATIO_METRICS
) + PROSE_SHAPE_METRIC_NAMES
_MAX_STYLE_WEIGHT = 0.25
_MAX_QUALITY_DROP = 0.08
_MIN_ACTIVE_METRICS = 12
_MIN_ACTIVE_CONFIDENCE = 0.60
_MIN_ACTIVE_CHARS = 300
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_METRIC_GROUPS: dict[str, tuple[str, ...]] = {
    "paragraph_shape": PROSE_SHAPE_METRIC_NAMES,
    "sentence_shape": (
        "avg_sentence_length",
        "sentence_length_std",
        "short_sentence_ratio",
        "long_sentence_ratio",
    ),
    "punctuation_rhythm": (
        "punctuation_density_per_1k",
        "dash_em_density_per_1k",
        "ellipsis_density_per_1k",
        "semicolon_density_per_1k",
        "question_density_per_1k",
    ),
    "register": ("classical_word_ratio", "colloquial_marker_ratio"),
    "figurative_proxy": ("metaphor_density_per_1k", "personification_density_per_1k"),
    "sensory_proxy": (
        "sensory_visual_per_1k",
        "sensory_auditory_per_1k",
        "sensory_olfactory_per_1k",
        "sensory_tactile_per_1k",
        "sensory_gustatory_per_1k",
    ),
}


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _config_float(
    payload: Mapping[str, Any],
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
    errors: list[str],
) -> float:
    value = _finite_float(payload.get(key, default))
    if value is None or not minimum <= value <= maximum:
        errors.append(f"{key}_out_of_range")
        return default
    return value


def _config_int(
    payload: Mapping[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
    errors: list[str],
) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool):
        errors.append(f"{key}_out_of_range")
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        errors.append(f"{key}_out_of_range")
        return default
    if not minimum <= parsed <= maximum:
        errors.append(f"{key}_out_of_range")
        return default
    return parsed


@dataclass(frozen=True, slots=True)
class CandidateRerankPolicy:
    requested_mode: str = "shadow"
    effective_mode: str = "shadow"
    style_weight: float = 0.18
    max_quality_drop: float = 0.04
    min_substantive_chars: int = 300
    min_metric_count: int = 12
    min_confidence: float = 0.65
    plagiarism_guard: bool = True
    plagiarism_ngram_size: int = 8
    plagiarism_threshold_chars: int = 12
    activation_report_id: str | None = None
    activation_report_sha256: str | None = None
    configuration_errors: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "CandidateRerankPolicy":
        raw = dict(payload or {})
        errors: list[str] = []
        requested_mode = str(raw.get("mode", "shadow") or "shadow").strip().lower()
        if requested_mode not in {"off", "shadow", "active"}:
            errors.append("mode_invalid")
            requested_mode = "shadow"

        style_weight = _config_float(
            raw,
            "style_weight",
            0.18,
            minimum=0.0,
            maximum=_MAX_STYLE_WEIGHT,
            errors=errors,
        )
        max_quality_drop = _config_float(
            raw,
            "max_quality_drop",
            0.04,
            minimum=0.0,
            maximum=_MAX_QUALITY_DROP,
            errors=errors,
        )
        min_substantive_chars = _config_int(
            raw,
            "min_substantive_chars",
            300,
            minimum=_MIN_ACTIVE_CHARS,
            maximum=10_000,
            errors=errors,
        )
        min_metric_count = _config_int(
            raw,
            "min_metric_count",
            12,
            minimum=_MIN_ACTIVE_METRICS,
            maximum=len(_TEXT_METRICS),
            errors=errors,
        )
        min_confidence = _config_float(
            raw,
            "min_confidence",
            0.65,
            minimum=_MIN_ACTIVE_CONFIDENCE,
            maximum=1.0,
            errors=errors,
        )
        ngram_size = _config_int(
            raw,
            "plagiarism_ngram_size",
            8,
            minimum=6,
            maximum=8,
            errors=errors,
        )
        threshold_chars = _config_int(
            raw,
            "plagiarism_threshold_chars",
            12,
            minimum=max(ngram_size, 8),
            maximum=12,
            errors=errors,
        )
        plagiarism_guard = raw.get("plagiarism_guard", True)
        if not isinstance(plagiarism_guard, bool):
            errors.append("plagiarism_guard_invalid")
            plagiarism_guard = True
        elif plagiarism_guard is False:
            # Exact-copy prevention is a source-safety invariant, not an
            # optimization knob.  A config edit cannot weaken it silently.
            errors.append("plagiarism_guard_cannot_be_disabled")
            plagiarism_guard = True

        activation = raw.get("activation_evidence")
        activation = activation if isinstance(activation, Mapping) else {}
        report_id = str(activation.get("report_id") or "").strip() or None
        report_sha256 = (
            str(activation.get("report_sha256") or "").strip().lower() or None
        )
        activation_valid = bool(
            activation.get("human_verified") is True
            and activation.get("policy_evidence_eligible") is True
            and report_id
            and report_sha256
            and _SHA256_RE.fullmatch(report_sha256)
        )

        effective_mode = requested_mode
        if errors:
            effective_mode = "shadow"
        elif requested_mode == "active" and not activation_valid:
            errors.append("active_mode_missing_frozen_human_evidence")
            effective_mode = "shadow"

        return cls(
            requested_mode=requested_mode,
            effective_mode=effective_mode,
            style_weight=style_weight,
            max_quality_drop=max_quality_drop,
            min_substantive_chars=min_substantive_chars,
            min_metric_count=min_metric_count,
            min_confidence=min_confidence,
            plagiarism_guard=plagiarism_guard,
            plagiarism_ngram_size=ngram_size,
            plagiarism_threshold_chars=threshold_chars,
            activation_report_id=report_id,
            activation_report_sha256=report_sha256,
            configuration_errors=tuple(dict.fromkeys(errors)),
        )


@dataclass(frozen=True, slots=True)
class StyleMetricTarget:
    metric: str
    mean: float
    std: float
    tolerance: float
    component_count: int


@dataclass(frozen=True, slots=True)
class StyleTarget:
    profile_ids: tuple[str, ...]
    metrics: Mapping[str, StyleMetricTarget]
    target_hash: str


@dataclass(slots=True)
class CandidateAssessment:
    row_id: str
    quality_score: float
    style_score: float | None = None
    style_confidence: float = 0.0
    metric_count: int = 0
    substantive_chars: int = 0
    group_scores: dict[str, float] = field(default_factory=dict)
    top_deviations: list[dict[str, Any]] = field(default_factory=list)
    plagiarism_checked: bool = False
    plagiarism_passed: bool | None = None
    plagiarism_hit_count: int = 0
    plagiarism_max_match_chars: int = 0
    style_eligible: bool = False
    combined_score: float | None = None
    rank: int | None = None
    selected: bool = False
    selection_reason: str = "quality_order"

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "quality_score": round(self.quality_score, 6),
            "style_score": (
                None if self.style_score is None else round(self.style_score, 6)
            ),
            "style_confidence": round(self.style_confidence, 6),
            "metric_count": self.metric_count,
            "substantive_chars": self.substantive_chars,
            "group_scores": {
                key: round(value, 6) for key, value in sorted(self.group_scores.items())
            },
            "top_deviations": self.top_deviations,
            "plagiarism_checked": self.plagiarism_checked,
            "plagiarism_passed": self.plagiarism_passed,
            "plagiarism_hit_count": self.plagiarism_hit_count,
            "plagiarism_max_match_chars": self.plagiarism_max_match_chars,
            "style_eligible": self.style_eligible,
            "combined_score": (
                None if self.combined_score is None else round(self.combined_score, 6)
            ),
            "rank": self.rank,
            "selected": self.selected,
            "selection_reason": self.selection_reason,
            "scorer_version": SCORER_VERSION,
        }


@dataclass(slots=True)
class CandidateRerankOutcome:
    ordered_candidates: list[Any]
    assessments: dict[str, CandidateAssessment]
    audit: dict[str, Any]


def build_style_target(
    profiles: Sequence[Any],
    *,
    floors: Mapping[str, Any] | None = None,
) -> StyleTarget | None:
    """Blend profile baselines using the same generic-to-specific weights as injection."""
    if not profiles:
        return None
    if floors is None:
        try:
            floors = load_yaml_config("tolerance_floors")
        except FileNotFoundError:
            floors = {}

    blended = blend_profile_metric_baselines(profiles)
    targets: dict[str, StyleMetricTarget] = {}
    for metric in _TEXT_METRICS:
        component = blended.get(metric)
        if not isinstance(component, Mapping):
            continue
        target_mean = float(component["mean"])
        target_std = float(component["std"])
        floor = _finite_float((floors or {}).get(metric, DEFAULT_FLOOR))
        if floor is None or floor <= 0:
            floor = DEFAULT_FLOOR
        targets[metric] = StyleMetricTarget(
            metric=metric,
            mean=target_mean,
            std=target_std,
            tolerance=max(target_std * 1.25, floor),
            component_count=int(component.get("component_count", 1)),
        )

    if not targets:
        return None
    profile_ids = tuple(str(getattr(profile, "profile_id", "")) for profile in profiles)
    projection = {
        "scorer_version": SCORER_VERSION,
        "profile_ids": profile_ids,
        "metrics": {
            name: {
                "mean": target.mean,
                "std": target.std,
                "tolerance": target.tolerance,
                "component_count": target.component_count,
            }
            for name, target in sorted(targets.items())
        },
    }
    return StyleTarget(
        profile_ids=profile_ids,
        metrics=targets,
        target_hash=hashlib.sha256(
            canonical_json(projection).encode("utf-8")
        ).hexdigest(),
    )


def _metric_group(metric: str) -> str:
    for group, metrics in _METRIC_GROUPS.items():
        if metric in metrics:
            return group
    return "other"


def assess_candidate_text(
    row_id: str,
    text: str,
    quality_score: float,
    target: StyleTarget | None,
    policy: CandidateRerankPolicy,
    *,
    plagiarism_corpus: Sequence[str] = (),
) -> CandidateAssessment:
    assessment = CandidateAssessment(row_id=row_id, quality_score=float(quality_score))
    assessment.substantive_chars = len(
        re.findall(r"[A-Za-z0-9\u4e00-\u9fff]", text or "")
    )

    if target is not None and text and text.strip():
        actual_metrics = compute_generated_metrics(text)
        grouped: dict[str, list[float]] = {}
        deviations: list[tuple[float, str]] = []
        for metric, metric_target in target.metrics.items():
            actual = _finite_float(actual_metrics.get(metric))
            if actual is None:
                continue
            deviation = abs(actual - metric_target.mean) / max(
                metric_target.tolerance, 1e-9
            )
            # Gaussian closeness makes tolerance meaningful (d=1 -> 0.607) while
            # clipping prevents one noisy lexical proxy from dominating diagnostics.
            closeness = math.exp(-0.5 * min(deviation, 4.0) ** 2)
            grouped.setdefault(_metric_group(metric), []).append(closeness)
            deviations.append((deviation, metric))

        assessment.metric_count = sum(len(values) for values in grouped.values())
        assessment.group_scores = {
            group: sum(values) / len(values)
            for group, values in grouped.items()
            if values
        }
        if assessment.group_scores:
            assessment.style_score = sum(assessment.group_scores.values()) / len(
                assessment.group_scores
            )
        # 老画像没有 2026-08 新增的段落形态 baseline；置信度应按该画像实际可比
        # 的 target 数计算，不能仅因 schema 迭代把历史画像系统性降权。
        metric_coverage = min(
            1.0, assessment.metric_count / max(1, len(target.metrics))
        )
        length_coverage = min(
            1.0, assessment.substantive_chars / max(1, policy.min_substantive_chars)
        )
        assessment.style_confidence = min(metric_coverage, length_coverage)
        assessment.style_eligible = bool(
            assessment.style_score is not None
            and assessment.metric_count >= policy.min_metric_count
            and assessment.substantive_chars >= policy.min_substantive_chars
            and assessment.style_confidence >= policy.min_confidence
        )
        assessment.top_deviations = [
            {"metric": metric, "deviation_ratio": round(deviation, 4)}
            for deviation, metric in sorted(
                deviations, key=lambda item: (-item[0], item[1])
            )[:5]
        ]

    corpus = [item for item in plagiarism_corpus if item]
    if corpus and text:
        report = check_plagiarism(
            text,
            corpus,
            ngram_size=policy.plagiarism_ngram_size,
            threshold_chars=policy.plagiarism_threshold_chars,
        )
        assessment.plagiarism_checked = True
        assessment.plagiarism_passed = bool(report.passed)
        assessment.plagiarism_hit_count = len(report.hits)
        assessment.plagiarism_max_match_chars = max(
            (int(hit.matched_length) for hit in report.hits),
            default=0,
        )
    return assessment


def rerank_candidate_pairs(
    candidate_pairs: Sequence[tuple[Any, float]],
    *,
    target: StyleTarget | None,
    policy: CandidateRerankPolicy,
    plagiarism_corpus: Sequence[str] = (),
    active_allowed: bool = True,
    unavailable_reason: str | None = None,
) -> CandidateRerankOutcome:
    """Return a bounded deterministic order and a compact per-candidate audit."""
    indexed_pairs = list(enumerate(candidate_pairs))
    indexed_pairs.sort(key=lambda item: (-float(item[1][1]), item[0]))
    # Python's stable input position is the established tie-break.  Shadow mode
    # must not reorder equal-quality candidates merely because row IDs differ.
    quality_order = [pair for _index, pair in indexed_pairs]
    assessments = {
        str(getattr(candidate, "row_id", "")): assess_candidate_text(
            str(getattr(candidate, "row_id", "")),
            str(getattr(candidate, "content", "") or ""),
            float(quality_score),
            target,
            policy,
            plagiarism_corpus=plagiarism_corpus,
        )
        for candidate, quality_score in quality_order
    }
    if not quality_order:
        return CandidateRerankOutcome(
            ordered_candidates=[],
            assessments=assessments,
            audit={
                "scorer_version": SCORER_VERSION,
                "requested_mode": policy.requested_mode,
                "policy_mode": policy.effective_mode,
                "applied_mode": "off",
                "reason": "no_candidates",
                "selected_changed": False,
            },
        )

    original_best_id = str(getattr(quality_order[0][0], "row_id", ""))
    safe_pairs = [
        pair
        for pair in quality_order
        if assessments[str(getattr(pair[0], "row_id", ""))].plagiarism_passed
        is not False
    ]
    rejected_pairs = [
        pair
        for pair in quality_order
        if assessments[str(getattr(pair[0], "row_id", ""))].plagiarism_passed is False
    ]
    plagiarism_guard_applied = bool(
        policy.plagiarism_guard and safe_pairs and rejected_pairs
    )
    base_order = (
        safe_pairs + rejected_pairs if plagiarism_guard_applied else list(quality_order)
    )

    applied_mode = "shadow" if policy.effective_mode != "off" else "off"
    reason = unavailable_reason or "shadow_policy"
    ordered_pairs = list(base_order)
    if policy.effective_mode == "off":
        reason = unavailable_reason or "policy_off"
    elif target is None:
        reason = unavailable_reason or "style_target_unavailable"
    elif policy.effective_mode == "active" and active_allowed:
        best_safe_pair = base_order[0]
        best_safe_id = str(getattr(best_safe_pair[0], "row_id", ""))
        best_safe_quality = float(best_safe_pair[1])
        eligible_pairs = [
            pair
            for pair in base_order
            if assessments[str(getattr(pair[0], "row_id", ""))].style_eligible
            and assessments[str(getattr(pair[0], "row_id", ""))].plagiarism_passed
            is not False
            and float(pair[1]) >= best_safe_quality - policy.max_quality_drop
        ]
        eligible_ids = {str(getattr(pair[0], "row_id", "")) for pair in eligible_pairs}
        if best_safe_id not in eligible_ids:
            reason = "quality_leader_style_evidence_insufficient"
        elif len(eligible_pairs) < 2:
            reason = "insufficient_comparable_candidates"
        else:
            for candidate, quality_score in eligible_pairs:
                assessment = assessments[str(getattr(candidate, "row_id", ""))]
                assert assessment.style_score is not None
                effective_style = assessment.style_score * assessment.style_confidence
                assessment.combined_score = (1.0 - policy.style_weight) * float(
                    quality_score
                ) + policy.style_weight * effective_style
            ranked_eligible = sorted(
                eligible_pairs,
                key=lambda pair: (
                    -float(
                        assessments[str(getattr(pair[0], "row_id", ""))].combined_score
                        or 0.0
                    ),
                    -float(pair[1]),
                    str(getattr(pair[0], "row_id", "")),
                ),
            )
            ranked_ids = {
                str(getattr(pair[0], "row_id", "")) for pair in ranked_eligible
            }
            ordered_pairs = ranked_eligible + [
                pair
                for pair in base_order
                if str(getattr(pair[0], "row_id", "")) not in ranked_ids
            ]
            applied_mode = "active"
            reason = "bounded_style_rerank"
    elif policy.effective_mode == "active":
        reason = unavailable_reason or "active_lineage_not_verified"

    ordered_candidates = [candidate for candidate, _score in ordered_pairs]
    selected_id = str(getattr(ordered_candidates[0], "row_id", ""))
    for rank, candidate in enumerate(ordered_candidates):
        row_id = str(getattr(candidate, "row_id", ""))
        assessment = assessments[row_id]
        assessment.rank = rank
        assessment.selected = rank == 0
        if rank == 0:
            if (
                plagiarism_guard_applied
                and row_id != original_best_id
                and applied_mode != "active"
            ):
                assessment.selection_reason = "plagiarism_guard"
            elif applied_mode == "active" and row_id != original_best_id:
                assessment.selection_reason = "bounded_style_rerank"
            else:
                assessment.selection_reason = "quality_order"
        elif assessment.plagiarism_passed is False and plagiarism_guard_applied:
            assessment.selection_reason = "plagiarism_rejected"
        elif assessment.style_eligible and applied_mode == "active":
            assessment.selection_reason = "style_ranked"

    audit = {
        "scorer_version": SCORER_VERSION,
        "requested_mode": policy.requested_mode,
        "policy_mode": policy.effective_mode,
        "applied_mode": applied_mode,
        "reason": reason,
        "style_weight": policy.style_weight,
        "max_quality_drop": policy.max_quality_drop,
        "profile_ids": list(target.profile_ids) if target is not None else [],
        "target_hash": target.target_hash if target is not None else None,
        "metric_count": len(target.metrics) if target is not None else 0,
        "activation_report_id": policy.activation_report_id,
        "activation_report_sha256": policy.activation_report_sha256,
        "configuration_errors": list(policy.configuration_errors),
        "plagiarism_guard_applied": plagiarism_guard_applied,
        "quality_leader_row_id": original_best_id,
        "selected_row_id": selected_id,
        "selected_changed": selected_id != original_best_id,
    }
    return CandidateRerankOutcome(
        ordered_candidates=ordered_candidates,
        assessments=assessments,
        audit=audit,
    )


def _bundle_profile_ids(bundle: Mapping[str, Any]) -> list[str]:
    snapshot = bundle.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    refs = snapshot.get("source_version_refs")
    refs = refs if isinstance(refs, Mapping) else {}
    raw = refs.get("reference_profile_ids")
    if isinstance(raw, str):
        values: Iterable[Any] = [raw]
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = raw
    else:
        values = []
    return list(
        dict.fromkeys(str(value).strip() for value in values if str(value).strip())
    )


def _frozen_source_matches(profile: Any, repo: StyleReferenceRepository) -> bool:
    frozen_book = getattr(profile, "runtime_contract_book", None)
    if not isinstance(frozen_book, Mapping):
        return True
    book_id = str(getattr(profile, "book_id", "") or "")
    current_book = repo.get_book(book_id) if book_id else None
    return bool(
        current_book is not None
        and str(getattr(current_book, "text_checksum", "") or "")
        == str(frozen_book.get("text_checksum") or "")
    )


class StyleCandidateReranker:
    """Resolve the frozen style lineage and apply the pure candidate reranker."""

    def __init__(
        self,
        session: Any,
        *,
        policy: CandidateRerankPolicy | None = None,
        quality_score: Callable[[str], float] | None = None,
    ) -> None:
        self.session = session
        self.repo = StyleReferenceRepository(session)
        if policy is None:
            try:
                raw_policy = load_yaml_config("candidate_rerank")
            except (FileNotFoundError, TypeError, ValueError):
                raw_policy = {}
            policy = CandidateRerankPolicy.from_mapping(raw_policy)
        self.policy = policy
        self.quality_score = quality_score

    def rerank(
        self,
        scene: Any,
        bundle: Mapping[str, Any],
        candidates: Sequence[Any],
        *,
        quality_scores: Mapping[str, float] | None = None,
    ) -> CandidateRerankOutcome:
        contract_state = resolve_style_runtime_contract_state(bundle)
        runtime_contract_status = contract_state.status
        runtime_contract = contract_state.contract
        profile_ids = (
            list(runtime_contract["profile_ids"])
            if runtime_contract is not None
            else _bundle_profile_ids(bundle)
        )
        pairs: list[tuple[Any, float]] = []
        for candidate in candidates:
            row_id = str(getattr(candidate, "row_id", ""))
            score = (quality_scores or {}).get(row_id)
            if score is None:
                if self.quality_score is None:
                    raise ValueError(f"quality score missing for candidate {row_id!r}")
                score = self.quality_score(str(getattr(candidate, "content", "") or ""))
            pairs.append((candidate, float(score)))

        if contract_state.mode == "absent":
            outcome = rerank_candidate_pairs(
                pairs,
                target=None,
                policy=self.policy,
                unavailable_reason="bundle_has_no_style_profile",
            )
            outcome.audit["runtime_contract_status"] = runtime_contract_status
            return outcome

        if contract_state.error_code is not None:
            # A contract-aware bundle whose snapshot is missing/degraded must not
            # quietly score against today's live profile. Keep only the
            # independent source-copy safety guard when its corpus is available.
            safety_corpus: list[str] = []
            for profile_id in profile_ids:
                profile = self.repo.get_profile(profile_id)
                if profile is not None:
                    safety_corpus.extend(
                        _load_plagiarism_corpus(
                            self.repo,
                            str(getattr(profile, "book_id", "")),
                        )
                    )
            outcome = rerank_candidate_pairs(
                pairs,
                target=None,
                policy=self.policy,
                plagiarism_corpus=list(
                    dict.fromkeys(item for item in safety_corpus if item)
                ),
                active_allowed=False,
                unavailable_reason="frozen_runtime_contract_unavailable",
            )
            outcome.audit["bundle_profile_ids"] = profile_ids
            outcome.audit["runtime_contract_status"] = runtime_contract_status
            outcome.audit["runtime_contract_error_code"] = contract_state.error_code
            return outcome

        if not profile_ids:
            outcome = rerank_candidate_pairs(
                pairs,
                target=None,
                policy=self.policy,
                unavailable_reason="bundle_has_no_style_profile",
            )
            outcome.audit["runtime_contract_status"] = runtime_contract_status
            return outcome

        live_profiles = [
            self.repo.get_profile(profile_id) for profile_id in profile_ids
        ]
        profiles_complete = all(profile is not None for profile in live_profiles)
        if runtime_contract is not None:
            # Frozen snapshots are the scoring truth. Repeated profile layers remain
            # repeated so generic→specific weights mirror prompt composition.
            resolved_profiles = contract_profile_objects(runtime_contract)
        else:
            resolved_profiles = [
                profile for profile in live_profiles if profile is not None
            ]
        statuses_active = profiles_complete and all(
            getattr(profile, "status", None) == "active"
            for profile in live_profiles
            if profile is not None
        )
        target = build_style_target(resolved_profiles) if resolved_profiles else None

        live_layers = InjectionService(self.session).resolve_binding_layers(
            getattr(scene, "project_id", None),
            "scene_generation",
            character_ids=ordered_character_ids(
                getattr(scene, "pov_character_id", None),
                getattr(scene, "onstage_chars_json", None),
            ),
            scene_id=getattr(scene, "scene_id", None),
        )
        live_profile_ids = list(
            dict.fromkeys(str(layer.profile_id) for layer in live_layers)
        )
        live_contract_hash = None
        if runtime_contract is not None:
            try:
                live_contract = build_style_runtime_contract(
                    self.repo,
                    live_layers,
                    task_type="scene_generation",
                )
                live_contract_hash = (
                    str(live_contract["contract_hash"])
                    if live_contract is not None
                    else None
                )
            except Exception:  # noqa: BLE001 — active mode fails closed
                live_contract_hash = None
            lineage_match = live_contract_hash == runtime_contract["contract_hash"]
        else:
            lineage_match = live_profile_ids == profile_ids

        corpus: list[str] = []
        frozen_sources_complete = True
        for profile in resolved_profiles:
            if not _frozen_source_matches(profile, self.repo):
                frozen_sources_complete = False
                continue
            corpus.extend(
                _load_plagiarism_corpus(self.repo, str(getattr(profile, "book_id", "")))
            )
        corpus = list(dict.fromkeys(item for item in corpus if item))

        unavailable_reason = None
        if not frozen_sources_complete:
            unavailable_reason = "frozen_reference_source_changed"
        elif not profiles_complete:
            unavailable_reason = "frozen_profile_missing"
        elif target is None or len(target.metrics) < self.policy.min_metric_count:
            unavailable_reason = "profile_metrics_insufficient"
        elif not statuses_active:
            unavailable_reason = "frozen_profile_not_active"
        elif not lineage_match:
            unavailable_reason = (
                "live_contract_differs_from_frozen_bundle"
                if runtime_contract is not None
                else "live_binding_differs_from_frozen_bundle"
            )

        outcome = rerank_candidate_pairs(
            pairs,
            target=target,
            policy=self.policy,
            plagiarism_corpus=corpus,
            active_allowed=bool(
                profiles_complete
                and frozen_sources_complete
                and statuses_active
                and lineage_match
                and target is not None
                and len(target.metrics) >= self.policy.min_metric_count
            ),
            unavailable_reason=unavailable_reason,
        )
        outcome.audit["bundle_profile_ids"] = profile_ids
        outcome.audit["live_profile_ids"] = live_profile_ids
        outcome.audit["lineage_match"] = lineage_match
        outcome.audit["frozen_sources_complete"] = frozen_sources_complete
        outcome.audit["runtime_contract_version"] = (
            runtime_contract.get("contract_version")
            if runtime_contract is not None
            else None
        )
        outcome.audit["runtime_contract_hash"] = (
            runtime_contract.get("contract_hash")
            if runtime_contract is not None
            else None
        )
        outcome.audit["live_runtime_contract_hash"] = live_contract_hash
        outcome.audit["runtime_contract_status"] = runtime_contract_status
        return outcome


__all__ = [
    "SCORER_VERSION",
    "CandidateAssessment",
    "CandidateRerankOutcome",
    "CandidateRerankPolicy",
    "StyleCandidateReranker",
    "StyleMetricTarget",
    "StyleTarget",
    "assess_candidate_text",
    "build_style_target",
    "rerank_candidate_pairs",
]
