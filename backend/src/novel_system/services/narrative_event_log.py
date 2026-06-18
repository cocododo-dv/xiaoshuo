"""Narrative event sourcing — append-only event log + deterministic state projection.

Blueprint §2: "事件溯源为唯一真相源"
Blueprint §17 Action B: minimal verifiable kernel

Event types:
  character_state   — physical/emotional state change
  character_learns  — character acquires information
  location_change   — character moves
  relation_change   — relationship shift
  item_change       — item gained/lost
  foreshadow_plant  — foreshadow set up
  foreshadow_resolve — foreshadow paid off

Entity types: character, location, item, relation, foreshadow
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ChapterGoal,
    NarrativeEvent,
    SceneCard,
)


EVENT_TYPES = (
    "character_state",
    "character_learns",
    "location_change",
    "relation_change",
    "item_change",
    "foreshadow_plant",
    "foreshadow_reinforce",
    "foreshadow_resolve",
)

ENTITY_TYPES = ("character", "location", "item", "relation", "foreshadow")


@dataclass(slots=True)
class ProjectedFact:
    entity_type: str
    entity_id: str
    fact_key: str
    fact_value: str
    scene_id: str
    scene_seq: int
    event_id: str


@dataclass(slots=True)
class EntityState:
    entity_type: str
    entity_id: str
    facts: dict[str, ProjectedFact] = field(default_factory=dict)

    def get(self, fact_key: str) -> str | None:
        f = self.facts.get(fact_key)
        return f.fact_value if f else None

    def as_dict(self) -> dict[str, str]:
        return {k: v.fact_value for k, v in sorted(self.facts.items())}


@dataclass(slots=True)
class CharacterState:
    character_id: str
    facts: dict[str, ProjectedFact] = field(default_factory=dict)

    def get(self, fact_key: str) -> str | None:
        f = self.facts.get(fact_key)
        return f.fact_value if f else None

    def as_dict(self) -> dict[str, str]:
        return {k: v.fact_value for k, v in sorted(self.facts.items())}


@dataclass(slots=True)
class ConsistencyViolation:
    fact_key: str
    expected: str
    actual: str
    entity_id: str
    evidence: str
    # §15: "keyword" = high-confidence deterministic match (blocking);
    # "llm_flag" = advisory LLM flag for human spot-check (never auto-blocks).
    source: str = "keyword"


@dataclass(slots=True)
class ConsistencyReport:
    passed: bool
    violations: list[ConsistencyViolation] = field(default_factory=list)
    facts_checked: int = 0

    @property
    def blocking_violations(self) -> list[ConsistencyViolation]:
        """Only deterministic (keyword) violations gate generation; LLM flags advise."""
        return [v for v in self.violations if v.source == "keyword"]


class NarrativeEventLog:
    def __init__(self, session: Session) -> None:
        self.session = session

    def log_event(
        self,
        *,
        project_id: str,
        scene_id: str,
        chapter_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        fact_key: str,
        fact_value: str,
        confidence: str = "high",
        causal_predecessor_id: str | None = None,
        theme_tags: list[str] | None = None,
        obligation_ids: list[str] | None = None,
        source_text_excerpt: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> NarrativeEvent:
        scene_seq = self._scene_seq(scene_id)
        event = NarrativeEvent(
            event_id=f"nevt_{uuid.uuid4().hex[:16]}",
            project_id=project_id,
            scene_id=scene_id,
            chapter_id=chapter_id,
            scene_seq=scene_seq,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            fact_key=fact_key,
            fact_value=fact_value,
            confidence=confidence,
            causal_predecessor_id=causal_predecessor_id,
            theme_tags=theme_tags or [],
            obligation_ids=obligation_ids or [],
            source_text_excerpt=source_text_excerpt,
            payload_json=payload or {},
        )
        self.session.add(event)
        self.session.flush()
        return event

    def log_events_batch(self, events: list[dict[str, Any]]) -> list[NarrativeEvent]:
        result = []
        for evt in events:
            result.append(self.log_event(**evt))
        return result

    def project_character_state(
        self,
        character_id: str,
        project_id: str,
        *,
        up_to_scene_seq: int | None = None,
    ) -> CharacterState:
        """Replay events to reconstruct character state. Latest fact per key wins."""
        query = (
            select(NarrativeEvent)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.entity_id == character_id,
            )
            .order_by(NarrativeEvent.scene_seq.asc(), NarrativeEvent.created_at.asc())
        )
        if up_to_scene_seq is not None:
            query = query.where(NarrativeEvent.scene_seq <= up_to_scene_seq)

        events = self.session.execute(query).scalars().all()
        state = CharacterState(character_id=character_id)
        for evt in events:
            state.facts[evt.fact_key] = ProjectedFact(
                entity_type=evt.entity_type,
                entity_id=evt.entity_id,
                fact_key=evt.fact_key,
                fact_value=evt.fact_value,
                scene_id=evt.scene_id,
                scene_seq=evt.scene_seq,
                event_id=evt.event_id,
            )
        return state

    def project_entity_state(
        self,
        entity_type: str,
        entity_id: str,
        project_id: str,
        *,
        up_to_scene_seq: int | None = None,
    ) -> EntityState:
        """Replay events to reconstruct any entity's state. Latest fact per key wins."""
        query = (
            select(NarrativeEvent)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.entity_type == entity_type,
                NarrativeEvent.entity_id == entity_id,
            )
            .order_by(NarrativeEvent.scene_seq.asc(), NarrativeEvent.created_at.asc())
        )
        if up_to_scene_seq is not None:
            query = query.where(NarrativeEvent.scene_seq <= up_to_scene_seq)

        events = self.session.execute(query).scalars().all()
        state = EntityState(entity_type=entity_type, entity_id=entity_id)
        for evt in events:
            state.facts[evt.fact_key] = ProjectedFact(
                entity_type=evt.entity_type,
                entity_id=evt.entity_id,
                fact_key=evt.fact_key,
                fact_value=evt.fact_value,
                scene_id=evt.scene_id,
                scene_seq=evt.scene_seq,
                event_id=evt.event_id,
            )
        return state

    def project_location_state(
        self,
        location_id: str,
        project_id: str,
        *,
        up_to_scene_seq: int | None = None,
    ) -> EntityState:
        """Replay location events to reconstruct location state."""
        return self.project_entity_state(
            "location", location_id, project_id, up_to_scene_seq=up_to_scene_seq,
        )

    def project_item_state(
        self,
        item_id: str,
        project_id: str,
        *,
        up_to_scene_seq: int | None = None,
    ) -> EntityState:
        """Replay item events to reconstruct item state."""
        return self.project_entity_state(
            "item", item_id, project_id, up_to_scene_seq=up_to_scene_seq,
        )

    def known_facts_for_character(
        self,
        character_id: str,
        project_id: str,
        *,
        up_to_scene_seq: int | None = None,
    ) -> list[ProjectedFact]:
        """All facts an entity has accumulated up to a scene — for POV filtering."""
        query = (
            select(NarrativeEvent)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.entity_id == character_id,
                NarrativeEvent.event_type == "character_learns",
            )
            .order_by(NarrativeEvent.scene_seq.asc(), NarrativeEvent.created_at.asc())
        )
        if up_to_scene_seq is not None:
            query = query.where(NarrativeEvent.scene_seq <= up_to_scene_seq)

        events = self.session.execute(query).scalars().all()
        return [
            ProjectedFact(
                entity_type=evt.entity_type,
                entity_id=evt.entity_id,
                fact_key=evt.fact_key,
                fact_value=evt.fact_value,
                scene_id=evt.scene_id,
                scene_seq=evt.scene_seq,
                event_id=evt.event_id,
            )
            for evt in events
        ]

    def all_facts_at_scene(
        self,
        project_id: str,
        scene_seq: int,
    ) -> dict[str, CharacterState]:
        """Project all character states at a given scene. Returns {character_id: CharacterState}."""
        events = self.session.execute(
            select(NarrativeEvent)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.entity_type == "character",
                NarrativeEvent.scene_seq <= scene_seq,
            )
            .order_by(NarrativeEvent.scene_seq.asc(), NarrativeEvent.created_at.asc())
        ).scalars().all()

        states: dict[str, CharacterState] = {}
        for evt in events:
            state = states.setdefault(evt.entity_id, CharacterState(character_id=evt.entity_id))
            state.facts[evt.fact_key] = ProjectedFact(
                entity_type=evt.entity_type,
                entity_id=evt.entity_id,
                fact_key=evt.fact_key,
                fact_value=evt.fact_value,
                scene_id=evt.scene_id,
                scene_seq=evt.scene_seq,
                event_id=evt.event_id,
            )
        return states

    def all_entities_at_scene(
        self,
        project_id: str,
        scene_seq: int,
    ) -> dict[str, dict[str, EntityState]]:
        """Project all entity states at a given scene.

        Returns {entity_type: {entity_id: EntityState}} for every entity type.
        """
        events = self.session.execute(
            select(NarrativeEvent)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.scene_seq <= scene_seq,
            )
            .order_by(NarrativeEvent.scene_seq.asc(), NarrativeEvent.created_at.asc())
        ).scalars().all()

        by_type: dict[str, dict[str, EntityState]] = {}
        for evt in events:
            type_bucket = by_type.setdefault(evt.entity_type, {})
            state = type_bucket.setdefault(
                evt.entity_id,
                EntityState(entity_type=evt.entity_type, entity_id=evt.entity_id),
            )
            state.facts[evt.fact_key] = ProjectedFact(
                entity_type=evt.entity_type,
                entity_id=evt.entity_id,
                fact_key=evt.fact_key,
                fact_value=evt.fact_value,
                scene_id=evt.scene_id,
                scene_seq=evt.scene_seq,
                event_id=evt.event_id,
            )
        return by_type

    def check_consistency(
        self,
        generated_text: str,
        project_id: str,
        scene_id: str,
        *,
        character_ids: list[str] | None = None,
    ) -> ConsistencyReport:
        """Check generated text against projected character state for contradictions.

        Checks hard facts (location, physical_state, alive) against text content.
        This is the "one incremental consistency check" from blueprint §17 Action B.
        """
        scene_seq = self._scene_seq(scene_id)
        if character_ids:
            chars = character_ids
        else:
            chars = self._characters_in_project(project_id)

        violations: list[ConsistencyViolation] = []
        facts_checked = 0
        text_lower = generated_text.lower()
        # Known location names in this project — used by the location detector to
        # distinguish "character is at the WRONG named place" from generic prose.
        # Locations live both as location entities AND as `location` facts asserted
        # on characters (location_change events), so gather both.
        known_locations = {
            loc.lower()
            for loc in self._entities_of_type_in_project(project_id, "location")
            if loc
        }
        loc_values = self.session.execute(
            select(NarrativeEvent.fact_value).where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.fact_key == "location",
            ).distinct()
        ).scalars().all()
        known_locations |= {v.lower() for v in loc_values if v}

        for char_id in chars:
            state = self.project_character_state(char_id, project_id, up_to_scene_seq=scene_seq - 1)
            for fact_key, projected in state.facts.items():
                if fact_key not in _CHECKABLE_FACT_KEYS:
                    continue
                facts_checked += 1
                violation = _check_fact_against_text(
                    text_lower, char_id, fact_key, projected.fact_value,
                    known_locations=known_locations,
                )
                if violation is not None:
                    violations.append(violation)

        return ConsistencyReport(
            passed=len(violations) == 0,
            violations=violations,
            facts_checked=facts_checked,
        )

    def check_consistency_llm(
        self,
        generated_text: str,
        project_id: str,
        scene_id: str,
        *,
        character_ids: list[str] | None = None,
        llm_runner: Any | None = None,
    ) -> ConsistencyReport:
        """§15 honest-boundary hybrid check: keyword pass + ONE advisory LLM flag pass.

        Blueprint §15 is explicit that "校验是用不可靠验证不可靠" — a structural circular
        dependency. So this stays deliberately conservative:
        - The keyword pass (check_consistency) remains the authoritative, blocking layer.
        - The LLM pass runs at most ONE call, ONLY over already-projected hard facts, and
          its findings are marked source="llm_flag" → advisory (human spot-check), never
          auto-blocking. This is the "+ 人工抽检兜底" half of §15 made cheaper.
        - When no llm_runner is supplied, this degrades to the pure keyword result.

        Catches cases the deterministic keyword scan cannot — e.g. an *implied*
        two-handed action ("拉紧两侧的缰绳") when an arm is missing — without letting a
        hallucinating extractor gate generation. (Literal misuse such as "双手握剑"
        or "抬起右手握刀" is now caught deterministically by the keyword layer.)
        """
        base = self.check_consistency(
            generated_text, project_id, scene_id, character_ids=character_ids,
        )
        if llm_runner is None:
            return base

        scene_seq = self._scene_seq(scene_id)
        chars = character_ids or self._characters_in_project(project_id)
        fact_lines: list[str] = []
        for char_id in chars:
            state = self.project_character_state(char_id, project_id, up_to_scene_seq=scene_seq - 1)
            for fact_key, projected in state.facts.items():
                if fact_key in _CHECKABLE_FACT_KEYS:
                    fact_lines.append(f"- {char_id}.{fact_key} = {projected.fact_value}")
        if not fact_lines:
            return base

        facts_block = "\n".join(fact_lines)
        task_prompt = _LLM_CONSISTENCY_TASK_TEMPLATE.format(
            facts_block=facts_block, text=generated_text,
        )
        try:
            response = llm_runner.run_task(
                task_name="consistency_extract",
                prompt_text=task_prompt,
                system_prompt=_LLM_CONSISTENCY_SYSTEM_PROMPT,
            )
        except Exception:
            return base  # LLM failure must never break the conservative path

        llm_violations = _parse_llm_consistency_response(response)
        if not llm_violations:
            return base

        # Merge advisory flags, deduped against keyword hits by (entity, fact_key).
        seen = {(v.entity_id, v.fact_key) for v in base.violations}
        merged = list(base.violations)
        for v in llm_violations:
            if (v.entity_id, v.fact_key) not in seen:
                merged.append(v)
                seen.add((v.entity_id, v.fact_key))
        return ConsistencyReport(
            # passed reflects only blocking (keyword) violations; LLM flags are advisory.
            passed=len([m for m in merged if m.source == "keyword"]) == 0,
            violations=merged,
            facts_checked=base.facts_checked,
        )

    def format_state_for_prompt(
        self,
        project_id: str,
        scene_seq: int,
        *,
        pov_character_id: str | None = None,
        onstage_character_ids: list[str] | None = None,
    ) -> str:
        """Format projected entity states as a prompt section for injection."""
        chars = onstage_character_ids or self._characters_in_project(project_id)
        lines: list[str] = []
        lines.append("## Authoritative Character State (from event log, do NOT contradict)")
        for char_id in chars:
            state = self.project_character_state(char_id, project_id, up_to_scene_seq=scene_seq - 1)
            if not state.facts:
                continue
            lines.append(f"\n### {char_id}")
            for key, value in sorted(state.as_dict().items()):
                lines.append(f"- {key}: {value}")

        if pov_character_id:
            known = self.known_facts_for_character(
                pov_character_id, project_id, up_to_scene_seq=scene_seq - 1,
            )
            if known:
                lines.append(f"\n### POV知识边界 ({pov_character_id} 已知信息)")
                for fact in known:
                    lines.append(f"- {fact.fact_key}: {fact.fact_value}")

        location_ids = self._entities_of_type_in_project(project_id, "location")
        if location_ids:
            loc_lines: list[str] = []
            for loc_id in location_ids:
                state = self.project_entity_state(
                    "location", loc_id, project_id, up_to_scene_seq=scene_seq - 1,
                )
                if state.facts:
                    loc_lines.append(f"\n### {loc_id}")
                    for key, value in sorted(state.as_dict().items()):
                        loc_lines.append(f"- {key}: {value}")
            if loc_lines:
                lines.append("\n## Authoritative Location State (from event log, do NOT contradict)")
                lines.extend(loc_lines)

        item_ids = self._entities_of_type_in_project(project_id, "item")
        if item_ids:
            item_lines: list[str] = []
            for item_id in item_ids:
                state = self.project_entity_state(
                    "item", item_id, project_id, up_to_scene_seq=scene_seq - 1,
                )
                if state.facts:
                    item_lines.append(f"\n### {item_id}")
                    for key, value in sorted(state.as_dict().items()):
                        item_lines.append(f"- {key}: {value}")
            if item_lines:
                lines.append("\n## Authoritative Item State (from event log, do NOT contradict)")
                lines.extend(item_lines)

        return "\n".join(lines) if len(lines) > 1 else ""

    def information_asymmetry_digest(
        self,
        project_id: str,
        scene_seq: int,
        onstage_character_ids: list[str],
    ) -> str:
        """Blueprint §2/§11: format information gaps between onstage characters for prompt injection.

        For each pair of onstage characters, identify what one knows that the other doesn't.
        Also surface active secrets and false beliefs.
        """
        if len(onstage_character_ids) < 2:
            return ""

        lines: list[str] = []
        lines.append("## Information Asymmetry (who knows what the other doesn't)")

        knowledge: dict[str, set[str]] = {}
        secrets: dict[str, list[str]] = {}
        false_beliefs: dict[str, list[str]] = {}

        for char_id in onstage_character_ids:
            facts = self.known_facts_for_character(char_id, project_id, up_to_scene_seq=scene_seq - 1)
            knowledge[char_id] = {f"{f.fact_key}:{f.fact_value}" for f in facts}

            state = self.project_character_state(char_id, project_id, up_to_scene_seq=scene_seq - 1)
            for fk, pf in state.facts.items():
                if fk == "secret_held_by":
                    secrets.setdefault(char_id, []).append(pf.fact_value)
                elif fk == "believes_false":
                    false_beliefs.setdefault(char_id, []).append(pf.fact_value)

        for i, char_a in enumerate(onstage_character_ids):
            for char_b in onstage_character_ids[i + 1:]:
                a_knows = knowledge.get(char_a, set())
                b_knows = knowledge.get(char_b, set())
                a_exclusive = a_knows - b_knows
                b_exclusive = b_knows - a_knows
                if a_exclusive or b_exclusive:
                    lines.append(f"\n### {char_a} ↔ {char_b}")
                    if a_exclusive:
                        lines.append(f"  {char_a} knows but {char_b} doesn't:")
                        for fact in list(a_exclusive)[:5]:
                            lines.append(f"    - {fact}")
                    if b_exclusive:
                        lines.append(f"  {char_b} knows but {char_a} doesn't:")
                        for fact in list(b_exclusive)[:5]:
                            lines.append(f"    - {fact}")

        for char_id in onstage_character_ids:
            if char_id in secrets:
                lines.append(f"\n### Secrets held by {char_id}")
                for s in secrets[char_id][:3]:
                    lines.append(f"  - {s}")
            if char_id in false_beliefs:
                lines.append(f"\n### False beliefs of {char_id}")
                for b in false_beliefs[char_id][:3]:
                    lines.append(f"  - {b}")

        return "\n".join(lines) if len(lines) > 1 else ""

    # ------------------------------------------------------------------
    # Causal chain queries (blueprint §2: 因果链追踪)
    # ------------------------------------------------------------------

    def trace_causal_chain(
        self,
        event_id: str,
        *,
        max_depth: int = 20,
    ) -> list[NarrativeEvent]:
        """Walk causal_predecessor_id links backward from *event_id*.

        Returns the chain in chronological order (oldest ancestor first,
        the starting event last).  Stops when max_depth is reached or the
        predecessor link is ``None``.
        """
        chain: list[NarrativeEvent] = []
        current_id: str | None = event_id
        visited: set[str] = set()

        while current_id is not None and len(chain) < max_depth:
            if current_id in visited:
                break  # cycle guard
            visited.add(current_id)
            evt = self.session.get(NarrativeEvent, current_id)
            if evt is None:
                break
            chain.append(evt)
            current_id = evt.causal_predecessor_id

        chain.reverse()  # oldest ancestor first
        return chain

    def downstream_events(self, event_id: str) -> list[NarrativeEvent]:
        """Return immediate children — events whose causal_predecessor_id == *event_id*."""
        query = (
            select(NarrativeEvent)
            .where(NarrativeEvent.causal_predecessor_id == event_id)
            .order_by(NarrativeEvent.scene_seq.asc(), NarrativeEvent.created_at.asc())
        )
        return list(self.session.execute(query).scalars().all())

    def find_unfulfilled_obligations(
        self,
        project_id: str,
        *,
        up_to_scene_seq: int | None = None,
    ) -> list[dict[str, str]]:
        """Identify foreshadow obligations that have not yet been resolved.

        Scans events with non-empty ``obligation_ids`` and checks whether a
        corresponding ``foreshadow_resolve`` event exists for each obligation.

        Returns a list of dicts::

            {"event_id", "scene_id", "obligation_id", "status"}

        where *status* is ``"fulfilled"`` or ``"unfulfilled"``.
        """
        # 1. Collect all events that carry obligations
        plant_query = (
            select(NarrativeEvent)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.obligation_ids.isnot(None),
            )
            .order_by(NarrativeEvent.scene_seq.asc(), NarrativeEvent.created_at.asc())
        )
        if up_to_scene_seq is not None:
            plant_query = plant_query.where(NarrativeEvent.scene_seq <= up_to_scene_seq)
        plant_events = self.session.execute(plant_query).scalars().all()

        # 2. Collect all foreshadow_resolve events in the project
        resolve_query = (
            select(NarrativeEvent)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.event_type == "foreshadow_resolve",
            )
        )
        if up_to_scene_seq is not None:
            resolve_query = resolve_query.where(NarrativeEvent.scene_seq <= up_to_scene_seq)
        resolve_events = self.session.execute(resolve_query).scalars().all()

        # Build a set of resolved obligation IDs.
        resolved_ids: set[str] = set()
        for rev in resolve_events:
            resolved_ids.add(rev.entity_id)
            for oid in (rev.obligation_ids or []):
                resolved_ids.add(oid)

        # 3. Match
        results: list[dict[str, str]] = []
        for evt in plant_events:
            for oid in (evt.obligation_ids or []):
                status = "fulfilled" if oid in resolved_ids else "unfulfilled"
                results.append({
                    "event_id": evt.event_id,
                    "scene_id": evt.scene_id,
                    "obligation_id": oid,
                    "status": status,
                })
        return results

    def format_causal_context_for_prompt(
        self,
        project_id: str,
        scene_id: str,
        *,
        onstage_character_ids: list[str] | None = None,
    ) -> str:
        """Format a compact "Causal Context" prompt section.

        Includes:
        * recent causal chain entries relevant to onstage characters
        * unfulfilled foreshadow obligations

        Kept to ~20 lines to stay within prompt budget.
        """
        scene_seq = self._scene_seq(scene_id)
        lines: list[str] = ["## Causal Context"]

        # --- Recent causal events for onstage characters ---
        char_ids = onstage_character_ids or self._characters_in_project(project_id)
        if char_ids:
            recent_query = (
                select(NarrativeEvent)
                .where(
                    NarrativeEvent.project_id == project_id,
                    NarrativeEvent.entity_id.in_(char_ids),
                    NarrativeEvent.causal_predecessor_id.isnot(None),
                )
                .order_by(NarrativeEvent.scene_seq.desc(), NarrativeEvent.created_at.desc())
                .limit(8)
            )
            if scene_seq > 0:
                recent_query = recent_query.where(NarrativeEvent.scene_seq < scene_seq)
            recent = list(self.session.execute(recent_query).scalars().all())
            recent.reverse()  # chronological

            if recent:
                lines.append("")
                lines.append("### Recent causal events")
                for evt in recent:
                    lines.append(
                        f"- [{evt.entity_id}] {evt.event_type}: "
                        f"{evt.fact_key}={evt.fact_value} (scene {evt.scene_seq})"
                    )

        # --- Unfulfilled obligations ---
        obligations = self.find_unfulfilled_obligations(
            project_id, up_to_scene_seq=scene_seq - 1 if scene_seq > 0 else None,
        )
        unfulfilled = [o for o in obligations if o["status"] == "unfulfilled"]
        if unfulfilled:
            lines.append("")
            lines.append("### Unfulfilled foreshadow obligations")
            for ob in unfulfilled[:6]:  # cap to stay compact
                lines.append(f"- obligation {ob['obligation_id']} (planted in scene {ob['scene_id']})")

        return "\n".join(lines) if len(lines) > 1 else ""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _scene_seq(self, scene_id: str) -> int:
        scene = self.session.get(SceneCard, scene_id)
        if scene is not None:
            return scene.scene_seq or 0
        return 0

    def _characters_in_project(self, project_id: str) -> list[str]:
        return self._entities_of_type_in_project(project_id, "character")

    def _entities_of_type_in_project(self, project_id: str, entity_type: str) -> list[str]:
        rows = self.session.execute(
            select(NarrativeEvent.entity_id)
            .where(
                NarrativeEvent.project_id == project_id,
                NarrativeEvent.entity_type == entity_type,
            )
            .distinct()
        ).scalars().all()
        return list(rows)


