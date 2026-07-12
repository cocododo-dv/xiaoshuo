"""Wave 5 质量实验通道：匿名 A/B 人类盲评三张表（结果闭环治理 §6.2）

新增 evaluation_experiments / evaluation_pairs / evaluation_votes。实验通道不写
FinalScene，只写实验产物（§5.1）。建表带 has_table 存在性守卫（仓库惯例：初始迁移
0001 是 Base.metadata.create_all，新库跑迁移链时表可能已存在）。

命名索引与 ORM `index=True` 自动名保持一致，保 tests/test_metadata_isolation.py 漂移守卫通过：
- ix_evaluation_pairs_experiment_id / ix_evaluation_pairs_scene_snapshot_hash
- ix_evaluation_votes_pair_id

Revision ID: 20260712_0063
Revises: 20260711_0062
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260712_0063"
down_revision = "20260711_0062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("evaluation_experiments"):
        op.create_table(
            "evaluation_experiments",
            sa.Column("experiment_id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("hypothesis", sa.String(), nullable=False, server_default=""),
            sa.Column("treatment_policy_json", sa.JSON(), nullable=True),
            sa.Column("control_policy_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="collecting"),
            sa.Column("isolation_mode", sa.String(), nullable=True),
            sa.Column("snapshot_source_ref", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=True),
        )

    if not inspector.has_table("evaluation_pairs"):
        op.create_table(
            "evaluation_pairs",
            sa.Column("pair_id", sa.String(), primary_key=True),
            sa.Column("experiment_id", sa.String(), nullable=False),
            sa.Column("scene_snapshot_hash", sa.String(), nullable=False),
            sa.Column("left_artifact_ref", sa.String(), nullable=True),
            sa.Column("right_artifact_ref", sa.String(), nullable=True),
            sa.Column("left_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("right_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("blind_mapping_json", sa.JSON(), nullable=True),
            sa.Column("token_cost_json", sa.JSON(), nullable=True),
            sa.Column("no_contrast", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.String(), nullable=True),
        )
        op.create_index("ix_evaluation_pairs_experiment_id", "evaluation_pairs", ["experiment_id"])
        op.create_index("ix_evaluation_pairs_scene_snapshot_hash", "evaluation_pairs", ["scene_snapshot_hash"])

    if not inspector.has_table("evaluation_votes"):
        op.create_table(
            "evaluation_votes",
            sa.Column("vote_id", sa.String(), primary_key=True),
            sa.Column("pair_id", sa.String(), nullable=False),
            sa.Column("choice", sa.String(), nullable=False),
            sa.Column("reviewer_ref", sa.String(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=True),
        )
        op.create_index("ix_evaluation_votes_pair_id", "evaluation_votes", ["pair_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("evaluation_votes"):
        op.drop_table("evaluation_votes")
    if inspector.has_table("evaluation_pairs"):
        op.drop_table("evaluation_pairs")
    if inspector.has_table("evaluation_experiments"):
        op.drop_table("evaluation_experiments")
