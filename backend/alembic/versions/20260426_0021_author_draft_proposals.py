"""add author draft proposals

Revision ID: 20260426_0021
Revises: 20260426_0020
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0021"
down_revision = "20260426_0020"
branch_labels = None
depends_on = None


AUTHOR_DRAFT_EVENT_TYPE_SQL = (
    "event_type IN ("
    "'created','edited','candidate_inserted','candidate_saved','candidate_rejected',"
    "'proposal_applied','proposal_rejected'"
    ")"
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "author_draft_proposals" not in tables:
        op.create_table(
            "author_draft_proposals",
            sa.Column("proposal_id", sa.String(), nullable=False),
            sa.Column("draft_id", sa.String(), nullable=False),
            sa.Column("object_type", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=False),
            sa.Column("proposal_type", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("source_llm_call_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("author_decision_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint("object_type IN ('scene','chapter')", name="ck_author_draft_proposals_object_type"),
            sa.CheckConstraint(
                "status IN ('candidate','accepted','rejected','superseded')",
                name="ck_author_draft_proposals_status",
            ),
            sa.PrimaryKeyConstraint("proposal_id"),
        )

    if "author_draft_events" in tables:
        checks = {row.get("name") for row in inspector.get_check_constraints("author_draft_events")}
        if "ck_author_draft_events_type" in checks:
            with op.batch_alter_table("author_draft_events", recreate="always") as batch_op:
                batch_op.drop_constraint("ck_author_draft_events_type", type_="check")
                batch_op.create_check_constraint("ck_author_draft_events_type", AUTHOR_DRAFT_EVENT_TYPE_SQL)


def downgrade() -> None:
    pass
