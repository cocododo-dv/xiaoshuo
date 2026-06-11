"""add snowflake_scene_plans.row_uid (immutable scene identity)

Revision ID: 20260606_0042
Revises: 20260606_0041
Create Date: 2026-06-06

P1-1 (收口-1): scene identity used to be derived from the author-editable
``scene_id`` (``scene_plan_id = ..._{scene_id}``), so editing ``scene_id`` in the
scene-list form orphaned the old plan and broke the seed / diff chain. ``row_uid``
is a system-minted, immutable anchor: minted once, never changed by author input,
and the stable key the staleness diff (P0-3) aligns scenes on.

Backfills every existing row with a fresh uuid and adds a per-project unique index.
Idempotent + SQLite-batch-safe, matching the project's existing migration style.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "20260606_0042"
down_revision = "20260606_0041"
branch_labels = None
depends_on = None

_TABLE = "snowflake_scene_plans"
_INDEX = "ix_snowflake_scene_plans_row_uid"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if "row_uid" not in columns:
        with op.batch_alter_table(_TABLE, recreate="always") as batch_op:
            batch_op.add_column(sa.Column("row_uid", sa.String(), nullable=True))

    # Backfill: every existing plan gets a stable, immutable row identity.
    rows = bind.execute(
        sa.text(f"SELECT scene_plan_id FROM {_TABLE} WHERE row_uid IS NULL OR row_uid = ''")
    ).fetchall()
    for (scene_plan_id,) in rows:
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET row_uid = :row_uid WHERE scene_plan_id = :pid"),
            {"row_uid": f"row_{uuid.uuid4().hex}", "pid": scene_plan_id},
        )

    existing_indexes = {index["name"] for index in inspector.get_indexes(_TABLE)}
    if _INDEX not in existing_indexes:
        op.create_index(_INDEX, _TABLE, ["project_id", "row_uid"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in set(inspector.get_table_names()):
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes(_TABLE)}
    if _INDEX in existing_indexes:
        op.drop_index(_INDEX, table_name=_TABLE)

    columns = {column["name"] for column in inspector.get_columns(_TABLE)}
    if "row_uid" in columns:
        with op.batch_alter_table(_TABLE, recreate="always") as batch_op:
            batch_op.drop_column("row_uid")
