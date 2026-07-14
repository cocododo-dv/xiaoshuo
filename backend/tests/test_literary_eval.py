from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from novel_system.db.models import LlmCall, LlmCallAttempt
from novel_system.services.literary_eval import (
    BaselineLiteraryCaseGenerator,
    LLMLiteraryCaseGenerator,
    LiteraryEvalRunner,
    load_literary_eval_suite,
    score_literary_case,
)
from novel_system.services.llm_client import LLMResponse, ModelRoutingConfig, ProviderRuntimeConfig, TaskModelConfig
from novel_system.tools.literary_eval import main as literary_eval_main
from tests.accounted_llm_fakes import AccountedGenerateMixin


def test_load_literary_eval_suite_requires_small_structured_cases(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
suite_id: literary_small_test
pass_threshold: 0.72
cases:
  - case_id: reunion_pressure
    title: Rooftop reunion pressure
    prompt: Write a short reunion scene around a red envelope.
    required_terms: ["red envelope", "clocktower"]
    style_cues: ["short sentences", "pressure"]
    banned_terms: ["woke up"]
    model_voice_banned_terms: ["somehow meaningful"]
    expository_dialogue_banned_terms: ["as you know"]
    choice_pressure_cues: ["choose", "cannot both"]
    summary_ending_banned_terms: ["everything changed forever"]
    image_variety_cues: ["envelope", "clocktower"]
    min_chars: 60
    max_chars: 320
""".strip(),
        encoding="utf-8",
    )

    suite = load_literary_eval_suite(suite_path)

    assert suite.suite_id == "literary_small_test"
    assert suite.pass_threshold == 0.72
    assert suite.cases[0].case_id == "reunion_pressure"
    assert suite.cases[0].required_terms == ("red envelope", "clocktower")
    assert suite.cases[0].style_cues == ("short sentences", "pressure")
    assert suite.cases[0].banned_terms == ("woke up",)
    assert suite.cases[0].choice_pressure_cues == ("choose", "cannot both")
    assert suite.cases[0].model_voice_banned_terms == ("somehow meaningful",)


def test_literary_eval_suite_rejects_duplicate_case_ids_during_load() -> None:
    with pytest.raises(ValueError, match="duplicate case_id: duplicate_case"):
        load_literary_eval_suite(
            {
                "suite_id": "duplicate-suite",
                "cases": [
                    {
                        "case_id": "duplicate_case",
                        "title": "First",
                        "prompt": "First prompt",
                    },
                    {
                        "case_id": "duplicate_case",
                        "title": "Second",
                        "prompt": "Second prompt",
                    },
                ],
            }
        )


def test_literary_eval_runner_rejects_direct_duplicate_suite_before_generator() -> None:
    suite = load_literary_eval_suite(
        {
            "suite_id": "direct-duplicate-suite",
            "cases": [
                {
                    "case_id": "duplicate_case",
                    "title": "First",
                    "prompt": "First prompt",
                }
            ],
        }
    )
    duplicate_suite = replace(suite, cases=(suite.cases[0], suite.cases[0]))
    provider_calls = 0

    def unexpected_generator(case):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("generator must not run")

    with pytest.raises(ValueError, match="duplicate case_id: duplicate_case"):
        LiteraryEvalRunner(duplicate_suite, generator=unexpected_generator)

    assert provider_calls == 0


def test_score_literary_case_rewards_required_terms_style_cues_and_length() -> None:
    suite = load_literary_eval_suite(
        {
            "suite_id": "inline",
            "cases": [
                {
                    "case_id": "reunion_pressure",
                    "title": "Rooftop reunion pressure",
                    "prompt": "Write a short reunion scene.",
                    "required_terms": ["red envelope", "clocktower"],
                    "style_cues": ["short sentences", "pressure"],
                    "banned_terms": ["woke up"],
                    "model_voice_banned_terms": ["somehow meaningful"],
                    "expository_dialogue_banned_terms": ["as you know"],
                    "choice_pressure_cues": ["choose", "cannot both"],
                    "summary_ending_banned_terms": ["everything changed forever"],
                    "image_variety_cues": ["fog", "red envelope", "clocktower"],
                    "min_chars": 60,
                    "max_chars": 320,
                }
            ],
        }
    )

    score = score_literary_case(
        suite.cases[0],
        (
            "The clocktower kept its teeth in the fog. She held out the red envelope. "
            "Short sentences cut the air; pressure gathered between them. "
            "She had to choose and cannot both keep the letter and save the boy."
        ),
    )
    weak_score = score_literary_case(
        suite.cases[0],
        "He woke up far away and, as you know, explained everything in a plain summary. "
        "It was somehow meaningful. In the end, everything changed forever.",
    )

    assert score.score > 0.9
    assert score.passed is True
    assert score.dimensions["required_terms"] == 1.0
    assert score.dimensions["banned_terms"] == 1.0
    assert score.dimensions["model_voice"] == 1.0
    assert score.dimensions["expository_dialogue"] == 1.0
    assert score.dimensions["choice_pressure"] == 1.0
    assert score.dimensions["summary_ending"] == 1.0
    assert score.dimensions["image_homogeneity"] == 1.0
    assert weak_score.score < 0.5
    assert weak_score.passed is False
    assert "missing required term: red envelope" in weak_score.issues
    assert "contains banned term: woke up" in weak_score.issues
    assert "contains model voice term: somehow meaningful" in weak_score.issues
    assert "contains expository dialogue term: as you know" in weak_score.issues
    assert "missing choice pressure cue: choose" in weak_score.issues
    assert "contains summary ending term: everything changed forever" in weak_score.issues


def test_score_literary_case_checks_deep_revision_signals() -> None:
    suite = load_literary_eval_suite(
        {
            "suite_id": "inline",
            "cases": [
                {
                    "case_id": "confession_key",
                    "title": "Confession key",
                    "prompt": "Write a compact confrontation.",
                    "required_terms": ["key"],
                    "style_cues": ["pressure"],
                    "banned_terms": ["explained everything"],
                    "character_contradiction_cues": ["confess", "hide"],
                    "dialogue_edge_cues": ["No."],
                    "image_necessity_cues": ["key changed hands"],
                    "ending_drive_cues": ["door opened"],
                    "model_voice_banned_terms": ["somehow meaningful"],
                    "expository_dialogue_banned_terms": ["as you know"],
                    "choice_pressure_cues": ["choose", "cannot both"],
                    "summary_ending_banned_terms": ["everything changed forever"],
                    "image_variety_cues": ["key", "door", "room"],
                    "min_chars": 80,
                    "max_chars": 420,
                }
            ],
        }
    )

    strong = score_literary_case(
        suite.cases[0],
        (
            "She came to confess and still tried to hide the key. Pressure narrowed the room. "
            "\"No.\" The key changed hands before either of them named the betrayal. "
            "She had to choose and cannot both keep him safe and keep the lie. "
            "Behind them, the locked door opened."
        ),
    )
    weak = score_literary_case(
        suite.cases[0],
        "She held a key and, as you know, explained everything in a tidy paragraph about how she felt. "
        "It was somehow meaningful. In the end, everything changed forever.",
    )

    assert strong.dimensions["character_contradiction"] == 1.0
    assert strong.dimensions["dialogue_edge"] == 1.0
    assert strong.dimensions["image_necessity"] == 1.0
    assert strong.dimensions["ending_drive"] == 1.0
    assert strong.dimensions["choice_pressure"] == 1.0
    assert strong.dimensions["image_homogeneity"] == 1.0
    assert strong.passed is True
    assert weak.dimensions["character_contradiction"] == 0.0
    assert weak.dimensions["dialogue_edge"] == 0.0
    assert weak.dimensions["image_necessity"] == 0.0
    assert weak.dimensions["ending_drive"] == 0.0
    assert weak.dimensions["model_voice"] == 0.0
    assert weak.dimensions["expository_dialogue"] == 0.0
    assert weak.dimensions["summary_ending"] == 0.0
    assert "missing character contradiction cue: confess" in weak.issues
    assert "missing ending drive cue: door opened" in weak.issues


def test_literary_eval_runner_uses_generator_and_returns_summary(tmp_path: Path) -> None:
    suite = load_literary_eval_suite(
        {
            "suite_id": "inline",
            "pass_threshold": 0.7,
            "cases": [
                {
                    "case_id": "gate_scene",
                    "title": "Gate scene",
                    "prompt": "Write a gate scene.",
                    "required_terms": ["gate", "letter"],
                    "style_cues": ["gesture"],
                    "banned_terms": ["dream"],
                    "min_chars": 40,
                    "max_chars": 240,
                },
                {
                    "case_id": "bad_scene",
                    "title": "Bad scene",
                    "prompt": "Write a bad scene.",
                    "required_terms": ["key"],
                    "style_cues": ["tension"],
                    "banned_terms": ["dream"],
                    "min_chars": 40,
                    "max_chars": 240,
                },
            ],
        }
    )

    def fake_generator(case):
        if case.case_id == "gate_scene":
            return "At the gate, her gesture hid the letter until the hinge stopped singing."
        return "It was a dream."

    output_path = tmp_path / "literary_eval.json"
    result = LiteraryEvalRunner(suite, generator=fake_generator).run(output_path=output_path)

    assert result["suite_id"] == "inline"
    assert result["summary"] == {
        "case_count": 2,
        "passed_count": 1,
        "failed_count": 1,
        "mean_score": result["summary"]["mean_score"],
        "pass_threshold": 0.7,
    }
    assert result["summary"]["mean_score"] < 1.0
    assert result["cases"][0]["case_id"] == "gate_scene"
    assert result["cases"][0]["passed"] is True
    assert result["cases"][1]["passed"] is False
    assert output_path.exists()


def test_llm_literary_case_generator_builds_json_request_with_rubric_context(
    session,
) -> None:
    suite = load_literary_eval_suite(
        {
            "suite_id": "inline",
            "cases": [
                {
                    "case_id": "reunion_pressure",
                    "title": "Rooftop reunion pressure",
                    "prompt": "Write a short reunion scene around a red envelope.",
                    "required_terms": ["red envelope", "clocktower"],
                    "style_cues": ["short sentences", "pressure"],
                    "banned_terms": ["woke up"],
                    "min_chars": 60,
                    "max_chars": 320,
                }
            ],
        }
    )

    class FakeClient(AccountedGenerateMixin):
        def __init__(self) -> None:
            self.requests = []

        def generate(self, request):
            self.requests.append(request)
            return LLMResponse(
                request_id="resp_eval_001",
                provider="fake-provider",
                model=request.model,
                text='{"scene_text": "The clocktower held the red envelope under pressure."}',
                structured_output={"scene_text": "The clocktower held the red envelope under pressure."},
                response_format=request.response_format,
                raw_response={},
                usage={"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
                finish_reason="stop",
                raw_usage={"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
                usage_present=True,
                usage_complete=True,
            )

    client = FakeClient()
    generated = LLMLiteraryCaseGenerator(
        client,
        session=session,
        eval_run_id="literary_eval_test_run",
        model="gpt-5-mini",
    )(suite.cases[0])

    assert generated["generated_text"] == "The clocktower held the red envelope under pressure."
    assert generated["provider"] == "fake-provider"
    assert generated["model"] == "gpt-5-mini"
    assert generated["provider_request_id"] == "resp_eval_001"
    assert generated["llm_call_id"].startswith("llm_eval_")
    assert client.requests[0].response_format == "json_object"
    assert client.requests[0].temperature == 0.75
    assert "required terms: red envelope; clocktower" in client.requests[0].messages[1]["content"]
    assert "style cues: short sentences; pressure" in client.requests[0].messages[1]["content"]
    assert "banned terms: woke up" in client.requests[0].messages[1]["content"]
    call = session.query(LlmCall).one()
    attempt = session.query(LlmCallAttempt).one()
    assert call.llm_call_id == generated["llm_call_id"]
    assert (call.scope_type, call.scope_id, call.step) == (
        "literary_eval_case",
        "literary_eval_test_run:reunion_pressure",
        "case:reunion_pressure",
    )
    assert call.usage_is_estimate is False
    assert attempt.accounting_status == "settled"


def test_llm_literary_case_generator_accounts_missing_usage_provider_failure_and_schema_failure(
    session,
) -> None:
    suite = load_literary_eval_suite(
        {
            "suite_id": "accounting",
            "cases": [
                {
                    "case_id": "case_one",
                    "title": "Case one",
                    "prompt": "Write one scene.",
                }
            ],
        }
    )
    case = suite.cases[0]

    class MissingUsageClient(AccountedGenerateMixin):
        def generate(self, request):
            return LLMResponse(
                request_id=None,
                provider="fake-provider",
                model=request.model,
                text='{"scene_text": "A sufficiently clear scene."}',
                structured_output={"scene_text": "A sufficiently clear scene."},
                response_format=request.response_format,
                raw_response={},
                usage={},
                raw_usage=None,
                usage_present=False,
                usage_complete=False,
            )

    missing = LLMLiteraryCaseGenerator(
        MissingUsageClient(),
        session=session,
        eval_run_id="literary_eval_missing_usage",
        model="fake-model",
    )(case)
    missing_call = session.get(LlmCall, missing["llm_call_id"])
    assert missing_call is not None
    assert missing_call.accounting_status == "settled"
    assert missing_call.usage_is_estimate is True
    assert missing_call.total_tokens > 0

    class FailingClient(AccountedGenerateMixin):
        def generate(self, _request):
            raise RuntimeError("provider unavailable")

    failing = LLMLiteraryCaseGenerator(
        FailingClient(),
        session=session,
        eval_run_id="literary_eval_provider_failure",
        model="fake-model",
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        failing(case)

    class InvalidSchemaClient(AccountedGenerateMixin):
        def generate(self, request):
            return LLMResponse(
                request_id="provider-schema-error",
                provider="fake-provider",
                model=request.model,
                text="{}",
                structured_output={},
                response_format=request.response_format,
                raw_response={},
                usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
                raw_usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
                usage_present=True,
                usage_complete=True,
            )

    invalid = LLMLiteraryCaseGenerator(
        InvalidSchemaClient(),
        session=session,
        eval_run_id="literary_eval_schema_failure",
        model="fake-model",
    )
    with pytest.raises(ValueError, match="missing scene_text"):
        invalid(case)

    calls = {call.scope_id: call for call in session.query(LlmCall).all()}
    attempts = {
        attempt.llm_call_id: attempt for attempt in session.query(LlmCallAttempt).all()
    }
    provider_failure = calls["literary_eval_provider_failure:case_one"]
    schema_failure = calls["literary_eval_schema_failure:case_one"]
    assert provider_failure.accounting_status == "failed"
    assert attempts[provider_failure.llm_call_id].accounting_status == "failed"
    assert schema_failure.accounting_status == "failed"
    assert schema_failure.error_code == "LLM_RESPONSE_INVALID_SCHEMA"
    assert attempts[schema_failure.llm_call_id].accounting_status == "settled"


def test_literary_eval_runner_and_live_generator_share_one_eval_run_id_or_reject(
    session,
) -> None:
    suite = load_literary_eval_suite(
        {
            "suite_id": "run-id-ownership",
            "cases": [
                {
                    "case_id": "case_one",
                    "title": "Case one",
                    "prompt": "Write one scene.",
                }
            ],
        }
    )

    class NeverCalledClient(AccountedGenerateMixin):
        def __init__(self) -> None:
            self.provider_calls = 0

        def generate(self, request):
            self.provider_calls += 1
            raise AssertionError("provider must not run for eval_run_id mismatch")

    client = NeverCalledClient()
    generator = LLMLiteraryCaseGenerator(
        client,
        session=session,
        eval_run_id="generator-run-id",
        model="fake-model",
    )

    with pytest.raises(ValueError, match="eval_run_id mismatch"):
        LiteraryEvalRunner(
            suite,
            generator=generator,
            eval_run_id="runner-run-id",
        )

    assert client.provider_calls == 0
    assert session.query(LlmCall).count() == 0
    assert session.query(LlmCallAttempt).count() == 0

    runner = LiteraryEvalRunner(suite, generator=generator)
    assert runner.eval_run_id == "generator-run-id"


def test_baseline_literary_case_generator_scores_suite_without_live_llm() -> None:
    suite = load_literary_eval_suite(
        {
            "suite_id": "inline",
            "pass_threshold": 0.7,
            "cases": [
                {
                    "case_id": "letter_gate",
                    "title": "Letter gate",
                    "prompt": "Write a gate scene.",
                    "baseline_text": "The gate held. Her gesture hid the letter while tension tightened the hinge.",
                    "required_terms": ["gate", "letter"],
                    "style_cues": ["gesture", "tension"],
                    "banned_terms": ["dream"],
                    "min_chars": 40,
                    "max_chars": 240,
                }
            ],
        }
    )

    result = LiteraryEvalRunner(suite, generator=BaselineLiteraryCaseGenerator()).run()

    assert suite.cases[0].baseline_text == "The gate held. Her gesture hid the letter while tension tightened the hinge."
    assert result["summary"]["passed_count"] == 1
    assert result["cases"][0]["generation"] == {"mode": "baseline_text"}


def test_repo_literary_small_suite_baselines_are_valid() -> None:
    suite_path = Path(__file__).resolve().parents[2] / "config" / "evals" / "literary_small.yaml"

    suite = load_literary_eval_suite(suite_path)
    result = LiteraryEvalRunner(suite, generator=BaselineLiteraryCaseGenerator()).run()

    assert suite.suite_id == "literary_small_v1"
    assert len(suite.cases) >= 5
    assert all(case.character_contradiction_cues for case in suite.cases)
    assert all(case.dialogue_edge_cues for case in suite.cases)
    assert all(case.image_necessity_cues for case in suite.cases)
    assert all(case.ending_drive_cues for case in suite.cases)
    assert all(case.model_voice_banned_terms for case in suite.cases)
    assert all(case.expository_dialogue_banned_terms for case in suite.cases)
    assert all(case.choice_pressure_cues for case in suite.cases)
    assert all(case.summary_ending_banned_terms for case in suite.cases)
    assert all(case.image_variety_cues for case in suite.cases)
    assert any(any("\u4e00" <= char <= "\u9fff" for char in case.prompt) for case in suite.cases)
    assert result["summary"]["case_count"] == len(suite.cases)
    assert result["summary"]["failed_count"] == 0


def test_repo_literary_small_suite_includes_chinese_strong_plot_gate_cases() -> None:
    suite_path = Path(__file__).resolve().parents[2] / "config" / "evals" / "literary_small.yaml"

    suite = load_literary_eval_suite(suite_path)
    strong_plot_cases = [case for case in suite.cases if case.case_id.startswith("chinese_strong_plot_")]

    assert len(strong_plot_cases) >= 2
    assert all(case.required_terms for case in strong_plot_cases)
    assert all(case.choice_pressure_cues for case in strong_plot_cases)
    assert all(case.ending_drive_cues for case in strong_plot_cases)
    assert any("解释了一切" in case.summary_ending_banned_terms for case in strong_plot_cases)
    assert any("某种意义上" in case.model_voice_banned_terms for case in strong_plot_cases)


def test_repo_literary_small_suite_includes_chinese_anti_template_gates() -> None:
    suite_path = Path(__file__).resolve().parents[2] / "config" / "evals" / "literary_small.yaml"

    suite = load_literary_eval_suite(suite_path)
    anti_template_cases = [case for case in suite.cases if case.case_id.startswith("chinese_anti_template_")]

    assert {case.case_id for case in anti_template_cases} >= {
        "chinese_anti_template_repeated_gesture",
        "chinese_anti_template_cross_scene_reuse",
    }
    assert all(case.required_terms for case in anti_template_cases)
    assert all(case.choice_pressure_cues for case in anti_template_cases)
    assert all(case.ending_drive_cues for case in anti_template_cases)
    assert any("低头看着" in case.banned_terms for case in anti_template_cases)
    assert any("沉默了片刻" in case.banned_terms for case in anti_template_cases)
    assert any("盐霜" in case.banned_terms for case in anti_template_cases)
    assert any("她知道" in case.model_voice_banned_terms for case in anti_template_cases)
    assert any("这意味着" in case.summary_ending_banned_terms for case in anti_template_cases)


def test_literary_eval_tool_baseline_mode_writes_report(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
suite_id: cli_suite
pass_threshold: 0.7
cases:
  - case_id: gate_scene
    title: Gate scene
    prompt: Write a gate scene.
    baseline_text: The gate held the letter in tension.
    required_terms: ["gate", "letter"]
    style_cues: ["tension"]
    banned_terms: ["dream"]
    min_chars: 20
    max_chars: 200
""".strip(),
        encoding="utf-8",
    )
    output_path = tmp_path / "report.json"

    exit_code = literary_eval_main(["--suite", str(suite_path), "--output", str(output_path), "--mode", "baseline"])

    assert exit_code == 0
    assert '"suite_id": "cli_suite"' in output_path.read_text(encoding="utf-8")


