from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml


RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
SUPPORTED_PROVIDERS = {"openai_compatible"}
SUPPORTED_RESPONSE_FORMATS = {"json_object", "text"}
SUPPORTED_API_MODES = {"responses", "chat"}


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


@dataclass(slots=True, frozen=True)
class TaskModelConfig:
    provider: str
    model: str
    temperature: float
    max_output_tokens: int
    response_format: str


@dataclass(slots=True, frozen=True)
class ModelRoutingConfig:
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
    ) -> None:
        self._provider = provider
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._transport = transport

    def generate(self, request: LLMRequest) -> LLMResponse:
        provider = request.provider or self._provider
        self._validate_provider(provider)
        self._validate_request(request)
        payload = self._build_payload(request)
        headers = self._build_headers()
        timeout_seconds = request.timeout_seconds or self._timeout_seconds
        endpoint = "/responses" if request.api_mode == "responses" else "/chat/completions"

        with httpx.Client(
            base_url=self._base_url,
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

                return self._parse_response(body, request, provider)

        raise LLMHTTPError(
            "LLM_HTTP_FAILURE",
            "llm request failed without a response",
            retryable=True,
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _build_payload(self, request: LLMRequest) -> dict[str, Any]:
        if request.api_mode == "responses":
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
            if request.response_format == "json_object":
                payload["text"] = {"format": {"type": "json_object"}}
            return payload

        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _parse_response(
        self,
        body: dict[str, Any],
        request: LLMRequest,
        provider: str,
    ) -> LLMResponse:
        text = self._extract_output_text(body, api_mode=request.api_mode)
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
            provider=provider,
            model=str(body.get("model", request.model)),
            text=text,
            structured_output=structured_output,
            response_format=request.response_format,
            raw_response=body,
            usage=_normalize_usage(body.get("usage")),
            finish_reason=_extract_finish_reason(body, request.api_mode),
        )

    def _extract_output_text(self, body: dict[str, Any], *, api_mode: Literal["responses", "chat"]) -> str:
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


def load_model_routing_config(path: str | Path | None = None) -> ModelRoutingConfig:
    config_path = Path(path) if path is not None else _default_models_config_path()
    raw_payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if raw_payload is None:
        raw_payload = {}
    if not isinstance(raw_payload, dict):
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            "models config must decode to a mapping",
        )

    task_routing = _require_mapping(raw_payload, "task_routing")
    retry_budget = _require_mapping(raw_payload, "retry_budget")
    job_runtime = _require_mapping(raw_payload, "job_runtime")
    return ModelRoutingConfig(
        task_routing={
            task_name: _load_task_model_config(task_name, task_payload)
            for task_name, task_payload in task_routing.items()
        },
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
            model=str(payload["model"]),
            temperature=_parse_float_config_value(task_name, payload, "temperature"),
            max_output_tokens=_parse_int_config_value(task_name, payload, "max_output_tokens"),
            response_format=_parse_response_format(task_name, payload),
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
    value = str(payload["provider"])
    if value not in SUPPORTED_PROVIDERS:
        raise LLMConfigurationError(
            "LLM_MODEL_CONFIG_INVALID",
            f"task_routing.{task_name} has unsupported provider {value}",
        )
    return value


def _normalize_usage(usage: Any) -> dict[str, int]:
    if not isinstance(usage, dict):
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    if "input_tokens" in usage or "output_tokens" in usage:
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }

    return {
        "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "output_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }


def _extract_finish_reason(body: dict[str, Any], api_mode: Literal["responses", "chat"]) -> str | None:
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
