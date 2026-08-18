"""Merge the restored real-only branch and enforce chapter-plan membership.

Revision ID: 20260802_0077
Revises: 20260717_0075, 20260725_0076
Create Date: 2026-08-02

The repository briefly shipped the ``20260717_0074 -> 20260717_0075``
real-only migration branch before a forced history replacement introduced the
``20260722_0074 -> 20260725_0076`` chaptering branch.  Runtime databases stamped
with the former branch must remain upgradeable, so both original branches are
now retained and converge here.

The 0076 migration added ``snowflake_scene_plans.chapter_plan_id`` as a plain
SQLite column on historical databases even though the ORM declares a foreign
key.  This migration repairs impossible references to NULL (the domain value
for an unassigned scene), installs the missing foreign key, and indexes the
membership column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260802_0077"
down_revision = ("20260717_0075", "20260725_0076")
branch_labels = None
depends_on = None


_SCENE_TABLE = "snowflake_scene_plans"
_CHAPTER_TABLE = "snowflake_chapter_plans"
_FK_NAME = "fk_snowflake_scene_plans_chapter_plan_id"
_INDEX_NAME = "ix_snowflake_scene_plans_chapter_plan_id"


def _has_membership_foreign_key(inspector: sa.Inspector) -> bool:
    return any(
        tuple(foreign_key.get("constrained_columns") or ())
        == ("chapter_plan_id",)
        and str(foreign_key.get("referred_table") or "") == _CHAPTER_TABLE
        and tuple(foreign_key.get("referred_columns") or ())
        == ("chapter_plan_id",)
        for foreign_key in inspector.get_foreign_keys(_SCENE_TABLE)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    missing_tables = sorted({_SCENE_TABLE, _CHAPTER_TABLE} - tables)
    if missing_tables:
        raise RuntimeError(
            "cannot enforce snowflake chapter membership; missing tables: "
            + ", ".join(missing_tables)
        )
    scene_columns = {
        str(column["name"]) for column in inspector.get_columns(_SCENE_TABLE)
    }
    if "chapter_plan_id" not in scene_columns:
        raise RuntimeError(
            "cannot enforce snowflake chapter membership; "
            "snowflake_scene_plans.chapter_plan_id is missing"
        )

    # A missing parent means the value can never identify a real chapter plan.
    # NULL is the existing domain representation for an unassigned scene and is
    # therefore the only lossless, deterministic repair before enabling the FK.
    bind.execute(
        sa.text(
            "UPDATE snowflake_scene_plans AS scene_plan "
            "SET chapter_plan_id = NULL "
            "WHERE chapter_plan_id IS NOT NULL "
            "AND NOT EXISTS ("
            "SELECT 1 FROM snowflake_chapter_plans AS chapter_plan "
            "WHERE chapter_plan.chapter_plan_id = scene_plan.chapter_plan_id"
            ")"
        )
    )

    inspector = sa.inspect(bind)
    if not _has_membership_foreign_key(inspector):
        with op.batch_alter_table(_SCENE_TABLE) as batch_op:
            batch_op.create_foreign_key(
                _FK_NAME,
                _CHAPTER_TABLE,
                ["chapter_plan_id"],
                ["chapter_plan_id"],
            )

    indexes = {
        str(index["name"])
        for index in sa.inspect(bind).get_indexes(_SCENE_TABLE)
    }
    if _INDEX_NAME not in indexes:
        op.create_index(
            _INDEX_NAME,
            _SCENE_TABLE,
            ["chapter_plan_id"],
        )


def downgrade() -> None:
    raise RuntimeError(
        "20260802_0077 is intentionally irreversible: it merges a previously "
        "published irreversible migration branch and repairs invalid chapter "
        "membership references"
    )
