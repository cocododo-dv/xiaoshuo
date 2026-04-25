"""add author structure candidates

Revision ID: 20260425_0017
Revises: 20260425_0016
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0017"
down_revision = "20260425_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "author_structure_candidates" in tables:
        return
    op.create_table(
        "author_structure_candidates",
        sa.Column("candidate_id", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=False),
        sa.Column("object_id", sa.String(), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=True),
        sa.Column("scene_id", sa.String(), nullable=True),
        sa.Column("source_draft_id", sa.String(), nullable=False),
        sa.Column("source_text_ref", sa.String(), nullable=True),
        sa.Column("extraction_llm_call_id", sa.String(), nullable=True),
        sa.Column("candidate_brief_json", sa.JSON(), nullable=False),
        sa.Column("uncertainty_notes_json", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("author_decision", sa.String(), nullable=False),
        sa.Column("author_decision_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.CheckConstraint("object_type IN ('scene','chapter')", name="ck_author_structure_candidates_object_type"),
        sa.CheckConstraint(
            "status IN ('candidate','accepted','rejected','superseded')",
            name="ck_author_structure_candidates_status",
        ),
        sa.CheckConstraint(
            "author_decision IN ('pending','accepted','rejected')",
            name="ck_author_structure_candidates_author_decision",
        ),
        sa.PrimaryKeyConstraint("candidate_id"),
    )


def downgrade() -> None:
    pass
