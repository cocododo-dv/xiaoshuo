"""PR-8 §5.1 — StyleProfile 注入到 LLM system_prompt 的服务。

InjectionService 给定 `project_id` 与 `task_type`,从 `style_reference_injection_bindings`
查 active binding,再读 profile.profile_json + 关联 forbidden_pattern findings,
按 binding.strategy 拼成 :class:`SystemPromptFragments`(3 block + strategy 回填)。

调用方(scene_generation / chapter_draft 等)拿到 fragments 后调
``fragments.to_system_prompt_prefix()`` 得到字符串,prepend 到 LLM
``messages[0]["content"]`` 头部。

Strategy 实现摘要:
- **A** — positive + forbidden + metric_anchor 三块全文注入(默认)
- **B** — 按 ``config/style_reference/injection_budget.yaml`` 预算截断
- **C** — positive 全文 + forbidden 摘要(≤200 字) + 不注入 metric_anchor
- **MIXED** — binding.config_json 自定义 ``include_positive`` /
  ``include_forbidden`` / ``include_metric`` 三个布尔开关
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from novel_system.services.style_reference.config_loader import load_yaml_config
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    InjectionStrategy,
    SystemPromptFragments,
)

_DEFAULT_BUDGET = {
    "system_prompt_max_tokens": 800,
    "positive_block_ratio": 0.6,
    "forbidden_block_ratio": 0.3,
    "metric_anchor_block_ratio": 0.1,
}


def _load_budget() -> dict[str, Any]:
    try:
        return {**_DEFAULT_BUDGET, **load_yaml_config("injection_budget")}
    except FileNotFoundError:
        return dict(_DEFAULT_BUDGET)


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1] + "…"


class InjectionService:
    """读 active binding + profile,渲染 SystemPromptFragments。"""

    def __init__(self, session: Session):
        self.session = session
        self.repo = StyleReferenceRepository(session)

    # --------------------------------------------------------------- public
    def fragments_for(
        self,
        project_id: str | None,
        task_type: str,
    ) -> SystemPromptFragments:
        """主入口。无 active binding / profile 时返 empty fragments(no-op)。"""
        if not project_id:
            return SystemPromptFragments()
        binding = self._pick_active_binding(project_id, task_type)
        if binding is None:
            return SystemPromptFragments()
        profile = self.repo.get_profile(binding.profile_id)
        if profile is None or profile.status != "active":
            return SystemPromptFragments()
        try:
            strategy = InjectionStrategy(binding.strategy)
        except ValueError:
            strategy = InjectionStrategy.A
        config = binding.config_json or {}
        return self._render(profile, strategy, config)

    # ------------------------------------------------------------- internals
    def _pick_active_binding(self, project_id: str, task_type: str):
        """优先级:scope=project + scope_ref_id 完全匹配 > scope=global。

        同 scope 内取最新 ``created_at``。
        """
        bindings = [
            b
            for b in self.repo.list_bindings(task_type=task_type)
            if b.status == "active"
        ]
        if not bindings:
            return None

        def _sort_key(b):
            scope_rank = 0 if (b.scope == "project" and b.scope_ref_id == project_id) else (
                1 if b.scope == "global" else 2
            )
            return (scope_rank, -1 * _ts_to_int(b.created_at))

        bindings = [
            b
            for b in bindings
            if (b.scope == "project" and b.scope_ref_id == project_id)
            or b.scope == "global"
        ]
        if not bindings:
            return None
        bindings.sort(key=_sort_key)
        return bindings[0]

    def _render(
        self,
        profile,
        strategy: InjectionStrategy,
        config: dict[str, Any],
    ) -> SystemPromptFragments:
        positive = self._render_positive(profile)
        forbidden = self._render_forbidden(profile)
        metric = self._render_metric(profile)

        if strategy == InjectionStrategy.B:
            positive, forbidden, metric = self._apply_budget(positive, forbidden, metric)
        elif strategy == InjectionStrategy.C:
            forbidden = self._summarize_forbidden(forbidden, max_chars=200)
            metric = ""
        elif strategy == InjectionStrategy.MIXED:
            if not config.get("include_positive", True):
                positive = ""
            if not config.get("include_forbidden", True):
                forbidden = ""
            if not config.get("include_metric", False):
                metric = ""

        return SystemPromptFragments(
            positive_block=positive,
            forbidden_block=forbidden,
            metric_anchor_block=metric,
            strategy=strategy,
        )

    def _render_positive(self, profile) -> str:
        data = profile.profile_json or {}
        narrative = (data.get("narrative_summary") or "").strip()
        features = [f.strip() for f in (data.get("style_features") or []) if str(f).strip()]
        patterns = [p.strip() for p in (data.get("narrative_patterns") or []) if str(p).strip()]
        if not (narrative or features or patterns):
            return ""
        lines: list[str] = ["[正向风格特征]"]
        if narrative:
            lines.append(f"概述:{narrative}")
        if features:
            lines.append("风格要点:")
            lines.extend(f"- {item}" for item in features)
        if patterns:
            lines.append("叙事模式:")
            lines.extend(f"- {item}" for item in patterns)
        return "\n".join(lines)

    def _render_forbidden(self, profile) -> str:
        rules = [
            r.strip()
            for r in ((profile.profile_json or {}).get("banned_replication_rules") or [])
            if str(r).strip()
        ]
        finding_statements = self._collect_forbidden_finding_statements(profile)
        if not (rules or finding_statements):
            return ""
        lines = ["[禁忌模式]"]
        for rule in rules:
            lines.append(f"- {rule}")
        for stmt in finding_statements:
            lines.append(f"- {stmt}")
        return "\n".join(lines)

    def _collect_forbidden_finding_statements(self, profile) -> list[str]:
        ids = profile.source_finding_ids_json or []
        statements: list[str] = []
        for fid in ids:
            row = self.repo.get_finding(fid)
            if row is not None and row.finding_kind == "forbidden_pattern":
                stmt = (row.statement or "").strip()
                if stmt:
                    statements.append(stmt)
        return statements

    def _render_metric(self, profile) -> str:
        baseline = (profile.profile_json or {}).get("metrics_baseline") or {}
        if not isinstance(baseline, dict) or not baseline:
            return ""
        lines = ["[量化锚点]"]
        for metric_name, stats in list(baseline.items())[:8]:
            if not isinstance(stats, dict):
                continue
            mean = stats.get("mean")
            std = stats.get("std")
            if mean is None:
                continue
            if std is None:
                lines.append(f"- {metric_name}:目标 {float(mean):.2f}")
            else:
                lines.append(f"- {metric_name}:目标 {float(mean):.2f} ± {float(std):.2f}")
        if len(lines) == 1:
            return ""
        return "\n".join(lines)

    def _apply_budget(self, positive: str, forbidden: str, metric: str) -> tuple[str, str, str]:
        budget = _load_budget()
        total = int(budget.get("system_prompt_max_tokens", 800))
        p_ratio = float(budget.get("positive_block_ratio", 0.6))
        f_ratio = float(budget.get("forbidden_block_ratio", 0.3))
        m_ratio = float(budget.get("metric_anchor_block_ratio", 0.1))
        return (
            _truncate(positive, int(total * p_ratio)),
            _truncate(forbidden, int(total * f_ratio)),
            _truncate(metric, int(total * m_ratio)),
        )

    def _summarize_forbidden(self, forbidden: str, *, max_chars: int) -> str:
        if not forbidden:
            return ""
        return _truncate(forbidden, max_chars)


def _ts_to_int(ts: str | None) -> int:
    """把 ISO 时间串转为可比 int(只用于排序,失败回 0)。"""
    if not ts:
        return 0
    cleaned = "".join(ch for ch in ts if ch.isdigit())
    if not cleaned:
        return 0
    try:
        return int(cleaned[:14])
    except ValueError:
        return 0
