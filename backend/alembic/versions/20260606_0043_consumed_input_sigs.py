"""add consumed_input_sigs_json to snowflake step rows

Revision ID: 20260606_0043
Revises: 20260606_0042
Create Date: 2026-06-06

P0-3 (收口-3): both snowflake stacks (planner ``snowflake_artifacts`` and workspace
``snowflake_step_runs``) record per-upstream content signatures at approval time so
downstream staleness becomes dependency/diff-aware instead of "stale everything
later". Existing rows have no snapshot (NULL) and fall back to the conservative
dependency-edge behavior on their first revision, then self-heal on next approval —
so no data backfill is required.

Idempotent + SQLite-batch-safe, matching the project's existing migration style.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260606_0043"
down_revision = "20260606_0042"
branch_labels = None
depends_on = None

_TABLES = ("snowflake_artifacts", "snowflake_step_runs")
_COLUMN = "consumed_input_sigs_json"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table in _TABLES:
        if table not in existing_tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if _COLUMN in columns:
            continue
        with op.batch_alter_table(table, recreate="always") as batch_op:
            batch_op.add_column(sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    for table in _TABLES:
        if table not in existing_tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if _COLUMN not in columns:
            continue
        with op.batch_alter_table(table, recreate="always") as batch_op:
            batch_op.drop_column(_COLUMN)
