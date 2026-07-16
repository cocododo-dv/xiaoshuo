"""Relationship dynamics matrix — blueprint §11.

Tracks pairwise character relationships with:
- Current relationship state (ally/rival/mentor/student/lover/stranger)
- Power balance (who has leverage)
- Information asymmetry (who knows what the other doesn't)
- Tension potential (what could create conflict between them)
- Recent trajectory (warming/cooling/stable/volatile)

Storage: WorkProfile with profile_key="relationship_matrix".
Live info-asymmetry data is merged from NarrativeEventLog at query time.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import WorkProfile


_LOGGER = logging.getLogger(__name__)

RELATIONSHIP_TYPES = (
    "ally", "rival", "mentor", "student", "lover",
    "stranger", "family", "complex",
)
POWER_BALANCE_VALUES = ("A_dominant", "B_dominant", "equal", "contested")
TRAJECTORY_VALUES = ("warming", "cooling", "stable", "volatile")


@dataclass(slots=True)
class RelationshipEdge:
    character_a: str
    character_b: str
    relationship_type: str = "stranger"
    power_balance: str = "equal"
    tension_source: str = ""
    trajectory: str = "stable"
    a_secret_from_b: list[str] = field(default_factory=list)
    b_secret_from_a: list[str] = field(default_factory=list)

    def pair_key(self) -> tuple[str, str]:
        return (min(self.character_a, self.character_b),
                max(self.character_a, self.character_b))

    def to_dict(self) -> dict[str, Any]:
        return {
            "character_a": self.character_a,
            "character_b": self.character_b,
            "relationship_type": self.relationship_type,
            "power_balance": self.power_balance,
            "tension_source": self.tension_source,
            "trajectory": self.trajectory,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RelationshipEdge:
        return cls(
            character_a=d.get("character_a", ""),
            character_b=d.get("character_b", ""),
            relationship_type=d.get("relationship_type", "stranger"),
            power_balance=d.get("power_balance", "equal"),
            tension_source=d.get("tension_source", ""),
            trajectory=d.get("trajectory", "stable"),
        )


@dataclass(slots=True)
class RelationshipMatrix:
    project_id: str
    edges: list[RelationshipEdge] = field(default_factory=list)


class RelationshipMatrixService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build_matrix(
        self,
        project_id: str,
        scene_seq: int | None,
        onstage_character_ids: list[str],
        *,
        scene_id: str | None = None,
    ) -> RelationshipMatrix:
        """Build the relationship matrix for onstage characters.

        Merges static relationship definitions (from WorkProfile) with
        live information-asymmetry data from the event log.
        """
        stored_edges = self._load_stored_edges(project_id)
        onstage_set = set(onstage_character_ids)

        knowledge = self._load_knowledge_sets(
            project_id,
            scene_seq,
            onstage_character_ids,
            scene_id=scene_id,
        )

        edges: list[RelationshipEdge] = []
        seen_pairs: set[tuple[str, str]] = set()

        for edge in stored_edges:
            if edge.character_a not in onstage_set or edge.character_b not in onstage_set:
                continue
            pair = edge.pair_key()
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            self._enrich_with_asymmetry(edge, knowledge)
            edges.append(edge)

        for i, char_a in enumerate(onstage_character_ids):
            for char_b in onstage_character_ids[i + 1:]:
                pair = (min(char_a, char_b), max(char_a, char_b))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                edge = RelationshipEdge(character_a=char_a, character_b=char_b)
                self._enrich_with_asymmetry(edge, knowledge)
                if edge.a_secret_from_b or edge.b_secret_from_a:
                    edges.append(edge)

        return RelationshipMatrix(project_id=project_id, edges=edges)

    def set_relationship(self, project_id: str, edge: RelationshipEdge) -> None:
        """Store or update a relationship edge in the project's WorkProfile."""
        profile = self._get_profile(project_id)
        edge_dicts: list[dict[str, Any]]
        if profile is None:
            edge_dicts = [edge.to_dict()]
            profile = WorkProfile(
                profile_id=f"wp_rm_{uuid.uuid4().hex[:12]}",
                scope_type="global",
                scope_ref_id=project_id,
                profile_key="relationship_matrix",
                display_name="关系动力学矩阵",
                status="active",
                profile_json={"edges": edge_dicts},
            )
            self.session.add(profile)
        else:
            edge_dicts = list((profile.profile_json or {}).get("edges", []))
            pair = edge.pair_key()
            edge_dicts = [
                e for e in edge_dicts
                if RelationshipEdge.from_dict(e).pair_key() != pair
            ]
            edge_dicts.append(edge.to_dict())
            profile.profile_json = {"edges": edge_dicts}
            profile.status = "active"
        self.session.flush()

    @staticmethod
    def format_for_prompt(matrix: RelationshipMatrix) -> str | None:
        """Format as a prompt section for generation context injection."""
        if not matrix.edges:
            return None
        lines = ["## Relationship Dynamics Matrix"]
        lines.append("Use these dynamics to create subtext and tension in dialogue/interaction.\n")

        for edge in matrix.edges:
            header = (
                f"**{edge.character_a} ↔ {edge.character_b}**: "
                f"{edge.relationship_type} ({edge.trajectory}), "
                f"power: {edge.power_balance}"
            )
            lines.append(header)
            if edge.tension_source:
                lines.append(f"  tension source: {edge.tension_source}")
            if edge.a_secret_from_b:
                lines.append(f"  {edge.character_a} withholds from {edge.character_b}: "
                             + "; ".join(edge.a_secret_from_b[:3]))
            if edge.b_secret_from_a:
                lines.append(f"  {edge.character_b} withholds from {edge.character_a}: "
                             + "; ".join(edge.b_secret_from_a[:3]))
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def tension_opportunities(matrix: RelationshipMatrix) -> list[str]:
        """Identify tension-generating interaction opportunities."""
        opportunities: list[str] = []
        for edge in matrix.edges:
            has_secrets = bool(edge.a_secret_from_b or edge.b_secret_from_a)

            if edge.relationship_type == "ally" and has_secrets:
                secret_holder = edge.character_a if edge.a_secret_from_b else edge.character_b
                opportunities.append(
                    f"{edge.character_a} and {edge.character_b} are allies but "
                    f"{secret_holder} is hiding information — potential trust breach."
                )
            elif edge.relationship_type == "rival" and edge.trajectory == "warming":
                opportunities.append(
                    f"{edge.character_a} and {edge.character_b} are rivals but warming — "
                    f"reluctant cooperation or betrayal of expectations."
                )
            elif edge.power_balance == "contested" and has_secrets:
                opportunities.append(
                    f"Power between {edge.character_a} and {edge.character_b} is contested "
                    f"and one holds hidden knowledge — leverage shift possible."
                )
            elif edge.trajectory == "volatile":
                opportunities.append(
                    f"{edge.character_a} ↔ {edge.character_b} relationship is volatile — "
                    f"small triggers can cause disproportionate reactions."
                )
            elif edge.relationship_type == "mentor" and edge.power_balance == "B_dominant":
                opportunities.append(
                    f"{edge.character_b} (student) has surpassed {edge.character_a} (mentor) "
                    f"in power — role reversal tension."
                )
            elif edge.relationship_type in ("lover", "family") and has_secrets:
                secret_holder = edge.character_a if edge.a_secret_from_b else edge.character_b
                opportunities.append(
                    f"{secret_holder} is keeping secrets from someone close ({edge.relationship_type}) — "
                    f"intimacy makes the revelation more devastating."
                )

        return opportunities

    def _get_profile(self, project_id: str) -> WorkProfile | None:
        return self.session.execute(
            select(WorkProfile)
            .where(
                WorkProfile.scope_ref_id == project_id,
                WorkProfile.profile_key == "relationship_matrix",
            )
        ).scalars().first()

    def _load_stored_edges(self, project_id: str) -> list[RelationshipEdge]:
        profile = self._get_profile(project_id)
        if profile is None:
            return []
        edge_dicts = (profile.profile_json or {}).get("edges", [])
        return [RelationshipEdge.from_dict(e) for e in edge_dicts if e.get("character_a")]

    def _load_knowledge_sets(
        self,
        project_id: str,
        scene_seq: int | None,
        character_ids: list[str],
        *,
        scene_id: str | None = None,
    ) -> dict[str, set[str]]:
        """Load what each character knows at the given scene seq."""
        try:
            from novel_system.services.narrative_event_log import NarrativeEventLog
            log = NarrativeEventLog(self.session)
            knowledge: dict[str, set[str]] = {}
            for char_id in character_ids:
                facts = log.known_facts_for_character(
                    char_id,
                    project_id,
                    before_scene_id=scene_id,
                    up_to_scene_seq=(
                        int(scene_seq or 0) - 1 if scene_id is None else None
                    ),
                )
                knowledge[char_id] = {f"{f.fact_key}:{f.fact_value}" for f in facts}
            return knowledge
        except Exception:
            _LOGGER.warning(
                "Relationship knowledge projection degraded project_id=%s scene_id=%s",
                project_id,
                scene_id,
                exc_info=True,
            )
            return {}

    @staticmethod
    def _enrich_with_asymmetry(
        edge: RelationshipEdge,
        knowledge: dict[str, set[str]],
    ) -> None:
        """Merge live event-sourced info asymmetry into the edge."""
        a_knows = knowledge.get(edge.character_a, set())
        b_knows = knowledge.get(edge.character_b, set())

        a_exclusive = a_knows - b_knows
        b_exclusive = b_knows - a_knows

        if a_exclusive:
            edge.a_secret_from_b = list(a_exclusive)[:5]
        if b_exclusive:
            edge.b_secret_from_a = list(b_exclusive)[:5]
