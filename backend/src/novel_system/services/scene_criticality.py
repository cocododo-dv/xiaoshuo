"""Scene criticality classification — blueprint §13 cost differentiation.

Classifies scenes as critical / standard / transition based on structural
signals. Critical scenes get full pipeline (N=5, critique pass, human gate);
transition scenes skip multi-path and critique for cost savings.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_system.db.models import SceneCard


CRITICAL_FUNCTION_TAGS = frozenset({"turn", "reveal"})
HIGH_TENSION_THRESHOLD = 7
GOLDEN_CHAPTER_COUNT = 3
GOLDEN_SCENE_SEQ_HEURISTIC = 9


@dataclass(slots=True)
class SceneCriticality:
    level: str  # "critical" | "standard" | "transition"
    reasons: list[str]
    best_of_n: int
    skip_critique: bool  # advisory: transition scenes may skip proactive editor passes
    human_gate: bool  # critical scenes get proactive human review before archival

    @property
    def is_critical(self) -> bool:
        return self.level == "critical"


def classify_scene(
    scene: SceneCard,
    *,
    chapter_seq: int | None = None,
    consecutive_transition_count: int | None = None,
    constraint_intensity: float | None = None,
) -> SceneCriticality:
    """Classify a scene's criticality from its spec fields.

    Signals that elevate to critical:
    - Function tag is turn/reveal
    - Tension target >= 7
    - is_chapter_last (chapter climax position)
    - scene_crucible is substantial (>30 chars — complex dramatic premise)
    - Writer brief flags (expected_reader_emotion contains strong markers)
    - Golden chapter (first 3 chapters — §10 黄金三章)

    Returns criticality with recommended pipeline settings.
    """
    reasons: list[str] = []
    score = 0

    writer_brief: dict[str, Any] = scene.writer_brief_json or {}

    is_golden = False
    if chapter_seq is not None:
        is_golden = chapter_seq <= GOLDEN_CHAPTER_COUNT
    if is_golden:
        score += 2
        reasons.append("golden_chapter")

    function_tag = writer_brief.get("function_tag") or ""
    if function_tag in CRITICAL_FUNCTION_TAGS:
        score += 3
        reasons.append(f"function_tag={function_tag}")

    tension_target = writer_brief.get("tension_target")
    if isinstance(tension_target, (int, float)) and tension_target >= HIGH_TENSION_THRESHOLD:
        score += 2
        reasons.append(f"tension={tension_target}")

    if scene.is_chapter_last == 1:
        score += 2
        reasons.append("chapter_climax")

    scene_crucible = writer_brief.get("scene_crucible") or ""
    if len(scene_crucible) > 30:
        score += 1
        reasons.append("substantial_crucible")

    scene_form = writer_brief.get("scene_form") or scene.scene_type or ""
    if scene_form == "proactive":
        score += 1
        reasons.append("proactive_scene")

    # §16 "breathing gap" — per-scene constraint_intensity slider overrides criticality
    if constraint_intensity is not None:
        if constraint_intensity <= 0.2:
            return SceneCriticality(
                level="transition",
                reasons=reasons + ["constraint_intensity_free_flow"],
                best_of_n=1,
                skip_critique=True,
                human_gate=False,
            )
        elif constraint_intensity >= 0.8:
            return SceneCriticality(
                level="critical",
                reasons=reasons + ["constraint_intensity_full_rigor"],
                best_of_n=5,
                skip_critique=False,
                human_gate=True,
            )
        else:
            return SceneCriticality(
                level="standard",
                reasons=reasons + [f"constraint_intensity={constraint_intensity:.1f}"],
                best_of_n=3,
                skip_critique=False,
                human_gate=False,
            )

    if score >= 4:
        return SceneCriticality(
            level="critical",
            reasons=reasons,
            best_of_n=5,
            skip_critique=False,
            human_gate=True,
        )
    elif score >= 2:
        return SceneCriticality(
            level="standard",
            reasons=reasons,
            best_of_n=3,
            skip_critique=False,
            human_gate=False,
        )
    else:
        # §6.4 mitigation: probabilistic promotion after consecutive transitions
        # prevents systematic "温吞" (tepidness) in long stretches of transition scenes
        if consecutive_transition_count is not None and consecutive_transition_count >= 3:
            return SceneCriticality(
                level="standard",
                reasons=reasons + ["promoted_after_3_consecutive_transitions"],
                best_of_n=3,
                skip_critique=False,
                human_gate=False,
            )
        return SceneCriticality(
            level="transition",
            reasons=reasons or ["default_transition"],
            best_of_n=1,
            skip_critique=True,
            human_gate=False,
        )
