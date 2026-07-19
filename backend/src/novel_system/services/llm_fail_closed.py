from __future__ import annotations

from typing import NoReturn

from novel_system.services.errors import DomainError
from novel_system.services.llm_accounting import LLMAccountingRejected
from novel_system.services.llm_client import LLMConfigurationError
from novel_system.services.llm_task_runner import LLMNodeExecutionError


# These failures mean that the requested LLM capability is unavailable in the
# current runtime.  They are actionable configuration/conflict responses, not
# upstream model failures.  Everything else (transport, provider, timeout and
# response parsing failures) is a bad-gateway failure.
_CAPABILITY_ERROR_CODES = frozenset(
    {
        "LLM_ROUTE_NOT_CONFIGURED",
        "LLM_PROVIDER_DISABLED",
        "LLM_PROVIDER_UNSUPPORTED",
        "LLM_MODEL_CONFIG_INVALID",
        "LLM_ACCOUNTING_CONTEXT_INVALID",
        "LLM_ACCOUNTING_CONTEXT_REQUIRED",
        "LLM_ACCOUNTING_SESSION_REQUIRED",
    }
)


def is_llm_capability_error(exc: LLMNodeExecutionError) -> bool:
    return exc.error_code in _CAPABILITY_ERROR_CODES or isinstance(
        exc.original_error,
        LLMConfigurationError,
    )


def raise_llm_domain_error(
    exc: LLMNodeExecutionError,
    *,
    capability_code: str,
    failure_code: str,
    operation: str,
    node_id: str,
    next_action: str,
) -> NoReturn:
    capability_error = is_llm_capability_error(exc)
    if isinstance(exc.original_error, LLMAccountingRejected) and not capability_error:
        raise DomainError(
            exc.error_code,
            exc.message,
            status_code=409,
            details={
                "llm_call_id": exc.llm_call_id,
                "node_id": node_id,
                "error_code": exc.error_code,
                "retryable": exc.retryable,
                "next_action": "restore_llm_accounting_capacity_and_retry",
                "response_summary": exc.response_summary,
            },
        ) from exc
    raise DomainError(
        capability_code if capability_error else failure_code,
        (
            f"{operation} requires a configured live LLM capability: {exc.message}"
            if capability_error
            else f"{operation} failed: {exc.message}"
        ),
        status_code=409 if capability_error else 502,
        details={
            "llm_call_id": exc.llm_call_id,
            "node_id": node_id,
            "error_code": exc.error_code,
            "retryable": exc.retryable,
            "next_action": next_action,
            "response_summary": exc.response_summary,
        },
    ) from exc
