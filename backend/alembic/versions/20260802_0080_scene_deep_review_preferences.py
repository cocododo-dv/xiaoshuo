"""Persist per-scene deep-review decisions and ignored diagnostics.

Revision ID: 20260802_0080
Revises: 20260802_0079
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0080"
down_revision = "20260802_0079"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns("scene_cards")
    }
    if "deep_review_decision_log_json" not in existing:
        op.add_column(
            "scene_cards",
            sa.Column("deep_review_decision_log_json", sa.JSON(), nullable=False, server_default="[]"),
        )
    if "deep_review_ignored_keys_json" not in existing:
        op.add_column(
            "scene_cards",
            sa.Column("deep_review_ignored_keys_json", sa.JSON(), nullable=False, server_default="[]"),
        )
    if "deep_review_preferences_revision_no" not in existing:
        op.add_column(
            "scene_cards",
            sa.Column(
                "deep_review_preferences_revision_no",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    existing = {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns("scene_cards")
    }
    with op.batch_alter_table("scene_cards") as batch_op:
        if "deep_review_preferences_revision_no" in existing:
            batch_op.drop_column("deep_review_preferences_revision_no")
        if "deep_review_ignored_keys_json" in existing:
            batch_op.drop_column("deep_review_ignored_keys_json")
        if "deep_review_decision_log_json" in existing:
            batch_op.drop_column("deep_review_decision_log_json")
