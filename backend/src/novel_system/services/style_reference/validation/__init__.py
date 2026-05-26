"""Style Reference v1.1 Validation 编排(PR-4 半盘 + PR-7 完整三路)。

- `run_sync_validate(generated_text, profile, session)` — PR-4 sync_only
  半盘(plag + forbidden_local),preview.py 仍调用此函数
- `ValidationOrchestrator.validate(req)` — PR-7 完整双路径
  - sync_only:同 run_sync_validate
  - async_full:ThreadPoolExecutor + 独立 session 跑 4 路(quant + semantic
    + plag + forbid_semantic),主线程立返 report_id + polling_url
- `_compute_verdict`(PR-4)只看 plag + forbid,保留兼容
- `_compute_full_verdict`(PR-7)扩入 quant + semantic
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from novel_system.services.style_reference.schemas import (
    ValidationMode,
    ValidationReport,
    ValidationVerdict,
)
from novel_system.services.style_reference.validation.forbidden_local import (
    check_forbidden_local,
)
from novel_system.services.style_reference.validation.forbidden_semantic import (
    check_forbidden_semantic,
)
from novel_system.services.style_reference.validation.plagiarism import (
    check_plagiarism,
)
from novel_system.services.style_reference.validation.quantitative import (
    check_quantitative,
)
from novel_system.services.style_reference.validation.runner import (
    ValidationOrchestrator,
)
from novel_system.services.style_reference.validation.semantic import check_semantic

if TYPE_CHECKING:
    from novel_system.db.models import StyleReferenceProfile


def run_sync_validate(
    generated_text: str,
    profile: "StyleReferenceProfile",
    session: Session,
    *,
    profile_quotes: list[str] | None = None,
) -> ValidationReport:
    """sync_only 简化版(PR-4)— plag + forbidden_local 双层。"""
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
    """PR-4 半盘聚合规则;PR-7 async_full 用 _compute_full_verdict。"""
    if not plag.passed:
        return ValidationVerdict.PLAGIARISM
    if any(h.severity == "error" for h in forbid):
        return ValidationVerdict.FAIL
    return ValidationVerdict.PASS


def _compute_full_verdict(*, quant, semantic, plag, forbid) -> ValidationVerdict:
    """PR-7 完整 4 路聚合(§7.5):

    - plag.passed=False → PLAGIARISM(最高优先级)
    - any forbid.severity=error → FAIL
    - quant pass_rate ≥ 0.8 且 semantic mean_score ≥ 6.0 → PASS
    - quant pass_rate ≥ 0.5 或 semantic mean_score ≥ 4.5 → PARTIAL
    - 否则 FAIL
    """
    if not plag.passed:
        return ValidationVerdict.PLAGIARISM
    if any(h.severity == "error" for h in forbid):
        return ValidationVerdict.FAIL

    quant_pass_rate = (
        sum(1 for q in quant if q.passed) / len(quant) if quant else 1.0
    )
    semantic_mean = (
        sum(s.score for s in semantic) / len(semantic) if semantic else 6.0
    )

    if quant_pass_rate >= 0.8 and semantic_mean >= 6.0:
        return ValidationVerdict.PASS
    if quant_pass_rate >= 0.5 or semantic_mean >= 4.5:
        return ValidationVerdict.PARTIAL
    return ValidationVerdict.FAIL


__all__ = [
    "ValidationReport",
    "ValidationOrchestrator",
    "run_sync_validate",
    "check_plagiarism",
    "check_forbidden_local",
    "check_quantitative",
    "check_semantic",
    "check_forbidden_semantic",
]
