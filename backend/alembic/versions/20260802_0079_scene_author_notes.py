"""Persist per-scene author notes with optimistic concurrency.

Revision ID: 20260802_0079
Revises: 20260802_0078
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0079"
down_revision = "20260802_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns("scene_cards")
    }
    if "author_notes" not in existing:
        op.add_column(
            "scene_cards",
            sa.Column("author_notes", sa.Text(), nullable=False, server_default=""),
        )
    if "author_notes_revision_no" not in existing:
        op.add_column(
            "scene_cards",
            sa.Column("author_notes_revision_no", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    existing = {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns("scene_cards")
    }
    with op.batch_alter_table("scene_cards") as batch_op:
        if "author_notes_revision_no" in existing:
            batch_op.drop_column("author_notes_revision_no")
        if "author_notes" in existing:
            batch_op.drop_column("author_notes")
