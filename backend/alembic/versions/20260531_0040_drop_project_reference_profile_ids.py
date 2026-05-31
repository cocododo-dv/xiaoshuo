"""drop story_projects.reference_profile_ids_json

Revision ID: 20260531_0040
Revises: 20260524_0039
Create Date: 2026-05-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260531_0040"
down_revision = "20260524_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "story_projects" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("story_projects")}
    if "reference_profile_ids_json" not in columns:
        return

    with op.batch_alter_table("story_projects", recreate="always") as batch_op:
        batch_op.drop_column("reference_profile_ids_json")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "story_projects" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("story_projects")}
    if "reference_profile_ids_json" in columns:
        return

    with op.batch_alter_table("story_projects", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column(
                "reference_profile_ids_json",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'[]'"),
            )
        )
