"""PR-10 §13 — 统一 metric event 写入入口。

业务路径(InjectionService / qc gate / ValidationOrchestrator /
SceneAutoRewriteService)在末尾调 ``MetricsRecorder.record(...)`` 落 1 行
``style_reference_metric_events`` 事件;失败 swallow + warn log,**绝不抛**,
业务流程不被 metrics 阻塞。

Aggregator 通过 SQL group by 算 4 个指标(injection 命中率 / qc gate 拒绝率
/ auto_rewrite 通过率 / validation P95 延迟)。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import StyleReferenceMetricEvent

_LOGGER = logging.getLogger(__name__)


class MetricsRecorder:
    """static helper;无状态。"""

    @staticmethod
    def record(
        session: Session,
        event_kind: str,
        *,
        target_kind: str | None = None,
        target_ref_id: str | None = None,
        profile_id: str | None = None,
        binding_id: str | None = None,
        outcome: str | None = None,
        latency_ms: int | None = None,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """写 1 行 metric event。

        失败时 swallow + warn log,返 ``None``。**绝不抛异常**。

        Returns
        -------
        event_id : 成功时 ``sr_metric_<hex>``;失败时 ``None``。
        """
        try:
            event_id = f"sr_metric_{uuid.uuid4().hex[:12]}"
            event = StyleReferenceMetricEvent(
                event_id=event_id,
                event_kind=event_kind,
                target_kind=target_kind,
                target_ref_id=target_ref_id,
                profile_id=profile_id,
                binding_id=binding_id,
                outcome=outcome,
                latency_ms=latency_ms,
                context_json=context or {},
            )
            session.add(event)
            session.flush()
            return event_id
        except Exception as exc:  # noqa: BLE001 — metrics 不阻塞主业务
            _LOGGER.warning(
                "metrics recorder failed for %s (outcome=%s): %s",
                event_kind, outcome, exc,
            )
            return None
