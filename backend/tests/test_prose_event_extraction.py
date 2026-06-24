"""Blueprint §2 — prose-grounded event extraction (close the "spec mirror" gap).

The spec-based recorder logs what the plan declared; this extractor reads the actual
prose and records what the TEXT realized, tagged as advisory (confidence="extracted",
source="prose") so a hallucinating extractor can never hard-block consistency (§15).
"""

from __future__ import annotations


class _Resp:
    def __init__(self, text: str) -> None:
        self.text = text
        self.structured_output = None


class _Runner:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    def run_task(self, *, task_name, prompt_text, system_prompt):
        self.calls.append({"task_name": task_name, "prompt_text": prompt_text})
        return _Resp(self._text)


def test_extract_without_runner_returns_empty() -> None:
    from novel_system.services.prose_event_extractor import extract_events_from_prose

    assert extract_events_from_prose("some prose", llm_runner=None) == []
    # also empty content with a runner
    assert extract_events_from_prose("", llm_runner=_Runner("{}")) == []


def test_extract_parses_and_filters_invalid() -> None:
    from novel_system.services.prose_event_extractor import (
        EXTRACT_TASK_NAME,
        extract_events_from_prose,
    )

    runner = _Runner(
        '{"events": ['
        '{"event_type":"character_state","entity_id":"林远","fact_key":"injury","fact_value":"右臂截断","evidence":"他的右臂被斩断"},'
        '{"event_type":"NOT_A_TYPE","entity_id":"B","fact_key":"k","fact_value":"v"},'
        '{"event_type":"location_change","entity_id":"","fact_key":"loc","fact_value":"城外"}'
        ']}'
    )
    events = extract_events_from_prose("林远的右臂被斩断了。", llm_runner=runner)

    assert len(events) == 1  # invalid type + empty entity filtered out
    assert events[0].entity_id == "林远"
    assert events[0].fact_key == "injury"
    # routed via the dedicated §2 extraction task
    assert runner.calls[0]["task_name"] == EXTRACT_TASK_NAME


def test_extract_runner_error_returns_empty() -> None:
    from novel_system.services.prose_event_extractor import extract_events_from_prose

    class _Broken:
        def run_task(self, **_kw):
            raise RuntimeError("LLM down")

    assert extract_events_from_prose("prose", llm_runner=_Broken()) == []


def test_extract_malformed_json_returns_empty() -> None:
    from novel_system.services.prose_event_extractor import extract_events_from_prose

    assert extract_events_from_prose("prose", llm_runner=_Runner("not json at all")) == []


def test_narrative_event_extract_aliases_to_existing_route(session) -> None:
    from novel_system.services.llm_task_runner import _AD_HOC_ROUTE_ALIASES, LLMNodeRunner

    assert _AD_HOC_ROUTE_ALIASES["narrative_event_extract"] == "extraction"
    cfg = LLMNodeRunner(session).task_config("extraction")
    assert getattr(cfg, "model", None), "extraction (extractor alias target) did not resolve"


def test_extracted_events_logged_as_advisory(session) -> None:
    """End-to-end: prose -> extract -> log as advisory (confidence=extracted, source=prose),
    so projection/consistency can distinguish it from authoritative spec facts."""
    from novel_system.services.narrative_event_log import NarrativeEventLog
    from novel_system.services.prose_event_extractor import extract_events_from_prose

    runner = _Runner(
        '{"events": [{"event_type":"character_state","entity_id":"林远",'
        '"fact_key":"injury","fact_value":"右臂截断","evidence":"右臂已断"}]}'
    )
    events = extract_events_from_prose("林远的右臂被斩断。", llm_runner=runner)
    assert len(events) == 1

    log = NarrativeEventLog(session)
    ev = events[0]
    logged = log.log_event(
        project_id="p1", scene_id="s1", chapter_id="c1",
        event_type=ev.event_type, entity_type="character", entity_id=ev.entity_id,
        fact_key=ev.fact_key, fact_value=ev.fact_value,
        confidence="extracted", source_text_excerpt=ev.evidence,
        payload={"source": "prose"},
    )
    assert logged.confidence == "extracted"
    assert logged.payload_json.get("source") == "prose"


def test_orchestrator_prose_extraction_gate_open_when_flag_enabled(session, monkeypatch) -> None:
    """§2 gate teeth (real code path): flag ON + runner present -> the orchestrator's
    _record_prose_events extracts from prose and logs an advisory NarrativeEvent
    (confidence=extracted, source=prose). Drives the REAL gate (orchestrator.py:648),
    not a mirror — removing the `llm_event_extraction_enabled` guard flips the OFF test."""
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_EVENT_EXTRACTION_ENABLED", "true")
    from sqlalchemy import select

    from novel_system.db.models import NarrativeEvent
    from novel_system.services.narrative_event_log import NarrativeEventLog
    from novel_system.services.orchestrator import Orchestrator

    runner = _Runner(
        '{"events": [{"event_type":"character_state","entity_id":"林远",'
        '"fact_key":"injury","fact_value":"右臂截断","evidence":"右臂被斩断"}]}'
    )
    orch = Orchestrator(session)
    orch.llm_runner = runner
    log = NarrativeEventLog(session)
    base = {"project_id": "p_pe", "scene_id": "s_pe", "chapter_id": "c_pe"}
    orch._record_prose_events(log, None, base, "林远的右臂被斩断了。")
    session.flush()

    assert runner.calls, "extractor never called -> gate stayed closed despite flag ON"
    rows = (
        session.execute(
            select(NarrativeEvent).where(
                NarrativeEvent.scene_id == "s_pe",
                NarrativeEvent.confidence == "extracted",
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].entity_id == "林远"
    assert rows[0].fact_key == "injury"
    assert rows[0].payload_json.get("source") == "prose"


def test_orchestrator_prose_extraction_gate_closed_when_flag_disabled(session, monkeypatch) -> None:
    """§2 default: flag OFF -> the gate short-circuits before touching the runner."""
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_EVENT_EXTRACTION_ENABLED", "false")
    from sqlalchemy import select

    from novel_system.db.models import NarrativeEvent
    from novel_system.services.narrative_event_log import NarrativeEventLog
    from novel_system.services.orchestrator import Orchestrator

    runner = _Runner(
        '{"events": [{"event_type":"character_state","entity_id":"林远",'
        '"fact_key":"injury","fact_value":"x","evidence":"y"}]}'
    )
    orch = Orchestrator(session)
    orch.llm_runner = runner
    log = NarrativeEventLog(session)
    base = {"project_id": "p_pe2", "scene_id": "s_pe2", "chapter_id": "c_pe2"}
    orch._record_prose_events(log, None, base, "林远的右臂被斩断了。")
    session.flush()

    assert runner.calls == [], "runner called despite flag OFF -> gate broken"
    rows = (
        session.execute(
            select(NarrativeEvent).where(NarrativeEvent.confidence == "extracted")
        )
        .scalars()
        .all()
    )
    assert rows == []
