"""Character decision weights & arc tracking — blueprint §11.

Stores probability distributions for how a character responds to situations,
and tracks how these weights shift across the story (the quantifiable arc).

Weights are stored in SnowflakeCharacterPlan.bible_json under the key
"decision_weights", avoiding the need for a migration.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import SnowflakeCharacterPlan


@dataclass(slots=True)
class DecisionWeight:
    situation: str
    options: dict[str, float]
    story_phase: str

    def dominant_option(self) -> str:
        return max(self.options, key=lambda k: self.options[k])

    def has_shifted(self, other: "DecisionWeight") -> bool:
        if self.situation != other.situation:
            return False
        return self.dominant_option() != other.dominant_option()


@dataclass(slots=True)
class ArcShift:
    character_id: str
    situation: str
    from_phase: str
    to_phase: str
    from_dominant: str
    to_dominant: str


class CharacterArcService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_decision_weights(
        self,
        project_id: str,
        character_id: str,
    ) -> list[DecisionWeight]:
        """Read decision weights from bible_json."""
        plan = self._get_plan(project_id, character_id)
        if plan is None:
            return []
        bible = plan.bible_json or {}
        raw_weights = bible.get("decision_weights", [])
        return [
            DecisionWeight(
                situation=w["situation"],
                options=w["options"],
                story_phase=w.get("story_phase", "default"),
            )
            for w in raw_weights
            if isinstance(w, dict) and "situation" in w and "options" in w
        ]

    def set_decision_weights(
        self,
        project_id: str,
        character_id: str,
        weights: list[dict[str, Any]],
    ) -> None:
        """Store decision weights in bible_json."""
        plan = self._get_plan(project_id, character_id)
        if plan is None:
            return
        bible = dict(plan.bible_json or {})
        bible["decision_weights"] = weights
        plan.bible_json = bible
        self.session.flush()

    def get_weight_at_phase(
        self,
        project_id: str,
        character_id: str,
        situation: str,
        story_phase: str,
    ) -> DecisionWeight | None:
        """Get a specific decision weight for a situation at a story phase."""
        weights = self.get_decision_weights(project_id, character_id)
        for w in weights:
            if w.situation == situation and w.story_phase == story_phase:
                return w
        for w in weights:
            if w.situation == situation:
                return w
        return None

    def detect_arc_shifts(
        self,
        project_id: str,
        character_id: str,
    ) -> list[ArcShift]:
        """Detect where decision weights shift between story phases."""
        weights = self.get_decision_weights(project_id, character_id)
        by_situation: dict[str, list[DecisionWeight]] = {}
        for w in weights:
            by_situation.setdefault(w.situation, []).append(w)

        shifts: list[ArcShift] = []
        for situation, phase_weights in by_situation.items():
            phase_weights.sort(key=lambda w: w.story_phase)
            for i in range(1, len(phase_weights)):
                prev, curr = phase_weights[i - 1], phase_weights[i]
                if prev.has_shifted(curr):
                    shifts.append(ArcShift(
                        character_id=character_id,
                        situation=situation,
                        from_phase=prev.story_phase,
                        to_phase=curr.story_phase,
                        from_dominant=prev.dominant_option(),
                        to_dominant=curr.dominant_option(),
                    ))
        return shifts

    def format_weights_for_prompt(
        self,
        project_id: str,
        character_id: str,
        story_phase: str = "current",
    ) -> str | None:
        """Format current decision weights as prompt injection."""
        weights = self.get_decision_weights(project_id, character_id)
        phase_weights = [w for w in weights if w.story_phase == story_phase]
        if not phase_weights:
            phase_weights = weights
        if not phase_weights:
            return None

        lines = [f"## Decision Weights for {character_id} (story phase: {story_phase})"]
        for w in phase_weights:
            options_str = " / ".join(f"{k} {v*100:.0f}%" for k, v in sorted(w.options.items(), key=lambda x: -x[1]))
            lines.append(f"- When facing {w.situation}: {options_str}")
        lines.append("\nThese weights guide character behavior — not deterministic, but the dominant option should be most likely.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Blueprint §11: progress-based weight interpolation
    # ------------------------------------------------------------------

    # Canonical ordering of story phases for interpolation
    PHASE_ORDER: tuple[str, ...] = (
        "opening", "early", "rising", "midpoint",
        "escalation", "crisis", "climax", "resolution",
        "default",  # fallback catch-all always at the end
    )

    def weights_at_progress(
        self,
        project_id: str,
        character_id: str,
        progress: float,
    ) -> list[DecisionWeight]:
        """Interpolate decision weights at a given story progress (0.0–1.0).

        Blueprint §11: "决策权重随故事推进迁移…迁移速度不均匀——关键转折场景
        允许较大跳变，普通场景只微调。"

        Groups weights by *situation*, sorts the available phases, maps them
        to equidistant progress anchors, then linearly interpolates each
        option's probability at the requested progress fraction.
        """
        progress = max(0.0, min(1.0, progress))
        all_weights = self.get_decision_weights(project_id, character_id)
        if not all_weights:
            return []

        by_situation: dict[str, list[DecisionWeight]] = {}
        for w in all_weights:
            by_situation.setdefault(w.situation, []).append(w)

        result: list[DecisionWeight] = []
        for situation, phase_weights in by_situation.items():
            interpolated = self._interpolate_situation(situation, phase_weights, progress)
            if interpolated is not None:
                result.append(interpolated)
        return result

    def _interpolate_situation(
        self,
        situation: str,
        phase_weights: list[DecisionWeight],
        progress: float,
    ) -> DecisionWeight | None:
        if len(phase_weights) == 0:
            return None
        if len(phase_weights) == 1:
            return DecisionWeight(
                situation=situation,
                options=dict(phase_weights[0].options),
                story_phase=f"interpolated@{progress:.2f}",
            )

        # Sort by canonical phase order
        def _phase_sort_key(w: DecisionWeight) -> int:
            phase = w.story_phase.lower().strip()
            for idx, canon in enumerate(self.PHASE_ORDER):
                if canon in phase or phase in canon:
                    return idx
            return len(self.PHASE_ORDER)

        sorted_weights = sorted(phase_weights, key=_phase_sort_key)

        # Map each phase to an equidistant anchor on 0.0–1.0
        n = len(sorted_weights)
        anchors = [i / max(n - 1, 1) for i in range(n)]

        # Find the two surrounding phases
        lower_idx = 0
        for i in range(n):
            if anchors[i] <= progress:
                lower_idx = i
        upper_idx = min(lower_idx + 1, n - 1)

        if lower_idx == upper_idx:
            return DecisionWeight(
                situation=situation,
                options=dict(sorted_weights[lower_idx].options),
                story_phase=f"interpolated@{progress:.2f}",
            )

        # Linear interpolation factor between the two anchors
        span = anchors[upper_idx] - anchors[lower_idx]
        t = (progress - anchors[lower_idx]) / span if span > 0 else 0.0

        lower_w = sorted_weights[lower_idx]
        upper_w = sorted_weights[upper_idx]
        all_options = set(lower_w.options) | set(upper_w.options)

        interpolated_options: dict[str, float] = {}
        for opt in all_options:
            v_low = lower_w.options.get(opt, 0.0)
            v_high = upper_w.options.get(opt, 0.0)
            interpolated_options[opt] = round(v_low + t * (v_high - v_low), 3)

        # Normalize to sum to 1.0
        total = sum(interpolated_options.values())
        if total > 0:
            interpolated_options = {k: round(v / total, 3) for k, v in interpolated_options.items()}

        return DecisionWeight(
            situation=situation,
            options=interpolated_options,
            story_phase=f"interpolated@{progress:.2f}",
        )

    def format_weights_at_progress_for_prompt(
        self,
        project_id: str,
        character_id: str,
        progress: float,
    ) -> str | None:
        """Format interpolated decision weights at a given progress as prompt injection."""
        weights = self.weights_at_progress(project_id, character_id, progress)
        if not weights:
            return None

        lines = [
            f"## Decision Weights for {character_id} (progress: {progress:.0%})",
            "These weights reflect the character's current arc position — "
            "they shift across the story as the character grows.",
        ]
        for w in weights:
            options_str = " / ".join(
                f"{k} {v*100:.0f}%" for k, v in sorted(w.options.items(), key=lambda x: -x[1])
            )
            lines.append(f"- When facing {w.situation}: {options_str}")
        lines.append(
            "\nHonor these weights in the character's behavior. The dominant option "
            "should be most likely, but not deterministic."
        )
        return "\n".join(lines)

    def _get_plan(self, project_id: str, character_id: str) -> SnowflakeCharacterPlan | None:
        return self.session.execute(
            select(SnowflakeCharacterPlan)
            .where(
                SnowflakeCharacterPlan.project_id == project_id,
                SnowflakeCharacterPlan.character_id == character_id,
            )
            .order_by(SnowflakeCharacterPlan.updated_at.desc())
        ).scalars().first()
