"""bundle traceability sources

Revision ID: 20260409_0002
Revises: 20260408_0001
Create Date: 2026-04-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260409_0002"
down_revision = "20260408_0001"
branch_labels = None
depends_on = None


def _create_table(table_name: str, *columns: object) -> None:
    if table_name in sa.inspect(op.get_bind()).get_table_names():
        return
    (op.create_table)(table_name, *columns)


def upgrade() -> None:
    _create_table(
        "voice_profiles",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("voice_profile_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("active_flag", sa.Integer(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
    )
    _create_table(
        "relation_profiles",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("relation_profile_id", sa.String(), nullable=False),
        sa.Column("left_character_id", sa.String(), nullable=False),
        sa.Column("right_character_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("active_flag", sa.Integer(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("row_id"),
    )


def downgrade() -> None:
    op.drop_table("relation_profiles")
    op.drop_table("voice_profiles")
