"""PR-10 §13 — MetricsAggregator:从 metric_events 表算 4 个运营指标。

PR-12 §"性能轨道":加模块级 in-memory TTL cache(默认 300s),按 window_hours
分键。聚合 5 个 SQL 较重,GET /metrics 高频调用时命中 cache 直返快照;
cleanup_metric_events 真删后调 clear_metrics_cache() 失效避免脏读;
conftest 每 test 清 cache 保证跨 test 隔离。
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from novel_system.db.models import StyleReferenceMetricEvent

# event_kind 5 个允许值(由文档约束,非 Enum)
KIND_INJECTION = "injection_invoked"
KIND_QC_GATE = "qc_gate_decided"
KIND_VALIDATION = "validation_executed"
KIND_AUTO_REWRITE_TRIGGERED = "auto_rewrite_triggered"
KIND_AUTO_REWRITE_COMPLETED = "auto_rewrite_completed"

# PR-12 — 模块级 TTL cache:window_hours -> (expires_at_monotonic, snapshot)
_CACHE_TTL_SECONDS = 300
_METRICS_CACHE: dict[int, tuple[float, dict[str, Any]]] = {}


def clear_metrics_cache() -> None:
    """清空 metrics 聚合缓存(测试隔离 + cleanup 真删后失效)。"""
    _METRICS_CACHE.clear()


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _since_ts(window_hours: int) -> str | None:
    """window_hours=0 表示全部历史(返 None);否则返 ISO 时间串。"""
    if window_hours <= 0:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=int(window_hours))
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")


class MetricsAggregator:
    def __init__(self, session: Session) -> None:
        self.session = session

    def compute_all(self, window_hours: int = 168, *, use_cache: bool = True) -> dict[str, Any]:
        """按 window_hours 算 4 指标 + sample_counts。

        use_cache=True(默认)时走模块级 TTL cache;同 window_hours 在 TTL 内
        二次调用直返快照,不重算 5 个 SQL。use_cache=False 绕过(供单测精确断言)。
        """
        key = int(window_hours)
        now = time.monotonic()
        if use_cache:
            cached = _METRICS_CACHE.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]
        snapshot = self._compute_uncached(window_hours)
        if use_cache:
            _METRICS_CACHE[key] = (now + _CACHE_TTL_SECONDS, snapshot)
        return snapshot

    def _compute_uncached(self, window_hours: int) -> dict[str, Any]:
        since = _since_ts(window_hours)
        return {
            "injection_hit_rate": self._injection_hit_rate(since),
            "qc_gate_reject_rate": self._qc_gate_reject_rate(since),
            "auto_rewrite_pass_rate": self._auto_rewrite_pass_rate(since),
            "validation_p95_latency_ms": self._validation_p95(since),
            "sample_counts": self._sample_counts(since),
            "window_hours": int(window_hours),
            "computed_at": _utcnow(),
        }

    # ---------------------------------------------------------------- helpers
    def _count_by_outcome(
        self,
        event_kind: str,
        since: str | None,
        outcomes: list[str] | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(StyleReferenceMetricEvent).where(
            StyleReferenceMetricEvent.event_kind == event_kind,
        )
        if since is not None:
            stmt = stmt.where(StyleReferenceMetricEvent.created_at >= since)
        if outcomes is not None:
            stmt = stmt.where(StyleReferenceMetricEvent.outcome.in_(outcomes))
        return int(self.session.scalar(stmt) or 0)

    # ------------------------------------------------------------- 4 metrics
    def _injection_hit_rate(self, since: str | None) -> float:
        total = self._count_by_outcome(KIND_INJECTION, since)
        if total == 0:
            return 0.0
        hits = self._count_by_outcome(KIND_INJECTION, since, ["hit"])
        return round(hits / total, 4)

    def _qc_gate_reject_rate(self, since: str | None) -> float:
        total = self._count_by_outcome(KIND_QC_GATE, since)
        if total == 0:
            return 0.0
        rejects = self._count_by_outcome(KIND_QC_GATE, since, ["fail", "plagiarism"])
        return round(rejects / total, 4)

    def _auto_rewrite_pass_rate(self, since: str | None) -> float:
        triggered = self._count_by_outcome(KIND_AUTO_REWRITE_TRIGGERED, since)
        if triggered == 0:
            return 0.0
        success = self._count_by_outcome(KIND_AUTO_REWRITE_COMPLETED, since, ["success"])
        return round(success / triggered, 4)

    def _validation_p95(self, since: str | None) -> float:
        stmt = select(StyleReferenceMetricEvent.latency_ms).where(
            StyleReferenceMetricEvent.event_kind == KIND_VALIDATION,
            StyleReferenceMetricEvent.latency_ms.is_not(None),
        )
        if since is not None:
            stmt = stmt.where(StyleReferenceMetricEvent.created_at >= since)
        latencies = [int(v) for v in self.session.scalars(stmt).all() if v is not None]
        if not latencies:
            return 0.0
        if len(latencies) < 2:
            return float(latencies[0])
        # statistics.quantiles(n=20) 把数据切成 20 段,index [18] 是 95th percentile
        quantiles = statistics.quantiles(latencies, n=20, method="exclusive")
        return round(float(quantiles[18]), 2)

    def _sample_counts(self, since: str | None) -> dict[str, int]:
        return {
            KIND_INJECTION: self._count_by_outcome(KIND_INJECTION, since),
            KIND_QC_GATE: self._count_by_outcome(KIND_QC_GATE, since),
            KIND_VALIDATION: self._count_by_outcome(KIND_VALIDATION, since),
            KIND_AUTO_REWRITE_TRIGGERED: self._count_by_outcome(KIND_AUTO_REWRITE_TRIGGERED, since),
            KIND_AUTO_REWRITE_COMPLETED: self._count_by_outcome(KIND_AUTO_REWRITE_COMPLETED, since),
        }

    # ----------------------------------------------------------- PR-22 trend
    def daily_injection_counts(self, window_days: int = 14) -> dict[str, Any]:
        """PR-22 — 按天聚合 injection_invoked 计数,零填充为连续日期轴。

        created_at 存 ISO 串 ``YYYY-MM-DDThh:mm:ssZ``,``substr(created_at,1,10)``
        即日期(纯 SQL,无方言依赖);缺失日在 Python 侧零填充。不缓存(单条
        GROUP BY 廉价,且 cleanup 真删后永远新鲜)。
        """
        window_days = max(1, min(90, int(window_days)))
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=window_days - 1)
        since = start.strftime("%Y-%m-%dT00:00:00Z")
        day_expr = func.substr(StyleReferenceMetricEvent.created_at, 1, 10)
        rows = self.session.execute(
            select(day_expr.label("day"), func.count().label("n"))
            .where(
                StyleReferenceMetricEvent.event_kind == KIND_INJECTION,
                StyleReferenceMetricEvent.created_at >= since,
            )
            .group_by(day_expr)
        ).all()
        counts = {row.day: int(row.n) for row in rows}
        daily = []
        for i in range(window_days):
            day = (start + timedelta(days=i)).isoformat()
            daily.append({"date": day, "count": counts.get(day, 0)})
        return {"daily": daily, "window_days": window_days, "computed_at": _utcnow()}
