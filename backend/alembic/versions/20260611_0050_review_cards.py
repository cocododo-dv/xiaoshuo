"""review item card columns + derived snoozes (FE-ALIGN Phase 5 待办收件箱)

Revision ID: 20260611_0050
Revises: 20260611_0049
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_0050"
down_revision = "20260611_0049"
branch_labels = None
depends_on = None

CARD_COLUMNS = (
    ("project_id", sa.String()),
    ("kind", sa.String()),
    ("priority", sa.Integer()),
    ("provenance_json", sa.JSON()),
    ("card_json", sa.JSON()),
    ("actions_json", sa.JSON()),
    ("state", sa.String()),
    ("snooze_until", sa.String()),
    ("resolved_action_index", sa.Integer()),
    ("dedupe_key", sa.String()),
)

UNIQUE_INDEX = "ux_review_items_project_dedupe"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "review_items" in tables:
        existing = {col["name"] for col in inspector.get_columns("review_items")}
        for name, col_type in CARD_COLUMNS:
            if name not in existing:
                op.add_column("review_items", sa.Column(name, col_type, nullable=True))
        indexes = {idx["name"] for idx in inspector.get_indexes("review_items")}
        if UNIQUE_INDEX not in indexes:
            # onceTask 语义：同一作品同一 dedupe_key 只允许一张卡（NULL 不参与唯一性）
            op.create_index(UNIQUE_INDEX, "review_items", ["project_id", "dedupe_key"], unique=True)

    if "review_derived_snoozes" not in tables:
        op.create_table(
            "review_derived_snoozes",
            sa.Column("project_id", sa.String(), primary_key=True),
            sa.Column("fingerprint", sa.String(), primary_key=True),
            sa.Column("snooze_until", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "review_derived_snoozes" in tables:
        op.drop_table("review_derived_snoozes")
    if "review_items" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("review_items")}
        if UNIQUE_INDEX in indexes:
            op.drop_index(UNIQUE_INDEX, table_name="review_items")
        existing = {col["name"] for col in inspector.get_columns("review_items")}
        for name, _t in reversed(CARD_COLUMNS):
            if name in existing:
                op.drop_column("review_items", name)
