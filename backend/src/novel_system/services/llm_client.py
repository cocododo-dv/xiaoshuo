from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml

from novel_system.services.llm_providers import (
    default_provider_base_urls,
    get_adapter,
    supported_provider_types,
)
from novel_system.services.llm_providers.anthropic import CLAUDE_THINKING_BUDGETS
from novel_system.services.llm_providers.base import (
    LLMClientError,
    LLMConfigurationError,
    LLMHTTPError,
    LLMRateLimitError,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
    ProviderRuntimeConfig,
    SUPPORTED_API_MODES,
    SUPPORTED_CREDENTIAL_MODES,
    SUPPORTED_REASONING_LEVELS,
    SUPPORTED_RESPONSE_FORMATS,
)
from novel_system.services.llm_providers.gemini import GEMINI_THINKING_BUDGETS

__all__ = [
    "CLAUDE_THINKING_BUDGETS",
    "DEFAULT_PROVIDER_BASE_URLS",
    "GEMINI_THINKING_BUDGETS",
    "LLMClient",
    "LLMClientError",
    "LLMConfigurationError",
    "LLMHTTPError",
    "LLMRateLimitError",
    "LLMRequest",
    "LLMResponse",
    "LLMResponseError",
    "LLMTimeoutError",
    "ModelRoutingConfig",
    "ProviderRuntimeConfig",
    "RETRYABLE_RESPONSE_ERROR_CODES",
    "RETRYABLE_STATUS_CODES",
    "SUPPORTED_API_MODES",
    "SUPPORTED_CREDENTIAL_MODES",
    "SUPPORTED_PROVIDERS",
    "SUPPORTED_REASONING_LEVELS",
    "SUPPORTED_RESPONSE_FORMATS",
    "TaskModelConfig",
    "load_model_routing_config",
    "parse_model_routing_config",
]


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
RETRYABLE_RESPONSE_ERROR_CODES = {"LLM_RESPONSE_INVALID_JSON", "LLM_RESPONSE_MISSING_TEXT"}
SUPPORTED_PROVIDERS = frozenset(supported_provider_types())
MAX_RETRY_BACKOFF_SECONDS = 30.0

DEFAULT_PROVIDER_BASE_URLS = default_provider_base_urls()


@dataclass(slots=True, frozen=True)
class TaskModelConfig:
    provider: str
    model: str
    temperature: float
    max_output_tokens: int
    response_format: str
    model_profile: str | None = None
    provider_id: str | None = None
    account_id: str | None = None
    reasoning_level: Literal["off", "low", "medium", "high"] = "medium"
    api_mode: Literal["responses", "chat"] = "responses"
    credential_mode: Literal["api_key", "none"] | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    # §7 anti-mean sampling — optional decoding-level penalties (OpenAI-compatible APIs)
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    top_p: float | None = None


