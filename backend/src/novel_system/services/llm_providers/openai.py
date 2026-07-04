"""OpenAI native + generic OpenAI-compatible adapters (Responses / Chat dual mode)."""

from __future__ import annotations

from typing import Any, ClassVar

from novel_system.services.llm_providers.base import (
    AdapterHTTPRequest,
    CompletionProbeRequest,
    LLMRequest,
    ProviderAdapter,
    ProviderRuntimeConfig,
)
from novel_system.services.llm_providers.openai_common import (
    bearer_generate_headers,
    extract_chat_finish_reason,
    extract_openai_output_text,
    openai_chat_response_format,
    openai_reasoning,
    openai_text_format,
)


class OpenAIFamilyAdapter(ProviderAdapter):
    """Dual-mode adapter speaking either the Responses API or Chat Completions."""

    default_api_mode: ClassVar[str] = "responses"
    appends_v1_to_bare_host: ClassVar[bool] = True

    def build_request(self, request: LLMRequest, provider_config: ProviderRuntimeConfig) -> AdapterHTTPRequest:
        # request.api_mode 已在 LLMClient.generate 入口按 provider 声明归一化
        # (端点能力,chat-only 中转收到 /responses 必 404);build 与响应解析
        # (extract_output_text)共用 request.api_mode,不得在此另行改写。
        api_mode = request.api_mode or provider_config.api_mode
        native_reasoning = openai_reasoning(request.reasoning_level)
        if api_mode == "responses":
            payload: dict[str, Any] = {
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
            # §7 anti-mean sampling — inject decoding-level penalties when set
            if request.frequency_penalty is not None:
                payload["frequency_penalty"] = request.frequency_penalty
            if request.presence_penalty is not None:
                payload["presence_penalty"] = request.presence_penalty
            if request.top_p is not None:
                payload["top_p"] = request.top_p
            if native_reasoning:
                payload["reasoning"] = native_reasoning
            if request.response_format == "json_object" and request.wire_response_format:
                payload["text"] = {"format": openai_text_format(request)}
            extra_payload = (request.provider_options or {}).get("extra_payload")
            if isinstance(extra_payload, dict):
                payload.update(extra_payload)
            return AdapterHTTPRequest(
                endpoint="/responses",
                payload=payload,
                headers=bearer_generate_headers(provider_config),
                native_reasoning=native_reasoning,
            )

        payload = {
            "model": request.model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
        }
        # §7 anti-mean sampling — inject decoding-level penalties when set
        if request.frequency_penalty is not None:
            payload["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty is not None:
            payload["presence_penalty"] = request.presence_penalty
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if native_reasoning:
            payload["reasoning"] = native_reasoning
        if request.response_format == "json_object" and request.wire_response_format:
            payload["response_format"] = openai_chat_response_format(request)
        # 连通性降级/用户配置的额外 wire 参数直通(如 qwen/vllm 系
        # chat_template_kwargs.enable_thinking 思考开关)
        extra_payload = (request.provider_options or {}).get("extra_payload")
        if isinstance(extra_payload, dict):
            payload.update(extra_payload)
        return AdapterHTTPRequest(
            endpoint="/chat/completions",
            payload=payload,
            headers=bearer_generate_headers(provider_config),
            native_reasoning=native_reasoning,
        )

    def extract_output_text(self, body: dict[str, Any], *, request: LLMRequest) -> str:
        return extract_openai_output_text(body, api_mode=request.api_mode)

    def extract_finish_reason(self, body: dict[str, Any], *, api_mode: str) -> str | None:
        if api_mode == "chat":
            return extract_chat_finish_reason(body)
        finish_reason = body.get("finish_reason")
        if isinstance(finish_reason, str):
            return finish_reason
        return None

    def protocol_hint(
        self,
        *,
        status_code: int,
        endpoint: str,
        request: LLMRequest,
        provider_config: ProviderRuntimeConfig,
    ) -> dict[str, str] | None:
        if status_code == 404 and endpoint == "/responses" and request.api_mode == "responses":
            return {
                "message": (
                    "Responses API endpoint returned 404. This provider or relay may only support Chat Completions; "
                    "set api_mode to chat and sync node routes, or use a provider that supports the Responses API."
                ),
                "next_action": "switch_provider_api_mode_to_chat_or_use_responses_compatible_provider",
            }
        return None

    def completion_probe_request(
        self,
        *,
        base_url: str,
        model: str,
        api_mode: str,
        api_key: str | None,
        provider_options: dict[str, Any] | None = None,
    ) -> CompletionProbeRequest | None:
        headers = self.auth_headers(api_key=api_key, provider_options=provider_options)
        if api_mode == "responses":
            return CompletionProbeRequest(
                url=f"{base_url}/responses",
                payload={
                    "model": model,
                    "input": [
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": "ping"}],
                        }
                    ],
                    "temperature": 0,
                    "max_output_tokens": 8,
                },
                headers=headers,
                api_mode="responses",
                endpoint="/responses",
            )
        return CompletionProbeRequest(
            url=f"{base_url}/chat/completions",
            payload={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": 0,
                "max_tokens": 8,
                "stream": False,
            },
            headers=headers,
            api_mode="chat",
            endpoint="/chat/completions",
        )


class OpenAIAdapter(OpenAIFamilyAdapter):
    provider_type: ClassVar[str] = "openai"
    label_zh: ClassVar[str] = "OpenAI"
    default_base_url: ClassVar[str] = "https://api.openai.com/v1"
    docs_url: ClassVar[str | None] = "https://platform.openai.com/docs/api-reference"


class OpenAICompatibleAdapter(OpenAIFamilyAdapter):
    provider_type: ClassVar[str] = "openai_compatible"
    label_zh: ClassVar[str] = "本地 / OpenAI 兼容"
    default_base_url: ClassVar[str] = "http://127.0.0.1:11434/v1"
    credential_modes: ClassVar[tuple[str, ...]] = ("none", "api_key")
    category: ClassVar[str] = "local"
