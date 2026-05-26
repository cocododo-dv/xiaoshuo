"""Quantitative validation:自适应 tolerance 的硬指标对照(PR-7 §7.2)。

`check_quantitative(generated_text, profile)`:
1. 把 generated_text 包装成临时 paragraphs 列表(全部归 narration)
2. MetricsEngine.compute_all → 26 项 metric
3. 对照 profile.profile_json["metrics_baseline"](PR-4 ProfileSynthesizer 落)
4. tolerance = max(baseline_std × 1.25, ABSOLUTE_FLOORS[metric])
5. 返 list[QuantitativeReportItem]

baseline 缺失或 generated_text 为空时返 []。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from novel_system.services.style_reference.config_loader import load_yaml_config
from novel_system.services.style_reference.metrics import (
    METRIC_NAMES,
    MetricsEngine,
    ParagraphRecord,
)
from novel_system.services.style_reference.schemas import QuantitativeReportItem

if TYPE_CHECKING:
    from novel_system.db.models import StyleReferenceProfile


DEFAULT_FLOOR = 0.1


def _wrap_as_paragraphs(generated_text: str) -> list[ParagraphRecord]:
    """把 generated_text 切成临时段(按双换行),全部归 narration。

    quant 不依赖 paragraph_type 精确性;只关心句长/词频/感官词密度等纯文本统计。
    """
    if not generated_text:
        return []
    raw_parts = re.split(r"\n\s*\n", generated_text)
    parts = [p.strip() for p in raw_parts if p.strip()]
    if not parts:
        parts = [generated_text.strip()]
    return [ParagraphRecord(text=p, paragraph_type="narration") for p in parts]


def _dim_for_metric(metric: str) -> str:
    if metric.startswith("sensory_"):
        return "scene"
    if metric in {
        "dialogue_ratio",
        "psychology_ratio",
        "description_env_ratio",
        "description_char_ratio",
        "action_ratio",
        "narration_ratio",
        "transition_ratio",
        "flashback_ratio",
    }:
        return "narrative"
    return "language"


def check_quantitative(
    generated_text: str,
    profile: "StyleReferenceProfile",
    *,
    floors: dict[str, float] | None = None,
) -> list[QuantitativeReportItem]:
    paragraphs = _wrap_as_paragraphs(generated_text)
    if not paragraphs:
        return []

    profile_json = profile.profile_json or {}
    baseline = profile_json.get("metrics_baseline") or {}
    if not baseline:
        return []

    if floors is None:
        try:
            floors = load_yaml_config("tolerance_floors")
        except FileNotFoundError:
            floors = {}

    gen_metrics = MetricsEngine().compute_all(paragraphs)

    reports: list[QuantitativeReportItem] = []
    for name in METRIC_NAMES:
        base = baseline.get(name)
        if not isinstance(base, dict):
            continue
        if name not in gen_metrics:
            continue
        baseline_mean = float(base.get("mean", 0.0))
        baseline_std = float(base.get("std", 0.0))
        floor = float(floors.get(name, DEFAULT_FLOOR))
        tolerance = max(baseline_std * 1.25, floor)
        actual = float(gen_metrics[name])
        deviation = abs(actual - baseline_mean) / max(tolerance, 1e-6)
        reports.append(
            QuantitativeReportItem(
                dimension=_dim_for_metric(name),
                metric=name,
                target_mean=baseline_mean,
                target_std=baseline_std,
                actual=actual,
                tolerance=tolerance,
                passed=deviation <= 1.0,
                deviation_ratio=deviation,
            )
        )
    return reports
