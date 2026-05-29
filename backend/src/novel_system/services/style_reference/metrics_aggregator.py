"""PR-10 §13 — MetricsAggregator:从 metric_events 表算 4 个运营指标。

无缓存(本 PR 范围);每次 GET 直接 SQL 算。后续 PR-11 可加 5 分钟 in-memory cache。
"""

from __future__ import annotations

import statistics
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

    def compute_all(self, window_hours: int = 168) -> dict[str, Any]:
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
