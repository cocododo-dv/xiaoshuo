"""add staged backfill runtime state

Revision ID: 20260412_0005
Revises: 20260411_0004
Create Date: 2026-04-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

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

    if "staged_backfill" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "staged_backfill",
            sa.Column("stage_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=False),
            sa.Column("scene_id", sa.String(), nullable=False),
            sa.Column("marker_id", sa.String(), nullable=False),
            sa.Column("marker_text", sa.Text(), nullable=False),
            sa.Column("marker_token", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("linked_tracker_row_id", sa.String(), nullable=True),
            sa.Column("last_strategy", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.CheckConstraint(
                "status IN ('pending','completed','deferred','abandoned')",
                name="ck_staged_backfill_status",
            ),
            sa.ForeignKeyConstraint(["chapter_id"], ["chapter_goals.chapter_id"]),
            sa.ForeignKeyConstraint(["scene_id"], ["scene_cards.scene_id"]),
            sa.PrimaryKeyConstraint("stage_id"),
        )


def downgrade() -> None:
    op.drop_table("staged_backfill")

    with op.batch_alter_table("chapter_states") as batch_op:
        batch_op.drop_column("manual_hold_reason")
