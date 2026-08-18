"""add interop artifacts table

Revision ID: 20260411_0004
Revises: 20260410_0003
Create Date: 2026-04-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260411_0004"
down_revision = "20260410_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "interop_artifacts" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "interop_artifacts",
        sa.Column("artifact_id", sa.String(), nullable=False),
        sa.Column("artifact_kind", sa.String(), nullable=False),
        sa.Column("scene_id", sa.String(), nullable=True),
        sa.Column("chapter_id", sa.String(), nullable=True),
        sa.Column("source_bundle_id", sa.String(), nullable=True),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_format", sa.String(), nullable=False),
        sa.Column("file_checksum", sa.String(), nullable=True),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("artifact_id"),
    )


def downgrade() -> None:
    op.drop_table("interop_artifacts")
