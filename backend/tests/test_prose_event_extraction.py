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