_CHECKABLE_FACT_KEYS = {
    "alive",
    "location",
    "physical_state",
    "has_item",
    "missing_limb",
    "appearance",
    "ability",
}

# §15 hybrid consistency — advisory LLM flag layer. Strict prompt: only report
# CONTRADICTIONS of the given hard facts, never invent new facts, never judge style.
_LLM_CONSISTENCY_SYSTEM_PROMPT = (
    "你是连续性校验器。只做一件事：判断给定散文是否与【已确立的硬事实】矛盾。"
    "硬事实指角色生死、位置、身体状态（如断肢）、持有物、外貌、能力。"
    "规则：(1) 只报矛盾，不报风格问题；(2) 绝不臆造事实清单之外的内容；"
    "(3) 不确定时不报；(4) 严格输出 JSON，无任何额外文字。"
    'JSON 格式：{"violations": [{"entity": "角色名", "fact_key": "字段", '
    '"expected": "事实值", "actual": "文中矛盾表现", "evidence": "原文片段"}]}'
)

_LLM_CONSISTENCY_TASK_TEMPLATE = (
    "【已确立的硬事实】\n{facts_block}\n\n"
    "【待校验散文】\n{text}\n\n"
    "请仅输出矛盾项的 JSON。若无矛盾，输出 {{\"violations\": []}}。"
)


