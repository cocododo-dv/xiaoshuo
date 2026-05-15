"""add stale acceptance audit fields

Revision ID: 20260515_0034
Revises: 20260514_0033
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260515_0034"
down_revision = "20260514_0033"
branch_labels = None
depends_on = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def _add_nullable_column(inspector: sa.Inspector, table_name: str, column: sa.Column) -> None:
    if table_name in inspector.get_table_names() and not _has_column(inspector, table_name, column.name):
        op.add_column(table_name, column)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name in ("snowflake_step_runs", "snowflake_scene_plans"):
        _add_nullable_column(inspector, table_name, sa.Column("stale_accepted_at", sa.String(), nullable=True))
        _add_nullable_column(inspector, table_name, sa.Column("stale_accepted_by", sa.String(), nullable=True))
        _add_nullable_column(inspector, table_name, sa.Column("stale_accepted_note", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name in ("snowflake_scene_plans", "snowflake_step_runs"):
        if table_name not in inspector.get_table_names():
            continue
        for column_name in ("stale_accepted_note", "stale_accepted_by", "stale_accepted_at"):
            if _has_column(inspector, table_name, column_name):
                op.drop_column(table_name, column_name)