def test_literary_eval_tool_live_mode_accounts_each_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session,
) -> None:
    from novel_system.tools import literary_eval as tool_module

    suite_path = tmp_path / "live-suite.yaml"
    suite_path.write_text(
        """
suite_id: cli_live_suite
cases:
  - case_id: live_case
    title: Live case
    prompt: Write a gate scene.
    required_terms: ["gate"]
""".strip(),
        encoding="utf-8",
    )
    output_path = tmp_path / "live-report.json"
    task_config = TaskModelConfig(
        provider="openai_compatible",
        provider_id="local_cli",
        model="local-model",
        temperature=0.2,
        max_output_tokens=200,
        response_format="json_object",
        api_mode="chat",
        credential_mode="none",
    )
    monkeypatch.setattr(
        tool_module,
        "get_settings",
        lambda: SimpleNamespace(
            llm_enabled=True,
            llm_provider="openai_compatible",
            llm_base_url="http://localhost:8080/v1",
            llm_api_key=None,
            llm_timeout_seconds=5,
        ),
    )
    monkeypatch.setattr(
        tool_module,
        "load_model_routing_config",
        lambda: ModelRoutingConfig(
            node_routing={"literary_eval_live": task_config},
            task_routing={},
            retry_budget={},
            job_runtime={},
        ),
    )
    monkeypatch.setattr(
        tool_module,
        "load_llm_provider_runtime_configs",
        lambda: {
            "local_cli": ProviderRuntimeConfig(
                provider_id="local_cli",
                provider_type="openai_compatible",
                base_url="http://localhost:8080/v1",
                credential_mode="none",
                enabled=True,
                models=("local-model",),
            )
        },
    )

    class FakeLiveClient(AccountedGenerateMixin):
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def generate(self, request):
            return LLMResponse(
                request_id="provider_cli_live",
                provider="openai_compatible",
                model=request.model,
                text='{"scene_text": "The gate held."}',
                structured_output={"scene_text": "The gate held."},
                response_format=request.response_format,
                raw_response={},
                usage={"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
                raw_usage={"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
                usage_present=True,
                usage_complete=True,
            )

    monkeypatch.setattr(tool_module, "LLMClient", FakeLiveClient)

    exit_code = tool_module.main(
        [
            "--suite",
            str(suite_path),
            "--output",
            str(output_path),
            "--mode",
            "live",
        ]
    )

    assert exit_code == 0
    report = json.loads(output_path.read_text(encoding="utf-8"))
    generation = report["cases"][0]["generation"]
    assert generation["llm_call_id"].startswith("llm_eval_")
    assert generation["provider_request_id"] == "provider_cli_live"
    call = session.query(LlmCall).one()
    assert call.scope_id == f"{report['eval_run_id']}:live_case"
    assert call.step == "case:live_case"


def test_literary_eval_latest_api_returns_empty_state(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LITERARY_EVAL_REPORT_PATH", str(tmp_path / "latest.json"))

    response = client.get("/api/v1/literary-eval/latest")

    assert response.status_code == 200
    assert response.json()["data"] == {"report": None}


def test_literary_eval_run_api_writes_latest_baseline_report(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "latest.json"
    monkeypatch.setenv("NOVEL_SYSTEM_LITERARY_EVAL_REPORT_PATH", str(report_path))

    run_response = client.post("/api/v1/literary-eval/run", json={"mode": "baseline"})

    assert run_response.status_code == 200
    report = run_response.json()["data"]["report"]
    assert report["mode"] == "baseline"
    assert report["suite_id"] == "literary_small_v1"
    assert report["summary"]["case_count"] >= 5
    assert report["summary"]["failed_count"] == 0
    assert report_path.exists()

    latest_response = client.get("/api/v1/literary-eval/latest")

    assert latest_response.status_code == 200
    assert latest_response.json()["data"]["report"]["suite_id"] == "literary_small_v1"
    assert latest_response.json()["data"]["report"]["summary"]["passed_count"] == report["summary"]["case_count"]


def test_literary_eval_run_api_allows_live_local_provider_without_api_key(
    client: TestClient,
    session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "latest.json"
    monkeypatch.setenv("NOVEL_SYSTEM_LITERARY_EVAL_REPORT_PATH", str(report_path))
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.delenv("NOVEL_SYSTEM_LLM_API_KEY", raising=False)

    from novel_system.api.routes import literary_eval as route_module

    task_config = TaskModelConfig(
        provider="openai_compatible",
        provider_id="local_qwen3",
        model="Qwen3-14B-Q8_0.gguf",
        temperature=0.2,
        max_output_tokens=200,
        response_format="json_object",
        api_mode="chat",
        credential_mode="none",
    )
    monkeypatch.setattr(
        route_module,
        "load_model_routing_config",
        lambda: ModelRoutingConfig(
            node_routing={"literary_eval_live": task_config},
            task_routing={},
            retry_budget={},
            job_runtime={},
        ),
    )
    monkeypatch.setattr(
        route_module,
        "load_llm_provider_runtime_configs",
        lambda: {
            "local_qwen3": ProviderRuntimeConfig(
                provider_id="local_qwen3",
                provider_type="openai_compatible",
                base_url="http://127.0.0.1:8080/v1",
                credential_mode="none",
                enabled=True,
                models=("Qwen3-14B-Q8_0.gguf",),
            )
        },
    )

    class FakeLiveClient(AccountedGenerateMixin):
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def generate(self, request):
            scene = "gate letter archive page dock urgency gesture tension suspicion visual hook"
            return LLMResponse(
                request_id=f"provider_{request.node_id}",
                provider="openai_compatible",
                model=request.model,
                text='{"scene_text": "' + scene + '"}',
                structured_output={"scene_text": scene},
                response_format=request.response_format,
                raw_response={},
                usage={"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
                raw_usage={"input_tokens": 10, "output_tokens": 10, "total_tokens": 20},
                usage_present=True,
                usage_complete=True,
            )

    monkeypatch.setattr(route_module, "LLMClient", FakeLiveClient)

    response = client.post("/api/v1/literary-eval/run", json={"mode": "live"})

    assert response.status_code == 200
    report = response.json()["data"]["report"]
    assert report["mode"] == "live"
    assert report["cases"][0]["generation"]["model"] == "Qwen3-14B-Q8_0.gguf"
    assert report["cases"][0]["generation"]["llm_call_id"].startswith("llm_eval_")
    assert report["cases"][0]["generation"]["provider_request_id"].startswith(
        "provider_"
    )
    calls = session.query(LlmCall).all()
    assert len(calls) == report["summary"]["case_count"]
    assert {call.scope_type for call in calls} == {"literary_eval_case"}
    assert all(call.scope_id.startswith(report["eval_run_id"] + ":") for call in calls)
    assert report_path.exists()


def test_literary_eval_live_requires_direct_node_route_instead_of_style_fallback(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = tmp_path / "latest.json"
    monkeypatch.setenv("NOVEL_SYSTEM_LITERARY_EVAL_REPORT_PATH", str(report_path))
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_BASE_URL", "http://127.0.0.1:8080/v1")

    from novel_system.api.routes import literary_eval as route_module

    task_config = TaskModelConfig(
        provider="openai_compatible",
        provider_id="local_qwen3",
        model="Qwen3-14B-Q8_0.gguf",
        temperature=0.2,
        max_output_tokens=200,
        response_format="json_object",
        api_mode="chat",
        credential_mode="none",
    )
    monkeypatch.setattr(
        route_module,
        "load_model_routing_config",
        lambda: ModelRoutingConfig(
            node_routing={"style_draft": task_config},
            task_routing={"stylize": task_config},
            retry_budget={},
            job_runtime={},
        ),
    )

    response = client.post("/api/v1/literary-eval/run", json={"mode": "live"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LITERARY_EVAL_LIVE_MODEL_MISSING"
