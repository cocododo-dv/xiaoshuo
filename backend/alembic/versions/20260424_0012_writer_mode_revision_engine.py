"""add writer briefs and revision candidate ledger

Revision ID: 20260424_0012
Revises: 20260419_0011
Create Date: 2026-04-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260424_0012"
down_revision = "20260419_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "chapter_goals" in tables:
        chapter_columns = {column["name"] for column in inspector.get_columns("chapter_goals")}
        if "writer_brief_json" not in chapter_columns:
            op.add_column("chapter_goals", sa.Column("writer_brief_json", sa.JSON(), nullable=True))

    if "scene_cards" in tables:
        scene_columns = {column["name"] for column in inspector.get_columns("scene_cards")}
        if "writer_brief_json" not in scene_columns:
            op.add_column("scene_cards", sa.Column("writer_brief_json", sa.JSON(), nullable=True))

    if "writer_evaluations" not in tables:
        op.create_table(
            "writer_evaluations",
            sa.Column("evaluation_id", sa.String(), nullable=False),
            sa.Column("object_type", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=True),
            sa.Column("scene_id", sa.String(), nullable=True),
            sa.Column("rubric_id", sa.String(), nullable=False),
            sa.Column("source_text_ref", sa.String(), nullable=True),
            sa.Column("source_bundle_id", sa.String(), nullable=True),
            sa.Column("evaluator_llm_call_id", sa.String(), nullable=True),
            sa.Column("overall_score", sa.Float(), nullable=True),
            sa.Column("scores_json", sa.JSON(), nullable=False),
            sa.Column("findings_json", sa.JSON(), nullable=False),
            sa.Column("revision_brief_json", sa.JSON(), nullable=False),
            sa.Column("requires_human_review", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("evaluation_id"),
        )

    if "revision_candidates" not in tables:
        op.create_table(
            "revision_candidates",
            sa.Column("revision_id", sa.String(), nullable=False),
            sa.Column("evaluation_id", sa.String(), nullable=True),
            sa.Column("object_type", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=True),
            sa.Column("scene_id", sa.String(), nullable=True),
            sa.Column("revision_type", sa.String(), nullable=False),
            sa.Column("source_text_ref", sa.String(), nullable=True),
            sa.Column("proposed_text", sa.Text(), nullable=False),
            sa.Column("instruction_json", sa.JSON(), nullable=False),
            sa.Column("diff_summary_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("author_decision_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status IN ('candidate','accepted','rejected','superseded')",
                name="ck_revision_candidates_status",
            ),
            sa.PrimaryKeyConstraint("revision_id"),
        )


def downgrade() -> None:
    pass
