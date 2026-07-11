"""Wave 1 正文真值统一（结果闭环治理 §5.2/§6.1）

1. scene_run_states 加 latest_valid_draft_row_id——最近有效正文指针，
   与 current_* 不同，失败/重写路径不清空（§4.3 永远保留最近有效正文）。
2. 归档状态词表统一：历史上被 scene_status='archived' 的运行态指向的
   final_scenes 行仍是建行时的 'approved'/'near_final_ready'——迁移映射为
   权威归档态 'archived'（此后归档事务由 Archiver 统一写入该状态）。

加列带存在性守卫（仓库惯例，同 0059）：初始迁移 0001 是
``Base.metadata.create_all``，新库跑迁移链时表已含本列。

Revision ID: 20260711_0061
Revises: 20260702_0060
Create Date: 2026-07-11
"""
from alembic import op
import sqlalchemy as sa

revision = "20260711_0061"
down_revision = "20260702_0060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("scene_run_states"):
        srs_cols = {col["name"] for col in inspector.get_columns("scene_run_states")}
        if "latest_valid_draft_row_id" not in srs_cols:
            op.add_column(
                "scene_run_states",
                sa.Column("latest_valid_draft_row_id", sa.String(), nullable=True),
            )

    # 历史归档行的状态映射：只覆盖被已归档运行态指向的行，其余保持原状
    if inspector.has_table("final_scenes") and inspector.has_table("scene_run_states"):
        op.execute(
            """
            UPDATE final_scenes
            SET status = 'archived'
            WHERE row_id IN (
                SELECT current_final_scene_row_id
                FROM scene_run_states
                WHERE scene_status = 'archived'
                  AND current_final_scene_row_id IS NOT NULL
            )
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 状态映射不可精确回退（原值 approved/near_final_ready 已不可区分），
    # 统一回落到模型默认值 approved
    if inspector.has_table("final_scenes"):
        op.execute("UPDATE final_scenes SET status = 'approved' WHERE status = 'archived'")
    if inspector.has_table("scene_run_states"):
        srs_cols = {col["name"] for col in inspector.get_columns("scene_run_states")}
        if "latest_valid_draft_row_id" in srs_cols:
            op.drop_column("scene_run_states", "latest_valid_draft_row_id")
