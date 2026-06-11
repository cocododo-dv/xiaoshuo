"""library entities and relations (设计稿 ws-library 后端 P0)

Revision ID: 20260611_0044
Revises: 20260606_0043
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_0044"
down_revision = "20260606_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 init_schema 通过 Base.metadata.create_all 建当前全部模型表,
    # 干净库从头走链时这两张表已存在——仓库惯例:inspector 守卫。
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "library_entities" in existing and "library_relations" in existing:
        return

    op.create_table(
        "library_entities",
        sa.Column("entity_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="concept"),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("aliases_json", sa.JSON(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("tags_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_library_entities_project", "library_entities", ["project_id"])

    op.create_table(
        "library_relations",
        sa.Column("relation_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
        sa.Column("from_ref", sa.String(), nullable=False),
        sa.Column("to_ref", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="related"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_library_relations_project", "library_relations", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    if "library_relations" in existing:
        indexes = {idx["name"] for idx in inspector.get_indexes("library_relations")}
        if "ix_library_relations_project" in indexes:
            op.drop_index("ix_library_relations_project", table_name="library_relations")
        op.drop_table("library_relations")
    if "library_entities" in existing:
        indexes = {idx["name"] for idx in inspector.get_indexes("library_entities")}
        if "ix_library_entities_project" in indexes:
            op.drop_index("ix_library_entities_project", table_name="library_entities")
        op.drop_table("library_entities")
