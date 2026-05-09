"""persist snowflake assistant turns

Revision ID: 20260429_0032
Revises: 20260429_0031
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260429_0032"
down_revision = "20260429_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "snowflake_assistant_turns" in tables:
        return
    op.create_table(
        "snowflake_assistant_turns",
        sa.Column("turn_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
        sa.Column("step_key", sa.String(), nullable=False),
        sa.Column("focus_scene_id", sa.String(), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("suggestions_json", sa.JSON(), nullable=True),
        sa.Column("candidate_label", sa.String(), nullable=True),
        sa.Column("candidate_patch_json", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="fallback"),
        sa.Column("llm_call_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "snowflake_assistant_turns" in tables:
        op.drop_table("snowflake_assistant_turns")
