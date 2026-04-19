from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

import httpx
import yaml


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
SUPPORTED_PROVIDERS = {"openai_compatible", "openai", "anthropic", "deepseek", "zhipu_glm", "gemini"}
SUPPORTED_RESPONSE_FORMATS = {"json_object", "text"}
SUPPORTED_API_MODES = {"responses", "chat"}
SUPPORTED_REASONING_LEVELS = {"off", "low", "medium", "high"}
SUPPORTED_CREDENTIAL_MODES = {"api_key", "oauth2", "none"}

DEFAULT_PROVIDER_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "openai_compatible": "http://127.0.0.1:11434/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "zhipu_glm": "https://open.bigmodel.cn/api/paas/v4",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}

CLAUDE_THINKING_BUDGETS = {"medium": 4096, "high": 10000}
GEMINI_THINKING_BUDGETS = {"low": 1024, "medium": 4096, "high": 8192}


@dataclass(slots=True, frozen=True)
class ProviderRuntimeConfig:
    provider_id: str
    provider_type: str
    base_url: str
    api_key: str | None = None
    account_id: str | None = None
    enabled: bool = True
    credential_mode: Literal["api_key", "oauth2", "none"] = "api_key"
    api_mode: Literal["responses", "chat"] = "chat"
    models: tuple[str, ...] = ()
    access_token: str | None = None
    refresh_token: str | None = None
    token_expires_at: str | None = None
    scopes: tuple[str, ...] = ()
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class LLMRequest:
    model: str
    messages: list[dict[str, str]]
    temperature: float
    max_output_tokens: int
    response_format: str
    provider: str | None = None
    timeout_seconds: float | None = None
    api_mode: Literal["responses", "chat"] = "responses"
    node_id: str | None = None
    provider_id: str | None = None
    account_id: str | None = None
    reasoning_level: Literal["off", "low", "medium", "high"] = "medium"
    response_schema: dict[str, Any] | None = None
    credential_mode: Literal["api_key", "oauth2", "none"] | None = None
    provider_options: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class LLMResponse:
    request_id: str | None
    provider: str
    model: str
    text: str
    structured_output: dict[str, Any] | None
    response_format: str
    raw_response: dict[str, Any]
    usage: dict[str, int]
    finish_reason: str | None = None
    native_reasoning: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class TaskModelConfig:
    provider: str
    model: str
    temperature: float
    max_output_tokens: int
    response_format: str
    provider_id: str | None = None
    account_id: str | None = None
    reasoning_level: Literal["off", "low", "medium", "high"] = "medium"
    api_mode: Literal["responses", "chat"] = "responses"
    credential_mode: Literal["api_key", "oauth2", "none"] | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ModelRoutingConfig:
    node_routing: dict[str, TaskModelConfig]
    task_routing: dict[str, TaskModelConfig]
    retry_budget: dict[str, int]
    job_runtime: dict[str, Any]


class LLMClientError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}


class LLMConfigurationError(LLMClientError):
    pass


class LLMTimeoutError(LLMClientError):
    pass


class LLMHTTPError(LLMClientError):
    pass


class LLMRateLimitError(LLMHTTPError):
    pass


class LLMResponseError(LLMClientError):
    pass


