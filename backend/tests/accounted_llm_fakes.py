"""Test-only adapter for legacy fake clients used by accounted LLM paths."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from novel_system.services.llm_client import (
    LLMAttemptHook,
    LLMRequest,
    LLMResponse,
    OnlineAccountedExecution,
)


def accounted_generate_method(fake_generate):
    """把旧 ``generate(self, request)`` monkeypatch 包成显式记账能力。"""

    def generate_accounted(self, request: LLMRequest, *, accounting_hook: LLMAttemptHook) -> LLMResponse:
        handle = accounting_hook.before_dispatch(
            request=request,
            dispatch_kind="initial",
        )
        try:
            response = _coerce_response(fake_generate(self, request), request)
        except BaseException as exc:
            accounting_hook.after_error(
                handle,
                request=request,
                error=exc,
                raw_response=None,
                provider_request_id=None,
                latency_ms=1,
            )
            raise
        accounting_hook.after_response(
            handle,
            request=request,
            response=response,
            latency_ms=1,
        )
        return response

    return generate_accounted


class AccountedGenerateMixin(OnlineAccountedExecution):
    """Forward a fake ``generate`` implementation through the attempt hook."""

    def generate_accounted(
        self,
        request: LLMRequest,
        *,
        accounting_hook: LLMAttemptHook,
    ) -> LLMResponse:
        return accounted_generate_method(type(self).generate)(  # type: ignore[attr-defined]
            self,
            request,
            accounting_hook=accounting_hook,
        )


def _coerce_response(raw: Any, request: LLMRequest) -> LLMResponse:
    if isinstance(raw, LLMResponse):
        if raw.usage and raw.raw_usage is None and raw.usage_present is None:
            has_input = "input_tokens" in raw.usage or "prompt_tokens" in raw.usage
            has_output = "output_tokens" in raw.usage or "completion_tokens" in raw.usage
            return replace(
                raw,
                raw_usage=dict(raw.usage),
                usage_present=True,
                usage_complete=has_input and has_output and "total_tokens" in raw.usage,
            )
        return raw
    return LLMResponse(
        request_id=getattr(raw, "request_id", None),
        provider=str(getattr(raw, "provider", None) or request.provider or "fake"),
        model=str(getattr(raw, "model", None) or request.model),
        text=str(getattr(raw, "text", "")),
        structured_output=getattr(raw, "structured_output", None),
        response_format=str(
            getattr(raw, "response_format", None) or request.response_format
        ),
        raw_response=dict(getattr(raw, "raw_response", None) or {}),
        usage=dict(getattr(raw, "usage", None) or {}),
        finish_reason=getattr(raw, "finish_reason", None),
        raw_usage=getattr(raw, "raw_usage", None),
        usage_present=getattr(raw, "usage_present", None),
        usage_complete=getattr(raw, "usage_complete", None),
    )
