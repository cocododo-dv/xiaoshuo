"""Dynamic style drift detection + adaptive correction — blueprint §9.

After each chapter is archived, compare quantitative style metrics against the
reference profile baseline.  When deviation on any dimension exceeds a threshold,
record a drift event so the next chapter's bundle can inject targeted corrective
guidance.

Uses all 18 content-computed metrics from MetricsEngine (13 language + 5 sensory).
The 8 paragraph-type ratio metrics (dialogue_ratio, psychology_ratio, etc.) are
excluded because they require LLM-based paragraph classification unavailable at
drift-detection time.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import FinalScene, SceneCard
from novel_system.services.style_reference.metrics import (
    METRIC_NAMES,
    MetricsEngine,
    ParagraphRecord,
)

_LOGGER = logging.getLogger(__name__)

DRIFT_THRESHOLD = 0.25
MAX_CORRECTIVE_DIMENSIONS = 5

_TYPE_RATIO_METRICS = frozenset({
    "dialogue_ratio",
    "psychology_ratio",
    "description_env_ratio",
    "description_char_ratio",
    "action_ratio",
    "narration_ratio",
    "transition_ratio",
    "flashback_ratio",
})

_DRIFTABLE_METRICS = tuple(m for m in METRIC_NAMES if m not in _TYPE_RATIO_METRICS)

_LANGUAGE_METRICS = frozenset({
    "avg_sentence_length",
    "sentence_length_std",
    "short_sentence_ratio",
    "long_sentence_ratio",
    "punctuation_density_per_1k",
    "dash_em_density_per_1k",
    "ellipsis_density_per_1k",
    "semicolon_density_per_1k",
    "question_density_per_1k",
    "classical_word_ratio",
    "colloquial_marker_ratio",
    "metaphor_density_per_1k",
    "personification_density_per_1k",
})

_SENSORY_METRICS = frozenset({
    "sensory_visual_per_1k",
    "sensory_auditory_per_1k",
    "sensory_olfactory_per_1k",
    "sensory_tactile_per_1k",
    "sensory_gustatory_per_1k",
})

_DIMENSION_ADVICE: dict[str, str] = {
    "avg_sentence_length": "Adjust average sentence length — mix short punchy sentences with longer flowing ones",
    "sentence_length_std": "Vary sentence lengths more/less — the rhythm feels too uniform/chaotic",
    "short_sentence_ratio": "Adjust the proportion of short sentences (≤10 chars)",
    "long_sentence_ratio": "Adjust the proportion of long sentences (≥30 chars)",
    "punctuation_density_per_1k": "Adjust punctuation frequency to match the reference cadence",
    "dash_em_density_per_1k": "Adjust em-dash (——) usage for parenthetical/dramatic breaks",
    "ellipsis_density_per_1k": "Adjust ellipsis (……) usage for trailing-off effects",
    "semicolon_density_per_1k": "Adjust semicolon usage for clause-joining rhythm",
    "question_density_per_1k": "Adjust interrogative sentence frequency",
    "classical_word_ratio": "Adjust classical/literary word density (之/乎/者/也/焉/矣)",
    "colloquial_marker_ratio": "Adjust colloquial particle density (吧/呢/啊/嗯/哎/嘛)",
    "metaphor_density_per_1k": "Adjust metaphor/simile frequency (像/如同/仿佛/犹如)",
    "personification_density_per_1k": "Adjust personification frequency",
    "sensory_visual_per_1k": "Adjust visual sensory detail density",
    "sensory_auditory_per_1k": "Adjust auditory sensory detail density",
    "sensory_olfactory_per_1k": "Adjust olfactory sensory detail density",
    "sensory_tactile_per_1k": "Adjust tactile sensory detail density",
    "sensory_gustatory_per_1k": "Adjust gustatory sensory detail density",
}


@dataclass(slots=True)
class DimensionDrift:
    dimension: str
    baseline_value: float
    current_value: float
    deviation: float

    @property
    def direction(self) -> str:
        return "high" if self.current_value > self.baseline_value else "low"

    @property
    def layer(self) -> str:
        if self.dimension in _SENSORY_METRICS:
            return "sensory"
        return "language"


@dataclass(slots=True)
class DriftReport:
    chapter_id: str
    drifts: list[DimensionDrift] = field(default_factory=list)
    metrics_computed: int = 0

    @property
    def has_drift(self) -> bool:
        return len(self.drifts) > 0


def detect_chapter_drift(
    session: Session,
    chapter_id: str,
    baseline_metrics: dict[str, float] | None = None,
) -> DriftReport:
    """Compare chapter's aggregate metrics against baseline profile.

    Uses 18 content-computed metrics from MetricsEngine (13 language-layer +
    5 sensory-layer).  Paragraph-type ratio metrics are excluded as they
    require LLM classification not available at drift-detection time.
    """
    scenes = session.execute(
        select(FinalScene)
        .join(SceneCard, SceneCard.scene_id == FinalScene.scene_id)
        .where(
            FinalScene.chapter_id == chapter_id,
            FinalScene.status.in_(("approved", "near_final_ready")),
            SceneCard.trashed_flag == 0,
        )
        .order_by(SceneCard.scene_seq.asc())
    ).scalars().all()

    if not scenes:
        return DriftReport(chapter_id=chapter_id)

    combined = "\n".join(s.content or "" for s in scenes if s.content)
    if not combined.strip():
        return DriftReport(chapter_id=chapter_id)

    current = _compute_metrics(combined)
    if not baseline_metrics:
        return DriftReport(chapter_id=chapter_id, metrics_computed=len(current))

    report = DriftReport(chapter_id=chapter_id, metrics_computed=len(current))
    for dim in _DRIFTABLE_METRICS:
        cur_val = current.get(dim)
        base_val = baseline_metrics.get(dim)
        if cur_val is None or base_val is None or base_val == 0:
            continue
        deviation = abs(cur_val - base_val) / max(abs(base_val), 0.01)
        if deviation >= DRIFT_THRESHOLD:
            report.drifts.append(DimensionDrift(
                dimension=dim,
                baseline_value=base_val,
                current_value=cur_val,
                deviation=round(deviation, 3),
            ))

    report.drifts.sort(key=lambda d: d.deviation, reverse=True)
    report.drifts = report.drifts[:MAX_CORRECTIVE_DIMENSIONS]
    return report


def format_drift_correction_prompt(report: DriftReport) -> str | None:
    """Format drift findings as corrective guidance for the next chapter's bundle."""
    if not report.has_drift:
        return None
    lines = ["## Style Drift Correction (auto-detected from previous chapter)"]
    lines.append("The following dimensions drifted from the reference profile baseline.")
    lines.append("Adjust the next chapter to steer back toward the target:\n")

    for drift in report.drifts:
        direction_label = "too high" if drift.direction == "high" else "too low"
        action = "Reduce" if drift.direction == "high" else "Increase"
        advice = _DIMENSION_ADVICE.get(drift.dimension, f"{action} this dimension")

        lines.append(
            f"- **{drift.dimension}** [{drift.layer}]: {direction_label} "
            f"(baseline={drift.baseline_value:.2f}, actual={drift.current_value:.2f}, "
            f"deviation={drift.deviation:.0%}). {advice}."
        )

    return "\n".join(lines)


