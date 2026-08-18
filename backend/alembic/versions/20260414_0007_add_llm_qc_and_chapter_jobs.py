"""add llm qc and chapter jobs

Revision ID: 20260414_0007
Revises: 20260413_0006
Create Date: 2026-04-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260414_0007"
down_revision = "20260413_0006"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "llm_calls" not in existing_tables:
        op.create_table(
            "llm_calls",
            sa.Column("llm_call_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("prompt_hash", sa.String(), nullable=True),
            sa.Column("step", sa.String(), nullable=True),
            sa.Column("scene_id", sa.String(), nullable=True),
            sa.Column("chapter_id", sa.String(), nullable=True),
            sa.Column("request_payload_summary", sa.JSON(), nullable=True),
            sa.Column("response_payload_summary", sa.JSON(), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=True),
            sa.Column("completion_tokens", sa.Integer(), nullable=True),
            sa.Column("total_tokens", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("finish_reason", sa.String(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("llm_call_id"),
        )

    if "qc_reports" not in existing_tables:
        op.create_table(
            "qc_reports",
            sa.Column("qc_report_id", sa.String(), nullable=False),
            sa.Column("scene_id", sa.String(), nullable=True),
            sa.Column("chapter_id", sa.String(), nullable=True),
            sa.Column("qc_type", sa.String(), nullable=True),
            sa.Column("source_draft_row_id", sa.String(), nullable=True),
            sa.Column("source_bundle_id", sa.String(), nullable=True),
            sa.Column("resolution_code", sa.String(), nullable=True),
            sa.Column("pass_flag", sa.Integer(), nullable=True),
            sa.Column("next_action", sa.String(), nullable=True),
            sa.Column("issues_json", sa.JSON(), nullable=True),
            sa.Column("rewrite_brief_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("qc_report_id"),
        )

    if "chapter_run_jobs" not in existing_tables:
        op.create_table(
            "chapter_run_jobs",
            sa.Column("job_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("job_type", sa.String(), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("result_summary_json", sa.JSON(), nullable=True),
            sa.Column("worker_id", sa.String(), nullable=True),
            sa.Column("attempt_no", sa.Integer(), nullable=True),
            sa.Column("heartbeat_at", sa.String(), nullable=True),
            sa.Column("lease_expires_at", sa.String(), nullable=True),
            sa.Column("started_at", sa.String(), nullable=True),
            sa.Column("finished_at", sa.String(), nullable=True),
            sa.Column("error_code", sa.String(), nullable=True),
            sa.Column("error_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("job_id"),
        )

    scene_draft_columns = _column_names("scene_drafts")
    if "generation_llm_call_id" not in scene_draft_columns:
        with op.batch_alter_table("scene_drafts") as batch_op:
            batch_op.add_column(sa.Column("generation_llm_call_id", sa.String(), nullable=True))

    final_scene_columns = _column_names("final_scenes")
    if "generation_llm_call_id" not in final_scene_columns:
        with op.batch_alter_table("final_scenes") as batch_op:
            batch_op.add_column(sa.Column("generation_llm_call_id", sa.String(), nullable=True))


def downgrade() -> None:
    # Older installations may have run the dynamic base migration form of 0001 and
    # therefore may already have these objects before 0007. Dropping them here would
    # risk destructive rollback drift, so this downgrade is intentionally a no-op.
    pass
