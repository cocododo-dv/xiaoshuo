"""Wave 3 运行策略与场景 token 预算（结果闭环治理 §5.5/§6.1）

scene_run_states 加三列：
- run_policy：本次运行的生效策略（reliable|strict|auto），Wave 2 为请求级，本 Wave 落列
- scene_token_budget：场景 token 预算（5 × 单发基线，§4.6）
- scene_tokens_used：场景生命周期累计消耗（自动流程不得重置，§7.12）

加列带存在性守卫（仓库惯例，同 0061）：初始迁移 0001 是
``Base.metadata.create_all``，新库跑迁移链时表已含本列。

Revision ID: 20260711_0062
Revises: 20260711_0061
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "20260711_0062"
down_revision = "20260711_0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("scene_run_states"):
        return
    srs_cols = {col["name"] for col in inspector.get_columns("scene_run_states")}
    if "run_policy" not in srs_cols:
        op.add_column("scene_run_states", sa.Column("run_policy", sa.String(), nullable=True))
    if "scene_token_budget" not in srs_cols:
        op.add_column("scene_run_states", sa.Column("scene_token_budget", sa.Integer(), nullable=True))
    if "scene_tokens_used" not in srs_cols:
        op.add_column(
            "scene_run_states",
            sa.Column("scene_tokens_used", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("scene_run_states"):
        return
    srs_cols = {col["name"] for col in inspector.get_columns("scene_run_states")}
    with op.batch_alter_table("scene_run_states") as batch:
        if "scene_tokens_used" in srs_cols:
            batch.drop_column("scene_tokens_used")
        if "scene_token_budget" in srs_cols:
            batch.drop_column("scene_token_budget")
        if "run_policy" in srs_cols:
            batch.drop_column("run_policy")
