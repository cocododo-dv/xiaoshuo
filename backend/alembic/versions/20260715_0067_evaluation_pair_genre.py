"""Add the optional genre label to blind-evaluation pairs.

Revision ID: 20260715_0067
Revises: 20260715_0066
Create Date: 2026-07-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260715_0067"
down_revision = "20260715_0066"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _column_names("evaluation_pairs")
    if not existing or "genre" in existing:
        return
    op.add_column("evaluation_pairs", sa.Column("genre", sa.String(), nullable=True))


def downgrade() -> None:
    existing = _column_names("evaluation_pairs")
    if "genre" in existing:
        with op.batch_alter_table("evaluation_pairs") as batch:
            batch.drop_column("genre")
