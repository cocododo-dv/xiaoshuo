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
    ProviderRuntimeConfig,
    build_oauth_state,
    load_model_routing_config,
    parse_model_routing_config,
    validate_oauth_state,
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
    assert response.attempt_count == 2
    assert response.max_retries == 1
    assert response.retryable is False


def test_llm_client_retries_malformed_json_before_succeeding() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                200,
                json={
                    "id": "resp_bad_json_once",
                    "model": "local-qwen",
                    "output_text": "I will explain instead of returning JSON.",
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "resp_good_json_retry",
                "model": "local-qwen",
                "output_text": '{"scene_text": "ok"}',
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key=None,
        timeout_seconds=12,
        max_retries=1,
        transport=httpx.MockTransport(handler),
    )

    response = client.generate(
        LLMRequest(
            model="local-qwen",
            messages=[{"role": "user", "content": "Return JSON."}],
            temperature=0,
            max_output_tokens=64,
            response_format="json_object",
        )
    )

    assert attempts == 2
    assert response.request_id == "resp_good_json_retry"
    assert response.structured_output == {"scene_text": "ok"}
    assert response.attempt_count == 2
    assert response.max_retries == 1
    assert response.retryable is False


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


def test_llm_client_extracts_wrapped_json_object_from_local_model_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "resp_wrapped_json",
                "model": "local-qwen",
                "output_text": 'Here is the JSON:\n```json\n{"scene_text": "ok"}\n```',
            },
        )

    client = LLMClient(
        provider="openai_compatible",
        base_url="https://example.test/v1",
        api_key=None,
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
    )

    response = client.generate(
        LLMRequest(
            model="local-qwen",
            messages=[{"role": "user", "content": "Return JSON."}],
            temperature=0,
            max_output_tokens=64,
            response_format="json_object",
        )
    )

    assert response.text == 'Here is the JSON:\n```json\n{"scene_text": "ok"}\n```'
    assert response.structured_output == {"scene_text": "ok"}


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
        "attempt_count": 1,
        "max_retries": 2,
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
        "attempt_count": 1,
        "max_retries": 0,
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
    assert exc_info.value.details["attempt_count"] == 1
    assert exc_info.value.details["max_retries"] == 0


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
    assert exc_info.value.details["attempt_count"] == 1
    assert exc_info.value.details["max_retries"] == 0


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


def test_parse_model_routing_config_normalizes_node_routing_and_legacy_stylize() -> None:
    config = parse_model_routing_config(
        {
            "node_routing": {
                "neutral_draft": {
                    "provider": "openai",
                    "provider_id": "openai_primary",
                    "account_id": "acct_ops",
                    "model": "gpt-5.4",
                    "temperature": 0.35,
                    "max_output_tokens": 3200,
                    "response_format": "json_object",
                    "reasoning_level": "medium",
                    "api_mode": "responses",
                    "provider_options": {"text_verbosity": "low"},
                }
            },
            "task_routing": {
                "stylize": {
                    "provider": "anthropic",
                    "provider_id": "claude_primary",
                    "model": "claude-sonnet-4-5",
                    "temperature": 0.7,
                    "max_output_tokens": 5000,
                    "response_format": "json_object",
                    "reasoning_level": "high",
                }
            },
            "retry_budget": {"total_attempt_budget": 3},
            "job_runtime": {},
        }
    )

    neutral = config.node_routing["neutral_draft"]
    style = config.node_routing["style_draft"]
    patch = config.node_routing["style_patch"]

    assert neutral.provider == "openai"
    assert neutral.provider_id == "openai_primary"
    assert neutral.account_id == "acct_ops"
    assert neutral.reasoning_level == "medium"
    assert neutral.provider_options == {"text_verbosity": "low"}
    assert style.provider == "anthropic"
    assert style.model == "claude-sonnet-4-5"
    assert patch.model == "claude-sonnet-4-5"
    assert config.task_routing["stylize"].model == "claude-sonnet-4-5"


def test_parse_model_routing_config_rejects_invalid_reasoning_level() -> None:
    with pytest.raises(LLMConfigurationError, match="unsupported reasoning_level turbo"):
        parse_model_routing_config(
            {
                "node_routing": {
                    "neutral_draft": {
                        "provider": "openai",
                        "model": "gpt-5.4",
                        "temperature": 0.2,
                        "max_output_tokens": 1000,
                        "response_format": "json_object",
                        "reasoning_level": "turbo",
                    }
                },
                "retry_budget": {},
                "job_runtime": {},
            }
        )


