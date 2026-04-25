"""add literary engine blueprints and review lenses

Revision ID: 20260425_0013
Revises: 20260424_0012
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0013"
down_revision = "20260424_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "scene_blueprints" not in tables:
        op.create_table(
            "scene_blueprints",
            sa.Column("row_id", sa.String(), nullable=False),
            sa.Column("scene_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=False),
            sa.Column("source_bundle_id", sa.String(), nullable=True),
            sa.Column("source_bundle_hash", sa.String(), nullable=True),
            sa.Column("blueprint_json", sa.JSON(), nullable=False),
            sa.Column("llm_call_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status IN ('draft','accepted','superseded')",
                name="ck_scene_blueprints_status",
            ),
            sa.PrimaryKeyConstraint("row_id"),
        )

    if "writer_evaluations" in tables:
        columns = {column["name"] for column in inspector.get_columns("writer_evaluations")}
        if "lens" not in columns:
            op.add_column("writer_evaluations", sa.Column("lens", sa.String(), nullable=True))
        if "parent_evaluation_id" not in columns:
            op.add_column("writer_evaluations", sa.Column("parent_evaluation_id", sa.String(), nullable=True))
        if "evidence_spans_json" not in columns:
            op.add_column("writer_evaluations", sa.Column("evidence_spans_json", sa.JSON(), nullable=True))
        if "source_blueprint_row_id" not in columns:
            op.add_column("writer_evaluations", sa.Column("source_blueprint_row_id", sa.String(), nullable=True))

    if "revision_candidates" in tables:
        columns = {column["name"] for column in inspector.get_columns("revision_candidates")}
        if "patches_json" not in columns:
            op.add_column("revision_candidates", sa.Column("patches_json", sa.JSON(), nullable=True))
        if "apply_mode" not in columns:
            op.add_column("revision_candidates", sa.Column("apply_mode", sa.String(), nullable=True))
            op.execute("UPDATE revision_candidates SET apply_mode = 'manual_only' WHERE apply_mode IS NULL")
        if "target_text_ref" not in columns:
            op.add_column("revision_candidates", sa.Column("target_text_ref", sa.String(), nullable=True))


def downgrade() -> None:
    pass
