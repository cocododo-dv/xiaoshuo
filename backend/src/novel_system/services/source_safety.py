from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from novel_system.services.versioning.shared import now_iso


PROTECTED_SOURCE_TERMS = (
    "龙族",
    "路明非",
    "楚子航",
    "恺撒",
    "诺诺",
    "陈墨瞳",
    "卡塞尔",
    "昂热",
    "龙王",
    "白王",
    "黑王",
    "青铜与火",
    "血统",
    "屠龙",
    "江南",
)

SOURCE_PROFILE_REF_KEY_HINTS = (
    "profile",
    "style",
    "banned",
    "narrative",
    "calibration",
    "voice",
    "relation",
)


def scan_source_safety(
    texts: str | Iterable[str | None],
    *,
    source_profile_ids: Iterable[Any] | None = None,
) -> dict[str, Any]:
    content = _coerce_text(texts)
    blocked_terms = [term for term in PROTECTED_SOURCE_TERMS if term and term in content]
    refs = _unique_strings(source_profile_ids or [])
    return {
        "safe": not blocked_terms,
        "blocked_terms": blocked_terms,
        "source_profile_ids": refs,
        "checked_at": now_iso(),
    }


def source_profile_ids_from_snapshot(snapshot: dict[str, Any] | None) -> list[str]:
    if not isinstance(snapshot, dict):
        return []
    refs = snapshot.get("source_version_refs")
    if not isinstance(refs, dict):
        return []

    values: list[Any] = []
    for key, value in refs.items():
        normalized_key = str(key or "").lower()
        if normalized_key.endswith("_row_id") or normalized_key.endswith("_version"):
            continue
        if normalized_key.endswith("_contract"):
            continue
        if not (
            normalized_key.endswith("_id")
            or normalized_key.endswith("_ids")
            or any(hint in normalized_key for hint in SOURCE_PROFILE_REF_KEY_HINTS)
        ):
            continue
        values.extend(_flatten(value))
    return _unique_strings(values)


def _coerce_text(texts: str | Iterable[str | None]) -> str:
    if isinstance(texts, str):
        return texts
    return "\n".join(str(item or "") for item in texts)


def _flatten(value: Any) -> list[Any]:
    if isinstance(value, dict):
        values: list[Any] = []
        for item in value.values():
            values.extend(_flatten(item))
        return values
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_flatten(item))
        return values
    return [value]


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