def test_openai_adapter_maps_reasoning_and_json_schema() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = {
            "url": str(request.url),
            "headers": dict(request.headers),
            "body": json.loads(request.content.decode("utf-8")),
        }
        return httpx.Response(
            200,
            json={
                "id": "resp_openai_reasoning",
                "model": "gpt-5.4",
                "output_text": '{"scene_text": "ok"}',
                "usage": {"input_tokens": 4, "output_tokens": 5, "total_tokens": 9},
                "finish_reason": "stop",
            },
        )

    client = LLMClient(
        provider="openai",
        base_url="https://example.test/v1",
        api_key="legacy-unused",
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
        provider_configs={
            "openai_primary": ProviderRuntimeConfig(
                provider_id="openai_primary",
                provider_type="openai",
                base_url="https://example.test/v1",
                api_key="openai-key",
                api_mode="responses",
            )
        },
    )

    response = client.generate(
        LLMRequest(
            node_id="neutral_draft",
            provider_id="openai_primary",
            account_id="acct_openai",
            model="gpt-5.4",
            messages=[{"role": "user", "content": "Return JSON."}],
            temperature=0.2,
            max_output_tokens=100,
            response_format="json_object",
            response_schema={"name": "scene_payload", "schema": {"type": "object"}},
            reasoning_level="high",
        )
    )

    body = captured["body"]
    assert captured["url"] == "https://example.test/v1/responses"
    assert captured["headers"]["authorization"] == "Bearer openai-key"
    assert body["reasoning"] == {"effort": "high"}
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["name"] == "scene_payload"
    assert response.provider == "openai"
    assert response.model == "gpt-5.4"
    assert response.structured_output == {"scene_text": "ok"}