def _parse_llm_consistency_response(response: Any) -> list[ConsistencyViolation]:
    """Parse the advisory LLM consistency response into source='llm_flag' violations."""
    import json as _json

    if response is None:
        return []
    raw = response
    if not isinstance(raw, str):
        raw = getattr(response, "text", None) or getattr(response, "content", None) or ""
    raw = (raw or "").strip()
    if not raw:
        return []
    # Tolerate ```json fences and surrounding prose.
    if "```" in raw:
        raw = raw.replace("```json", "```").split("```")[1] if raw.count("```") >= 2 else raw
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        parsed = _json.loads(raw[start:end + 1])
    except (ValueError, TypeError):
        return []
    out: list[ConsistencyViolation] = []
    for item in parsed.get("violations") or []:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity") or "").strip()
        fact_key = str(item.get("fact_key") or "").strip()
        if not entity or not fact_key:
            continue
        out.append(ConsistencyViolation(
            fact_key=fact_key,
            expected=str(item.get("expected") or ""),
            actual=str(item.get("actual") or ""),
            entity_id=entity,
            evidence=str(item.get("evidence") or "")[:200],
            source="llm_flag",
        ))
    return out

INFORMATION_ASYMMETRY_FACT_KEYS = {
    "secret_held_by",     # character holds a secret: value = secret description
    "believes_false",     # character has a false belief: value = what they wrongly believe
    "revealed_to",        # a secret was revealed to someone: value = who learned
    "scene_revelation",   # what POV character learned in a scene
}


