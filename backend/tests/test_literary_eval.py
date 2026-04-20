from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from novel_system.services.literary_eval import (
    BaselineLiteraryCaseGenerator,
    LLMLiteraryCaseGenerator,
    LiteraryEvalRunner,
    load_literary_eval_suite,
    score_literary_case,
)
from novel_system.services.llm_client import LLMResponse, ModelRoutingConfig, ProviderRuntimeConfig, TaskModelConfig
from novel_system.tools.literary_eval import main as literary_eval_main


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
            "Short sentences cut the air; pressure gathered between them."
        ),
    )
    weak_score = score_literary_case(
        suite.cases[0],
        "He woke up far away and explained everything in a plain summary.",
    )

    assert score.score > 0.9
    assert score.passed is True
    assert score.dimensions["required_terms"] == 1.0
    assert score.dimensions["banned_terms"] == 1.0
    assert weak_score.score < 0.5
    assert weak_score.passed is False
    assert "missing required term: red envelope" in weak_score.issues
    assert "contains banned term: woke up" in weak_score.issues


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


def test_llm_literary_case_generator_builds_json_request_with_rubric_context() -> None:
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

    class FakeClient:
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
            )

    client = FakeClient()
    generated = LLMLiteraryCaseGenerator(client, model="gpt-5-mini")(suite.cases[0])

    assert generated["generated_text"] == "The clocktower held the red envelope under pressure."
    assert generated["provider"] == "fake-provider"
    assert generated["model"] == "gpt-5-mini"
    assert generated["request_id"] == "resp_eval_001"
    assert client.requests[0].response_format == "json_object"
    assert client.requests[0].temperature == 0.75
    assert "required terms: red envelope; clocktower" in client.requests[0].messages[1]["content"]
    assert "style cues: short sentences; pressure" in client.requests[0].messages[1]["content"]
    assert "banned terms: woke up" in client.requests[0].messages[1]["content"]


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
    assert len(suite.cases) >= 3
    assert result["summary"]["case_count"] == len(suite.cases)
    assert result["summary"]["failed_count"] == 0


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
    assert report["summary"]["case_count"] == 3
    assert report["summary"]["failed_count"] == 0
    assert report_path.exists()

    latest_response = client.get("/api/v1/literary-eval/latest")

    assert latest_response.status_code == 200
    assert latest_response.json()["data"]["report"]["suite_id"] == "literary_small_v1"
    assert latest_response.json()["data"]["report"]["summary"]["passed_count"] == 3


def test_literary_eval_run_api_allows_live_local_provider_without_api_key(
    client: TestClient,
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

    class FakeLiveGenerator:
        def __init__(self, *_args, model: str, provider_id: str | None, credential_mode: str | None, **_kwargs) -> None:
            assert model == "Qwen3-14B-Q8_0.gguf"
            assert provider_id == "local_qwen3"
            assert credential_mode == "none"

        def __call__(self, case):
            return {
                "generated_text": "gate letter archive page dock urgency gesture tension suspicion visual hook",
                "provider": "openai_compatible",
                "model": "Qwen3-14B-Q8_0.gguf",
                "request_id": f"fake_{case.case_id}",
            }

    monkeypatch.setattr(route_module, "LLMLiteraryCaseGenerator", FakeLiveGenerator)

    response = client.post("/api/v1/literary-eval/run", json={"mode": "live"})

    assert response.status_code == 200
    report = response.json()["data"]["report"]
    assert report["mode"] == "live"
    assert report["cases"][0]["generation"]["model"] == "Qwen3-14B-Q8_0.gguf"
    assert report_path.exists()
