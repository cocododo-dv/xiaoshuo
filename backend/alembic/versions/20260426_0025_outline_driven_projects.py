"""add outline driven story projects

Revision ID: 20260426_0025
Revises: 20260426_0024
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0025"
down_revision = "20260426_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "story_projects" not in tables:
        op.create_table(
            "story_projects",
            sa.Column("project_id", sa.String(), primary_key=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("genre", sa.String(), nullable=True),
            sa.Column("target_word_count", sa.Integer(), nullable=True),
            sa.Column("target_chapter_count", sa.Integer(), nullable=True),
            sa.Column("outline_text", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="outline_draft"),
            sa.Column("active_outline_plan_id", sa.String(), nullable=True),
            sa.Column("current_chapter_id", sa.String(), nullable=True),
            sa.Column("approved_chapter_ids_json", sa.JSON(), nullable=True),
            sa.Column("reference_profile_ids_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "outline_plans" not in tables:
        op.create_table(
            "outline_plans",
            sa.Column("plan_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(), nullable=False, server_default="pending_review"),
            sa.Column("plan_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("approved_at", sa.String(), nullable=True),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    _add_nullable_column("chapter_goals", "project_id", sa.Column("project_id", sa.String(), nullable=True))
    _add_nullable_column("chapter_goals", "outline_plan_id", sa.Column("outline_plan_id", sa.String(), nullable=True))
    _add_nullable_column("scene_cards", "project_id", sa.Column("project_id", sa.String(), nullable=True))
    _add_nullable_column("scene_cards", "outline_plan_id", sa.Column("outline_plan_id", sa.String(), nullable=True))


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
