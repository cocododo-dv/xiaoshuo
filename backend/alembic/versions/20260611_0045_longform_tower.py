"""longform tower anchors and chapter contracts (设计稿 lf6/lf7 塔台化 P0)

Revision ID: 20260611_0045
Revises: 20260611_0044
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_0045"
down_revision = "20260611_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 init_schema 通过 Base.metadata.create_all 建当前全部模型表,
    # 干净库从头走链时这两张表已存在——仓库惯例:inspector 守卫。
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "longform_anchors" in existing and "chapter_contracts" in existing:
        return

    op.create_table(
        "longform_anchors",
        sa.Column("anchor_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="fact"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pinned"),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_longform_anchors_project", "longform_anchors", ["project_id"])

    op.create_table(
        "chapter_contracts",
        sa.Column("contract_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="drafting"),
        sa.Column("constraints_json", sa.JSON(), nullable=True),
        sa.Column("dispatched_at", sa.String(), nullable=True),
        sa.Column("archived_at", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_chapter_contracts_project", "chapter_contracts", ["project_id", "chapter_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    if "chapter_contracts" in existing:
        indexes = {idx["name"] for idx in inspector.get_indexes("chapter_contracts")}
        if "ix_chapter_contracts_project" in indexes:
            op.drop_index("ix_chapter_contracts_project", table_name="chapter_contracts")
        op.drop_table("chapter_contracts")
    if "longform_anchors" in existing:
        indexes = {idx["name"] for idx in inspector.get_indexes("longform_anchors")}
        if "ix_longform_anchors_project" in indexes:
            op.drop_index("ix_longform_anchors_project", table_name="longform_anchors")
        op.drop_table("longform_anchors")
