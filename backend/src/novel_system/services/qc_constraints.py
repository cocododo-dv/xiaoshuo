from __future__ import annotations

import re
from typing import Any


def constraint_terms(text: str) -> list[str]:
    return [term.strip() for term in re.split(r"[,，、;；\n]+", text) if len(term.strip()) >= 2]


def contains_forbidden_term(forbidden_text: Any, content: str) -> bool:
    if not isinstance(forbidden_text, str) or not forbidden_text.strip():
        return False
    return any(term in content for term in constraint_terms(forbidden_text))


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
    source_text = source_text.strip()
    if source_text in content:
        return True
    fragments = significant_fragments(source_text)
    if not fragments:
        return False
    matched = [fragment for fragment in fragments if fragment in content]
    return len(matched) >= min(2, len(fragments))


def issue_mentions_source(issue_blob: str, source_text: str) -> bool:
    source_text = source_text.strip()
    if source_text and source_text in issue_blob:
        return True
    return any(fragment in issue_blob for fragment in significant_fragments(source_text))
