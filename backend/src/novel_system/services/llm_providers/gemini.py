from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from novel_system.services.llm_providers.base import (
    AdapterHTTPRequest,
    CompletionProbeRequest,
    LLMRequest,
    LLMResponseError,
    ModelListRequest,
    ProviderAdapter,
    ProviderRuntimeConfig,
)


GEMINI_THINKING_BUDGETS = {"low": 1024, "medium": 4096, "high": 8192}


def gemini_reasoning(reasoning_level: str) -> dict[str, Any] | None:
    if reasoning_level == "off":
        return {"thinkingBudget": 0}
    if reasoning_level in GEMINI_THINKING_BUDGETS:
        return {"thinkingBudget": GEMINI_THINKING_BUDGETS[reasoning_level]}
    return None


class GeminiAdapter(ProviderAdapter):
    provider_type: ClassVar[str] = "gemini"
    label_zh: ClassVar[str] = "Gemini / Google"
    default_base_url: ClassVar[str] = "https://generativelanguage.googleapis.com/v1beta"
    docs_url: ClassVar[str | None] = "https://ai.google.dev/gemini-api/docs"

    def build_request(self, request: LLMRequest, provider_config: ProviderRuntimeConfig) -> AdapterHTTPRequest:
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
        native_reasoning = gemini_reasoning(request.reasoning_level)
        if native_reasoning:
            generation_config["thinkingConfig"] = native_reasoning

        payload: dict[str, Any] = {
            "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
            "generationConfig": generation_config,
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        endpoint = f"/models/{quote(request.model, safe='')}:generateContent"
        if provider_config.api_key:
            endpoint = f"{endpoint}?key={quote(provider_config.api_key, safe='')}"

        return AdapterHTTPRequest(
            endpoint=endpoint,
            payload=payload,
            headers={"Content-Type": "application/json"},
            native_reasoning=native_reasoning,
        )

    def extract_output_text(self, body: dict[str, Any], *, request: LLMRequest) -> str:
        candidates = body.get("candidates", [])
        if candidates and isinstance(candidates[0], dict):
            content = candidates[0].get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            content_parts = [
                part.get("text")
                for part in parts
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ]
            if content_parts:
                return "".join(content_parts)
        raise LLMResponseError(
            "LLM_RESPONSE_MISSING_TEXT",
            "llm provider response did not include text output",
        )

    def extract_finish_reason(self, body: dict[str, Any], *, api_mode: str) -> str | None:
        candidates = body.get("candidates", [])
        if candidates and isinstance(candidates[0], dict) and isinstance(candidates[0].get("finishReason"), str):
            return candidates[0]["finishReason"]
        return None

    def auth_headers(self, *, api_key: str | None, provider_options: dict[str, Any] | None = None) -> dict[str, str]:
        # Gemini authenticates via the ?key= query parameter, not headers.
        return {}

    def list_models_request(
        self,
        *,
        base_url: str,
        api_key: str | None,
        provider_options: dict[str, Any] | None = None,
    ) -> ModelListRequest | None:
        url = f"{base_url}/models"
        if api_key:
            url = f"{url}?key={quote(api_key, safe='')}"
        return ModelListRequest(url=url, headers={})

    def normalize_listed_model_ids(self, model_ids: list[str]) -> list[str]:
        normalized = []
        for model_id in model_ids:
            normalized.append(model_id[len("models/"):] if model_id.startswith("models/") else model_id)
        return normalized

    def completion_probe_request(
        self,
        *,
        base_url: str,
        model: str,
        api_mode: str,
        api_key: str | None,
        provider_options: dict[str, Any] | None = None,
    ) -> CompletionProbeRequest | None:
        url = f"{base_url}/models/{quote(model, safe='')}:generateContent"
        if api_key:
            url = f"{url}?key={quote(api_key, safe='')}"
        return CompletionProbeRequest(
            url=url,
            payload={
                "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
                "generationConfig": {"temperature": 0, "maxOutputTokens": 8},
            },
            headers={"Content-Type": "application/json"},
            api_mode="chat",
            endpoint=":generateContent",
        )
