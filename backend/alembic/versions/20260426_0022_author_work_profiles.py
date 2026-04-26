"""add author work profiles and proposal source

Revision ID: 20260426_0022
Revises: 20260426_0021
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0022"
down_revision = "20260426_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "work_profiles" not in tables:
        op.create_table(
            "work_profiles",
            sa.Column("profile_id", sa.String(), nullable=False),
            sa.Column("scope_type", sa.String(), nullable=False),
            sa.Column("scope_ref_id", sa.String(), nullable=False),
            sa.Column("profile_key", sa.String(), nullable=False),
            sa.Column("display_name", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("profile_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint("scope_type IN ('global','chapter')", name="ck_work_profiles_scope_type"),
            sa.CheckConstraint("status IN ('active','archived')", name="ck_work_profiles_status"),
            sa.PrimaryKeyConstraint("profile_id"),
        )

    if "author_draft_proposals" in tables:
        columns = {column["name"] for column in inspector.get_columns("author_draft_proposals")}
        if "proposal_source" not in columns:
            with op.batch_alter_table("author_draft_proposals") as batch_op:
                batch_op.add_column(sa.Column("proposal_source", sa.String(), nullable=False, server_default="single_request"))


def downgrade() -> None:
    pass
