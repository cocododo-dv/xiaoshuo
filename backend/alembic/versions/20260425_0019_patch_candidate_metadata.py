"""add patch candidate metadata

Revision ID: 20260425_0019
Revises: 20260425_0018
Create Date: 2026-04-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0019"
down_revision = "20260425_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "passage_patch_candidates" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("passage_patch_candidates")}
    with op.batch_alter_table("passage_patch_candidates") as batch_op:
        if "candidate_category" not in columns:
            batch_op.add_column(sa.Column("candidate_category", sa.String(), nullable=False, server_default="local_patch"))
        if "target_range_json" not in columns:
            batch_op.add_column(sa.Column("target_range_json", sa.JSON(), nullable=True))
        if "revision_strategy" not in columns:
            batch_op.add_column(sa.Column("revision_strategy", sa.Text(), nullable=True))
        if "preference_tags_json" not in columns:
            batch_op.add_column(sa.Column("preference_tags_json", sa.JSON(), nullable=False, server_default="[]"))
        if "inserted_into_author_draft" not in columns:
            batch_op.add_column(sa.Column("inserted_into_author_draft", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    pass