# ---------------------------------------------------------------------------
# Hard-fact contradiction detection (blueprint §13 Step 6 / §17 Action B)
#
# Works at *clause* granularity with proximity + synonym matching instead of
# brittle adjacent-substring matching. This is what makes recall survive
# realistic prose ("他抬起右手攥紧剑柄") rather than only textbook-exact phrasings
# ("右手握"). Precision is held up by negative guards (memory / loss framing)
# and by requiring an action signal near the entity reference.
# ---------------------------------------------------------------------------

_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;：:\n\r，,、（）()「」『』“”\"'…—　]+")


def _split_clauses(text: str) -> list[str]:
    return [c for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]


def _all_idx(haystack: str, needle: str) -> list[int]:
    out: list[int] = []
    i = haystack.find(needle)
    while i >= 0:
        out.append(i)
        i = haystack.find(needle, i + 1)
    return out


def _min_gap(clause: str, tokens_a: tuple[str, ...], tokens_b: tuple[str, ...]) -> int | None:
    """Smallest char distance between any A-token and any B-token within a clause."""
    pa = [i for t in tokens_a for i in _all_idx(clause, t)]
    pb = [i for t in tokens_b for i in _all_idx(clause, t)]
    if not pa or not pb:
        return None
    return min(abs(a - b) for a in pa for b in pb)


