"""timeline events table (FE-ALIGN Phase 6 资料库时间线)

Revision ID: 20260611_0051
Revises: 20260611_0050
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260611_0051"
down_revision = "20260611_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "timeline_events" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "timeline_events",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("story_projects.project_id"), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("time_label", sa.String(), nullable=True),
        sa.Column("chapter_ref", sa.String(), nullable=True),
        sa.Column("entity_refs_json", sa.JSON(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_index("ix_timeline_events_project", "timeline_events", ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "timeline_events" in set(inspector.get_table_names()):
        indexes = {idx["name"] for idx in inspector.get_indexes("timeline_events")}
        if "ix_timeline_events_project" in indexes:
            op.drop_index("ix_timeline_events_project", table_name="timeline_events")
        op.drop_table("timeline_events")
