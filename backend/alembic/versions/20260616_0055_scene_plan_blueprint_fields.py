"""scene plan blueprint fields: tension_target, function_tag, involved_foreshadowing

Revision ID: 20260616_0055
Revises: 20260616_0054
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "20260616_0055"
down_revision = "20260616_0054"
branch_labels = None
depends_on = None

_TABLE = "snowflake_scene_plans"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col["name"] for col in inspector.get_columns(_TABLE)}

    if "tension_target" not in existing_cols:
        op.add_column(_TABLE, sa.Column("tension_target", sa.Integer(), nullable=True))
    if "function_tag" not in existing_cols:
        op.add_column(_TABLE, sa.Column("function_tag", sa.String(), nullable=True))
    if "involved_foreshadowing_json" not in existing_cols:
        op.add_column(
            _TABLE,
            sa.Column("involved_foreshadowing_json", sa.JSON(), nullable=True, server_default="[]"),
        )


def downgrade() -> None:
    op.drop_column(_TABLE, "involved_foreshadowing_json")
    op.drop_column(_TABLE, "function_tag")
    op.drop_column(_TABLE, "tension_target")