@dataclass(slots=True, frozen=True)
class ModelRoutingConfig:
    node_routing: dict[str, TaskModelConfig]
    task_routing: dict[str, TaskModelConfig]
    model_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    retry_budget: dict[str, int] = field(default_factory=dict)
    job_runtime: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.0,
        transport: httpx.BaseTransport | None = None,
        provider_configs: dict[str, ProviderRuntimeConfig] | None = None,
    ) -> None:
        self._provider = provider
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_backoff_seconds = max(0.0, float(retry_backoff_seconds or 0.0))
        self._transport = transport
        self._provider_configs = provider_configs or {}

    def _sleep_before_retry(self, attempt: int, *, response: httpx.Response | None = None) -> None:
        """限流/瞬时故障重试前指数退避(默认 0 = 关闭,生产由 runner 开启)。

        立即重试对容量受限的中转(如 gcli2api 的 No capacity)只会三连击同一错误;
        退避给服务端腾出恢复窗口,429 时优先尊重 Retry-After。
        """
        if self._retry_backoff_seconds <= 0:
            return
        delay = self._retry_backoff_seconds * (2 ** attempt)
        if response is not None:
            retry_after = _parse_retry_after_seconds(response.headers.get("Retry-After"))
            if retry_after is not None:
                delay = max(delay, retry_after)
        delay = min(delay, MAX_RETRY_BACKOFF_SECONDS)
        delay *= 0.8 + 0.4 * random.random()
        time.sleep(delay)

    def generate(self, request: LLMRequest) -> LLMResponse:
        self._validate_request(request)
        provider_config = self._resolve_provider_config(request)
        self._validate_provider(provider_config.provider_type)
        endpoint, payload, headers, native_reasoning = self._build_http_request(request, provider_config)
        timeout_seconds = request.timeout_seconds or self._timeout_seconds

        with httpx.Client(
            base_url=provider_config.base_url.rstrip("/"),
            timeout=timeout_seconds,
            transport=self._transport,
        ) as client:
            for attempt in range(self._max_retries + 1):
                try:
                    response = client.post(endpoint, json=payload, headers=headers)
                except httpx.TimeoutException as exc:
                    if attempt < self._max_retries:
                        self._sleep_before_retry(attempt)
                        continue
                    raise LLMTimeoutError(
                        "LLM_REQUEST_TIMEOUT",
                        f"llm request timed out after {timeout_seconds} seconds",
                        retryable=True,
                        details=_with_attempt_metadata({}, attempt=attempt, max_retries=self._max_retries),
                    ) from exc
                except httpx.RequestError as exc:
                    if attempt < self._max_retries:
                        self._sleep_before_retry(attempt)
                        continue
                    raise LLMHTTPError(
                        "LLM_HTTP_REQUEST_FAILED",
                        f"llm request failed: {exc}",
                        retryable=True,
                        details=_with_attempt_metadata({}, attempt=attempt, max_retries=self._max_retries),
                    ) from exc

                if response.status_code == 429:
                    if attempt < self._max_retries:
                        self._sleep_before_retry(attempt, response=response)
                        continue
                    raise LLMRateLimitError(
                        "LLM_RATE_LIMITED",
                        _error_message_for_status(response, request=request, provider_config=provider_config, endpoint=endpoint),
                        status_code=429,
                        retryable=True,
                        details=_http_error_details(
                            response,
                            request=request,
                            provider_config=provider_config,
                            endpoint=endpoint,
                            attempt=attempt,
                            max_retries=self._max_retries,
                        ),
                    )

                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt < self._max_retries:
                        self._sleep_before_retry(attempt, response=response)
                        continue
                    raise LLMHTTPError(
                        "LLM_HTTP_RETRYABLE_FAILURE",
                        _error_message_for_status(response, request=request, provider_config=provider_config, endpoint=endpoint),
                        status_code=response.status_code,
                        retryable=True,
                        details=_http_error_details(
                            response,
                            request=request,
                            provider_config=provider_config,
                            endpoint=endpoint,
                            attempt=attempt,
                            max_retries=self._max_retries,
                        ),
                    )

                if response.is_error:
                    raise LLMHTTPError(
                        "LLM_HTTP_FAILURE",
                        _error_message_for_status(response, request=request, provider_config=provider_config, endpoint=endpoint),
                        status_code=response.status_code,
                        details=_http_error_details(
                            response,
                            request=request,
                            provider_config=provider_config,
                            endpoint=endpoint,
                            attempt=attempt,
                            max_retries=self._max_retries,
                        ),
                    )

                try:
                    body = response.json()
                except ValueError as exc:
                    raise LLMResponseError(
                        "LLM_RESPONSE_INVALID",
                        "llm provider returned invalid JSON",
                        details=_with_attempt_metadata({}, attempt=attempt, max_retries=self._max_retries),
                    ) from exc

                try:
                    return self._parse_response(
                        body,
                        request,
                        provider_config,
                        native_reasoning=native_reasoning,
                        attempt_count=attempt + 1,
                        max_retries=self._max_retries,
                    )
                except LLMResponseError as exc:
                    if exc.code in RETRYABLE_RESPONSE_ERROR_CODES and attempt < self._max_retries:
                        self._sleep_before_retry(attempt)
                        continue
                    exc.details = _with_attempt_metadata(
                        exc.details,
                        attempt=attempt,
                        max_retries=self._max_retries,
                    )
                    exc.retryable = exc.code in RETRYABLE_RESPONSE_ERROR_CODES
                    raise

        raise LLMHTTPError(
            "LLM_HTTP_FAILURE",
            "llm request failed without a response",
            retryable=True,
            details=_with_attempt_metadata({}, attempt=self._max_retries, max_retries=self._max_retries),
        )

    def _resolve_provider_config(self, request: LLMRequest) -> ProviderRuntimeConfig:
        provider_id = request.provider_id or request.provider
        if provider_id and provider_id in self._provider_configs:
            config = self._provider_configs[provider_id]
            if not config.enabled:
                raise LLMConfigurationError(
                    "LLM_PROVIDER_DISABLED",
                    f"llm provider {provider_id} is disabled",
                )
            return config

        provider_type = request.provider or self._provider
        return ProviderRuntimeConfig(
            provider_id=provider_id or provider_type,
            provider_type=provider_type,
            base_url=self._base_url,
            api_key=self._api_key,
            credential_mode=request.credential_mode or ("api_key" if self._api_key else "none"),
            api_mode=request.api_mode,
        )

    def _build_http_request(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[str, dict[str, Any], dict[str, str], dict[str, Any] | None]:
        adapter = get_adapter(provider_config.provider_type)
        built = adapter.build_request(request, provider_config)
        return built.endpoint, built.payload, built.headers, built.native_reasoning

    def _parse_response(
        self,
        body: dict[str, Any],
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
        *,
        native_reasoning: dict[str, Any] | None,
        attempt_count: int,
        max_retries: int,
    ) -> LLMResponse:
        adapter = get_adapter(provider_config.provider_type)
        text = adapter.extract_output_text(body, request=request)
        structured_output: dict[str, Any] | None = None
        if request.response_format == "json_object":
            try:
                structured_output = _loads_json_object_text(text)
            except json.JSONDecodeError as exc:
                raise LLMResponseError(
                    "LLM_RESPONSE_INVALID_JSON",
                    "llm provider returned malformed JSON content",
                ) from exc
            if not isinstance(structured_output, dict):
                raise LLMResponseError(
                    "LLM_RESPONSE_INVALID_JSON_OBJECT",
                    "llm provider returned a non-object JSON payload for json_object mode",
                )

        return LLMResponse(
            request_id=_extract_request_id(body),
            provider=provider_config.provider_type,
            model=str(body.get("model", request.model)),
            text=text,
            structured_output=structured_output,
            response_format=request.response_format,
            raw_response=body,
            usage=adapter.normalize_usage(body) or _normalize_usage(body.get("usage") or body.get("usageMetadata")),
            finish_reason=adapter.extract_finish_reason(body, api_mode=request.api_mode),
            native_reasoning=native_reasoning,
            attempt_count=attempt_count,
            max_retries=max_retries,
            retryable=False,
        )

    def _validate_provider(self, provider: str) -> None:
        if provider not in SUPPORTED_PROVIDERS:
            raise LLMConfigurationError(
                "LLM_PROVIDER_UNSUPPORTED",
                f"unsupported llm provider {provider}",
            )

    def _validate_request(self, request: LLMRequest) -> None:
        if request.response_format not in SUPPORTED_RESPONSE_FORMATS:
            raise LLMConfigurationError(
                "LLM_REQUEST_INVALID",
                f"unsupported response_format {request.response_format}",
            )
        if request.api_mode not in SUPPORTED_API_MODES:
            raise LLMConfigurationError(
                "LLM_REQUEST_INVALID",
                f"unsupported api_mode {request.api_mode}",
            )
        if request.reasoning_level not in SUPPORTED_REASONING_LEVELS:
            raise LLMConfigurationError(
                "LLM_REQUEST_INVALID",
                f"unsupported reasoning_level {request.reasoning_level}",
            )


def load_model_routing_config(path: str | Path | None = None) -> ModelRoutingConfig:
    if path is None:
        from novel_system.services.system_config import load_active_config_payload

        raw_payload = load_active_config_payload("models")
        if raw_payload is None:
            config_path = _default_models_config_path()
            raw_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    else:
        config_path = Path(path)
        raw_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return parse_model_routing_config(raw_payload)


def parse_model_routing_config(raw_payload: Any) -> ModelRoutingConfig:
    if raw_payload is None:
        raw_payload = {}
    if not isinstance(raw_payload, dict):
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            "models config must decode to a mapping",
        )

    raw_node_routing = _require_mapping(raw_payload, "node_routing")
    raw_task_routing = _require_mapping(raw_payload, "task_routing")
    raw_model_profiles = _require_mapping(raw_payload, "model_profiles")
    retry_budget = _require_mapping(raw_payload, "retry_budget")
    job_runtime = _require_mapping(raw_payload, "job_runtime")

    node_routing = {
        node_name: _load_task_model_config(node_name, node_payload)
        for node_name, node_payload in raw_node_routing.items()
    }
    task_routing = {
        task_name: _load_task_model_config(task_name, task_payload)
        for task_name, task_payload in raw_task_routing.items()
    }

    for task_name, task_config in task_routing.items():
        if task_name == "stylize":
            continue
        else:
            node_routing.setdefault(task_name, task_config)

    for node_name, node_config in node_routing.items():
        task_routing.setdefault(node_name, node_config)
    if "style_draft" in node_routing:
        task_routing.setdefault("stylize", node_routing["style_draft"])

    return ModelRoutingConfig(
        node_routing=node_routing,
        task_routing=task_routing,
        model_profiles=_normalize_model_profiles(raw_model_profiles),
        retry_budget=dict(retry_budget),
        job_runtime=dict(job_runtime),
    )


