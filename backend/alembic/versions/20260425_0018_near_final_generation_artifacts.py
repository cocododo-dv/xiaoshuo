"""add near-final generation planning artifacts

Revision ID: 20260425_0018
Revises: 20260425_0017
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0018"
down_revision = "20260425_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "generation_planning_artifacts" in tables:
        return
    op.create_table(
        "generation_planning_artifacts",
        sa.Column("row_id", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=True),
        sa.Column("scene_id", sa.String(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("llm_call_id", sa.String(), nullable=True),
        sa.Column("source_bundle_id", sa.String(), nullable=True),
        sa.Column("source_bundle_hash", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint(
            "artifact_type IN ('character_pressure_blueprint','chapter_story_architecture')",
            name="ck_generation_planning_artifacts_type",
        ),
        sa.CheckConstraint("object_type IN ('scene','chapter')", name="ck_generation_planning_artifacts_object_type"),
        sa.CheckConstraint("status IN ('active','superseded')", name="ck_generation_planning_artifacts_status"),
        sa.PrimaryKeyConstraint("row_id"),
    )


def downgrade() -> None:
    pass