# §9 Defect B: dimension → paragraph types mapping for "show, don't tell" drift correction.
# When a dimension drifts, we pick few-shot exemplars from paragraph types that best
# demonstrate the target baseline for that dimension.
_DIMENSION_PREFERRED_PTYPES: dict[str, tuple[str, ...]] = {
    "avg_sentence_length": ("narration", "description_env", "psychology"),
    "sentence_length_std": ("narration", "action", "dialogue"),
    "short_sentence_ratio": ("action", "dialogue", "narration"),
    "long_sentence_ratio": ("description_env", "psychology", "narration"),
    "punctuation_density_per_1k": ("dialogue", "narration", "action"),
    "dash_em_density_per_1k": ("psychology", "narration", "description_env"),
    "ellipsis_density_per_1k": ("dialogue", "psychology", "narration"),
    "semicolon_density_per_1k": ("narration", "description_env", "psychology"),
    "question_density_per_1k": ("dialogue", "psychology", "narration"),
    "classical_word_ratio": ("narration", "description_env", "description_char"),
    "colloquial_marker_ratio": ("dialogue", "narration", "action"),
    "metaphor_density_per_1k": ("description_env", "description_char", "narration"),
    "personification_density_per_1k": ("description_env", "description_char", "narration"),
    "sensory_visual_per_1k": ("description_env", "description_char", "action"),
    "sensory_auditory_per_1k": ("description_env", "action", "narration"),
    "sensory_olfactory_per_1k": ("description_env", "narration", "description_char"),
    "sensory_tactile_per_1k": ("description_env", "description_char", "action"),
    "sensory_gustatory_per_1k": ("description_env", "narration", "description_char"),
}


def drift_corrective_ptype_priority(report: DriftReport) -> list[str]:
    """Return paragraph types re-ordered by drift relevance for few-shot selection.

    Blueprint §9: "下一章在 few-shot 中增加该维度的对比示例" — the corrected priority
    ensures the few-shot injection picks exemplars from paragraph types most relevant
    to the drifted dimensions, replacing the static default order.
    """
    if not report.has_drift:
        return []
    # Score each ptype by how many drifted dimensions list it (weighted by deviation)
    ptype_scores: dict[str, float] = {}
    for drift in report.drifts:
        preferred = _DIMENSION_PREFERRED_PTYPES.get(drift.dimension, ())
        for rank, ptype in enumerate(preferred):
            weight = drift.deviation * (len(preferred) - rank)
            ptype_scores[ptype] = ptype_scores.get(ptype, 0) + weight
    return sorted(ptype_scores, key=lambda p: ptype_scores[p], reverse=True)


def format_drift_dimensions_for_bundle(report: DriftReport) -> list[dict[str, Any]] | None:
    """Serialize drifted dimensions for injection into the generation bundle.

    The bundle builder passes this to the style injection service, which overrides
    the default few-shot paragraph-type priority to "show" the correct baseline
    rather than just "tell" the model to adjust.
    """
    if not report.has_drift:
        return None
    return [
        {
            "dimension": d.dimension,
            "direction": d.direction,
            "baseline": round(d.baseline_value, 3),
            "actual": round(d.current_value, 3),
            "deviation": d.deviation,
            "preferred_ptypes": list(_DIMENSION_PREFERRED_PTYPES.get(d.dimension, ())),
        }
        for d in report.drifts
    ]


def _compute_metrics(text: str) -> dict[str, float]:
    """Compute all 26 metrics via MetricsEngine; caller filters to driftable subset."""
    paragraphs_raw = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs_raw:
        return {}
    paragraphs = [ParagraphRecord(text=p, paragraph_type="narration") for p in paragraphs_raw]
    engine = MetricsEngine()
    return engine.compute_all(paragraphs)
