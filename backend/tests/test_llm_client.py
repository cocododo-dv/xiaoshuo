from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from novel_system.settings import get_settings
from novel_system.services.llm_client import (
    LLMClient,
    LLMConfigurationError,
    LLMHTTPError,
    LLMRequest,
    LLMResponseError,
    LLMTimeoutError,
    load_model_routing_config,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_llm_client_generates_structured_json_from_responses_api() -> None:
    captured_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "resp_123",
                "model": "gpt-5-mini",
                "output_text": '{"outline": ["beat-1", "beat-2"]}',
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 15,
                    "output_tokens": 8,
                    "total_tokens": 23,
                },
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    response = client.generate(
        LLMRequest(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Return only JSON."},
                {"role": "user", "content": "Build a short outline."},
            ],
            temperature=0.2,
            max_output_tokens=256,
            response_format="json_object",
        )
    )

    assert captured_request["model"] == "gpt-5-mini"
    assert captured_request["max_output_tokens"] == 256
    assert captured_request["text"] == {"format": {"type": "json_object"}}
    assert response.provider == "openai_compatible"
    assert response.request_id == "resp_123"
    assert response.model == "gpt-5-mini"
    assert response.text == '{"outline": ["beat-1", "beat-2"]}'
    assert response.structured_output == {"outline": ["beat-1", "beat-2"]}
    assert response.usage == {
        "input_tokens": 15,
        "output_tokens": 8,
        "total_tokens": 23,
    }
    assert response.finish_reason == "stop"


def test_llm_client_generates_structured_json_from_chat_completions_api() -> None:
    captured_request: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl_123",
                "model": "gpt-5-mini",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"scene_goal": "advance the argument"}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 9,
                    "total_tokens": 21,
                },
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    response = client.generate(
        LLMRequest(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": "Return JSON."}],
            temperature=0.1,
            max_output_tokens=128,
            response_format="json_object",
            api_mode="chat",
        )
    )

    assert captured_request["model"] == "gpt-5-mini"
    assert captured_request["max_tokens"] == 128
    assert captured_request["response_format"] == {"type": "json_object"}
    assert response.request_id == "chatcmpl_123"
    assert response.text == '{"scene_goal": "advance the argument"}'
    assert response.structured_output == {"scene_goal": "advance the argument"}
    assert response.usage == {
        "input_tokens": 12,
        "output_tokens": 9,
        "total_tokens": 21,
    }
    assert response.finish_reason == "stop"


def test_llm_client_retries_http_429_before_succeeding() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return httpx.Response(
            200,
            json={
                "id": "resp_retry",
                "model": "gpt-5-mini",
                "output_text": '{"status": "ok"}',
                "finish_reason": "stop",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                },
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    response = client.generate(
        LLMRequest(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": "Return JSON."}],
            temperature=0,
            max_output_tokens=64,
            response_format="json_object",
        )
    )

    assert attempts == 2
    assert response.request_id == "resp_retry"
    assert response.text == '{"status": "ok"}'
    assert response.structured_output == {"status": "ok"}
    assert response.usage == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }
    assert response.finish_reason == "stop"


def test_llm_client_raises_normalized_error_for_malformed_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_bad_json",
                "model": "gpt-5-mini",
                "output_text": "definitely not valid json",
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMResponseError) as exc_info:
        client.generate(
            LLMRequest(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": "Return JSON."}],
                temperature=0,
                max_output_tokens=64,
                response_format="json_object",
            )
        )

    assert exc_info.value.code == "LLM_RESPONSE_INVALID_JSON"


def test_llm_client_rejects_invalid_runtime_response_format() -> None:
    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
    )

    with pytest.raises(LLMConfigurationError, match="unsupported response_format json_typo"):
        client.generate(
            LLMRequest(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": "Return JSON."}],
                temperature=0,
                max_output_tokens=64,
                response_format="json_typo",
            )
        )


def test_llm_client_rejects_invalid_runtime_api_mode() -> None:
    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
    )

    with pytest.raises(LLMConfigurationError, match="unsupported api_mode invalid_mode"):
        client.generate(
            LLMRequest(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": "Return JSON."}],
                temperature=0,
                max_output_tokens=64,
                response_format="json_object",
                api_mode="invalid_mode",  # type: ignore[arg-type]
            )
        )


def test_llm_client_rejects_non_object_json_in_json_object_mode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_array",
                "model": "gpt-5-mini",
                "output_text": '["not", "an", "object"]',
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMResponseError) as exc_info:
        client.generate(
            LLMRequest(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": "Return JSON."}],
                temperature=0,
                max_output_tokens=64,
                response_format="json_object",
            )
        )

    assert exc_info.value.code == "LLM_RESPONSE_INVALID_JSON_OBJECT"


def test_llm_client_preserves_provider_error_details_for_non_429_http_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": "invalid api key",
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                }
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMHTTPError) as exc_info:
        client.generate(
            LLMRequest(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": "Return JSON."}],
                temperature=0,
                max_output_tokens=64,
                response_format="json_object",
            )
        )

    assert exc_info.value.code == "LLM_HTTP_FAILURE"
    assert exc_info.value.status_code == 401
    assert exc_info.value.details == {
        "message": "invalid api key",
        "type": "invalid_request_error",
        "code": "invalid_api_key",
    }
    assert "invalid api key" in exc_info.value.message


