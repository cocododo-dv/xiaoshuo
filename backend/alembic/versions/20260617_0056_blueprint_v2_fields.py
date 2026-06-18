"""blueprint v2 fields: scene plan causal/cost + foreshadow lifecycle

Revision ID: 20260617_0056
Revises: 20260616_0055
Create Date: 2026-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = "20260617_0056"
down_revision = "20260616_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # --- SnowflakeScenePlan: causal prerequisite, cost requirement, downstream obligations ---
    sp_cols = {col["name"] for col in inspector.get_columns("snowflake_scene_plans")}
    if "causal_prerequisite_scene_id" not in sp_cols:
        op.add_column("snowflake_scene_plans", sa.Column("causal_prerequisite_scene_id", sa.String(), nullable=True))
    if "cost_requirement" not in sp_cols:
        op.add_column("snowflake_scene_plans", sa.Column("cost_requirement", sa.Text(), nullable=True))
    if "downstream_obligations_json" not in sp_cols:
        op.add_column(
            "snowflake_scene_plans",
            sa.Column("downstream_obligations_json", sa.JSON(), nullable=True, server_default="[]"),
        )

    # --- ForeshadowTracker: theme, reinforcement plan, plant/payoff methods ---
    if not inspector.has_table("foreshadow_tracker"):
        return
    ft_cols = {col["name"] for col in inspector.get_columns("foreshadow_tracker")}
    if "theme_tag" not in ft_cols:
        op.add_column("foreshadow_tracker", sa.Column("theme_tag", sa.String(), nullable=True))
    if "reinforce_plan_json" not in ft_cols:
        op.add_column(
            "foreshadow_tracker",
            sa.Column("reinforce_plan_json", sa.JSON(), nullable=True, server_default="[]"),
        )
    if "plant_method" not in ft_cols:
        op.add_column("foreshadow_tracker", sa.Column("plant_method", sa.Text(), nullable=True))
    if "payoff_method" not in ft_cols:
        op.add_column("foreshadow_tracker", sa.Column("payoff_method", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("foreshadow_tracker"):
        op.drop_column("foreshadow_tracker", "payoff_method")
        op.drop_column("foreshadow_tracker", "plant_method")
        op.drop_column("foreshadow_tracker", "reinforce_plan_json")
        op.drop_column("foreshadow_tracker", "theme_tag")
    op.drop_column("snowflake_scene_plans", "downstream_obligations_json")
    op.drop_column("snowflake_scene_plans", "cost_requirement")
    op.drop_column("snowflake_scene_plans", "causal_prerequisite_scene_id")
