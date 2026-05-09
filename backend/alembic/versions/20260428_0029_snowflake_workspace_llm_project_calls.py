"""add project scoped llm call linkage for snowflake workspace

Revision ID: 20260428_0029
Revises: 20260428_0028
Create Date: 2026-04-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260428_0029"
down_revision = "20260428_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "llm_calls" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("llm_calls")}
    if "project_id" in columns:
        return
    with op.batch_alter_table("llm_calls") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(), nullable=True))


def downgrade() -> None:
    pass
