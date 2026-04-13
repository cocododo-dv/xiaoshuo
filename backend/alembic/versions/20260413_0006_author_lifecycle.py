"""add author trash lifecycle columns

Revision ID: 20260413_0006
Revises: 20260412_0005
Create Date: 2026-04-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260413_0006"
down_revision = "20260412_0005"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    chapter_columns = _column_names("chapter_goals")
    with op.batch_alter_table("chapter_goals") as batch_op:
        if "trashed_flag" not in chapter_columns:
            batch_op.add_column(sa.Column("trashed_flag", sa.Integer(), nullable=False, server_default="0"))
        if "trashed_at" not in chapter_columns:
            batch_op.add_column(sa.Column("trashed_at", sa.String(), nullable=True))
        if "trashed_by" not in chapter_columns:
            batch_op.add_column(sa.Column("trashed_by", sa.String(), nullable=True))

    scene_columns = _column_names("scene_cards")
    with op.batch_alter_table("scene_cards") as batch_op:
        if "trashed_flag" not in scene_columns:
            batch_op.add_column(sa.Column("trashed_flag", sa.Integer(), nullable=False, server_default="0"))
        if "trashed_at" not in scene_columns:
            batch_op.add_column(sa.Column("trashed_at", sa.String(), nullable=True))
        if "trashed_by" not in scene_columns:
            batch_op.add_column(sa.Column("trashed_by", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("scene_cards") as batch_op:
        batch_op.drop_column("trashed_by")
        batch_op.drop_column("trashed_at")
        batch_op.drop_column("trashed_flag")

    with op.batch_alter_table("chapter_goals") as batch_op:
        batch_op.drop_column("trashed_by")
        batch_op.drop_column("trashed_at")
        batch_op.drop_column("trashed_flag")