def _verb_after(clause: str, anchor: str, verbs: tuple[str, ...], window: int) -> str | None:
    """First verb appearing within *window* chars AFTER *anchor* (i.e. anchor is subject)."""
    for start in _all_idx(clause, anchor):
        seg = clause[start + len(anchor): start + len(anchor) + window]
        for v in verbs:
            if v in seg:
                return v
    return None


# alive==dead: a dead character performing a living action, unless memory/flashback framing
_DEATH_MEMORY_GUARDS = (
    "想起", "记得", "回忆", "忆起", "曾经", "生前", "死前", "临终", "遗言", "遗体",
    "遗物", "遗像", "尸", "已故", "亡", "坟", "墓", "灵位", "牌位", "画像", "祭", "悼",
    "梦", "若还", "如果还", "仿佛还", "好像还", "似乎还", "当年", "那时", "过去",
)
_ALIVE_ACTION_VERBS = (
    "说道", "说", "开口", "喊道", "喊", "叫道", "问道", "问", "答道", "回答", "点头",
    "摇头", "起身", "站起", "坐起", "转身", "抬手", "抬起", "伸手", "迈步", "走来",
    "走向", "走进", "走到", "拔出", "握住", "握紧", "睁开", "看向", "望向", "盯着",
    "拿起", "举起", "笑了", "招手", "摆手", "开门",
    "said", "spoke", "walked", "nodded", "smiled",
)

