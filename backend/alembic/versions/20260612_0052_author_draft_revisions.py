"""author draft revision snapshots (FE-ALIGN F2 版本历史)

Revision ID: 20260612_0052
Revises: 20260611_0051
Create Date: 2026-06-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260612_0052"
down_revision = "20260611_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "author_draft_revisions" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "author_draft_revisions",
        sa.Column("draft_revision_id", sa.String(), primary_key=True),
        sa.Column("draft_id", sa.String(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("words", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origin", sa.String(), nullable=False, server_default="edited"),
        sa.Column("created_by", sa.String(), nullable=False, server_default="author_draft"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.UniqueConstraint("draft_id", "revision_no", name="uq_author_draft_revisions_draft_rev"),
    )
    op.create_index("ix_author_draft_revisions_draft", "author_draft_revisions", ["draft_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "author_draft_revisions" in set(inspector.get_table_names()):
        indexes = {idx["name"] for idx in inspector.get_indexes("author_draft_revisions")}
        if "ix_author_draft_revisions_draft" in indexes:
            op.drop_index("ix_author_draft_revisions_draft", table_name="author_draft_revisions")
        op.drop_table("author_draft_revisions")
