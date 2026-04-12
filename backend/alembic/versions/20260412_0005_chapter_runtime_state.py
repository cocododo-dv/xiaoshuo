"""add staged backfill runtime state

Revision ID: 20260412_0005
Revises: 20260411_0004
Create Date: 2026-04-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from novel_system.db import models  # noqa: F401
from novel_system.db.base import Base

revision = "20260412_0005"
down_revision = "20260411_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    chapter_state_columns = {column["name"] for column in inspector.get_columns("chapter_states")}
    if "manual_hold_reason" not in chapter_state_columns:
        with op.batch_alter_table("chapter_states") as batch_op:
            batch_op.add_column(sa.Column("manual_hold_reason", sa.Text(), nullable=True))

    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=[Base.metadata.tables["staged_backfill"]])


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.tables["staged_backfill"].drop(bind=bind, checkfirst=True)

    with op.batch_alter_table("chapter_states") as batch_op:
        batch_op.drop_column("manual_hold_reason")
