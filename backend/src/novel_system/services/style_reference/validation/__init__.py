"""Style Reference v1.1 Validation 编排(PR-4 半盘 + PR-7 完整三路)。

- `run_sync_validate(generated_text, profile, session)` — sync_only 快路径
  (quantitative + plag + forbidden_local;§4.3 设计:落盘 gate 必须含量化对照),
  preview.py 与 qc_engine gate 调用此路径
- `ValidationOrchestrator.validate(req)` — PR-7 完整双路径
  - sync_only:同 run_sync_validate
  - async_full:ThreadPoolExecutor + 独立 session 跑 4 路(quant + semantic
    + plag + forbid_semantic),主线程立返 report_id + polling_url
- `_compute_full_verdict` — 4 路聚合;semantic 路**尝试执行但失败**时
  semantic_degraded=True,PASS 封顶降为 PARTIAL(检查没跑完不能宣告全过)

抄袭检测语料 = **全书段落**(`_load_plagiarism_corpus`,带小型进程内缓存),
不再只覆盖抽取阶段引用过的 quotes——抄了未被引用的原文段落同样要能检出。
"""

from __future__ import annotations

from collections import OrderedDict
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


# (book_id, text_checksum) → 段落文本 list;书文本按 checksum 不可变,
# 小缓存避免每次 qc gate 都全表读段落
_CORPUS_CACHE: "OrderedDict[tuple[str, str], list[str]]" = OrderedDict()
_CORPUS_CACHE_MAX = 4


def _load_plagiarism_corpus(repo, book_id: str) -> list[str]:
    """加载全书段落文本作为抄袭检测语料(进程内按 checksum 缓存)。"""
    book = repo.get_book(book_id)
    checksum = (getattr(book, "text_checksum", "") or "") if book is not None else ""
    key = (book_id, checksum)
    cached = _CORPUS_CACHE.get(key)
    if cached is not None:
        _CORPUS_CACHE.move_to_end(key)
        return cached
    texts = [p.text for p in repo.list_paragraphs(book_id) if p.text]
    _CORPUS_CACHE[key] = texts
    _CORPUS_CACHE.move_to_end(key)
    while len(_CORPUS_CACHE) > _CORPUS_CACHE_MAX:
        _CORPUS_CACHE.popitem(last=False)
    return texts


def clear_plagiarism_corpus_cache() -> None:
    """测试 / 删书后清缓存。"""
    _CORPUS_CACHE.clear()


def run_sync_validate(
    generated_text: str,
    profile: "StyleReferenceProfile",
    session: Session,
    *,
    profile_quotes: list[str] | None = None,
) -> ValidationReport:
    """sync_only 快路径 — quantitative + plag + forbidden_local 三层。

    ``profile_quotes`` 形参名保留向后兼容;传入时作为**额外**语料并入全书段落
    (合成 counter_example 不在段落表里,preview 等调用方可显式补充)。
    """
    from novel_system.services.style_reference.repository import StyleReferenceRepository

    repo = StyleReferenceRepository(session)
    corpus = _load_plagiarism_corpus(repo, profile.book_id)
    if profile_quotes:
        corpus = corpus + [q for q in profile_quotes if q]

    plag = check_plagiarism(generated_text, corpus)
    forbid = check_forbidden_local(generated_text, profile.profile_id, session)
    quant = check_quantitative(generated_text, profile)
    verdict = _compute_full_verdict(quant=quant, semantic=[], plag=plag, forbid=forbid)

    return ValidationReport(
        verdict=verdict,
        mode_executed=ValidationMode.SYNC_ONLY,
        quantitative_json=[q.model_dump() for q in quant],
        semantic_json=[],
        plagiarism_json=plag.model_dump(),
        forbidden_hits_json=[h.model_dump() for h in forbid],
    )


def _compute_verdict(*, plag, forbid) -> ValidationVerdict:
    """PR-4 半盘聚合规则(保留兼容,现行路径均走 _compute_full_verdict)。"""
    if not plag.passed:
        return ValidationVerdict.PLAGIARISM
    if any(h.severity == "error" for h in forbid):
        return ValidationVerdict.FAIL
    return ValidationVerdict.PASS


def _compute_full_verdict(
    *,
    quant,
    semantic,
    plag,
    forbid,
    semantic_degraded: bool = False,
) -> ValidationVerdict:
    """PR-7 完整 4 路聚合(§7.5):

    - plag.passed=False → PLAGIARISM(最高优先级)
    - any forbid.severity=error → FAIL
    - quant pass_rate ≥ 0.8 且 semantic mean_score ≥ 6.0 → PASS
    - quant pass_rate ≥ 0.5 或 semantic mean_score ≥ 4.5 → PARTIAL
    - 否则 FAIL
    - ``semantic_degraded=True``(语义路尝试执行但失败)时 PASS 封顶 PARTIAL:
      一路检查没跑完,不能宣告全过(空集默认值不再静默折叠成满分)
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
        if semantic_degraded:
            return ValidationVerdict.PARTIAL
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
    "clear_plagiarism_corpus_cache",
]
