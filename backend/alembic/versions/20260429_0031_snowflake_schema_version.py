"""add snowflake schema version to story projects

Revision ID: 20260429_0031
Revises: 20260428_0030
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260429_0031"
down_revision = "20260428_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "story_projects" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("story_projects")}
    if "snowflake_schema_version" not in columns:
        with op.batch_alter_table("story_projects") as batch_op:
            batch_op.add_column(sa.Column("snowflake_schema_version", sa.String(), nullable=True))
    op.execute(
        "UPDATE story_projects "
        "SET snowflake_schema_version = '2026-04-28.v1' "
        "WHERE planning_mode = 'snowflake' AND snowflake_schema_version IS NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "story_projects" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("story_projects")}
    if "snowflake_schema_version" in columns:
        with op.batch_alter_table("story_projects") as batch_op:
            batch_op.drop_column("snowflake_schema_version")
