"""narrative_events: append-only event sourcing log for story state

Revision ID: 20260616_0054
Revises: 20260612_0053
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "20260616_0054"
down_revision = "20260612_0053"
branch_labels = None
depends_on = None

_TABLE = "narrative_events"


def upgrade() -> None:
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if _TABLE not in tables:
        op.create_table(
            _TABLE,
            sa.Column("event_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("scene_id", sa.String(), nullable=False),
            sa.Column("chapter_id", sa.String(), nullable=False),
            sa.Column("scene_seq", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("entity_id", sa.String(), nullable=False),
            sa.Column("fact_key", sa.String(), nullable=False),
            sa.Column("fact_value", sa.String(), nullable=False),
            sa.Column("confidence", sa.String(), nullable=False, server_default="high"),
            sa.Column("causal_predecessor_id", sa.String(), nullable=True),
            sa.Column("source_text_excerpt", sa.String(), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.String(), nullable=False),
        )
    existing_indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes(_TABLE)}
    for idx_name, columns in [
        ("ix_narrative_events_entity_scene", ["entity_id", "scene_seq"]),
        ("ix_narrative_events_project_scene", ["project_id", "scene_seq"]),
        ("ix_narrative_events_event_type", ["event_type"]),
        ("ix_narrative_events_scene_id", ["scene_id"]),
        ("ix_narrative_events_chapter_id", ["chapter_id"]),
        ("ix_narrative_events_entity_id", ["entity_id"]),
        ("ix_narrative_events_project_id", ["project_id"]),
    ]:
        if idx_name not in existing_indexes:
            op.create_index(idx_name, _TABLE, columns)


def downgrade() -> None:
    op.drop_table(_TABLE)
