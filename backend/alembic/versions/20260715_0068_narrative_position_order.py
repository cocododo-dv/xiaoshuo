"""Canonical cross-chapter narrative-position indexes and legacy repair.

Revision ID: 20260715_0068
Revises: 20260715_0067
Create Date: 2026-07-15
"""
from __future__ import annotations

from collections import defaultdict

import sqlalchemy as sa
from alembic import op


revision = "20260715_0068"
down_revision = "20260715_0067"
branch_labels = None
depends_on = None


_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    (
        "ix_chapter_goals_project_display_order",
        "chapter_goals",
        ["project_id", "display_order", "chapter_id"],
    ),
    (
        "ix_scene_cards_project_chapter_seq",
        "scene_cards",
        ["project_id", "chapter_id", "scene_seq", "scene_id"],
    ),
    (
        "ix_narrative_events_project_chapter_scene",
        "narrative_events",
        ["project_id", "chapter_id", "scene_id"],
    ),
    (
        "ix_narrative_events_project_entity_scene",
        "narrative_events",
        ["project_id", "entity_id", "scene_id"],
    ),
)


def _repair_legacy_positions(bind) -> None:
    inspector = sa.inspect(bind)
    required = {"chapter_goals", "scene_cards", "narrative_events"}
    if not required.issubset(set(inspector.get_table_names())):
        return

    # Scene project ownership is derivable from its chapter and is required by
    # project-wide ordered-scene queries.  Only fill an absent value.
    bind.execute(sa.text(
        """
        UPDATE scene_cards
        SET project_id = (
            SELECT chapter_goals.project_id
            FROM chapter_goals
            WHERE chapter_goals.chapter_id = scene_cards.chapter_id
        )
        WHERE project_id IS NULL
          AND EXISTS (
            SELECT 1 FROM chapter_goals
            WHERE chapter_goals.chapter_id = scene_cards.chapter_id
              AND chapter_goals.project_id IS NOT NULL
          )
        """
    ))

    # Conversely, fill an unowned chapter only when all of its owned scenes
    # point to exactly one project.  Ambiguous rows are intentionally untouched.
    bind.execute(sa.text(
        """
        UPDATE chapter_goals
        SET project_id = (
            SELECT MIN(scene_cards.project_id)
            FROM scene_cards
            WHERE scene_cards.chapter_id = chapter_goals.chapter_id
              AND scene_cards.project_id IS NOT NULL
        )
        WHERE project_id IS NULL
          AND 1 = (
            SELECT COUNT(DISTINCT scene_cards.project_id)
            FROM scene_cards
            WHERE scene_cards.chapter_id = chapter_goals.chapter_id
              AND scene_cards.project_id IS NOT NULL
          )
        """
    ))

    # Append NULL chapter orders deterministically after the highest explicit
    # order.  Existing non-NULL author order is never rewritten.
    rows = list(bind.execute(sa.text(
        """
        SELECT chapter_id, project_id, display_order
        FROM chapter_goals
        WHERE project_id IS NOT NULL
        ORDER BY project_id, chapter_id
        """
    )).mappings())
    by_project: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_project[str(row["project_id"])].append(dict(row))
    for project_rows in by_project.values():
        next_order = max(
            (int(row["display_order"]) for row in project_rows if row["display_order"] is not None),
            default=0,
        )
        for row in sorted(
            (row for row in project_rows if row["display_order"] is None),
            key=lambda item: str(item["chapter_id"]),
        ):
            next_order += 1
            bind.execute(
                sa.text(
                    "UPDATE chapter_goals SET display_order = :display_order "
                    "WHERE chapter_id = :chapter_id AND display_order IS NULL"
                ),
                {"display_order": next_order, "chapter_id": row["chapter_id"]},
            )

    # The append-only event row keeps scene_seq only as a compatibility snapshot.
    # Refresh it after any historical catalog reorder; runtime replay joins the
    # current SceneCard/ChapterGoal position and does not trust this cache.
    bind.execute(sa.text(
        """
        UPDATE narrative_events
        SET scene_seq = (
            SELECT scene_cards.scene_seq
            FROM scene_cards
            WHERE scene_cards.scene_id = narrative_events.scene_id
        )
        WHERE EXISTS (
            SELECT 1 FROM scene_cards
            WHERE scene_cards.scene_id = narrative_events.scene_id
        )
        """
    ))

    invalid_count = int(bind.execute(sa.text(
        """
        SELECT COUNT(*)
        FROM narrative_events AS ne
        LEFT JOIN scene_cards AS sc ON sc.scene_id = ne.scene_id
        LEFT JOIN chapter_goals AS cg ON cg.chapter_id = sc.chapter_id
        WHERE sc.scene_id IS NULL
           OR cg.chapter_id IS NULL
           OR ne.chapter_id <> sc.chapter_id
           OR (sc.project_id IS NOT NULL AND ne.project_id <> sc.project_id)
           OR (cg.project_id IS NOT NULL AND ne.project_id <> cg.project_id)
        """
    )).scalar_one())
    if invalid_count:
        raise RuntimeError(
            "NARRATIVE_EVENT_POSITION_INVALID: "
            f"{invalid_count} event row(s) disagree with their scene/chapter/project"
        )


def upgrade() -> None:
    bind = op.get_bind()
    _repair_legacy_positions(bind)
    inspector = sa.inspect(bind)
    for index_name, table_name, columns in _INDEXES:
        if not inspector.has_table(table_name):
            continue
        existing = {str(index["name"]) for index in inspector.get_indexes(table_name)}
        if index_name not in existing:
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for index_name, table_name, _columns in reversed(_INDEXES):
        if not inspector.has_table(table_name):
            continue
        existing = {str(index["name"]) for index in inspector.get_indexes(table_name)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table_name)

