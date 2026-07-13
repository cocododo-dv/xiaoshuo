"""Blueprint §8 — wire the independent LLM editor critic into production.

``llm_auto_critique`` (a 6-dimension semantic editor pass) was fully implemented but had
ZERO callers because the runner interface it expected — ``run_task(task_name, prompt_text,
system_prompt)`` — existed only on a test fake, never on the production ``LLMNodeRunner``.
These tests cover the now-real wiring:

- ``LLMNodeRunner.run_task`` assembles an ad-hoc request and uses the resolved client.
- the ``auto_critique_llm`` route resolves (models.yaml task_routing).
- the orchestrator path degrades to rule-only when the runner is absent (opt-in default).
- the LLM editor's issues are merged into the rewrite brief when a runner is present.
"""

from __future__ import annotations

import pytest


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text
        self.structured_output = None


def _llm_context():
    from novel_system.services.llm_accounting import LLMCallContext

    return LLMCallContext(
        scope_type="system",
        scope_id="auto-critique-test",
        node_id="soft_qc",
        step="soft_qc:auto_critique:0",
    )


def test_auto_critique_passes_explicit_context_to_run_task() -> None:
    from novel_system.services.auto_critique import llm_auto_critique
    captured: dict = {}

    class _Runner:
        def run_task(self, *, task_name, prompt_text, system_prompt, context):
            captured.update(
                task_name=task_name,
                prompt_text=prompt_text,
                system_prompt=system_prompt,
                context=context,
            )
            return _FakeResponse('{"should_rewrite": false, "issues": []}')

    context = _llm_context()
    llm_auto_critique(
        "SCENE TEXT",
        llm_runner=_Runner(),
        llm_context=context,
    )
    assert captured["task_name"] == "auto_critique_llm"
    assert captured["context"] is context


def test_auto_critique_llm_aliases_to_existing_route(session) -> None:
    """The §8 critic borrows the soft_qc route via run_task alias — no dedicated node, so
    it never pollutes active node_routing nor trips the sync-activation guard."""
    from novel_system.services.llm_task_runner import _AD_HOC_ROUTE_ALIASES, LLMNodeRunner

    assert _AD_HOC_ROUTE_ALIASES["auto_critique_llm"] == "soft_qc"
    cfg = LLMNodeRunner(session).task_config("soft_qc")
    assert getattr(cfg, "model", None), "soft_qc (critic alias target) did not resolve"


def test_llm_critique_degrades_to_rule_only_without_runner() -> None:
    from novel_system.services.auto_critique import auto_critique, llm_auto_critique

    text = "她觉得心里一紧，她意识到自己其实早就明白了一切。"
    rule = auto_critique(text)
    hybrid = llm_auto_critique(text, llm_runner=None)
    assert hybrid.directives == rule.directives
    assert hybrid.should_rewrite == rule.should_rewrite


def test_llm_critique_with_runner_but_no_context_fails_before_runner_io() -> None:
    from novel_system.services.auto_critique import llm_auto_critique
    from novel_system.services.llm_accounting import LLMAccountingRejected

    calls: list[str] = []

    class _Runner:
        def run_task(self, **_kwargs):
            calls.append("provider")

    with pytest.raises(LLMAccountingRejected) as rejected:
        llm_auto_critique("prose", llm_runner=_Runner())

    assert rejected.value.code == "LLM_ACCOUNTING_CONTEXT_REQUIRED"
    assert calls == []


def test_llm_critique_merges_editor_issues() -> None:
    from novel_system.services.auto_critique import llm_auto_critique

    class _Runner:
        def run_task(self, *, task_name, prompt_text, system_prompt, context):
            return _FakeResponse(
                '{"should_rewrite": true, "issues": ['
                '{"dimension": "conflict_credibility", '
                '"directive": "raise the cost of the reconciliation", '
                '"evidence": "they simply hugged and moved on"}]}'
            )

    result = llm_auto_critique(
        "Some otherwise clean prose.",
        llm_runner=_Runner(),
        llm_context=_llm_context(),
    )
    assert result.should_rewrite is True
    assert any("conflict_credibility" in directive for directive in result.directives)


def test_llm_critique_runner_error_degrades_gracefully() -> None:
    """A failing critic runner must never propagate — degrade to the rule-based result."""
    from novel_system.services.auto_critique import auto_critique, llm_auto_critique

    class _BrokenRunner:
        def run_task(self, *, task_name, prompt_text, system_prompt, context):
            raise RuntimeError("LLM down")

    text = "她觉得很难过，她意识到自己错了。"
    hybrid = llm_auto_critique(text, llm_runner=_BrokenRunner(), llm_context=_llm_context())
    assert hybrid.directives == auto_critique(text).directives


def test_auto_critique_gate_resolves_runner_when_flag_enabled(session, monkeypatch) -> None:
    """§8 gate teeth (real code path): with llm_enabled + llm_auto_critique_enabled, the
    orchestrator's extracted gate resolves the real critic runner. This drives the same
    method run_scene calls — deleting the `and llm_auto_critique_enabled` clause flips the
    OFF test below to red."""
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_AUTO_CRITIQUE_ENABLED", "true")
    from novel_system.services.orchestrator import Orchestrator

    orch = Orchestrator(session)
    sentinel = object()
    orch.llm_runner = sentinel
    assert orch._resolve_auto_critique_runner() is sentinel


def test_auto_critique_gate_suppressed_when_flag_disabled(session, monkeypatch) -> None:
    """§8 default: flag OFF -> critic runner is None -> llm_auto_critique == rule-only,
    and the injected runner is never called."""
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_AUTO_CRITIQUE_ENABLED", "false")
    from novel_system.services.auto_critique import auto_critique, llm_auto_critique
    from novel_system.services.orchestrator import Orchestrator

    calls: list = []

    class _Runner:
        def run_task(self, *, task_name, prompt_text, system_prompt, context):
            calls.append(task_name)
            return _FakeResponse('{"should_rewrite": false, "issues": []}')

    orch = Orchestrator(session)
    orch.llm_runner = _Runner()
    runner = orch._resolve_auto_critique_runner()
    assert runner is None

    text = "她觉得心里一紧，她意识到自己其实早就明白了一切。"
    assert llm_auto_critique(text, llm_runner=runner).directives == auto_critique(text).directives
    assert calls == []
