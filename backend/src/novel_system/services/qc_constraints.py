from __future__ import annotations

import re
from typing import Any


def constraint_terms(text: str) -> list[str]:
    return [term.strip() for term in re.split(r"[,，、;；\n]+", text) if len(term.strip()) >= 2]


def constraint_alternatives(term: str) -> list[str]:
    """拆分一个约束的等价写法；``A|B`` 表示满足任意一项即可。"""
    return [
        item.strip()
        for item in re.split(r"[|｜]+", str(term or ""))
        if len(item.strip()) >= 2
    ]


def named_scene_card_sources(
    scene: Any, fields: tuple[str, ...]
) -> list[tuple[str, str]]:
    """按给定字段顺序枚举场景卡的非空文本源，`beats_json` 恒附于末尾。

    字段顺序即归因优先级（调用方取首个命中源），故各调用方自带字段元组，
    不得在此固化某一侧的顺序。
    """
    sources: list[tuple[str, str]] = []
    for field in fields:
        value = getattr(scene, field, None)
        if isinstance(value, str) and value.strip():
            sources.append((f"scene_card.{field}", value))
    beats = getattr(scene, "beats_json", None)
    for index, beat in enumerate(beats if isinstance(beats, list) else []):
        if isinstance(beat, str) and beat.strip():
            sources.append((f"scene_card.beats_json[{index}]", beat))
    return sources


def contains_forbidden_term(forbidden_text: Any, content: str) -> bool:
    if not isinstance(forbidden_text, str) or not forbidden_text.strip():
        return False
    return any(
        alternative in content
        for term in constraint_terms(forbidden_text)
        for alternative in (constraint_alternatives(term) or [term])
    )


def significant_fragments(text: str) -> list[str]:
    fragments: list[str] = []
    fragments.extend(match.lower() for match in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}", text))
    for sequence in re.findall(r"[\u4e00-\u9fff]{3,}", text):
        fragments.extend(sequence[index : index + 3] for index in range(0, max(len(sequence) - 2, 0)))
    seen: set[str] = set()
    unique: list[str] = []
    for fragment in fragments:
        if fragment in seen:
            continue
        seen.add(fragment)
        unique.append(fragment)
    return unique


def source_field_satisfied(source_text: str, content: str) -> bool:
    alternatives = constraint_alternatives(source_text) or [source_text.strip()]
    for alternative in alternatives:
        if alternative in content:
            return True
        fragments = significant_fragments(alternative)
        if not fragments:
            continue
        matched = [fragment for fragment in fragments if fragment in content]
        if len(matched) >= min(2, len(fragments)):
            return True
    return False


def issue_mentions_source(issue_blob: str, source_text: str) -> bool:
    source_text = source_text.strip()
    if source_text and source_text in issue_blob:
        return True
    return any(fragment in issue_blob for fragment in significant_fragments(source_text))
