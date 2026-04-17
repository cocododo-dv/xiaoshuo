"""add system config snapshots

Revision ID: 20260417_0008
Revises: 20260414_0007
Create Date: 2026-04-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260417_0008"
down_revision = "20260414_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "system_config_snapshots" not in existing_tables:
        op.create_table(
            "system_config_snapshots",
            sa.Column("snapshot_id", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("yaml_raw", sa.Text(), nullable=False),
            sa.Column("parsed_json", sa.JSON(), nullable=False),
            sa.Column("validation_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("active_flag", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("activated_at", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("snapshot_id"),
        )

    if "system_secrets" not in existing_tables:
        op.create_table(
            "system_secrets",
            sa.Column("secret_id", sa.String(), nullable=False),
            sa.Column("encrypted_value", sa.Text(), nullable=False),
            sa.Column("value_hint", sa.String(), nullable=True),
            sa.Column("updated_by", sa.String(), nullable=True),
            sa.Column("updated_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("secret_id"),
        )


def downgrade() -> None:
    pass
