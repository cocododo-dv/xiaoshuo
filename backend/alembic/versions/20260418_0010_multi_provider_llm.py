"""add multi provider llm routing metadata

Revision ID: 20260418_0010
Revises: 20260418_0009
Create Date: 2026-04-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260418_0010"
down_revision = "20260418_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "llm_calls" in tables:
        columns = {column["name"] for column in inspector.get_columns("llm_calls")}
        missing_columns = [
            ("provider_id", sa.Column("provider_id", sa.String(), nullable=True)),
            ("account_id", sa.Column("account_id", sa.String(), nullable=True)),
            ("node_id", sa.Column("node_id", sa.String(), nullable=True)),
            ("reasoning_level", sa.Column("reasoning_level", sa.String(), nullable=True)),
            ("native_reasoning_json", sa.Column("native_reasoning_json", sa.JSON(), nullable=True)),
            ("credential_mode", sa.Column("credential_mode", sa.String(), nullable=True)),
        ]
        missing_columns = [(name, column) for name, column in missing_columns if name not in columns]
        if missing_columns:
            with op.batch_alter_table("llm_calls") as batch_op:
                for _, column in missing_columns:
                    batch_op.add_column(column)

    if "system_secrets" in tables:
        columns = {column["name"] for column in inspector.get_columns("system_secrets")}
        missing_columns = [
            ("secret_type", sa.Column("secret_type", sa.String(), nullable=False, server_default="generic")),
            ("metadata_json", sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}")),
            ("expires_at", sa.Column("expires_at", sa.String(), nullable=True)),
        ]
        missing_columns = [(name, column) for name, column in missing_columns if name not in columns]
        if missing_columns:
            with op.batch_alter_table("system_secrets") as batch_op:
                for _, column in missing_columns:
                    batch_op.add_column(column)


def downgrade() -> None:
    pass
