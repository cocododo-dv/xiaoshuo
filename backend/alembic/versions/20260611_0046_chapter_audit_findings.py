"""chapter audit findings (控制塔章级审计 — 守门归档)

Revision ID: 20260611_0046
Revises: 20260611_0045
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_0046"
down_revision = "20260611_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001 init_schema 通过 Base.metadata.create_all 建当前全部模型表 — inspector 守卫。
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "chapter_audit_findings" in existing:
        return

    op.create_table(
        "chapter_audit_findings",
        sa.Column("finding_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
        sa.Column("chapter_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="drift"),
        sa.Column("severity", sa.String(), nullable=False, server_default="warn"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_chapter_audit_project_chapter", "chapter_audit_findings", ["project_id", "chapter_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "chapter_audit_findings" in set(inspector.get_table_names()):
        indexes = {idx["name"] for idx in inspector.get_indexes("chapter_audit_findings")}
        if "ix_chapter_audit_project_chapter" in indexes:
            op.drop_index("ix_chapter_audit_project_chapter", table_name="chapter_audit_findings")
        op.drop_table("chapter_audit_findings")
