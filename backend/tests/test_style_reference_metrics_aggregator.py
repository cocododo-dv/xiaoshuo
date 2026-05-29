"""PR-10 §13 — MetricsAggregator 4 指标 + 时间窗口过滤。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.metrics_aggregator import (
    MetricsAggregator,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository


def _ts(hours_ago: int = 0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_events(events: list[dict]) -> None:
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        for i, ev in enumerate(events):
            payload = {"event_id": f"sr_metric_seed_{i}", **ev}
            payload.setdefault("created_at", _ts(0))
            repo.create_metric_event(**payload)
        session.commit()


def test_compute_all_empty_returns_zeros():
    with SessionLocal() as session:
        result = MetricsAggregator(session).compute_all()
    assert result["injection_hit_rate"] == 0.0
    assert result["qc_gate_reject_rate"] == 0.0
    assert result["auto_rewrite_pass_rate"] == 0.0
    assert result["validation_p95_latency_ms"] == 0.0
    assert result["sample_counts"]["injection_invoked"] == 0
    assert result["window_hours"] == 168


def test_injection_hit_rate_partial():
    _seed_events([
        {"event_kind": "injection_invoked", "outcome": "hit"},
        {"event_kind": "injection_invoked", "outcome": "hit"},
        {"event_kind": "injection_invoked", "outcome": "hit"},
        {"event_kind": "injection_invoked", "outcome": "miss"},
    ])
    with SessionLocal() as session:
        result = MetricsAggregator(session).compute_all()
    assert result["injection_hit_rate"] == 0.75
    assert result["sample_counts"]["injection_invoked"] == 4


def test_qc_gate_reject_rate_includes_fail_and_plagiarism():
    _seed_events([
        {"event_kind": "qc_gate_decided", "outcome": "pass"},
        {"event_kind": "qc_gate_decided", "outcome": "pass"},
        {"event_kind": "qc_gate_decided", "outcome": "fail"},
        {"event_kind": "qc_gate_decided", "outcome": "plagiarism"},
        {"event_kind": "qc_gate_decided", "outcome": "partial"},  # 不算 reject
    ])
    with SessionLocal() as session:
        result = MetricsAggregator(session).compute_all()
    # 2/5 拒绝(fail + plagiarism)
    assert result["qc_gate_reject_rate"] == 0.4


def test_auto_rewrite_pass_rate():
    _seed_events([
        {"event_kind": "auto_rewrite_triggered", "outcome": None},
        {"event_kind": "auto_rewrite_triggered", "outcome": None},
        {"event_kind": "auto_rewrite_triggered", "outcome": None},
        {"event_kind": "auto_rewrite_completed", "outcome": "success"},
        {"event_kind": "auto_rewrite_completed", "outcome": "success"},
        {"event_kind": "auto_rewrite_completed", "outcome": "fail"},
    ])
    with SessionLocal() as session:
        result = MetricsAggregator(session).compute_all()
    # 2 success / 3 triggered
    assert result["auto_rewrite_pass_rate"] == round(2 / 3, 4)


def test_validation_p95_with_100_data_points():
    events = []
    for i in range(100):
        events.append({
            "event_kind": "validation_executed",
            "outcome": "pass",
            "latency_ms": i + 1,  # 1..100ms
        })
    _seed_events(events)
    with SessionLocal() as session:
        result = MetricsAggregator(session).compute_all()
    # statistics.quantiles(n=20)[18] 对 1..100 的 P95 应近 95
    assert 90 <= result["validation_p95_latency_ms"] <= 100


def test_validation_p95_single_point_falls_back():
    _seed_events([
        {"event_kind": "validation_executed", "outcome": "pass", "latency_ms": 123},
    ])
    with SessionLocal() as session:
        result = MetricsAggregator(session).compute_all()
    # 单数据点 → 直接返回该值(<2 触发 fallback)
    assert result["validation_p95_latency_ms"] == 123.0


def test_window_hours_filter_excludes_old_events():
    _seed_events([
        # 8 天前 — 在 168h(7d)窗外
        {"event_kind": "injection_invoked", "outcome": "hit", "created_at": _ts(24 * 8)},
        # 1 小时前 — 在窗内
        {"event_kind": "injection_invoked", "outcome": "miss", "created_at": _ts(1)},
    ])
    with SessionLocal() as session:
        result = MetricsAggregator(session).compute_all(window_hours=168)
    # 仅窗内 1 个事件,outcome=miss → hit_rate=0
    assert result["sample_counts"]["injection_invoked"] == 1
    assert result["injection_hit_rate"] == 0.0


def test_window_hours_zero_means_all_history():
    _seed_events([
        {"event_kind": "injection_invoked", "outcome": "hit", "created_at": _ts(24 * 365)},
        {"event_kind": "injection_invoked", "outcome": "hit", "created_at": _ts(1)},
    ])
    with SessionLocal() as session:
        result = MetricsAggregator(session).compute_all(window_hours=0)
    assert result["sample_counts"]["injection_invoked"] == 2
    assert result["injection_hit_rate"] == 1.0
