"""add snowflake planning artifacts

Revision ID: 20260426_0026
Revises: 20260426_0025
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0026"
down_revision = "20260426_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    _add_nullable_column(
        "story_projects",
        "planning_mode",
        sa.Column("planning_mode", sa.String(), nullable=False, server_default="outline_driven"),
    )

    tables = set(sa.inspect(bind).get_table_names())
    if "snowflake_artifacts" not in tables:
        op.create_table(
            "snowflake_artifacts",
            sa.Column("artifact_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("step_key", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(), nullable=False, server_default="pending_review"),
            sa.Column("artifact_json", sa.JSON(), nullable=True),
            sa.Column("input_refs_json", sa.JSON(), nullable=True),
            sa.Column("diagnosis_json", sa.JSON(), nullable=True),
            sa.Column("llm_call_id", sa.String(), nullable=True),
            sa.Column("approved_at", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    if "story_characters" not in tables:
        op.create_table(
            "story_characters",
            sa.Column("character_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("role", sa.String(), nullable=True),
            sa.Column("summary_json", sa.JSON(), nullable=True),
            sa.Column("bible_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )


def downgrade() -> None:
    pass


def _add_nullable_column(table_name: str, column_name: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if table_name not in set(inspector.get_table_names()):
        return
    columns = {existing["name"] for existing in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(column)