# missing_limb synonym groups (normalise right_arm / 右臂 / 右手 → one group)
_LIMB_GROUPS: dict[str, tuple[str, ...]] = {
    "right_arm": ("右臂", "右手", "右胳膊", "右手臂", "右臂膀", "right arm", "right hand"),
    "left_arm": ("左臂", "左手", "左胳膊", "左手臂", "左臂膀", "left arm", "left hand"),
    "right_leg": ("右腿", "右脚", "右膝", "right leg", "right foot"),
    "left_leg": ("左腿", "左脚", "左膝", "left leg", "left foot"),
}
_LIMB_ACTION_VERBS = (
    "握", "攥", "抓", "举", "抬", "挥", "拔", "持", "拿", "伸", "搭", "按", "拍", "捏",
    "扯", "拽", "推", "抱", "捧", "接", "指", "划", "端", "提", "掂", "甩", "挡",
    "gripped", "raised", "grabbed", "clenched", "held", "swung",
)
_BOTH_HANDS = ("双手", "两手", "两只手", "双臂", "两臂", "十指", "both hands")
_LIMB_MISSING_GUARDS = (
    "断", "残", "失去", "没有了", "空荡荡", "仅存", "唯一", "缺", "截", "空袖", "断口",
    "残肢", "伤口", "本应", "本该", "曾经的", "想起", "记得",
)

