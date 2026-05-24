"""Style Reference v1.1 Validation 简化版(PR-4 范围)。

PR-4 落 plagiarism + 字面 banned_terms 双层;PR-7 加完整 quantitative +
semantic 三路并发(异步轮询)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from novel_system.services.style_reference.schemas import (
    ValidationMode,
    ValidationReport,
    ValidationVerdict,
)
from novel_system.services.style_reference.validation.forbidden_local import (
    check_forbidden_local,
)
from novel_system.services.style_reference.validation.plagiarism import (
    check_plagiarism,
)

if TYPE_CHECKING:
    from novel_system.db.models import StyleReferenceProfile


def run_sync_validate(
    generated_text: str,
    profile: "StyleReferenceProfile",
    session: Session,
    *,
    profile_quotes: list[str] | None = None,
) -> ValidationReport:
    """sync_only 简化版 ValidationReport(PR-4 范围)。

    - quantitative / semantic 字段为空 list(PR-7 填)
    - plagiarism:Rabin-Karp 命中 → verdict=plagiarism
    - forbidden:任 severity=error → verdict=fail
    - 否则 verdict=pass

    `profile_quotes` 可由 caller 预拉(避免重复 query);为 None 时按
    profile.book_id 自动 list_quotes。
    """
    from novel_system.services.style_reference.repository import StyleReferenceRepository

    repo = StyleReferenceRepository(session)
    if profile_quotes is None:
        profile_quotes = [q.quote_text for q in repo.list_quotes(profile.book_id)]

    plag = check_plagiarism(generated_text, profile_quotes)
    forbid = check_forbidden_local(generated_text, profile.profile_id, session)
    verdict = _compute_verdict(plag=plag, forbid=forbid)

    return ValidationReport(
        verdict=verdict,
        mode_executed=ValidationMode.SYNC_ONLY,
        quantitative_json=[],
        semantic_json=[],
        plagiarism_json=plag.model_dump(),
        forbidden_hits_json=[h.model_dump() for h in forbid],
    )


def _compute_verdict(*, plag, forbid) -> ValidationVerdict:
    if not plag.passed:
        return ValidationVerdict.PLAGIARISM
    if any(h.severity == "error" for h in forbid):
        return ValidationVerdict.FAIL
    return ValidationVerdict.PASS


__all__ = [
    "ValidationReport",
    "run_sync_validate",
    "check_plagiarism",
    "check_forbidden_local",
]
