"""add writer room proposal merge metadata

Revision ID: 20260426_0024
Revises: 20260426_0023
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0024"
down_revision = "20260426_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "author_draft_proposals" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("author_draft_proposals")}
    with op.batch_alter_table("author_draft_proposals") as batch_op:
        if "target_range_json" not in columns:
            batch_op.add_column(sa.Column("target_range_json", sa.JSON(), nullable=True))
        if "before_text_hash" not in columns:
            batch_op.add_column(sa.Column("before_text_hash", sa.String(), nullable=True))
        if "replacement_text" not in columns:
            batch_op.add_column(sa.Column("replacement_text", sa.Text(), nullable=True))
        if "proposal_kind" not in columns:
            batch_op.add_column(sa.Column("proposal_kind", sa.String(), nullable=True))
        if "source_evaluation_id" not in columns:
            batch_op.add_column(sa.Column("source_evaluation_id", sa.String(), nullable=True))
        if "merge_status" not in columns:
            batch_op.add_column(sa.Column("merge_status", sa.String(), nullable=True))

    op.execute("UPDATE author_draft_proposals SET proposal_kind = 'whole_draft' WHERE proposal_kind IS NULL")
    op.execute("UPDATE author_draft_proposals SET merge_status = 'pending' WHERE merge_status IS NULL")


def downgrade() -> None:
    pass
