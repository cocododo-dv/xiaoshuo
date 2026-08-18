"""Style Reference v1.1 段落分类调度入口。

参见《风格参考模块重构执行手册 v1.1》§6.2(段落分类锚定集校准)。

调度逻辑:
- `llm_enabled=False`(NOVEL_SYSTEM_LLM_ENABLED=false,仓库默认)→ 走启发式
- `llm_enabled=True` 且 `llm_client` 非空 → 走 LLM 锚定校准
- LLM 调用失败 → 降级到启发式,calibration 标 `fallback_reason="llm_call_failed"`
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from novel_system.services.llm_accounting import (
    LLMAccountingError,
    is_llm_control_plane_failure,
)
from novel_system.services.style_reference.segmentation.heuristic import classify_heuristic
from novel_system.services.style_reference.segmentation.llm import (
    SegmentationLLMError,
    classify_with_llm,
)
from novel_system.services.style_reference.segmentation.types import (
    ParagraphClassification,
    SegmentationResult,
)

logger = logging.getLogger(__name__)


def classify_paragraphs(
    paragraphs: list[tuple[int, int, str]],
    *,
    llm_enabled: bool,
    llm_client: Any | None = None,
    session: Session | None = None,
    scope_id: str | None = None,
) -> SegmentationResult:
    """调度段落分类。`paragraphs` 元素是 `(start_offset, end_offset, body)`。"""
    if not paragraphs:
        return SegmentationResult(classifications=[], calibration={"input_empty": True})

    if not llm_enabled or llm_client is None:
        return classify_heuristic(paragraphs)
    if session is None or not str(scope_id or "").strip():
        raise SegmentationLLMError(
            "STYLE_REF_ACCOUNTING_CONTEXT_REQUIRED",
            "LLM segmentation requires a durable session and style-reference scope",
        )

    try:
        return classify_with_llm(
            paragraphs,
            llm_client,
            session=session,
            scope_id=str(scope_id),
        )
    except SegmentationLLMError as exc:
        if is_llm_control_plane_failure(exc):
            raise
        logger.warning(
            "segmentation LLM call failed; falling back to heuristic: %s", exc
        )
        result = classify_heuristic(paragraphs)
        result.calibration["fallback_reason"] = f"llm_call_failed: {exc.code}"
        return result
    except Exception as exc:  # pylint: disable=broad-except
        if isinstance(exc, LLMAccountingError) or is_llm_control_plane_failure(exc):
            raise
        raise


__all__ = [
    "ParagraphClassification",
    "SegmentationResult",
    "classify_paragraphs",
    "SegmentationLLMError",
]
