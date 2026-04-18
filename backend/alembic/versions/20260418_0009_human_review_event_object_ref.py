"""repair human review event columns

Revision ID: 20260418_0009
Revises: 20260417_0008
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260418_0009"
down_revision = "20260417_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "human_review_events" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("human_review_events")}
    missing_columns = [
        ("object_ref", sa.Column("object_ref", sa.String(), nullable=True)),
        ("details_json", sa.Column("details_json", sa.JSON(), nullable=True)),
    ]
    missing_columns = [(name, column) for name, column in missing_columns if name not in columns]
    if not missing_columns:
        return
    with op.batch_alter_table("human_review_events") as batch_op:
        for _, column in missing_columns:
            batch_op.add_column(column)


def downgrade() -> None:
    pass
