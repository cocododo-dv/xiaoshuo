"""StyleReference 运行时 cleanup。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


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