# location: broadened "still at the wrong place" phrasings
_STILL_AT_PHRASES = (
    "还在", "仍在", "仍旧在", "依旧在", "依然在", "还停留", "仍停留", "还留在", "仍留在",
    "还待在", "仍待在", "依旧待在", "依然待在", "还守在", "仍守在", "还困在", "仍困在",
    "迟迟没有离开", "迟迟未离开", "没有离开", "未曾离开", "尚未离开",
    "still at", "still in", "remained at", "remained in", "was still at",
)

# has_item lost: a character using an item they no longer possess
_ITEM_POSSESS_VERBS = (
    "拿出", "掏出", "取出", "抽出", "拔出", "拿起", "握住", "握紧", "握", "举起", "举",
    "挥舞", "挥", "抓起", "攥", "佩", "掂", "提着", "捧着", "抚摸", "擦拭",
    "pulled out", "drew", "raised", "gripped",
)
_ITEM_LOSS_GUARDS = (
    "失去", "丢了", "丢失", "没了", "不见了", "遗失", "早已不在", "曾经的", "已经没有",
    "不在手中", "空空", "已断", "碎了", "毁了", "想起", "记得", "回忆", "怀念",
)


def _norm_limb_group(value_lower: str) -> str | None:
    """Map a missing_limb fact value (right_arm / 右臂 / 右手 …) to a canonical group key."""
    for key, words in _LIMB_GROUPS.items():
        if value_lower == key or value_lower in key or key in value_lower:
            return key
        for w in words:
            if w in value_lower or value_lower in w:
                return key
    return None


