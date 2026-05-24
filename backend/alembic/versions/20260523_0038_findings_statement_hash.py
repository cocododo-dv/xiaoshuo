"""findings statement_hash + UNIQUE 4 列复合(style_reference v1.1, PR-3 hotfix)

Revision ID: 20260523_0038
Revises: 20260523_0037
Create Date: 2026-05-23

PR-3 启动前置 hotfix:
- v1.1 §4.2 落地的 UNIQUE(extraction_id, sub_dim, finding_kind) 与 §6.5 prompt 输出
  schema(observations 0-8 条 / forbidden_patterns 0-3 条)矛盾。
- 按全局纪律 A 以代码事实为准:加 statement_hash 列 + UNIQUE 改 4 列复合。
- 详见 plans/style-reference-v1-1-fancy-shannon.md §"v1.2 文档修订清单 #8"。

注:PR-1 0036 已经 drop 旧 reference_* 表;style_reference_findings 在生产 db
当前为空,直接 add column + 改 constraint 即可,无需 backfill。
"""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "20260523_0038"
down_revision = "20260523_0037"
branch_labels = None
depends_on = None


_OLD_UQ = "uq_style_reference_findings_extract_sub_kind"
_NEW_UQ = "uq_style_reference_findings_extract_sub_kind_hash"


def _compute_hash(statement: str) -> str:
    return hashlib.sha256(statement.strip().encode("utf-8")).hexdigest()[:16]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("style_reference_findings")}

    if "statement_hash" not in columns:
        op.add_column(
            "style_reference_findings",
            sa.Column("statement_hash", sa.String(), nullable=True),
        )

    # backfill 存量行(若有):用 statement 列重新计算
    rows = bind.execute(
        sa.text(
            "SELECT finding_id, statement FROM style_reference_findings "
            "WHERE statement_hash IS NULL OR statement_hash = ''"
        )
    ).fetchall()
    for row in rows:
        bind.execute(
            sa.text(
                "UPDATE style_reference_findings SET statement_hash = :h "
                "WHERE finding_id = :fid"
            ),
            {"h": _compute_hash(row.statement or ""), "fid": row.finding_id},
        )

    # 改 UNIQUE 约束:drop 旧 3 列 → create 新 4 列复合;NOT NULL alter column
    # SQLite 不支持 ALTER 直接改约束,统一走 batch_alter_table
    existing_uniques = {
        uc.get("name") for uc in inspector.get_unique_constraints("style_reference_findings")
    }
    has_old_uq = _OLD_UQ in existing_uniques
    with op.batch_alter_table("style_reference_findings", recreate="always") as batch_op:
        if has_old_uq:
            batch_op.drop_constraint(_OLD_UQ, type_="unique")
        batch_op.create_unique_constraint(
            _NEW_UQ,
            ["extraction_id", "sub_dimension", "finding_kind", "statement_hash"],
        )
        batch_op.alter_column("statement_hash", existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("style_reference_findings")}
    existing_uniques = {
        uc.get("name") for uc in inspector.get_unique_constraints("style_reference_findings")
    }
    has_new_uq = _NEW_UQ in existing_uniques

    with op.batch_alter_table("style_reference_findings", recreate="always") as batch_op:
        if has_new_uq:
            batch_op.drop_constraint(_NEW_UQ, type_="unique")
        batch_op.create_unique_constraint(
            _OLD_UQ,
            ["extraction_id", "sub_dimension", "finding_kind"],
        )
        if "statement_hash" in columns:
            batch_op.drop_column("statement_hash")
