"""project-level soft delete columns (FE-ALIGN Phase 4 回收站)

Revision ID: 20260611_0049
Revises: 20260611_0048
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_0049"
down_revision = "20260611_0048"
branch_labels = None
depends_on = None

COLUMNS = (
    ("trashed_flag", sa.Integer(), "0"),
    ("trashed_at", sa.String(), None),
    ("trashed_by", sa.String(), None),
)


def upgrade() -> None:
    # inspector 守卫：历史快照库可能尚无 story_projects（届时 create_all 以完整列建表）。
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "story_projects" not in set(inspector.get_table_names()):
        return
    existing = {col["name"] for col in inspector.get_columns("story_projects")}
    for name, col_type, server_default in COLUMNS:
        if name not in existing:
            op.add_column("story_projects", sa.Column(name, col_type, nullable=True, server_default=server_default))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "story_projects" not in set(inspector.get_table_names()):
        return
    existing = {col["name"] for col in inspector.get_columns("story_projects")}
    for name, _t, _d in reversed(COLUMNS):
        if name in existing:
            op.drop_column("story_projects", name)