def _check_fact_against_text(
    text_lower: str,
    char_id: str,
    fact_key: str,
    fact_value: str,
    *,
    known_locations: set[str] | None = None,
) -> ConsistencyViolation | None:
    """Contradiction detection for hard facts (blueprint §15: hard facts only).

    Clause-level proximity + synonym matching so the detector survives realistic
    prose, not just textbook-exact phrasings. Returns at most one violation.
    Soft facts (tone, relationship nuance) are deliberately out of scope.
    """
    value_lower = fact_value.lower()
    char_lower = char_id.lower()
    clauses = _split_clauses(text_lower)
    known_locations = known_locations or set()

    # --- alive / dead: dead character performing a living action ---
    if fact_key == "alive" and value_lower == "dead":
        for clause in clauses:
            if char_lower not in clause:
                continue
            if any(g in clause for g in _DEATH_MEMORY_GUARDS):
                continue  # memory / flashback / corpse framing → not a contradiction
            verb = _verb_after(clause, char_lower, _ALIVE_ACTION_VERBS, window=10)
            if verb:
                return ConsistencyViolation(
                    fact_key=fact_key, expected="dead",
                    actual="appears alive in text",
                    entity_id=char_id, evidence=f"{char_id}…{verb}",
                )

    # --- location: character is still at the WRONG named place ---
    if fact_key == "location":
        wrong_locs = {loc for loc in known_locations if loc and loc != value_lower}
        for clause in clauses:
            if char_lower not in clause:
                continue
            if value_lower and value_lower in clause:
                continue  # correct location mentioned → assume consistent
            if not any(p in clause for p in _STILL_AT_PHRASES):
                continue
            present_wrong = next((w for w in wrong_locs if w in clause), None)
            if present_wrong:
                return ConsistencyViolation(
                    fact_key=fact_key, expected=fact_value,
                    actual=f"text places {char_id} at {present_wrong}",
                    entity_id=char_id, evidence=clause[:80],
                )

    # --- missing_limb: character uses a limb they no longer have ---
    if fact_key == "missing_limb" and value_lower:
        group = _norm_limb_group(value_lower)
        if group:
            limb_words = _LIMB_GROUPS[group]
            for clause in clauses:
                if any(g in clause for g in _LIMB_MISSING_GUARDS):
                    continue  # clause describes the loss, not a use of the limb
                gap = _min_gap(clause, limb_words, _LIMB_ACTION_VERBS)
                if gap is not None and gap <= 6:
                    return ConsistencyViolation(
                        fact_key=fact_key, expected=f"missing: {fact_value}",
                        actual="text uses the missing limb",
                        entity_id=char_id, evidence=clause[:80],
                    )
                # using BOTH hands when one arm is gone (blueprint's 双手握剑 example)
                if group in ("right_arm", "left_arm"):
                    gap2 = _min_gap(clause, _BOTH_HANDS, _LIMB_ACTION_VERBS)
                    if gap2 is not None and gap2 <= 6:
                        return ConsistencyViolation(
                            fact_key=fact_key, expected=f"missing: {fact_value}",
                            actual="text uses both hands despite a missing arm",
                            entity_id=char_id, evidence=clause[:80],
                        )

    # --- has_item: character uses an item they lost ---
    if fact_key == "has_item" and value_lower.startswith("lost:"):
        lost_item = value_lower.replace("lost:", "").strip()
        if lost_item:
            for clause in clauses:
                if lost_item not in clause:
                    continue
                if any(g in clause for g in _ITEM_LOSS_GUARDS):
                    continue
                gap = _min_gap(clause, (lost_item,), _ITEM_POSSESS_VERBS)
                if gap is not None and gap <= 6:
                    return ConsistencyViolation(
                        fact_key=fact_key, expected=f"item lost: {lost_item}",
                        actual="text shows character using the lost item",
                        entity_id=char_id, evidence=clause[:80],
                    )

    return None


def check_spec_constraints(
    generated_text: str,
    spec: dict[str, Any],
) -> list[ConsistencyViolation]:
    """Blueprint §13 Step 6: check generated text against scene spec hard constraints.

    Validates that mandatory spec elements (must_include_text, onstage characters,
    POV character presence, exit_change) are reflected in the generated prose.
    This is a spec-level check complementary to the event-log fact check.
    """
    violations: list[ConsistencyViolation] = []
    text_lower = generated_text.lower()

    # must_include_text — hard constraint from scene card
    must_include = spec.get("must_include_text") or ""
    if must_include and len(must_include) > 3:
        # Check each clause (split by semicolons or newlines)
        clauses = [c.strip() for c in must_include.replace("\n", ";").split(";") if c.strip()]
        for clause in clauses[:5]:  # cap to avoid noise
            if len(clause) > 5 and clause.lower() not in text_lower:
                violations.append(ConsistencyViolation(
                    fact_key="must_include_text",
                    expected=clause[:100],
                    actual="not found in generated text",
                    entity_id="scene_spec",
                    evidence=f"spec requires: {clause[:60]}",
                ))

    # POV character should appear in text
    pov = spec.get("pov_character_id") or ""
    if pov and len(pov) > 1 and pov.lower() not in text_lower:
        violations.append(ConsistencyViolation(
            fact_key="pov_character_presence",
            expected=f"POV character '{pov}' should appear",
            actual="POV character name not found in text",
            entity_id=pov,
            evidence="character name absent from prose",
        ))

    # cost_requirement — if specified, some cost signal should exist in text
    cost = spec.get("cost_requirement") or ""
    if cost and len(cost) > 10:
        # Extract key nouns from cost description for soft matching
        cost_keywords = [w for w in cost.lower().split() if len(w) > 2][:5]
        found_any = any(kw in text_lower for kw in cost_keywords)
        if not found_any and len(cost_keywords) >= 2:
            violations.append(ConsistencyViolation(
                fact_key="cost_requirement",
                expected=f"cost: {cost[:100]}",
                actual="no cost-related content detected in text",
                entity_id="scene_spec",
                evidence=f"keywords checked: {', '.join(cost_keywords[:3])}",
            ))

    return violations
