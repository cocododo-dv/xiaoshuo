"""Make snowflake scene_id collision-proof and give scene plans a soft delete.

Revision ID: 20260725_0075
Revises: 20260722_0074
Create Date: 2026-07-25

Two defects in the snowflake → chapter materialization path, both reproduced
against a live workspace before this migration was written:

1. ``scene_id`` was minted as ``f"{chapter_id}_SC{scene_seq:02d}"``, frozen at row
   creation, while ``scene_seq`` was recomputed on every save.  Deleting a scene and
   adding another therefore produced two rows with the *same* ``scene_id``.  At
   materialization ``_build_outline_plan``'s ``detail_by_id`` and
   ``approve_outline_plan``'s ``session.get(SceneCard, scene_id)`` both collapse on
   that key, so one scene was silently lost (5 scene plans → 4 scene cards).

2. ``_sync_scene_plans`` only ever inserted and updated — nothing in the repo ever
   deleted a ``SnowflakeScenePlan``.  A scene the author removed in the UI lived on,
   never received step-10 detail, was diagnosed ``rewrite``, and permanently blocked
   the materialization gate with a scene the author could no longer see.

This migration adds the soft-delete columns, repairs existing duplicate
``scene_id`` values, and installs a unique index so a future collision fails loudly
instead of eating a scene.

IRREVERSIBLE (partially): step 3 rewrites ``scene_id`` on rows that were never
materialized.  ``downgrade`` drops the index and the columns but cannot restore the
old identifiers.  Back the database up first:

    cp novel_system.db novel_system.db.bak-0075-$(date +%Y%m%d)

A ``scene_id`` that a ``scene_cards`` row points at is never left dangling: within
each duplicate group exactly one plan row keeps the identifier, chosen by matching
the card's own (chapter_id, scene_seq) position, so no existing
chapter/scene/manuscript link moves.  See the comment on step 2 for why the card
cannot simply be asked which plan row it came from.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "20260725_0075"
down_revision = "20260722_0074"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_snowflake_scene_plans_scene_id"


def _mint_row_uid() -> str:
    return f"row_{uuid.uuid4().hex}"


_NEW_COLUMNS = (
    ("removed_at", sa.String(), None),
    ("removed_by", sa.String(), None),
    ("orphaned_flag", sa.Integer(), "0"),
)


def upgrade() -> None:
    # 0001 init_schema 通过 Base.metadata.create_all 建当前全部模型表 — inspector 守卫；
    # 新库跑迁移链时这些列/索引已由 create_all 以完整定义建好，历史库才需要补。
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "snowflake_scene_plans" not in tables:
        return
    # 历史快照库（迁移链早期的检出点）可能还没有 scene_cards。没有它就等于「什么都没
    # 物化过」，所有场景计划都可以安全重铸 —— 但绝不能直接 SELECT 一张不存在的表。
    has_scene_cards = "scene_cards" in tables

    existing_columns = {col["name"] for col in inspector.get_columns("snowflake_scene_plans")}
    for name, column_type, server_default in _NEW_COLUMNS:
        if name not in existing_columns:
            op.add_column(
                "snowflake_scene_plans",
                sa.Column(name, column_type, nullable=True, server_default=server_default),
            )

    # 1. Backfill row_uid — it is the anchor the new scene_id is derived from, and
    #    pre-P1-1 rows may still be missing it.
    missing_anchor = bind.execute(
        sa.text(
            "SELECT scene_plan_id FROM snowflake_scene_plans "
            "WHERE row_uid IS NULL OR TRIM(row_uid) = ''"
        )
    ).fetchall()
    for (scene_plan_id,) in missing_anchor:
        bind.execute(
            sa.text("UPDATE snowflake_scene_plans SET row_uid = :row_uid WHERE scene_plan_id = :pk"),
            {"row_uid": _mint_row_uid(), "pk": scene_plan_id},
        )

    # 2. Repair duplicate scene_id within a project: one row keeps the identifier,
    #    the others are re-minted from row_uid.
    #
    #    Which row keeps it matters, because a scene_cards row (possibly carrying
    #    finished prose) points at that scene_id.  There is no column linking a card
    #    back to a specific plan row — the card records only scene_id, and every row
    #    in a duplicate group has the *same* scene_id.  So "keep it on the row that is
    #    already materialized" cannot be answered by probing scene_cards for that
    #    scene_id: the probe's bind values are identical for every row in the group,
    #    it answers yes-for-all or no-for-all, and the keeper always collapses back to
    #    the first row.  (That is exactly what the earlier version of this block did,
    #    N redundant queries per group included.)
    #
    #    What the card *does* carry is a position: (chapter_id, scene_seq).  Prefer the
    #    plan row whose position matches the card's — that is a real discriminator and
    #    picks the row the card was materialized from whenever the position still
    #    agrees.  Fall back to the oldest row, which is the deterministic, explainable
    #    choice when nothing distinguishes them.
    duplicate_groups = bind.execute(
        sa.text(
            "SELECT project_id, scene_id FROM snowflake_scene_plans "
            "GROUP BY project_id, scene_id HAVING COUNT(*) > 1"
        )
    ).fetchall()
    for project_id, scene_id in duplicate_groups:
        rows = bind.execute(
            sa.text(
                "SELECT scene_plan_id, row_uid, chapter_id, scene_seq FROM snowflake_scene_plans "
                "WHERE project_id = :project_id AND scene_id = :scene_id "
                "ORDER BY created_at ASC, scene_plan_id ASC"
            ),
            {"project_id": project_id, "scene_id": scene_id},
        ).fetchall()
        card_position = None
        if has_scene_cards:
            # scene_cards.scene_id is the primary key, so this is at most one row.
            card_position = bind.execute(
                sa.text("SELECT chapter_id, scene_seq FROM scene_cards WHERE scene_id = :scene_id"),
                {"scene_id": scene_id},
            ).first()
        keeper = next(
            (
                pk
                for pk, _row_uid, chapter_id, scene_seq in rows
                if card_position is not None
                and chapter_id == card_position[0]
                and scene_seq == card_position[1]
            ),
            rows[0][0],
        )
        for pk, row_uid, _chapter_id, _scene_seq in rows:
            if pk == keeper:
                continue
            bind.execute(
                sa.text("UPDATE snowflake_scene_plans SET scene_id = :scene_id WHERE scene_plan_id = :pk"),
                {"scene_id": f"{project_id}_SC_{row_uid}", "pk": pk},
            )

    # 3. Re-mint scene_id for every remaining row that was never materialized, so a
    #    project that has not reached the catalog yet leaves this migration entirely
    #    on the new, chapter-independent scheme.
    unmaterialized = bind.execute(
        sa.text(
            "SELECT sp.scene_plan_id, sp.project_id, sp.row_uid FROM snowflake_scene_plans AS sp "
            "WHERE NOT EXISTS (SELECT 1 FROM scene_cards AS sc WHERE sc.scene_id = sp.scene_id)"
            if has_scene_cards
            else "SELECT scene_plan_id, project_id, row_uid FROM snowflake_scene_plans"
        )
    ).fetchall()
    for scene_plan_id, project_id, row_uid in unmaterialized:
        bind.execute(
            sa.text("UPDATE snowflake_scene_plans SET scene_id = :scene_id WHERE scene_plan_id = :pk"),
            {"scene_id": f"{project_id}_SC_{row_uid}", "pk": scene_plan_id},
        )

    # 4. Structural guarantee: a future collision is now an error, not a lost scene.
    remaining = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT 1 FROM snowflake_scene_plans "
            "GROUP BY project_id, scene_id HAVING COUNT(*) > 1)"
        )
    ).scalar()
    if remaining:
        raise RuntimeError(
            f"{remaining} duplicate (project_id, scene_id) group(s) remain in "
            "snowflake_scene_plans after repair; refusing to create the unique index. "
            "Inspect those rows by hand before retrying."
        )
    existing_indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("snowflake_scene_plans")}
    if _INDEX_NAME not in existing_indexes:
        op.create_index(_INDEX_NAME, "snowflake_scene_plans", ["project_id", "scene_id"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "snowflake_scene_plans" not in set(inspector.get_table_names()):
        return
    if _INDEX_NAME in {idx["name"] for idx in inspector.get_indexes("snowflake_scene_plans")}:
        op.drop_index(_INDEX_NAME, table_name="snowflake_scene_plans")
    existing_columns = {col["name"] for col in inspector.get_columns("snowflake_scene_plans")}
    with op.batch_alter_table("snowflake_scene_plans") as batch:
        for name, _type, _default in reversed(_NEW_COLUMNS):
            if name in existing_columns:
                batch.drop_column(name)