def _default_models_config_path() -> Path:
    return Path(__file__).resolve().parents[4] / "config" / "models.yaml"


def _load_task_model_config(task_name: str, payload: Any) -> TaskModelConfig:
    if not isinstance(payload, dict):
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name} must be a mapping",
        )

    try:
        return TaskModelConfig(
            provider=_parse_provider(task_name, payload),
            model_profile=_optional_str(payload.get("model_profile")),
            provider_id=_optional_str(payload.get("provider_id")),
            account_id=_optional_str(payload.get("account_id")),
            model=str(payload["model"]),
            temperature=_parse_float_config_value(task_name, payload, "temperature"),
            max_output_tokens=_parse_int_config_value(task_name, payload, "max_output_tokens"),
            response_format=_parse_response_format(task_name, payload),
            reasoning_level=_parse_reasoning_level(task_name, payload),
            api_mode=_parse_api_mode(task_name, payload),
            credential_mode=_parse_credential_mode(task_name, payload),
            provider_options=_parse_provider_options(task_name, payload),
            frequency_penalty=_optional_sampling_value(task_name, payload, "frequency_penalty"),
            presence_penalty=_optional_sampling_value(task_name, payload, "presence_penalty"),
            top_p=_optional_sampling_value(task_name, payload, "top_p"),
        )
    except KeyError as exc:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name} is missing {exc.args[0]}",
        ) from exc


