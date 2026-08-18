"""Shared read-only schema contract for LLM accounting audits.

This module deliberately contains constants only.  Runtime services and
operator CLIs may both depend on it without making the service layer depend on
the command-line ``tools`` package.
"""

CALL_TABLE = "llm_calls"
ATTEMPT_TABLE = "llm_call_attempts"
BUDGET_TABLE = "scene_run_states"
TOKEN_COLUMNS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "estimated_tokens",
    "reserved_tokens",
    "budget_charged_tokens",
    "latency_ms",
)
REQUIRED_COLUMNS = {
    "alembic_version": ("version_num",),
    CALL_TABLE: (
        "llm_call_id",
        "scope_type",
        "scope_id",
        "usage_is_estimate",
        "accounting_status",
        "request_dispatched_at",
        "settled_at",
        *TOKEN_COLUMNS,
    ),
    ATTEMPT_TABLE: (
        "attempt_id",
        "llm_call_id",
        "provider_attempt_no",
        "usage_is_estimate",
        "accounting_status",
        "request_dispatched_at",
        "settled_at",
        *TOKEN_COLUMNS,
    ),
    BUDGET_TABLE: (
        "scene_id",
        "attempt_budget",
        "total_attempt_count",
        "scene_token_budget",
        "scene_tokens_used",
        "scene_tokens_reserved",
        "provider_attempts_used",
        "provider_attempt_budget",
    ),
}
AUDIT_TABLES = (CALL_TABLE, ATTEMPT_TABLE, BUDGET_TABLE)
REQUIRED_TABLES = frozenset(REQUIRED_COLUMNS)
