"""Add fail-closed evidence metadata to blind-evaluation experiments.

Revision ID: 20260715_0066
Revises: 20260713_0065
Create Date: 2026-07-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260715_0066"
down_revision = "20260713_0065"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    existing = _column_names("evaluation_experiments")
    if not existing:
        return
    columns = (
        sa.Column("evidence_provenance", sa.String(), nullable=False, server_default="synthetic"),
        sa.Column("frozen_at", sa.String(), nullable=True),
        sa.Column("frozen_pair_manifest_hash", sa.String(), nullable=True),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column("evaluation_experiments", column)


def downgrade() -> None:
    existing = _column_names("evaluation_experiments")
    for column_name in ("frozen_pair_manifest_hash", "frozen_at", "evidence_provenance"):
        if column_name in existing:
            with op.batch_alter_table("evaluation_experiments") as batch:
                batch.drop_column(column_name)
