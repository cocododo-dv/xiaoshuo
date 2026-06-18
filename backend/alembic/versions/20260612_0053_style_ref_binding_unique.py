"""style_reference binding 目标唯一约束(防并发 apply 重复绑定)

先按 (profile_id, scope, scope_ref_id, task_type) 去重(保留 created_at 最早
一行),再以 SQLite batch 模式重建表加 UNIQUE 约束。

Revision ID: 20260612_0053
Revises: 20260612_0052
Create Date: 2026-06-12
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260612_0053"
down_revision = "20260612_0052"
branch_labels = None
depends_on = None

TABLE = "style_reference_injection_bindings"
CONSTRAINT = "uq_style_reference_injection_bindings_target"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_unique_constraints(TABLE)}
    if CONSTRAINT in existing:
        return

    # 1. 去重:同目标保留 created_at(决平 binding_id)最小的一行
    bind.execute(
        sa.text(
            f"""
            DELETE FROM {TABLE}
            WHERE binding_id NOT IN (
                SELECT binding_id FROM (
                    SELECT binding_id,
                           ROW_NUMBER() OVER (
                               PARTITION BY profile_id, scope,
                                            COALESCE(scope_ref_id, ''), task_type
                               ORDER BY created_at, binding_id
                           ) AS rn
                    FROM {TABLE}
                ) ranked
                WHERE rn = 1
            )
            """
        )
    )

    # 2. batch 模式重建表加 UNIQUE(SQLite 不支持 ALTER ADD CONSTRAINT)
    with op.batch_alter_table(TABLE) as batch:
        batch.create_unique_constraint(
            CONSTRAINT,
            ["profile_id", "scope", "scope_ref_id", "task_type"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return
    existing = {c["name"] for c in inspector.get_unique_constraints(TABLE)}
    if CONSTRAINT not in existing:
        return
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(CONSTRAINT, type_="unique")
