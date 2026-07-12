"""Wave 7 存量孤儿修复（结果闭环治理 §8 Wave 7 项 4 / §11 规则 10）

SQLite 未启用 foreign_keys，历史手工级联可能遗留孤儿（child.fk 指向已删 parent）。
本迁移**幂等删除**孤儿（FK-reverse 序，先删叶子），是「启用 SQLite foreign keys」前的
盘点+修复前置。盘点工具见 `novel_system/tools/orphan_inventory.py`。

纯数据迁移（无 DDL）→ 不改 schema，tests/test_metadata_isolation.py 漂移守卫不受影响。
关系列表为**本迁移自持的冻结快照**（迁移不依赖会演化的项目代码）。缺表/缺列跳过（渐进）。

downgrade 是 no-op：删除的孤儿本就无效引用，无法也无需回填。

Revision ID: 20260712_0064
Revises: 20260712_0063
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "20260712_0064"
down_revision = "20260712_0063"
branch_labels = None
depends_on = None

# (child_table, child_fk, parent_table, parent_pk) —— FK-reverse（子在前）冻结快照
_ORPHAN_RELATIONS = (
    ("style_reference_finding_feedback", "finding_id", "style_reference_findings", "finding_id"),
    ("style_reference_evidences", "finding_id", "style_reference_findings", "finding_id"),
    ("style_reference_banned_terms", "profile_id", "style_reference_profiles", "profile_id"),
    ("style_reference_injection_bindings", "profile_id", "style_reference_profiles", "profile_id"),
    ("style_reference_validation_reports", "profile_id", "style_reference_profiles", "profile_id"),
    ("style_reference_findings", "book_id", "style_reference_books", "book_id"),
    ("style_reference_profiles", "book_id", "style_reference_books", "book_id"),
    ("style_reference_extractions", "book_id", "style_reference_books", "book_id"),
    ("style_reference_quotes", "book_id", "style_reference_books", "book_id"),
    ("style_reference_runs", "book_id", "style_reference_books", "book_id"),
    ("style_reference_paragraphs", "book_id", "style_reference_books", "book_id"),
    # 仅 FK-约束关系：scene_drafts/final_scenes/qc_reports.scene_id 是裸 String（非 FK）
    # 审计/历史行，故意不纳入（§11.10 只为启用 FK 清障，不删无约束历史行）。
    ("scene_run_states", "scene_id", "scene_cards", "scene_id"),
    ("scene_cards", "chapter_id", "chapter_goals", "chapter_id"),
)


def purge_orphans(bind) -> dict[str, int]:
    """幂等删除孤儿；返回 {child_table: 删除行数}。缺表/缺列跳过。"""
    inspector = sa.inspect(bind)
    counts: dict[str, int] = {}
    for child, fk, parent, ppk in _ORPHAN_RELATIONS:
        try:
            if not inspector.has_table(child) or not inspector.has_table(parent):
                continue
            child_cols = {c["name"] for c in inspector.get_columns(child)}
            parent_cols = {c["name"] for c in inspector.get_columns(parent)}
            if fk not in child_cols or ppk not in parent_cols:
                continue
            result = bind.execute(
                text(
                    f"DELETE FROM {child} WHERE {fk} IS NOT NULL "
                    f"AND {fk} NOT IN (SELECT {ppk} FROM {parent})"
                )
            )
            if result.rowcount:
                counts[child] = counts.get(child, 0) + int(result.rowcount)
        except Exception:  # 单关系失败不阻断整迁移（尽力修复）
            continue
    return counts


def upgrade() -> None:
    purge_orphans(op.get_bind())


def downgrade() -> None:
    # 无法回填被删除的无效引用；no-op。
    pass
