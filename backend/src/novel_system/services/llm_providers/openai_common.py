"""Helpers shared by every OpenAI-protocol adapter (native and compatible)."""

from __future__ import annotations

from typing import Any, Literal

from novel_system.services.llm_providers.base import LLMRequest, LLMResponseError, ProviderRuntimeConfig


def openai_reasoning(reasoning_level: str) -> dict[str, Any] | None:
    if reasoning_level in {"low", "medium", "high"}:
        return {"effort": reasoning_level}
    return None


def openai_text_format(request: LLMRequest) -> dict[str, Any]:
    if request.response_schema:
        schema = dict(request.response_schema)
        name = str(schema.get("name") or "structured_output")
        json_schema = schema.get("schema") if isinstance(schema.get("schema"), dict) else schema
        return {"type": "json_schema", "name": name, "schema": json_schema}
    return {"type": "json_object"}


def openai_chat_response_format(request: LLMRequest) -> dict[str, Any]:
    if request.response_schema:
        schema = dict(request.response_schema)
        name = str(schema.get("name") or "structured_output")
        json_schema = schema.get("schema") if isinstance(schema.get("schema"), dict) else schema
        return {"type": "json_schema", "json_schema": {"name": name, "schema": json_schema}}
    return {"type": "json_object"}


def extract_openai_output_text(body: dict[str, Any], *, api_mode: Literal["responses", "chat"]) -> str:
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


def extract_chat_finish_reason(body: dict[str, Any]) -> str | None:
    choices = body.get("choices", [])
    if choices and isinstance(choices[0], dict):
        finish_reason = choices[0].get("finish_reason")
        if isinstance(finish_reason, str):
            return finish_reason
    return None


def bearer_generate_headers(provider_config: ProviderRuntimeConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if provider_config.credential_mode == "api_key" and provider_config.api_key:
        headers["Authorization"] = f"Bearer {provider_config.api_key}"
    return headers