def _require_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"{key} must be a mapping",
        )
    return value


def _normalize_model_profiles(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for profile_key, profile_payload in payload.items():
        if not isinstance(profile_key, str):
            raise LLMConfigurationError(
                "LLM_MODEL_CONFIG_INVALID",
                "model profile names must be strings",
            )
        if not isinstance(profile_payload, dict):
            raise LLMConfigurationError(
                "LLM_MODEL_CONFIG_INVALID",
                f"model_profiles.{profile_key} must be a mapping",
            )
        profiles[profile_key] = dict(profile_payload)
    return profiles


def _parse_float_config_value(task_name: str, payload: dict[str, Any], field: str) -> float:
    value = payload[field]
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name}.{field} must be a valid float",
        ) from exc


def _optional_sampling_value(task_name: str, payload: dict[str, Any], field: str) -> float | None:
    """§7: parse an optional decoding-level sampling knob; absent key → None (provider default)."""
    if field not in payload or payload[field] is None:
        return None
    try:
        return float(payload[field])
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name}.{field} must be a valid float",
        ) from exc


def _parse_int_config_value(task_name: str, payload: dict[str, Any], field: str) -> int:
    value = payload[field]
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name}.{field} must be a valid integer",
        ) from exc


def _parse_response_format(task_name: str, payload: dict[str, Any]) -> str:
    value = str(payload["response_format"])
    if value not in SUPPORTED_RESPONSE_FORMATS:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name} has unsupported response_format {value}",
        )
    return value


def _parse_provider(task_name: str, payload: dict[str, Any]) -> str:
    value = str(payload.get("provider") or payload.get("provider_type") or "openai_compatible")
    if value not in SUPPORTED_PROVIDERS:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name} has unsupported provider {value}",
        )
    return value


def _parse_reasoning_level(task_name: str, payload: dict[str, Any]) -> Literal["off", "low", "medium", "high"]:
    value = str(payload.get("reasoning_level", "medium"))
    if value not in SUPPORTED_REASONING_LEVELS:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name} has unsupported reasoning_level {value}",
        )
    return value  # type: ignore[return-value]