class LLMClient:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
        provider_configs: dict[str, ProviderRuntimeConfig] | None = None,
    ) -> None:
        self._provider = provider
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._transport = transport
        self._provider_configs = provider_configs or {}

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
                        continue
                    raise LLMTimeoutError(
                        "LLM_REQUEST_TIMEOUT",
                        f"llm request timed out after {timeout_seconds} seconds",
                        retryable=True,
                    ) from exc
                except httpx.RequestError as exc:
                    if attempt < self._max_retries:
                        continue
                    raise LLMHTTPError(
                        "LLM_HTTP_REQUEST_FAILED",
                        f"llm request failed: {exc}",
                        retryable=True,
                    ) from exc

                if response.status_code == 429:
                    if attempt < self._max_retries:
                        continue
                    raise LLMRateLimitError(
                        "LLM_RATE_LIMITED",
                        _error_message_for_status(response),
                        status_code=429,
                        retryable=True,
                        details=_extract_error_details(response),
                    )

                if response.status_code in RETRYABLE_STATUS_CODES:
                    if attempt < self._max_retries:
                        continue
                    raise LLMHTTPError(
                        "LLM_HTTP_RETRYABLE_FAILURE",
                        _error_message_for_status(response),
                        status_code=response.status_code,
                        retryable=True,
                        details=_extract_error_details(response),
                    )

                if response.is_error:
                    raise LLMHTTPError(
                        "LLM_HTTP_FAILURE",
                        _error_message_for_status(response),
                        status_code=response.status_code,
                        details=_extract_error_details(response),
                    )

                try:
                    body = response.json()
                except ValueError as exc:
                    raise LLMResponseError(
                        "LLM_RESPONSE_INVALID",
                        "llm provider returned invalid JSON",
                    ) from exc

                return self._parse_response(body, request, provider_config, native_reasoning=native_reasoning)

        raise LLMHTTPError(
            "LLM_HTTP_FAILURE",
            "llm request failed without a response",
            retryable=True,
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
        provider_type = provider_config.provider_type
        if provider_type in {"openai", "openai_compatible"}:
            return self._build_openai_request(request, provider_config)
        if provider_type == "anthropic":
            return self._build_anthropic_request(request, provider_config)
        if provider_type in {"deepseek", "zhipu_glm"}:
            return self._build_openai_chat_compatible_request(request, provider_config)
        if provider_type == "gemini":
            return self._build_gemini_request(request, provider_config)
        raise LLMConfigurationError("LLM_PROVIDER_UNSUPPORTED", f"unsupported llm provider {provider_type}")

    def _build_openai_request(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[str, dict[str, Any], dict[str, str], dict[str, Any] | None]:
        api_mode = request.api_mode or provider_config.api_mode
        native_reasoning = _openai_reasoning(request.reasoning_level)
        if api_mode == "responses":
            payload = {
                "model": request.model,
                "input": [
                    {
                        "role": message["role"],
                        "content": [{"type": "input_text", "text": message["content"]}],
                    }
                    for message in request.messages
                ],
                "temperature": request.temperature,
                "max_output_tokens": request.max_output_tokens,
            }
            if native_reasoning:
                payload["reasoning"] = native_reasoning
            if request.response_format == "json_object":
                payload["text"] = {"format": _openai_text_format(request)}
            return "/responses", payload, self._build_headers(provider_config), native_reasoning

        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if native_reasoning:
            payload["reasoning"] = native_reasoning
        if request.response_format == "json_object":
            payload["response_format"] = _openai_chat_response_format(request)
        return "/chat/completions", payload, self._build_headers(provider_config), native_reasoning

    def _build_openai_chat_compatible_request(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[str, dict[str, Any], dict[str, str], dict[str, Any] | None]:
        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        native_reasoning = None
        if provider_config.provider_type == "deepseek" and request.reasoning_level in {"medium", "high"}:
            native_reasoning = {"type": "enabled"}
            payload["thinking"] = native_reasoning
        if provider_config.provider_type == "zhipu_glm":
            native_reasoning = {"type": "enabled" if request.reasoning_level in {"medium", "high"} else "disabled"}
            payload["thinking"] = native_reasoning

        return "/chat/completions", payload, self._build_headers(provider_config), native_reasoning

    def _build_anthropic_request(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[str, dict[str, Any], dict[str, str], dict[str, Any] | None]:
        system_prompts = [message["content"] for message in request.messages if message.get("role") == "system"]
        messages = [
            {"role": "assistant" if message.get("role") == "assistant" else "user", "content": message["content"]}
            for message in request.messages
            if message.get("role") != "system"
        ]
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages or [{"role": "user", "content": ""}],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        if system_prompts:
            payload["system"] = "\n\n".join(system_prompts)
        native_reasoning = _anthropic_reasoning(request.reasoning_level, request.max_output_tokens)
        if native_reasoning:
            payload["thinking"] = native_reasoning
        return "/messages", payload, self._build_headers(provider_config), native_reasoning

    def _build_gemini_request(
        self,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> tuple[str, dict[str, Any], dict[str, str], dict[str, Any] | None]:
        system_parts = [
            {"text": message["content"]}
            for message in request.messages
            if message.get("role") == "system"
        ]
        contents = [
            {
                "role": "model" if message.get("role") == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            }
            for message in request.messages
            if message.get("role") != "system"
        ]
        generation_config: dict[str, Any] = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_output_tokens,
        }
        if request.response_format == "json_object":
            generation_config["responseMimeType"] = "application/json"
        native_reasoning = _gemini_reasoning(request.reasoning_level)
        if native_reasoning:
            generation_config["thinkingConfig"] = native_reasoning

        payload: dict[str, Any] = {
            "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
            "generationConfig": generation_config,
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        endpoint = f"/models/{quote(request.model, safe='')}:generateContent"
        credential_mode = request.credential_mode or provider_config.credential_mode
        if credential_mode != "oauth2" and provider_config.api_key:
            endpoint = f"{endpoint}?key={quote(provider_config.api_key, safe='')}"
        return endpoint, payload, self._build_headers(provider_config, request=request), native_reasoning

    def _build_headers(
        self,
        provider_config: ProviderRuntimeConfig,
        *,
        request: LLMRequest | None = None,
    ) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        credential_mode = (request.credential_mode if request else None) or provider_config.credential_mode
        if provider_config.provider_type == "anthropic":
            headers["anthropic-version"] = str(provider_config.provider_options.get("anthropic_version", "2023-06-01"))
            if provider_config.api_key:
                headers["x-api-key"] = provider_config.api_key
            return headers
        if credential_mode == "oauth2" and provider_config.access_token:
            headers["Authorization"] = f"Bearer {provider_config.access_token}"
        elif credential_mode == "api_key" and provider_config.api_key and provider_config.provider_type != "gemini":
            headers["Authorization"] = f"Bearer {provider_config.api_key}"
        return headers

    def _parse_response(
        self,
        body: dict[str, Any],
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
        *,
        native_reasoning: dict[str, Any] | None,
    ) -> LLMResponse:
        text = self._extract_output_text(body, request=request, provider_type=provider_config.provider_type)
        structured_output: dict[str, Any] | None = None
        if request.response_format == "json_object":
            try:
                structured_output = json.loads(text)
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
            usage=_normalize_usage(body.get("usage") or body.get("usageMetadata")),
            finish_reason=_extract_finish_reason(body, request.api_mode, provider_type=provider_config.provider_type),
            native_reasoning=native_reasoning,
        )

    def _extract_output_text(
        self,
        body: dict[str, Any],
        *,
        request: LLMRequest,
        provider_type: str,
    ) -> str:
        if provider_type in {"anthropic"}:
            content_parts = []
            for content in body.get("content", []):
                if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
                    content_parts.append(content["text"])
            if content_parts:
                return "".join(content_parts)
        elif provider_type == "gemini":
            candidates = body.get("candidates", [])
            if candidates and isinstance(candidates[0], dict):
                content = candidates[0].get("content", {})
                parts = content.get("parts", []) if isinstance(content, dict) else []
                content_parts = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
                if content_parts:
                    return "".join(content_parts)
        else:
            api_mode = "chat" if provider_type in {"deepseek", "zhipu_glm"} else request.api_mode
            return _extract_openai_output_text(body, api_mode=api_mode)

        raise LLMResponseError(
            "LLM_RESPONSE_MISSING_TEXT",
            "llm provider response did not include text output",
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
            node_routing.setdefault("style_draft", task_config)
            node_routing.setdefault("style_patch", task_config)
        else:
            node_routing.setdefault(task_name, task_config)

    for node_name, node_config in node_routing.items():
        task_routing.setdefault(node_name, node_config)
    if "style_draft" in node_routing:
        node_routing.setdefault("style_patch", node_routing["style_draft"])
        task_routing.setdefault("stylize", node_routing["style_draft"])

    return ModelRoutingConfig(
        node_routing=node_routing,
        task_routing=task_routing,
        retry_budget=dict(retry_budget),
        job_runtime=dict(job_runtime),
    )


def build_oauth_state(
    *,
    provider_type: str,
    provider_id: str,
    account_id: str,
    redirect_path: str,
    secret: str,
) -> str:
    payload = {
        "provider_type": provider_type,
        "provider_id": provider_id,
        "account_id": account_id,
        "redirect_path": redirect_path,
        "iat": int(time.time()),
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return ".".join((_b64(payload_bytes), _b64(signature)))


def validate_oauth_state(state: str, *, secret: str) -> dict[str, Any]:
    try:
        payload_part, signature_part = state.split(".", 1)
        payload_bytes = _b64decode(payload_part)
        expected = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
        actual = _b64decode(signature_part)
    except Exception as exc:
        raise LLMConfigurationError("LLM_OAUTH_STATE_INVALID", "invalid oauth state") from exc
    if not hmac.compare_digest(expected, actual):
        raise LLMConfigurationError("LLM_OAUTH_STATE_INVALID", "invalid oauth state")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except ValueError as exc:
        raise LLMConfigurationError("LLM_OAUTH_STATE_INVALID", "invalid oauth state") from exc
    if not isinstance(payload, dict):
        raise LLMConfigurationError("LLM_OAUTH_STATE_INVALID", "invalid oauth state")
    return payload


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


def _parse_float_config_value(task_name: str, payload: dict[str, Any], field: str) -> float:
    value = payload[field]
    try:
        return float(value)
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


def _parse_credential_mode(task_name: str, payload: dict[str, Any]) -> Literal["api_key", "oauth2", "none"] | None:
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


def _openai_reasoning(reasoning_level: str) -> dict[str, Any] | None:
    if reasoning_level in {"low", "medium", "high"}:
        return {"effort": reasoning_level}
    return None


def _anthropic_reasoning(reasoning_level: str, max_output_tokens: int) -> dict[str, Any] | None:
    if reasoning_level not in CLAUDE_THINKING_BUDGETS:
        return None
    budget = min(CLAUDE_THINKING_BUDGETS[reasoning_level], max(1024, max_output_tokens - 1))
    return {"type": "enabled", "budget_tokens": budget}


def _gemini_reasoning(reasoning_level: str) -> dict[str, Any] | None:
    if reasoning_level == "off":
        return {"thinkingBudget": 0}
    if reasoning_level in GEMINI_THINKING_BUDGETS:
        return {"thinkingBudget": GEMINI_THINKING_BUDGETS[reasoning_level]}
    return None


def _openai_text_format(request: LLMRequest) -> dict[str, Any]:
    if request.response_schema:
        schema = dict(request.response_schema)
        name = str(schema.get("name") or "structured_output")
        json_schema = schema.get("schema") if isinstance(schema.get("schema"), dict) else schema
        return {"type": "json_schema", "name": name, "schema": json_schema}
    return {"type": "json_object"}


def _openai_chat_response_format(request: LLMRequest) -> dict[str, Any]:
    if request.response_schema:
        schema = dict(request.response_schema)
        name = str(schema.get("name") or "structured_output")
        json_schema = schema.get("schema") if isinstance(schema.get("schema"), dict) else schema
        return {"type": "json_schema", "json_schema": {"name": name, "schema": json_schema}}
    return {"type": "json_object"}


def _extract_openai_output_text(body: dict[str, Any], *, api_mode: Literal["responses", "chat"]) -> str:
    if api_mode == "responses":
        output_text = body.get("output_text")
        if isinstance(output_text, str) and output_text:
            return output_text

        content_parts: list[str] = []
        for item in body.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if not isinstance(content, dict):
                    continue
                text = content.get("text") or content.get("output_text")
                if isinstance(text, str):
                    content_parts.append(text)
        if content_parts:
            return "".join(content_parts)
    else:
        choices = body.get("choices", [])
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            content = message.get("content")
            if isinstance(content, str) and content:
                return content
            if isinstance(content, list):
                content_parts = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str):
                        content_parts.append(text)
                if content_parts:
                    return "".join(content_parts)

    raise LLMResponseError(
        "LLM_RESPONSE_MISSING_TEXT",
        "llm provider response did not include text output",
    )


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


def _extract_finish_reason(
    body: dict[str, Any],
    api_mode: Literal["responses", "chat"],
    *,
    provider_type: str,
) -> str | None:
    if provider_type == "anthropic":
        stop_reason = body.get("stop_reason")
        return stop_reason if isinstance(stop_reason, str) else None
    if provider_type == "gemini":
        candidates = body.get("candidates", [])
        if candidates and isinstance(candidates[0], dict) and isinstance(candidates[0].get("finishReason"), str):
            return candidates[0]["finishReason"]
        return None
    if provider_type in {"deepseek", "zhipu_glm"}:
        api_mode = "chat"
    if api_mode == "chat":
        choices = body.get("choices", [])
        if choices and isinstance(choices[0], dict):
            finish_reason = choices[0].get("finish_reason")
            if isinstance(finish_reason, str):
                return finish_reason
        return None

    finish_reason = body.get("finish_reason")
    if isinstance(finish_reason, str):
        return finish_reason
    return None


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


def _error_message_for_status(response: httpx.Response) -> str:
    details = _extract_error_details(response)
    detail_message = details.get("message")
    if isinstance(detail_message, str) and detail_message:
        return detail_message
    return f"llm request failed with status {response.status_code}"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))
