"""StyleReference 运行时 cleanup。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from novel_system.db.models import (
    ReviewItem,
    StyleReferenceBannedTerm,
    StyleReferenceEvidence,
    StyleReferenceExtraction,
    StyleReferenceFinding,
    StyleReferenceInjectionBinding,
    StyleReferenceProfile,
    StyleReferenceQuote,
    StyleReferenceRun,
    StyleReferenceValidationReport,
)


def purge_derived_data(session: Session, book_id: str) -> dict[str, int]:
    """删除 book 的全部派生数据,保留 paragraphs 与 book 本身。

    覆盖 9 张派生表(validation reports → bindings → banned terms → profiles →
    evidences → findings → extractions → quotes → runs,FK 反向顺序)+ 相关
    ReviewItem(``review_style_ref_apply_*`` / ``review_style_ref_calib_*`` /
    ``review_style_ref_finding_*`` 前缀)。

    路由 ``delete_book`` 与 ``reclassify`` 共用;flush 但不 commit。
    返回 {表名: 删除行数} 摘要。
    """
    from novel_system.services.style_reference.repository import (
        StyleReferenceRepository,
    )

    repo = StyleReferenceRepository(session)
    profile_ids = [p.profile_id for p in repo.list_profiles(book_id=book_id)]
    findings = repo.list_findings(book_id=book_id)
    finding_ids = [f.finding_id for f in findings]

    counts: dict[str, int] = {}

    def _exec(stmt, key: str) -> None:
        result = session.execute(stmt)
        counts[key] = counts.get(key, 0) + int(result.rowcount or 0)

    # 相关 ReviewItem:finding review id 是确定性的(finding_id 后 12 位),
    # apply / calib 按 profile_id 后 12 位做前缀匹配(见 materialization.py)。
    review_ids = {f"review_style_ref_finding_{fid[-12:]}" for fid in finding_ids}
    review_ids.update(f.review_id for f in findings if f.review_id)
    if review_ids:
        _exec(
            delete(ReviewItem).where(ReviewItem.review_id.in_(sorted(review_ids))),
            "review_items",
        )
    for pid in profile_ids:
        suffix = pid[-12:] if len(pid) > 12 else pid
        for prefix in ("review_style_ref_apply_", "review_style_ref_calib_"):
            _exec(
                delete(ReviewItem).where(
                    ReviewItem.review_id.startswith(f"{prefix}{suffix}_", autoescape=True)
                ),
                "review_items",
            )

    for pid in profile_ids:
        _exec(
            delete(StyleReferenceValidationReport).where(
                StyleReferenceValidationReport.profile_id == pid
            ),
            "validation_reports",
        )
        _exec(
            delete(StyleReferenceInjectionBinding).where(
                StyleReferenceInjectionBinding.profile_id == pid
            ),
            "bindings",
        )
        _exec(
            delete(StyleReferenceBannedTerm).where(
                StyleReferenceBannedTerm.profile_id == pid
            ),
            "banned_terms",
        )
    _exec(
        delete(StyleReferenceProfile).where(StyleReferenceProfile.book_id == book_id),
        "profiles",
    )
    if finding_ids:
        _exec(
            delete(StyleReferenceEvidence).where(
                StyleReferenceEvidence.finding_id.in_(finding_ids)
            ),
            "evidences",
        )
    _exec(
        delete(StyleReferenceFinding).where(StyleReferenceFinding.book_id == book_id),
        "findings",
    )
    _exec(
        delete(StyleReferenceExtraction).where(
            StyleReferenceExtraction.book_id == book_id
        ),
        "extractions",
    )
    _exec(
        delete(StyleReferenceQuote).where(StyleReferenceQuote.book_id == book_id),
        "quotes",
    )
    _exec(
        delete(StyleReferenceRun).where(StyleReferenceRun.book_id == book_id),
        "runs",
    )
    session.flush()
    return counts


def cleanup_metric_events(
    session: Session,
    *,
    days_threshold: int = 90,
    dry_run: bool = True,
) -> dict[str, Any]:
    """删除 ``style_reference_metric_events`` 中超过 ``days_threshold`` 天的事件。

    ``dry_run=True``(默认)只统计,不执行 DELETE;``dry_run=False`` 真删。
    返回执行摘要 dict,包含 ``deleted_count`` / ``oldest_kept_at`` /
    ``dry_run`` / ``days_threshold`` / ``cutoff`` / ``executed_at``。

    本函数 flush 但不 commit;由调用方(CLI / 测试)负责事务提交。
    """
    from datetime import timedelta

    now = datetime.now(UTC)
    cutoff_dt = now - timedelta(days=int(days_threshold))
    cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    count_row = session.execute(
        text(
            "SELECT COUNT(*) FROM style_reference_metric_events "
            "WHERE created_at < :cutoff"
        ),
        {"cutoff": cutoff},
    ).scalar()
    deleted_count = int(count_row or 0)

    oldest_kept = session.execute(
        text(
            "SELECT MIN(created_at) FROM style_reference_metric_events "
            "WHERE created_at >= :cutoff"
        ),
        {"cutoff": cutoff},
    ).scalar()

    if not dry_run and deleted_count > 0:
        session.execute(
            text(
                "DELETE FROM style_reference_metric_events WHERE created_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        session.flush()
        # PR-12 — 真删后失效聚合缓存,避免 GET /metrics 返回删前的旧快照
        from novel_system.services.style_reference.metrics_aggregator import (
            clear_metrics_cache,
        )

        clear_metrics_cache()

    return {
        "deleted_count": deleted_count,
        "oldest_kept_at": oldest_kept,
        "dry_run": dry_run,
        "days_threshold": int(days_threshold),
        "cutoff": cutoff,
        "executed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
