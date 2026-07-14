"""Add durable LLM accounting, budget fences, checkpoints, and scene-job lookup.

Historical ``llm_calls`` are logical-call evidence only.  This migration marks their
usage as estimated and conservatively copies recoverable token totals, but deliberately
does not fabricate ``llm_call_attempts`` rows for provider dispatches that cannot be
reconstructed.

Revision ID: 20260713_0065
Revises: 20260712_0064
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


revision = "20260713_0065"
down_revision = "20260712_0064"
branch_labels = None
depends_on = None


MIGRATION_PROVIDER_ATTEMPT_BUDGET = 32
ACCOUNTING_STATUS_SQL = (
    "accounting_status IN "
    "('reserved','settled','failed','released','rejected','usage_exceeds_reservation')"
)
DISPATCH_KIND_SQL = (
    "dispatch_kind IN "
    "('initial','transport_retry','response_parse_retry','api_mode_degrade',"
    "'structured_output_degrade','missing_text_degrade','system_probe')"
)

SCENE_COLUMNS = (
    sa.Column("scene_tokens_reserved", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("scene_budget_basis_json", sa.JSON(), nullable=True),
    sa.Column("provider_attempts_used", sa.Integer(), nullable=False, server_default="0"),
    sa.Column(
        "provider_attempt_budget",
        sa.Integer(),
        nullable=False,
        server_default=str(MIGRATION_PROVIDER_ATTEMPT_BUDGET),
    ),
    sa.Column("active_execution_id", sa.String(), nullable=True),
    sa.Column("run_execution_status", sa.String(), nullable=True),
    sa.Column("run_checkpoint", sa.String(), nullable=True),
    sa.Column("run_checkpoint_json", sa.JSON(), nullable=True),
    sa.Column("active_run_job_id", sa.String(), nullable=True),
)
LLM_COLUMNS = (
    sa.Column("scope_type", sa.String(), nullable=True),
    sa.Column("scope_id", sa.String(), nullable=True),
    sa.Column("run_job_id", sa.String(), nullable=True),
    sa.Column("execution_id", sa.String(), nullable=True),
    sa.Column("execution_step_key", sa.String(), nullable=True),
    sa.Column("estimated_tokens", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("budget_charged_tokens", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("usage_is_estimate", sa.Boolean(), nullable=False, server_default="1"),
    sa.Column("accounting_status", sa.String(), nullable=False, server_default="settled"),
    sa.Column("request_dispatched_at", sa.String(), nullable=True),
    sa.Column("settled_at", sa.String(), nullable=True),
)

SCENE_CHECKS = {
    "ck_scene_run_states_tokens_reserved_nonnegative": "scene_tokens_reserved >= 0",
    "ck_scene_run_states_provider_attempts_used_nonnegative": "provider_attempts_used >= 0",
    "ck_scene_run_states_provider_attempt_budget_nonnegative": "provider_attempt_budget >= 0",
}
LLM_CHECKS = {
    "ck_llm_calls_estimated_tokens_nonnegative": "estimated_tokens >= 0",
    "ck_llm_calls_reserved_tokens_nonnegative": "reserved_tokens >= 0",
    "ck_llm_calls_budget_charged_tokens_nonnegative": "budget_charged_tokens >= 0",
    "ck_llm_calls_budget_charged_within_reservation": (
        "budget_charged_tokens <= reserved_tokens"
    ),
    "ck_llm_calls_accounting_status": ACCOUNTING_STATUS_SQL,
}

LLM_INDEXES = {
    "ix_llm_calls_scope_created": ("scope_type", "scope_id", "created_at"),
    "ix_llm_calls_run_job": ("run_job_id",),
    "ix_llm_calls_execution_step": ("execution_id", "execution_step_key"),
    "ix_llm_calls_accounting_status": ("accounting_status",),
}
EXECUTION_STEP_CLAIM_INDEX = "uq_llm_calls_execution_step_claim"
EXECUTION_STEP_CLAIM_PREDICATE = (
    "execution_id IS NOT NULL AND execution_step_key IS NOT NULL "
    "AND NOT (request_dispatched_at IS NULL "
    "AND accounting_status IN ('released','rejected'))"
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _columns(table_name: str) -> dict[str, dict]:
    inspector = _inspector()
    if not inspector.has_table(table_name):
        return {}
    return {str(column["name"]): column for column in inspector.get_columns(table_name)}


def _add_missing_columns(table_name: str, columns: Iterable[sa.Column]) -> None:
    existing = set(_columns(table_name))
    if not existing:
        return
    for column in columns:
        if column.name not in existing:
            op.add_column(table_name, column)


def _check_names(table_name: str) -> set[str]:
    inspector = _inspector()
    if not inspector.has_table(table_name):
        return set()
    return {
        str(constraint["name"])
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }


def _index_names(table_name: str) -> set[str]:
    inspector = _inspector()
    if not inspector.has_table(table_name):
        return set()
    return {
        str(index["name"])
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }


def _ensure_checks(table_name: str, checks: dict[str, str], *, llm_call: bool = False) -> None:
    existing_checks = _check_names(table_name)
    missing = {name: sql for name, sql in checks.items() if name not in existing_checks}
    columns = _columns(table_name)
    needs_llm_not_null = llm_call and any(
        columns.get(name, {}).get("nullable", True)
        for name in ("scope_type", "scope_id", "accounting_status")
    )
    if not missing and not needs_llm_not_null:
        return
    with op.batch_alter_table(table_name, recreate="always") as batch:
        if llm_call:
            batch.alter_column("scope_type", existing_type=sa.String(), nullable=False)
            batch.alter_column("scope_id", existing_type=sa.String(), nullable=False)
            batch.alter_column(
                "accounting_status",
                existing_type=sa.String(),
                nullable=False,
                server_default="reserved",
            )
        for name, sql in missing.items():
            batch.create_check_constraint(name, sql)


def _ensure_indexes(table_name: str, indexes: dict[str, tuple[str, ...]]) -> None:
    existing = _index_names(table_name)
    for name, columns in indexes.items():
        if name not in existing:
            op.create_index(name, table_name, list(columns), unique=False)


def _ensure_execution_step_claim_index() -> None:
    if EXECUTION_STEP_CLAIM_INDEX in _index_names("llm_calls"):
        return
    predicate = sa.text(EXECUTION_STEP_CLAIM_PREDICATE)
    op.create_index(
        EXECUTION_STEP_CLAIM_INDEX,
        "llm_calls",
        ["execution_id", "execution_step_key"],
        unique=True,
        sqlite_where=predicate,
        postgresql_where=predicate,
    )


def _backfill_llm_calls() -> None:
    columns = set(_columns("llm_calls"))
    if not columns:
        return
    scope_cases: list[tuple[str, str, str]] = []
    for scope_type, column in (
        ("scene", "scene_id"),
        ("project", "project_id"),
        ("chapter", "chapter_id"),
    ):
        if column in columns:
            scope_cases.append(
                (
                    f"WHEN NULLIF(TRIM({column}), '') IS NOT NULL THEN '{scope_type}'",
                    f"WHEN NULLIF(TRIM({column}), '') IS NOT NULL THEN {column}",
                    column,
                )
            )
    type_sql = "CASE " + " ".join(item[0] for item in scope_cases) + " ELSE 'system' END"
    fallback = "NULLIF(TRIM(node_id), '')" if "node_id" in columns else "NULL"
    id_sql = (
        "CASE "
        + " ".join(item[1] for item in scope_cases)
        + f" ELSE COALESCE({fallback}, 'legacy') END"
    )
    if "total_tokens" in columns:
        total_sql = "CASE WHEN total_tokens >= 0 THEN total_tokens"
    else:
        total_sql = "CASE WHEN 0 = 1 THEN 0"
    prompt_sql = "COALESCE(prompt_tokens, 0)" if "prompt_tokens" in columns else "0"
    completion_sql = "COALESCE(completion_tokens, 0)" if "completion_tokens" in columns else "0"
    total_sql += f" ELSE MAX({prompt_sql} + {completion_sql}, 0) END"
    status_sql = (
        "CASE WHEN error_code IS NOT NULL THEN 'failed' ELSE 'settled' END"
        if "error_code" in columns
        else "'settled'"
    )
    op.get_bind().execute(
        text(
            f"""
            UPDATE llm_calls
            SET scope_type = {type_sql},
                scope_id = {id_sql},
                estimated_tokens = {total_sql},
                reserved_tokens = 0,
                budget_charged_tokens = 0,
                usage_is_estimate = 1,
                accounting_status = {status_sql}
            WHERE scope_type IS NULL
              AND scope_id IS NULL
            """
        )
    )


def _ensure_attempt_table() -> None:
    if _inspector().has_table("llm_call_attempts"):
        _ensure_indexes(
            "llm_call_attempts",
            {"ix_llm_call_attempts_call_status": ("llm_call_id", "accounting_status")},
        )
        return
    op.create_table(
        "llm_call_attempts",
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("llm_call_id", sa.String(), nullable=False),
        sa.Column("provider_attempt_no", sa.Integer(), nullable=False),
        sa.Column("dispatch_kind", sa.String(), nullable=False),
        sa.Column("request_max_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_request_id", sa.String(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("budget_charged_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_is_estimate", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("accounting_status", sa.String(), nullable=False),
        sa.Column("request_dispatched_at", sa.String(), nullable=True),
        sa.Column("settled_at", sa.String(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "provider_attempt_no >= 0",
            name="ck_llm_call_attempts_provider_attempt_no_nonnegative",
        ),
        sa.CheckConstraint(
            "request_max_output_tokens >= 0",
            name="ck_llm_call_attempts_request_max_output_tokens_nonnegative",
        ),
        sa.CheckConstraint("prompt_tokens >= 0", name="ck_llm_call_attempts_prompt_tokens_nonnegative"),
        sa.CheckConstraint(
            "completion_tokens >= 0",
            name="ck_llm_call_attempts_completion_tokens_nonnegative",
        ),
        sa.CheckConstraint("total_tokens >= 0", name="ck_llm_call_attempts_total_tokens_nonnegative"),
        sa.CheckConstraint(
            "estimated_tokens >= 0",
            name="ck_llm_call_attempts_estimated_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "reserved_tokens >= 0",
            name="ck_llm_call_attempts_reserved_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "budget_charged_tokens >= 0",
            name="ck_llm_call_attempts_budget_charged_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "budget_charged_tokens <= reserved_tokens",
            name="ck_llm_call_attempts_budget_charged_within_reservation",
        ),
        sa.CheckConstraint("latency_ms >= 0", name="ck_llm_call_attempts_latency_ms_nonnegative"),
        sa.CheckConstraint(ACCOUNTING_STATUS_SQL, name="ck_llm_call_attempts_accounting_status"),
        sa.CheckConstraint(DISPATCH_KIND_SQL, name="ck_llm_call_attempts_dispatch_kind"),
        sa.ForeignKeyConstraint(["llm_call_id"], ["llm_calls.llm_call_id"]),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint(
            "llm_call_id",
            "provider_attempt_no",
            name="uq_llm_call_attempts_call_ordinal",
        ),
    )
    op.create_index(
        "ix_llm_call_attempts_call_status",
        "llm_call_attempts",
        ["llm_call_id", "accounting_status"],
        unique=False,
    )


def _backfill_chapter_run_jobs() -> None:
    columns = set(_columns("chapter_run_jobs"))
    if "scene_id" not in columns:
        return
    payload_expr = (
        "CASE WHEN json_valid(payload_json) THEN "
        "NULLIF(json_extract(payload_json, '$.scene_id'), '') END"
        if "payload_json" in columns
        else "NULL"
    )
    result_expr = (
        "CASE WHEN json_valid(result_summary_json) THEN "
        "NULLIF(json_extract(result_summary_json, '$.scene_id'), '') END"
        if "result_summary_json" in columns
        else "NULL"
    )
    op.get_bind().execute(
        text(
            f"""
            UPDATE chapter_run_jobs
            SET scene_id = COALESCE(scene_id, {payload_expr}, {result_expr})
            WHERE scene_id IS NULL
            """
        )
    )


def upgrade() -> None:
    if _inspector().has_table("scene_run_states"):
        _add_missing_columns("scene_run_states", SCENE_COLUMNS)
        _ensure_checks("scene_run_states", SCENE_CHECKS)

    if _inspector().has_table("llm_calls"):
        _add_missing_columns("llm_calls", LLM_COLUMNS)
        _backfill_llm_calls()
        _ensure_checks("llm_calls", LLM_CHECKS, llm_call=True)
        _ensure_indexes("llm_calls", LLM_INDEXES)
        _ensure_execution_step_claim_index()
        _ensure_attempt_table()

    if _inspector().has_table("chapter_run_jobs"):
        _add_missing_columns(
            "chapter_run_jobs",
            (sa.Column("scene_id", sa.String(), nullable=True),),
        )
        _backfill_chapter_run_jobs()
        _ensure_indexes(
            "chapter_run_jobs",
            {"ix_chapter_run_jobs_scene_created": ("scene_id", "created_at")},
        )


def _drop_indexes(table_name: str, names: Iterable[str]) -> None:
    existing = _index_names(table_name)
    for name in names:
        if name in existing:
            op.drop_index(name, table_name=table_name)


def _drop_columns_with_checks(
    table_name: str,
    columns: Iterable[str],
    checks: Iterable[str],
) -> None:
    existing_columns = set(_columns(table_name))
    to_drop = [name for name in columns if name in existing_columns]
    if not to_drop:
        return
    existing_checks = _check_names(table_name)
    with op.batch_alter_table(table_name, recreate="always") as batch:
        for name in checks:
            if name in existing_checks:
                batch.drop_constraint(name, type_="check")
        for name in to_drop:
            batch.drop_column(name)


def downgrade() -> None:
    if _inspector().has_table("chapter_run_jobs"):
        _drop_indexes("chapter_run_jobs", ("ix_chapter_run_jobs_scene_created",))
        _drop_columns_with_checks("chapter_run_jobs", ("scene_id",), ())

    if _inspector().has_table("llm_call_attempts"):
        _drop_indexes("llm_call_attempts", ("ix_llm_call_attempts_call_status",))
        op.drop_table("llm_call_attempts")

    if _inspector().has_table("llm_calls"):
        _drop_indexes("llm_calls", (*LLM_INDEXES, EXECUTION_STEP_CLAIM_INDEX))
        _drop_columns_with_checks(
            "llm_calls",
            (column.name for column in LLM_COLUMNS),
            LLM_CHECKS,
        )

    if _inspector().has_table("scene_run_states"):
        _drop_columns_with_checks(
            "scene_run_states",
            (column.name for column in SCENE_COLUMNS),
            SCENE_CHECKS,
        )
