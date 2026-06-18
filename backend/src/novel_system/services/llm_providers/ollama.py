"""Ollama 本地原生 API(/api/chat + /api/tags)。

文档锚点(2026-06 核验,docs.ollama.com + ollama/ollama api.md):
- base: http://127.0.0.1:11434(原生 API 无 /v1 前缀)
- POST /api/chat: {model, messages, stream, format, options{temperature,
  num_predict}, think};format 取 "json" 或内联 JSON schema 对象
- 响应: message.content / done_reason / prompt_eval_count / eval_count
- GET /api/tags 列出本地模型({"models": [{"name": ...}]})
- think: 布尔(思考模型);think=false 与 format 同用有已知兼容问题
  (ollama#15260),故仅在 medium/high 时发送 think=true,从不发送 false。

若想走 Ollama 的 OpenAI 兼容层(/v1),用 openai_compatible 类型即可;
本适配器走原生协议,模型列表与 usage 统计更准。
"""

from __future__ import annotations

from typing import Any, ClassVar

from novel_system.services.llm_providers.base import (
    AdapterHTTPRequest,
    CompletionProbeRequest,
    LLMRequest,
    LLMResponseError,
    ModelListRequest,
    ProviderAdapter,
    ProviderRuntimeConfig,
)


class OllamaAdapter(ProviderAdapter):
    provider_type: ClassVar[str] = "ollama"
    label_zh: ClassVar[str] = "Ollama 本地（原生）"
    default_base_url: ClassVar[str] = "http://127.0.0.1:11434"
    credential_modes: ClassVar[tuple[str, ...]] = ("none", "api_key")
    category: ClassVar[str] = "local"
    docs_url: ClassVar[str | None] = "https://docs.ollama.com"

    def build_request(self, request: LLMRequest, provider_config: ProviderRuntimeConfig) -> AdapterHTTPRequest:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_output_tokens,
            },
        }
        if request.response_format == "json_object":
            if request.response_schema:
                schema = dict(request.response_schema)
                payload["format"] = schema.get("schema") if isinstance(schema.get("schema"), dict) else schema
            else:
                payload["format"] = "json"

        native_reasoning = None
        if request.reasoning_level in {"medium", "high"}:
            native_reasoning = {"think": True}
            payload["think"] = True

        headers = {"Content-Type": "application/json"}
        if provider_config.credential_mode == "api_key" and provider_config.api_key:
            headers["Authorization"] = f"Bearer {provider_config.api_key}"

        return AdapterHTTPRequest(
            endpoint="/api/chat",
            payload=payload,
            headers=headers,
            native_reasoning=native_reasoning,
        )

    def extract_output_text(self, body: dict[str, Any], *, request: LLMRequest) -> str:
        message = body.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content:
                return content
        raise LLMResponseError(
            "LLM_RESPONSE_MISSING_TEXT",
            "llm provider response did not include text output",
        )

    def extract_finish_reason(self, body: dict[str, Any], *, api_mode: str) -> str | None:
        done_reason = body.get("done_reason")
        return done_reason if isinstance(done_reason, str) else None

    def normalize_usage(self, body: dict[str, Any]) -> dict[str, int] | None:
        if "prompt_eval_count" not in body and "eval_count" not in body:
            return None
        input_tokens = int(body.get("prompt_eval_count", 0) or 0)
        output_tokens = int(body.get("eval_count", 0) or 0)
        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }

    def list_models_request(
        self,
        *,
        base_url: str,
        api_key: str | None,
        provider_options: dict[str, Any] | None = None,
    ) -> ModelListRequest | None:
        return ModelListRequest(
            url=f"{base_url}/api/tags",
            headers=self.auth_headers(api_key=api_key, provider_options=provider_options),
        )

    def completion_probe_request(
        self,
        *,
        base_url: str,
        model: str,
        api_mode: str,
        api_key: str | None,
        provider_options: dict[str, Any] | None = None,
    ) -> CompletionProbeRequest | None:
        return CompletionProbeRequest(
            url=f"{base_url}/api/chat",
            payload={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "stream": False,
                "options": {"temperature": 0, "num_predict": 8},
            },
            headers=self.auth_headers(api_key=api_key, provider_options=provider_options),
            api_mode="chat",
            endpoint="/api/chat",
        )
