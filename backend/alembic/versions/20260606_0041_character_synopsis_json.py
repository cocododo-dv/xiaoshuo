"""add story_characters.synopsis_json

Revision ID: 20260606_0041
Revises: 20260531_0040
Create Date: 2026-06-06

P0-4: the snowflake character pipeline (摘要 / 背景故事 / 全档案) collapses onto a
single authoritative StoryCharacter entity. This column persists the
``character_synopses`` (背景故事) layer, which previously had nowhere to live and
was silently dropped by ``_sync_characters``.

Idempotent + SQLite-batch-safe, matching the project's existing migration style.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260606_0041"
down_revision = "20260531_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "story_characters" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("story_characters")}
    if "synopsis_json" in columns:
        return

    with op.batch_alter_table("story_characters", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("synopsis_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "story_characters" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("story_characters")}
    if "synopsis_json" not in columns:
        return

    with op.batch_alter_table("story_characters", recreate="always") as batch_op:
        batch_op.drop_column("synopsis_json")
