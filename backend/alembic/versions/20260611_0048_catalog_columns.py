"""catalog columns: chapter narrative/state/words_target/display_order,
scene state/words_current (FE-ALIGN Phase 3 目录统一)

Revision ID: 20260611_0048
Revises: 20260611_0047
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_0048"
down_revision = "20260611_0047"
branch_labels = None
depends_on = None

CHAPTER_COLUMNS = (
    ("narrative_json", sa.JSON(), None),
    ("state", sa.String(), "planned"),
    ("words_target", sa.Integer(), None),
    ("display_order", sa.Integer(), None),
)

SCENE_COLUMNS = (
    ("state", sa.String(), "todo"),
    ("words_current", sa.Integer(), "0"),
)


def upgrade() -> None:
    # 0001 init_schema 通过 Base.metadata.create_all 建当前全部模型表 — inspector 守卫；
    # 历史快照库可能尚无目标表（届时由 create_all 以完整列建表），表不存在则跳过。
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "chapter_goals" in tables:
        chapter_cols = {col["name"] for col in inspector.get_columns("chapter_goals")}
        for name, col_type, server_default in CHAPTER_COLUMNS:
            if name not in chapter_cols:
                op.add_column("chapter_goals", sa.Column(name, col_type, nullable=True, server_default=server_default))

    if "scene_cards" in tables:
        scene_cols = {col["name"] for col in inspector.get_columns("scene_cards")}
        for name, col_type, server_default in SCENE_COLUMNS:
            if name not in scene_cols:
                op.add_column("scene_cards", sa.Column(name, col_type, nullable=True, server_default=server_default))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "scene_cards" in tables:
        scene_cols = {col["name"] for col in inspector.get_columns("scene_cards")}
        for name, _t, _d in reversed(SCENE_COLUMNS):
            if name in scene_cols:
                op.drop_column("scene_cards", name)
    if "chapter_goals" in tables:
        chapter_cols = {col["name"] for col in inspector.get_columns("chapter_goals")}
        for name, _t, _d in reversed(CHAPTER_COLUMNS):
            if name in chapter_cols:
                op.drop_column("chapter_goals", name)
