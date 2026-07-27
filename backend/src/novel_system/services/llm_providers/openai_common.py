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
            # 部分中转/本地引擎按 completions 风格把正文放 choices[0].text
            legacy_text = choices[0].get("text")
            if isinstance(legacy_text, str) and legacy_text:
                return legacy_text

    # 诊断细节:finish_reason=length + reasoning_content 非空 = 思考吃满输出预算
    first_choice = None
    body_choices = body.get("choices") or []
    if body_choices and isinstance(body_choices[0], dict):
        first_choice = body_choices[0]
    message = (first_choice or {}).get("message") or {}
    raise LLMResponseError(
        "LLM_RESPONSE_MISSING_TEXT",
        "llm provider response did not include text output",
        details={
            "finish_reason": (first_choice or {}).get("finish_reason"),
            "has_reasoning_content": bool(message.get("reasoning_content")),
            "completion_tokens": (body.get("usage") or {}).get("completion_tokens"),
        },
    )


def extract_chat_finish_reason(body: dict[str, Any]) -> str | None:
    choices = body.get("choices", [])
    if choices and isinstance(choices[0], dict):
        finish_reason = choices[0].get("finish_reason")
        if isinstance(finish_reason, str):
            return finish_reason
    return None


def extract_responses_finish_reason(body: dict[str, Any]) -> str | None:
    """Responses API 用 status=incomplete + incomplete_details.reason 表达截断。

    真实 Responses API 顶层没有 finish_reason:被 max_output_tokens 砍断时它给
    ``status="incomplete"`` 和 ``incomplete_details={"reason":"max_output_tokens"}``。
    把这个 reason 归一成 finish_reason 语义(例如 "max_output_tokens"),上层的截断判定
    才能在 responses 模式下生效——否则 snowflake_step_generate(默认 api_mode=responses)
    的截断永远抓不到。部分中转会直接把 finish_reason 放顶层,兼容保留。
    """
    status = body.get("status")
    if isinstance(status, str) and status.strip().lower() == "incomplete":
        details = body.get("incomplete_details")
        if isinstance(details, dict):
            reason = details.get("reason")
            if isinstance(reason, str) and reason.strip():
                return reason
        return "incomplete"
    finish_reason = body.get("finish_reason")
    if isinstance(finish_reason, str):
        return finish_reason
    return None


def bearer_generate_headers(provider_config: ProviderRuntimeConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if provider_config.credential_mode == "api_key" and provider_config.api_key:
        headers["Authorization"] = f"Bearer {provider_config.api_key}"
    return headers
