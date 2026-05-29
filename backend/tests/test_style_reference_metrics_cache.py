"""PR-12 — MetricsAggregator in-memory TTL cache。"""

from __future__ import annotations

import uuid

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference import metrics_aggregator as agg_mod
from novel_system.services.style_reference.metrics_aggregator import (
    MetricsAggregator,
    clear_metrics_cache,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository


def _seed_injection(*, hits: int, misses: int) -> None:
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        for _ in range(hits):
            repo.create_metric_event(
                event_id=f"sr_metric_hit_{uuid.uuid4().hex[:12]}",
                event_kind="injection_invoked", outcome="hit",
            )
        for _ in range(misses):
            repo.create_metric_event(
                event_id=f"sr_metric_miss_{uuid.uuid4().hex[:12]}",
                event_kind="injection_invoked", outcome="miss",
            )
        session.commit()


def test_cache_hit_returns_stale_snapshot_within_ttl():
    """第一次 compute 后再 seed 新数据,cache 命中应返回旧快照(证明走了 cache)。"""
    _seed_injection(hits=1, misses=1)
    with SessionLocal() as session:
        first = MetricsAggregator(session).compute_all(window_hours=168)
    assert first["injection_hit_rate"] == 0.5

    # 追加数据;cache 未过期 → 二次 compute 仍返旧值
    _seed_injection(hits=8, misses=0)
    with SessionLocal() as session:
        second = MetricsAggregator(session).compute_all(window_hours=168)
    assert second["injection_hit_rate"] == 0.5  # 命中 cache,未重算
    assert second is first or second == first


def test_use_cache_false_bypasses_cache():
    _seed_injection(hits=1, misses=1)
    with SessionLocal() as session:
        MetricsAggregator(session).compute_all(window_hours=168)  # 填 cache
    _seed_injection(hits=8, misses=0)
    with SessionLocal() as session:
        fresh = MetricsAggregator(session).compute_all(window_hours=168, use_cache=False)
    # 绕过 cache → 看到全部 9 hit / 10 total
    assert fresh["sample_counts"]["injection_invoked"] == 10
    assert fresh["injection_hit_rate"] == 0.9


def test_ttl_expiry_recomputes(monkeypatch):
    _seed_injection(hits=1, misses=1)
    fake_now = [1000.0]
    monkeypatch.setattr(agg_mod.time, "monotonic", lambda: fake_now[0])

    with SessionLocal() as session:
        first = MetricsAggregator(session).compute_all(window_hours=168)
    assert first["injection_hit_rate"] == 0.5

    _seed_injection(hits=8, misses=0)
    # 推进超过 TTL(300s)
    fake_now[0] = 1000.0 + agg_mod._CACHE_TTL_SECONDS + 1
    with SessionLocal() as session:
        second = MetricsAggregator(session).compute_all(window_hours=168)
    # cache 过期 → 重算,看到 9/10
    assert second["injection_hit_rate"] == 0.9


def test_clear_metrics_cache_forces_recompute():
    _seed_injection(hits=1, misses=1)
    with SessionLocal() as session:
        first = MetricsAggregator(session).compute_all(window_hours=168)
    assert first["injection_hit_rate"] == 0.5

    _seed_injection(hits=8, misses=0)
    clear_metrics_cache()
    with SessionLocal() as session:
        second = MetricsAggregator(session).compute_all(window_hours=168)
    assert second["injection_hit_rate"] == 0.9


def test_distinct_window_hours_keyed_separately():
    _seed_injection(hits=3, misses=1)
    with SessionLocal() as session:
        w168 = MetricsAggregator(session).compute_all(window_hours=168)
        w24 = MetricsAggregator(session).compute_all(window_hours=24)
    assert w168["window_hours"] == 168
    assert w24["window_hours"] == 24
    # 两个 key 都缓存,互不覆盖
    assert set(agg_mod._METRICS_CACHE.keys()) >= {168, 24}
