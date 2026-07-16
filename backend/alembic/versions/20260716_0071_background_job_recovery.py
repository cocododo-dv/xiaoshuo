"""Persist recoverable Style Reference background job state.

Revision ID: 20260716_0071
Revises: 20260715_0070
Create Date: 2026-07-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260716_0071"
down_revision = "20260715_0070"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table_name: str) -> set[str]:
    inspector = _inspector()
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    inspector = _inspector()
    if not inspector.has_table(table_name):
        return set()
    return {str(index["name"]) for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if not _inspector().has_table("background_recovery_leases"):
        op.create_table(
            "background_recovery_leases",
            sa.Column("lease_key", sa.String(), nullable=False),
            sa.Column("owner_id", sa.String(), nullable=False),
            sa.Column("lease_expires_at", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("lease_key"),
        )

    run_columns = _columns("style_reference_runs")
    run_additions = (
        sa.Column("dispatch_state", sa.String(), nullable=False, server_default="completed"),
        sa.Column("requested_layers_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("heartbeat_at", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    for column in run_additions:
        if run_columns and column.name not in run_columns:
            op.add_column("style_reference_runs", column)
    if run_columns:
        # Existing terminal rows are complete; an old in-flight row cannot be
        # resumed because requested layers were not persisted before this
        # migration, so expose it as retryable failure instead of a false queue.
        op.execute(
            "UPDATE style_reference_runs "
            "SET dispatch_state = CASE "
            "WHEN status = 'failed' THEN 'failed' "
            "WHEN status = 'cancelled' THEN 'cancelled' "
            "WHEN status IN ('running','pending') THEN 'failed' "
            "ELSE 'completed' END, "
            "retryable = CASE WHEN status IN ('running','pending') THEN TRUE ELSE retryable END, "
            "error_code = CASE WHEN status IN ('running','pending') "
            "THEN 'STYLE_REFERENCE_RUN_MIGRATION_INTERRUPTED' ELSE error_code END, "
            "error_text = CASE WHEN status IN ('running','pending') "
            "THEN 'legacy background extraction cannot be resumed; start a new run' ELSE error_text END, "
            "status = CASE WHEN status IN ('running','pending') THEN 'failed' ELSE status END"
        )
    if run_columns and "ix_style_reference_runs_dispatch_state" not in _indexes("style_reference_runs"):
        op.create_index(
            "ix_style_reference_runs_dispatch_state",
            "style_reference_runs",
            ["dispatch_state"],
            unique=False,
        )

    report_columns = _columns("style_reference_validation_reports")
    report_additions = (
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("heartbeat_at", sa.String(), nullable=True),
        sa.Column("finished_at", sa.String(), nullable=True),
    )
    for column in report_additions:
        if report_columns and column.name not in report_columns:
            op.add_column("style_reference_validation_reports", column)
    if report_columns:
        op.execute(
            "UPDATE style_reference_validation_reports "
            "SET status = CASE WHEN verdict = '' THEN 'failed' ELSE 'completed' END, "
            "retryable = CASE WHEN verdict = '' THEN TRUE ELSE retryable END, "
            "error_code = CASE WHEN verdict = '' "
            "THEN 'STYLE_REFERENCE_VALIDATION_MIGRATION_INTERRUPTED' ELSE error_code END, "
            "error_text = CASE WHEN verdict = '' "
            "THEN 'legacy async validation was interrupted; submit the text again to retry' ELSE error_text END, "
            "verdict = CASE WHEN verdict = '' THEN 'fail' ELSE verdict END, "
            "finished_at = CASE WHEN verdict = '' THEN created_at ELSE finished_at END"
        )
    if report_columns and "ix_style_reference_validation_reports_status" not in _indexes(
        "style_reference_validation_reports"
    ):
        op.create_index(
            "ix_style_reference_validation_reports_status",
            "style_reference_validation_reports",
            ["status"],
            unique=False,
        )


def downgrade() -> None:
    if "ix_style_reference_validation_reports_status" in _indexes(
        "style_reference_validation_reports"
    ):
        op.drop_index(
            "ix_style_reference_validation_reports_status",
            table_name="style_reference_validation_reports",
        )
    report_columns = _columns("style_reference_validation_reports")
    for name in (
        "finished_at",
        "heartbeat_at",
        "started_at",
        "retryable",
        "error_text",
        "error_code",
        "status",
    ):
        if name in report_columns:
            op.drop_column("style_reference_validation_reports", name)

    if "ix_style_reference_runs_dispatch_state" in _indexes("style_reference_runs"):
        op.drop_index("ix_style_reference_runs_dispatch_state", table_name="style_reference_runs")
    run_columns = _columns("style_reference_runs")
    for name in (
        "retryable",
        "error_text",
        "error_code",
        "heartbeat_at",
        "requested_layers_json",
        "dispatch_state",
    ):
        if name in run_columns:
            op.drop_column("style_reference_runs", name)
    if _inspector().has_table("background_recovery_leases"):
        op.drop_table("background_recovery_leases")
