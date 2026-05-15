"""humanized author flow fields

Revision ID: 20260515_0035
Revises: 20260515_0034
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260515_0035"
down_revision = "20260515_0034"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "story_projects" in inspector.get_table_names() and not _has_column(
        inspector,
        "story_projects",
        "snowflake_workflow_mode",
    ):
        op.add_column(
            "story_projects",
            sa.Column("snowflake_workflow_mode", sa.String(), nullable=False, server_default="strict"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "story_projects" in inspector.get_table_names() and _has_column(
        inspector,
        "story_projects",
        "snowflake_workflow_mode",
    ):
        op.drop_column("story_projects", "snowflake_workflow_mode")