@pytest.mark.parametrize(
    ("provider_id", "provider_config", "request_kwargs", "response_body", "assert_payload"),
    [
        (
            "claude_primary",
            ProviderRuntimeConfig(
                provider_id="claude_primary",
                provider_type="anthropic",
                base_url="https://api.anthropic.test/v1",
                api_key="claude-key",
            ),
            {"model": "claude-sonnet-4-5", "reasoning_level": "medium", "max_output_tokens": 12000},
            {
                "id": "msg_123",
                "model": "claude-sonnet-4-5",
                "content": [{"type": "text", "text": '{"scene_text": "claude"}'}],
                "usage": {"input_tokens": 11, "output_tokens": 22},
                "stop_reason": "end_turn",
            },
            lambda captured: (
                captured["url"].endswith("/messages")
                and captured["headers"]["x-api-key"] == "claude-key"
                and captured["body"]["thinking"] == {"type": "enabled", "budget_tokens": 4096}
            ),
        ),
        (
            "deepseek_primary",
            ProviderRuntimeConfig(
                provider_id="deepseek_primary",
                provider_type="deepseek",
                base_url="https://api.deepseek.test/v1",
                api_key="deepseek-key",
            ),
            {"model": "deepseek-reasoner", "reasoning_level": "high"},
            {
                "id": "chatcmpl_deepseek",
                "model": "deepseek-reasoner",
                "choices": [{"finish_reason": "stop", "message": {"content": '{"scene_text": "deepseek"}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
            },
            lambda captured: (
                captured["url"].endswith("/chat/completions")
                and captured["headers"]["authorization"] == "Bearer deepseek-key"
                and captured["body"]["thinking"] == {"type": "enabled"}
            ),
        ),
        (
            "glm_primary",
            ProviderRuntimeConfig(
                provider_id="glm_primary",
                provider_type="zhipu_glm",
                base_url="https://open.bigmodel.test/api/paas/v4",
                api_key="glm-key",
            ),
            {"model": "glm-4.6", "reasoning_level": "off"},
            {
                "id": "chatcmpl_glm",
                "model": "glm-4.6",
                "choices": [{"finish_reason": "stop", "message": {"content": '{"scene_text": "glm"}'}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 9, "total_tokens": 17},
            },
            lambda captured: (
                captured["url"].endswith("/chat/completions")
                and captured["headers"]["authorization"] == "Bearer glm-key"
                and captured["body"]["thinking"] == {"type": "disabled"}
            ),
        ),
        (
            "gemini_primary",
            ProviderRuntimeConfig(
                provider_id="gemini_primary",
                provider_type="gemini",
                base_url="https://generativelanguage.googleapis.test/v1beta",
                api_key="gemini-key",
            ),
            {"model": "gemini-2.5-pro", "reasoning_level": "medium"},
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": '{"scene_text": "gemini"}'}]},
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 4,
                    "totalTokenCount": 7,
                },
            },
            lambda captured: (
                "models/gemini-2.5-pro:generateContent?key=gemini-key" in captured["url"]
                and captured["body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 4096
                and captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
            ),
        ),
    ],
)
def test_provider_adapters_normalize_successful_json_responses(
    provider_id: str,
    provider_config: ProviderRuntimeConfig,
    request_kwargs: dict[str, object],
    response_body: dict[str, object],
    assert_payload,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = {
            "url": str(request.url),
            "headers": dict(request.headers),
            "body": json.loads(request.content.decode("utf-8")),
        }
        return httpx.Response(200, json=response_body)

    client = LLMClient(
        provider="openai",
        base_url="https://unused.test/v1",
        api_key=None,
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
        provider_configs={provider_id: provider_config},
    )

    response = client.generate(
        LLMRequest(
            node_id="style_draft",
            provider_id=provider_id,
            account_id="acct_primary",
            model=str(request_kwargs["model"]),
            messages=[
                {"role": "system", "content": "Return only JSON."},
                {"role": "user", "content": "Draft the scene."},
            ],
            temperature=0.2,
            max_output_tokens=int(request_kwargs.get("max_output_tokens", 1000)),
            response_format="json_object",
            reasoning_level=str(request_kwargs["reasoning_level"]),
        )
    )

    assert assert_payload(captured)
    assert response.provider == provider_config.provider_type
    assert response.structured_output
    assert response.usage["total_tokens"] > 0
    assert response.finish_reason


def test_gemini_oauth_credential_uses_bearer_without_api_key_query() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = {
            "url": str(request.url),
            "headers": dict(request.headers),
            "body": json.loads(request.content.decode("utf-8")),
        }
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": '{"scene_text": "oauth"}'}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2, "totalTokenCount": 3},
            },
        )

    client = LLMClient(
        provider="gemini",
        base_url="https://unused.test",
        api_key=None,
        timeout_seconds=12,
        transport=httpx.MockTransport(handler),
        provider_configs={
            "gemini_oauth": ProviderRuntimeConfig(
                provider_id="gemini_oauth",
                provider_type="gemini",
                base_url="https://generativelanguage.googleapis.test/v1beta",
                credential_mode="oauth2",
                access_token="ya29.test-token",
            )
        },
    )

    response = client.generate(
        LLMRequest(
            node_id="literary_eval_live",
            provider_id="gemini_oauth",
            credential_mode="oauth2",
            model="gemini-2.5-pro",
            messages=[{"role": "user", "content": "Return JSON."}],
            temperature=0.1,
            max_output_tokens=500,
            response_format="json_object",
            reasoning_level="low",
        )
    )

    assert "key=" not in captured["url"]
    assert captured["headers"]["authorization"] == "Bearer ya29.test-token"
    assert response.structured_output == {"scene_text": "oauth"}


def test_oauth_state_is_signed_and_tamper_resistant() -> None:
    state = build_oauth_state(
        provider_type="gemini",
        provider_id="gemini_oauth",
        account_id="acct_google",
        redirect_path="/api/v1/system-config/llm/oauth/callback",
        secret="config-secret",
    )

    payload = validate_oauth_state(state, secret="config-secret")
    payload_part, signature_part = state.split(".", 1)
    replacement = "A" if payload_part[-1] != "A" else "B"
    tampered = f"{payload_part[:-1]}{replacement}.{signature_part}"

    assert payload["provider_type"] == "gemini"
    assert payload["provider_id"] == "gemini_oauth"
    assert payload["account_id"] == "acct_google"
    with pytest.raises(LLMConfigurationError, match="invalid oauth state"):
        validate_oauth_state(tampered, secret="config-secret")
