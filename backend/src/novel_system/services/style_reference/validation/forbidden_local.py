"""字面 banned_terms 扫描(PR-4 范围)。

读取 `style_reference_banned_terms`(scope=generation)对 generated_text
做字符串匹配。PR-8 之后会加 forbidden_pattern 的 LLM 语义检查(semantic
forbidden),本 PR-4 只做字面。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import BannedTermScope, ForbiddenHit


def check_forbidden_local(
    generated_text: str,
    profile_id: str,
    session: Session,
) -> list[ForbiddenHit]:
    """从 banned_terms(scope=generation)读词表,逐 term 字符串匹配。"""
    if not generated_text:
        return []
    repo = StyleReferenceRepository(session)
    terms = repo.list_banned_terms(
        profile_id, scope=BannedTermScope.GENERATION.value
    )
    hits: list[ForbiddenHit] = []
    for term in terms:
        if not term.term:
            continue
        if term.term in generated_text:
            hits.append(
                ForbiddenHit(
                    pattern_statement=term.term,
                    matched_excerpt=term.term,
                    severity="error",
                )
            )
    return hits
