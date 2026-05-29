"""style_reference_metric_events 表(style_reference v1.1, PR-10 §13 可观测性)

Revision ID: 20260524_0039
Revises: 20260523_0038
Create Date: 2026-05-24

PR-10 §13:落盘 InjectionService / qc gate / ValidationOrchestrator /
SceneAutoRewriteService 调用事件,供 MetricsAggregator SQL group by 聚合
出 4 个运营指标(injection 命中率 / qc gate 拒绝率 / auto_rewrite 通过率 /
validation P95 延迟)。

表为 append-only,无外键(profile / binding 可能后删,允许 dangling reference)。
2 个索引覆盖最常用的聚合维度:
- ix_sr_metric_events_kind_created (event_kind, created_at) 按事件类型 + 时间窗口聚合
- ix_sr_metric_events_profile_created (profile_id, created_at) 按 profile 维度聚合
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260524_0039"
down_revision = "20260523_0038"
branch_labels = None
depends_on = None


_TABLE = "style_reference_metric_events"
_INDEX_KIND = "ix_sr_metric_events_kind_created"
_INDEX_PROFILE = "ix_sr_metric_events_profile_created"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if _TABLE in tables:
        return

    op.create_table(
        _TABLE,
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("event_kind", sa.String(), nullable=False),
        sa.Column("target_kind", sa.String(), nullable=True),
        sa.Column("target_ref_id", sa.String(), nullable=True),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("binding_id", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index(_INDEX_KIND, _TABLE, ["event_kind", "created_at"])
    op.create_index(_INDEX_PROFILE, _TABLE, ["profile_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if _TABLE not in tables:
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)}
    if _INDEX_KIND in existing_indexes:
        op.drop_index(_INDEX_KIND, table_name=_TABLE)
    if _INDEX_PROFILE in existing_indexes:
        op.drop_index(_INDEX_PROFILE, table_name=_TABLE)
    op.drop_table(_TABLE)