def test_llm_client_preserves_provider_error_details_for_429_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "message": "too many requests",
                    "type": "rate_limit_error",
                    "code": "rate_limit_exceeded",
                }
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMHTTPError) as exc_info:
        client.generate(
            LLMRequest(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": "Return JSON."}],
                temperature=0,
                max_output_tokens=64,
                response_format="json_object",
            )
        )

    assert exc_info.value.code == "LLM_RATE_LIMITED"
    assert exc_info.value.status_code == 429
    assert exc_info.value.retryable is True
    assert exc_info.value.details == {
        "message": "too many requests",
        "type": "rate_limit_error",
        "code": "rate_limit_exceeded",
    }
    assert "too many requests" in exc_info.value.message


def test_llm_client_normalizes_timeout_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMTimeoutError) as exc_info:
        client.generate(
            LLMRequest(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": "Return JSON."}],
                temperature=0,
                max_output_tokens=64,
                response_format="json_object",
            )
        )

    assert exc_info.value.code == "LLM_REQUEST_TIMEOUT"
    assert exc_info.value.retryable is True


def test_llm_client_normalizes_request_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=12,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LLMHTTPError) as exc_info:
        client.generate(
            LLMRequest(
                model="gpt-5-mini",
                messages=[{"role": "user", "content": "Return JSON."}],
                temperature=0,
                max_output_tokens=64,
                response_format="json_object",
            )
        )

    assert exc_info.value.code == "LLM_HTTP_REQUEST_FAILED"
    assert exc_info.value.retryable is True


def test_llm_settings_and_model_routing_config_load_from_env_and_repo_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_API_KEY", "env-test-key")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_TIMEOUT_SECONDS", "41")
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_ENABLED", "true")

    settings = get_settings()
    config = load_model_routing_config(_repo_root() / "config" / "models.yaml")

    assert settings.llm_provider == "openai_compatible"
    assert settings.llm_base_url == "https://llm.example.test/v1"
    assert settings.llm_api_key == "env-test-key"
    assert settings.llm_timeout_seconds == 41
    assert settings.llm_enabled is True

    extraction = config.task_routing["extraction"]
    stylize = config.task_routing["stylize"]
    assert extraction.provider == "openai_compatible"
    assert extraction.response_format == "json_object"
    assert extraction.max_output_tokens > 0
    assert stylize.temperature >= extraction.temperature


def test_llm_settings_raise_clear_error_for_invalid_timeout_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NOVEL_SYSTEM_LLM_TIMEOUT_SECONDS", "not-a-number")

    with pytest.raises(ValueError, match="NOVEL_SYSTEM_LLM_TIMEOUT_SECONDS"):
        get_settings()


@pytest.mark.parametrize(
    ("yaml_body", "expected_message"),
    [
        ("[]\n", "models config must decode to a mapping"),
        ("task_routing: []\nretry_budget: {}\njob_runtime: {}\n", "task_routing must be a mapping"),
        ("task_routing: {}\nretry_budget: []\njob_runtime: {}\n", "retry_budget must be a mapping"),
        ("task_routing: {}\nretry_budget: {}\njob_runtime: []\n", "job_runtime must be a mapping"),
    ],
)
def test_load_model_routing_config_rejects_malformed_top_level_shapes(
    tmp_path: Path,
    yaml_body: str,
    expected_message: str,
) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(yaml_body, encoding="utf-8")

    with pytest.raises(LLMConfigurationError, match=expected_message):
        load_model_routing_config(config_path)


@pytest.mark.parametrize(
    ("yaml_body", "expected_message"),
    [
        (
            """
task_routing:
  extraction:
    provider: openai_compatible
    model: gpt-5-mini
    temperature: 0.1
    max_output_tokens: 100
    response_format: json_typo
retry_budget: {}
job_runtime: {}
""".strip(),
            "task_routing.extraction has unsupported response_format json_typo",
        ),
        (
            """
task_routing:
  extraction:
    provider: openai_compatible
    model: gpt-5-mini
    temperature: not-a-number
    max_output_tokens: 100
    response_format: json_object
retry_budget: {}
job_runtime: {}
""".strip(),
            "task_routing.extraction.temperature must be a valid float",
        ),
        (
            """
task_routing:
  extraction:
    provider: openai_compatible
    model: gpt-5-mini
    temperature: 0.1
    max_output_tokens: not-a-number
    response_format: json_object
retry_budget: {}
job_runtime: {}
""".strip(),
            "task_routing.extraction.max_output_tokens must be a valid integer",
        ),
        (
            """
task_routing:
  extraction:
    provider: bad_provider
    model: gpt-5-mini
    temperature: 0.1
    max_output_tokens: 100
    response_format: json_object
retry_budget: {}
job_runtime: {}
""".strip(),
            "task_routing.extraction has unsupported provider bad_provider",
        ),
    ],
)
def test_load_model_routing_config_rejects_invalid_task_model_values(
    tmp_path: Path,
    yaml_body: str,
    expected_message: str,
) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(yaml_body, encoding="utf-8")

    with pytest.raises(LLMConfigurationError, match=expected_message):
        load_model_routing_config(config_path)
