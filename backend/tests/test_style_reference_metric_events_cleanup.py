"""PR-11 — cleanup_metric_events 按 days_threshold 删旧 metric events。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.cleanup import cleanup_metric_events
from novel_system.services.style_reference.repository import StyleReferenceRepository


def _ts(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _seed(events: list[tuple[str, int]]) -> None:
    """每个 (event_id, days_ago) 元组落一行。"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        for eid, days_ago in events:
            repo.create_metric_event(
                event_id=eid,
                event_kind="injection_invoked",
                outcome="hit",
                created_at=_ts(days_ago),
            )
        session.commit()


def test_cleanup_deletes_events_older_than_threshold():
    _seed([
        ("sr_metric_old_1", 100),  # 100 天前 — 删
        ("sr_metric_old_2", 95),   # 95 天前 — 删
        ("sr_metric_fresh_1", 30), # 30 天前 — 留
        ("sr_metric_fresh_2", 1),  # 昨天 — 留
    ])
    with SessionLocal() as session:
        result = cleanup_metric_events(session, days_threshold=90, dry_run=False)
        session.commit()
        # 实际剩余 2 行
        remaining = StyleReferenceRepository(session).list_metric_events()
    assert result["deleted_count"] == 2
    assert result["dry_run"] is False
    assert result["days_threshold"] == 90
    assert len(remaining) == 2
    assert {r.event_id for r in remaining} == {"sr_metric_fresh_1", "sr_metric_fresh_2"}


def test_cleanup_keeps_events_within_threshold():
    _seed([
        ("sr_metric_a", 89),  # 89 天前 — 在 90 天阈值内,留
        ("sr_metric_b", 1),
    ])
    with SessionLocal() as session:
        result = cleanup_metric_events(session, days_threshold=90, dry_run=False)
        session.commit()
        remaining = StyleReferenceRepository(session).list_metric_events()
    assert result["deleted_count"] == 0
    assert len(remaining) == 2


def test_cleanup_dry_run_does_not_delete():
    _seed([
        ("sr_metric_old", 365),
        ("sr_metric_fresh", 1),
    ])
    with SessionLocal() as session:
        result = cleanup_metric_events(session, days_threshold=90, dry_run=True)
        session.commit()
        remaining = StyleReferenceRepository(session).list_metric_events()
    assert result["deleted_count"] == 1
    assert result["dry_run"] is True
    # dry_run 不删,仍有 2 行
    assert len(remaining) == 2


def test_cleanup_custom_days_threshold():
    _seed([
        ("sr_metric_d10", 10),
        ("sr_metric_d3", 3),
        ("sr_metric_today", 0),
    ])
    # 自定义阈值 7 天:10 天前的删,3 天和今天的留
    with SessionLocal() as session:
        result = cleanup_metric_events(session, days_threshold=7, dry_run=False)
        session.commit()
        remaining = StyleReferenceRepository(session).list_metric_events()
    assert result["deleted_count"] == 1
    assert result["days_threshold"] == 7
    assert {r.event_id for r in remaining} == {"sr_metric_d3", "sr_metric_today"}
