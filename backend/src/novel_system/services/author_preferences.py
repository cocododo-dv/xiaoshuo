"""Pure helpers for scoped, prompt-safe author preference summaries.

This module deliberately has no service/model imports so generation, review,
and bundle construction can share the policy without circular imports.
"""

from __future__ import annotations

import json
from typing import Any


def merge_preference_summaries(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if key in {"safe_preference_hints", "rejected_ai_traces"} and isinstance(value, list):
            current = [str(item) for item in merged.get(key, []) if str(item).strip()]
            current.extend(str(item) for item in value if str(item).strip())
            merged[key] = _unique_tail(current, limit=20)
            continue
        if key in {"preference_signals", "manual_edit_observations"} and isinstance(value, list):
            rows = [row for row in merged.get(key, []) if isinstance(row, dict)]
            rows.extend(row for row in value if isinstance(row, dict))
            seen: set[str] = set()
            unique_rows: list[dict[str, Any]] = []
            for row in rows:
                marker = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if marker in seen:
                    continue
                seen.add(marker)
                unique_rows.append(row)
            merged[key] = unique_rows[-30:]
            continue
        merged[key] = value
    return merged


def safe_preference_summary_for_prompt(summary: dict[str, Any]) -> dict[str, Any]:
    if not summary:
        return {}
    safe: dict[str, Any] = {}
    for key in (
        "accepted_proposal_count",
        "rejected_proposal_count",
        "accepted_by_type",
        "rejected_by_type",
        "scope_type",
        "scope_ref_id",
        "manual_edit_count",
        "applied_scopes",
    ):
        if key in summary:
            safe[key] = summary[key]

    signals = []
    source_signals = summary.get("preference_signals", [])
    for row in source_signals if isinstance(source_signals, list) else []:
        if not isinstance(row, dict):
            continue
        labels = [str(label)[:80] for label in row.get("labels", []) if str(label).strip()]
        if labels:
            signals.append(
                {
                    "source_proposal_id": str(row.get("source_proposal_id") or "")[:120],
                    "proposal_type": str(row.get("proposal_type") or "")[:80],
                    "labels": labels[:8],
                    "safe_summary": "; ".join(labels[:8]),
                }
            )
    if signals:
        safe["preference_signals"] = signals[-20:]

    hints = [safe_runtime_phrase(item) for item in summary.get("safe_preference_hints", [])]
    hints = [item for item in hints if item]
    if hints:
        safe["safe_preference_hints"] = _unique_tail(hints, limit=20)

    for key in (
        "preferred_revision_moves",
        "rejected_revision_moves",
        "preferred_patch_categories",
        "rejected_patch_categories",
        "preference_tags",
        "ai_trace_terms_to_watch",
        "rejected_ai_traces",
    ):
        source_values = summary.get(key, [])
        values = [safe_runtime_phrase(value) for value in source_values] if isinstance(source_values, list) else []
        values = [value for value in values if value]
        if values:
            safe[key] = _unique_tail(values, limit=20)
    return safe


def safe_runtime_phrase(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    lowered = text.lower()
    blocked = (
        "ignore previous",
        "ignore all",
        "system prompt",
        "developer message",
        "tool call",
        "execute ",
        "忽略以上",
        "忽略之前",
        "系统提示",
        "开发者消息",
        "调用工具",
        "执行命令",
    )
    if any(marker in lowered for marker in blocked):
        return ""
    return text[:120]


def _unique_tail(values: list[str], *, limit: int) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output[-limit:]
