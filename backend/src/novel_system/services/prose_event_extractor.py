"""Blueprint §2 — extract narrative events from FINISHED prose, not just the spec.

The spec-based recorder (orchestrator._record_narrative_events) logs what the scene
*plan* declared would happen (exit_change / must_reveal / relationship_turn). That makes
the "single source of truth" a mirror of the spec — it cannot catch the model drifting
away from its spec on the page (e.g. the prose has 林远 using a severed arm).

This extractor reads the *actually generated* prose and asks an LLM to surface the
concrete state changes / location moves / knowledge gains / relationship shifts that the
text itself realizes. Extracted events are tagged ``confidence="extracted"`` +
``payload={"source": "prose"}`` so the consistency checker treats them as ADVISORY — an
LLM extractor hallucinates, so per blueprint §15 it must never become a hard
authoritative blocker, only human-checkable signal.

Opt-in (``NOVEL_SYSTEM_LLM_EVENT_EXTRACTION_ENABLED`` + ``llm_enabled``); returns ``[]``
on any error or when no runner is available — never raises, never blocks.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

EXTRACT_TASK_NAME = "narrative_event_extract"

EXTRACTOR_SYSTEM_PROMPT = """\
You are a precise continuity fact-extractor for a long-form novel.
Work in two passes: first scan the prose paragraph by paragraph and note every apparent
state change; then keep only the ones that are durable — facts that would still matter
several scenes later — and drop momentary action, mood, or interpretation.
Extract ONLY concrete, on-the-page facts that CHANGE STATE.

Event types (use exactly one of these strings):
- character_state: a durable change to a character (injury, item gained/lost, a
  condition that persists beyond this scene)
- location_change: a character is now at a specific place
- character_learns: a character gains specific knowledge/information
- relation_change: the relationship between two characters shifts

Examples of durable facts to report: a character loses an arm (character_state); a
character learns who the killer is (character_learns); two characters end a scene as
enemies after being allies (relation_change).
Examples to NOT report: a character feels afraid for a moment; a character walks across
a room; a character raises their voice.

Respond with JSON only, no prose:
{
  "events": [
    {
      "event_type": "character_state|location_change|character_learns|relation_change",
      "entity_id": "<character name/id exactly as written>",
      "fact_key": "<short snake_case key, e.g. injury / location / learned / stance_toward_X>",
      "fact_value": "<concise factual value>",
      "evidence": "<short quote from the prose supporting this fact>"
    }
  ]
}

Rules:
- Only facts literally supported by the prose. When unsure, omit it.
- Prefer durable facts (matter in later scenes) over momentary action.
- fact_value under 200 chars. Return {"events": []} if nothing qualifies.
"""

_VALID_EVENT_TYPES = frozenset(
    {"character_state", "location_change", "character_learns", "relation_change"}
)


@dataclass(slots=True)
class ExtractedEvent:
    event_type: str
    entity_id: str
    fact_key: str
    fact_value: str
    evidence: str = ""


def extract_events_from_prose(
    content: str,
    *,
    llm_runner: Any | None = None,
    max_chars: int = 6000,
) -> list[ExtractedEvent]:
    """Return prose-grounded events, or ``[]`` when disabled/unavailable/on any error."""
    if llm_runner is None or not content or not content.strip():
        return []

    task_prompt = f"## Scene prose\n\n{content[:max_chars]}"
    try:
        response = llm_runner.run_task(
            task_name=EXTRACT_TASK_NAME,
            prompt_text=task_prompt,
            system_prompt=EXTRACTOR_SYSTEM_PROMPT,
        )
    except Exception:
        logger.warning("prose event extraction call failed; skipping", exc_info=True)
        return []

    parsed = _parse_response(response)
    events: list[ExtractedEvent] = []
    for raw in parsed.get("events", []) or []:
        if not isinstance(raw, dict):
            continue
        etype = raw.get("event_type", "")
        if etype not in _VALID_EVENT_TYPES:
            continue
        entity_id = str(raw.get("entity_id", "")).strip()
        fact_key = str(raw.get("fact_key", "")).strip()
        fact_value = str(raw.get("fact_value", "")).strip()
        if not (entity_id and fact_key and fact_value):
            continue
        events.append(
            ExtractedEvent(
                event_type=etype,
                entity_id=entity_id,
                fact_key=fact_key[:80],
                fact_value=fact_value[:200],
                evidence=str(raw.get("evidence", ""))[:200],
            )
        )
    return events


def _parse_response(response: Any) -> dict[str, Any]:
    try:
        if hasattr(response, "structured_output") and response.structured_output:
            return response.structured_output
        raw = (getattr(response, "text", "") or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3]
        return json.loads(raw.strip())
    except (json.JSONDecodeError, TypeError, AttributeError):
        logger.warning("failed to parse prose extraction response", exc_info=True)
        return {}
