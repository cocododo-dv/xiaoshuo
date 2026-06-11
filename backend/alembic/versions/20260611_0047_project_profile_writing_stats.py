"""project profile fields + per-project writing stats (FE-ALIGN Phase 2)

Revision ID: 20260611_0047
Revises: 20260611_0046
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_0047"
down_revision = "20260611_0046"
branch_labels = None
depends_on = None

PROFILE_COLUMNS = (
    ("mark", sa.String(), None),
    ("accent", sa.String(), None),
    ("synopsis_line", sa.Text(), None),
    ("words_target_daily", sa.Integer(), None),
    ("is_demo", sa.Integer(), "0"),
)


def upgrade() -> None:
    # 0001 init_schema 通过 Base.metadata.create_all 建当前全部模型表 — inspector 守卫。
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_cols = {col["name"] for col in inspector.get_columns("story_projects")}
    for name, col_type, server_default in PROFILE_COLUMNS:
        if name in existing_cols:
            continue
        op.add_column(
            "story_projects",
            sa.Column(name, col_type, nullable=True, server_default=server_default),
        )

    if "project_writing_stats" not in set(inspector.get_table_names()):
        op.create_table(
            "project_writing_stats",
            sa.Column(
                "project_id",
                sa.String(),
                sa.ForeignKey("story_projects.project_id"),
                primary_key=True,
            ),
            sa.Column("words_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("day", sa.String(), nullable=True),
            sa.Column("words_today", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("streak_last_day", sa.String(), nullable=True),
            sa.Column("streak_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_active_at", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "project_writing_stats" in set(inspector.get_table_names()):
        op.drop_table("project_writing_stats")
    existing_cols = {col["name"] for col in inspector.get_columns("story_projects")}
    for name, _col_type, _default in reversed(PROFILE_COLUMNS):
        if name in existing_cols:
            op.drop_column("story_projects", name)
