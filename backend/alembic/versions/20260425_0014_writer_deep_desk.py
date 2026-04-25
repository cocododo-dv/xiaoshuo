"""add writer deep revision desk tables

Revision ID: 20260425_0014
Revises: 20260425_0013
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0014"
down_revision = "20260425_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "passage_patch_candidates" not in tables:
        op.create_table(
            "passage_patch_candidates",
            sa.Column("patch_id", sa.String(), nullable=False),
            sa.Column("object_type", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=True),
            sa.Column("scene_id", sa.String(), nullable=True),
            sa.Column("source_text_ref", sa.String(), nullable=True),
            sa.Column("target_text_ref", sa.String(), nullable=True),
            sa.Column("source_excerpt", sa.Text(), nullable=False),
            sa.Column("issue_dimension", sa.String(), nullable=False),
            sa.Column("replacement_options_json", sa.JSON(), nullable=False),
            sa.Column("manual_only", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("author_decision", sa.String(), nullable=False),
            sa.Column("selected_option_id", sa.String(), nullable=True),
            sa.Column("author_decision_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status IN ('candidate','accepted','rejected','superseded')",
                name="ck_passage_patch_candidates_status",
            ),
            sa.CheckConstraint(
                "author_decision IN ('pending','accepted','rejected','regenerate')",
                name="ck_passage_patch_candidates_author_decision",
            ),
            sa.PrimaryKeyConstraint("patch_id"),
        )

    if "author_preference_profiles" not in tables:
        op.create_table(
            "author_preference_profiles",
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("scope_type", sa.String(), nullable=False),
            sa.Column("scope_ref_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("runtime_eligible", sa.Integer(), nullable=False),
            sa.Column("summary_json", sa.JSON(), nullable=False),
            sa.Column("source_patch_ids_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status IN ('draft','approved','rejected','superseded')",
                name="ck_author_preference_profiles_status",
            ),
            sa.PrimaryKeyConstraint("profile_id"),
        )


def downgrade() -> None:
    pass
