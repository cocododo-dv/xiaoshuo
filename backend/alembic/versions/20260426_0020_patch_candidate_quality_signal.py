"""add patch candidate quality signal provenance

Revision ID: 20260426_0020
Revises: 20260425_0019
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0020"
down_revision = "20260425_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "passage_patch_candidates" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("passage_patch_candidates")}
    with op.batch_alter_table("passage_patch_candidates") as batch_op:
        if "quality_signal_id" not in columns:
            batch_op.add_column(sa.Column("quality_signal_id", sa.String(), nullable=True))


def downgrade() -> None:
    pass
