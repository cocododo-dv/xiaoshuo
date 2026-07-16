"""遗留关系孤儿诊断器（只读，不能单独作为发布门）。

应用连接现在默认强制 ``PRAGMA foreign_keys=ON``；完整发布判定必须使用
``novel_system.tools.database_preflight``，历史隔离处置使用
``novel_system.tools.orphan_quarantine``。本模块保留给 0064 迁移及旧关系清单的
兼容诊断，但任何缺表、缺列或 SQL 失败都会 fail-closed，绝不再把未完成扫描
报告成 ``clean=true``。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from novel_system.db.session import SessionLocal


class OrphanInventoryIncomplete(RuntimeError):
    """A registered legacy relation could not be audited completely."""


@dataclass(frozen=True, slots=True)
class OrphanRelation:
    child_table: str
    child_pk: str
    child_fk: str
    parent_table: str
    parent_pk: str


# 父→子关系登记（child.fk 非空却指向不存在的 parent.pk = 孤儿）。
# 顺序为 FK-reverse（子在前）——修复删除按此序，先删叶子避免二次孤儿。
ORPHAN_RELATIONS: tuple[OrphanRelation, ...] = (
    # —— style_reference 派生表族（cleanup.purge_derived_data 的手工级联对象）——
    OrphanRelation("style_reference_finding_feedback", "feedback_id", "finding_id",
                   "style_reference_findings", "finding_id"),
    OrphanRelation("style_reference_evidences", "evidence_id", "finding_id",
                   "style_reference_findings", "finding_id"),
    OrphanRelation("style_reference_banned_terms", "term_id", "profile_id",
                   "style_reference_profiles", "profile_id"),
    OrphanRelation("style_reference_injection_bindings", "binding_id", "profile_id",
                   "style_reference_profiles", "profile_id"),
    OrphanRelation("style_reference_validation_reports", "report_id", "profile_id",
                   "style_reference_profiles", "profile_id"),
    OrphanRelation("style_reference_findings", "finding_id", "book_id",
                   "style_reference_books", "book_id"),
    OrphanRelation("style_reference_profiles", "profile_id", "book_id",
                   "style_reference_books", "book_id"),
    OrphanRelation("style_reference_extractions", "extraction_id", "book_id",
                   "style_reference_books", "book_id"),
    OrphanRelation("style_reference_quotes", "quote_id", "book_id",
                   "style_reference_books", "book_id"),
    OrphanRelation("style_reference_runs", "run_id", "book_id",
                   "style_reference_books", "book_id"),
    OrphanRelation("style_reference_paragraphs", "paragraph_id", "book_id",
                   "style_reference_books", "book_id"),
    # —— 场景/章节生产链（仅纳入声明了 ForeignKey 的关系）——
    # 注意：scene_drafts/final_scenes/qc_reports.scene_id 是裸 String（非 FK），
    # 是审计/历史行，故意**不纳入**孤儿修复——§11.10 只为「启用 FK」前清障，
    # 无 FK 约束的历史行不该被删（否则会误删合法审计记录）。
    OrphanRelation("scene_run_states", "scene_id", "scene_id", "scene_cards", "scene_id"),
    OrphanRelation("scene_cards", "scene_id", "chapter_id", "chapter_goals", "chapter_id"),
)


def _orphan_ids(session: Session, rel: OrphanRelation) -> list[str]:
    sql = text(
        f"SELECT {rel.child_pk} FROM {rel.child_table} "
        f"WHERE {rel.child_fk} IS NOT NULL "
        f"AND {rel.child_fk} NOT IN (SELECT {rel.parent_pk} FROM {rel.parent_table})"
    )
    return [str(row[0]) for row in session.execute(sql).fetchall()]


def scan_orphans(session: Session) -> dict[str, list[str]]:
    """返回有孤儿的旧关系；任一登记关系无法检查时拒绝给出干净结论。"""
    found: dict[str, list[str]] = {}
    for rel in ORPHAN_RELATIONS:
        try:
            ids = _orphan_ids(session, rel)
        except Exception as exc:
            raise OrphanInventoryIncomplete(
                "legacy_orphan_scan_incomplete="
                f"{rel.child_table}.{rel.child_fk}->"
                f"{rel.parent_table}.{rel.parent_pk}:{type(exc).__name__}"
            ) from exc
        if ids:
            found.setdefault(rel.child_table, [])
            for oid in ids:
                if oid not in found[rel.child_table]:
                    found[rel.child_table].append(oid)
    return found


def orphan_report(session: Session) -> dict[str, Any]:
    found = scan_orphans(session)
    by_table = {tbl: len(ids) for tbl, ids in found.items()}
    total = sum(by_table.values())
    return {
        "clean": total == 0,
        "total_orphans": total,
        "by_table": by_table,
        "orphans": found,
        "relations_checked": len(ORPHAN_RELATIONS),
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="遗留关系孤儿诊断（只读；发布请使用 database_preflight）"
    )
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    args = parser.parse_args(argv)
    session = SessionLocal()
    try:
        try:
            report = orphan_report(session)
        except OrphanInventoryIncomplete as exc:
            report = {
                "clean": False,
                "complete": False,
                "error": str(exc),
                "relations_checked": 0,
                "total_orphans": None,
                "by_table": {},
                "orphans": {},
            }
    finally:
        session.close()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"relations_checked={report['relations_checked']} "
              f"total_orphans={report['total_orphans']} clean={report['clean']}")
        for tbl, n in report["by_table"].items():
            print(f"  {tbl}: {n}")
    if not report.get("complete", True):
        return 2
    return 0 if report["clean"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