def _parse_api_mode(task_name: str, payload: dict[str, Any]) -> Literal["responses", "chat"]:
    value = str(payload.get("api_mode", "responses"))
    if value not in SUPPORTED_API_MODES:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name} has unsupported api_mode {value}",
        )
    return value  # type: ignore[return-value]


def _parse_credential_mode(task_name: str, payload: dict[str, Any]) -> Literal["api_key", "none"] | None:
    if payload.get("credential_mode") is None:
        return None
    value = str(payload.get("credential_mode"))
    if value not in SUPPORTED_CREDENTIAL_MODES:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name} has unsupported credential_mode {value}",
        )
    return value  # type: ignore[return-value]


def _parse_provider_options(task_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    provider_options = payload.get("provider_options", {})
    if not isinstance(provider_options, dict):
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name}.provider_options must be a mapping",
        )
    return dict(provider_options)


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _loads_json_object_text(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_exc:
        for candidate in _iter_json_object_candidates(text):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        raise original_exc


def _iter_json_object_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break
        start = text.find("{", start + 1)
    return candidates


def _normalize_usage(usage: Any) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    if "input_tokens" in usage or "output_tokens" in usage:
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("total_tokens", input_tokens + output_tokens) or 0),
        }

    if "promptTokenCount" in usage or "candidatesTokenCount" in usage:
        input_tokens = int(usage.get("promptTokenCount", 0) or 0)
        output_tokens = int(usage.get("candidatesTokenCount", 0) or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": int(usage.get("totalTokenCount", input_tokens + output_tokens) or 0),
        }

    return {
        "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def _parse_retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError):
        return None  # HTTP-date 形式的 Retry-After 不解析,走指数退避
    if seconds < 0:
        return None
    return min(seconds, MAX_RETRY_BACKOFF_SECONDS)


def _extract_request_id(body: dict[str, Any]) -> str | None:
    request_id = body.get("id")
    if isinstance(request_id, str) and request_id:
        return request_id
    return None


def _extract_error_details(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        if response.text:
            return {"message": response.text}
        return {}

    if not isinstance(body, dict):
        return {"body": body}

    error = body.get("error")
    if isinstance(error, dict):
        return error
    return body


def _with_attempt_metadata(details: dict[str, Any], *, attempt: int, max_retries: int) -> dict[str, Any]:
    return {
        **dict(details),
        "attempt_count": attempt + 1,
        "max_retries": max_retries,
    }


def _http_error_details(
    response: httpx.Response,
    *,
    request: LLMRequest,
    provider_config: ProviderRuntimeConfig,
    endpoint: str,
    attempt: int,
    max_retries: int,
) -> dict[str, Any]:
    details = _with_attempt_metadata(
        _extract_error_details(response),
        attempt=attempt,
        max_retries=max_retries,
    )
    hint = _provider_protocol_hint(response, request=request, provider_config=provider_config, endpoint=endpoint)
    if hint:
        details.update(
            {
                "status_code": response.status_code,
                "provider_id": provider_config.provider_id,
                "provider_type": provider_config.provider_type,
                "model": request.model,
                "node_id": request.node_id,
                "api_mode": request.api_mode,
                "endpoint": endpoint,
            }
        )
        details.setdefault("hint", hint["message"])
        details.setdefault("next_action", hint["next_action"])
    return details


def _error_message_for_status(
    response: httpx.Response,
    *,
    request: LLMRequest | None = None,
    provider_config: ProviderRuntimeConfig | None = None,
    endpoint: str | None = None,
) -> str:
    details = _extract_error_details(response)
    detail_message = details.get("message")
    if isinstance(detail_message, str) and detail_message:
        message = detail_message
    else:
        message = f"llm request failed with status {response.status_code}"
    if request is not None and provider_config is not None and endpoint is not None:
        hint = _provider_protocol_hint(response, request=request, provider_config=provider_config, endpoint=endpoint)
        if hint:
            return f"{message}; {hint['message']}"
    return message


def _provider_protocol_hint(
    response: httpx.Response,
    *,
    request: LLMRequest,
    provider_config: ProviderRuntimeConfig,
    endpoint: str,
) -> dict[str, str] | None:
    try:
        adapter = get_adapter(provider_config.provider_type)
    except LLMConfigurationError:
        return None
    return adapter.protocol_hint(
        status_code=response.status_code,
        endpoint=endpoint,
        request=request,
        provider_config=provider_config,
    )
