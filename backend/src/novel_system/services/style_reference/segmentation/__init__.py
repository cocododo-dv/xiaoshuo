"""Style Reference v1.1 段落分类调度入口。

参见《风格参考模块重构执行手册 v1.1》§6.2(段落分类锚定集校准)。

调度逻辑:
- `llm_enabled=False`(NOVEL_SYSTEM_LLM_ENABLED=false,仓库默认)→ 走启发式
- `llm_enabled=True` 且 `llm_client` 非空 → 走 LLM 锚定校准
- LLM 调用失败 → 降级到启发式,calibration 标 `fallback_reason="llm_call_failed"`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from novel_system.services.style_reference.segmentation.heuristic import classify_heuristic
from novel_system.services.style_reference.segmentation.llm import (
    SegmentationLLMError,
    classify_with_llm,
)

logger = logging.getLogger(__name__)


@dataclass
class ParagraphClassification:
    """单段分类结果。"""

    paragraph_index: int
    paragraph_type: str  # ParagraphType.value
    confidence: float
    classifier_confidence_level: str = "medium"  # high / medium / low


@dataclass
class SegmentationResult:
    """段落分类全集结果 + 校准元数据。

    用于落盘到 `style_reference_books.stats_json.classifier_calibration` 与
    `style_reference_paragraphs.paragraph_type`。
    """

    classifications: list[ParagraphClassification]
    calibration: dict[str, Any] = field(default_factory=dict)


def classify_paragraphs(
    paragraphs: list[tuple[int, int, str]],
    *,
    llm_enabled: bool,
    llm_client: Any | None = None,
) -> SegmentationResult:
    """调度段落分类。`paragraphs` 元素是 `(start_offset, end_offset, body)`。"""
    if not paragraphs:
        return SegmentationResult(classifications=[], calibration={"input_empty": True})

    if not llm_enabled or llm_client is None:
        return classify_heuristic(paragraphs)

    try:
        return classify_with_llm(paragraphs, llm_client)
    except SegmentationLLMError as exc:
        logger.warning(
            "segmentation LLM call failed; falling back to heuristic: %s", exc
        )
        result = classify_heuristic(paragraphs)
        result.calibration["fallback_reason"] = f"llm_call_failed: {exc.code}"
        return result
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            "segmentation LLM unexpected error; falling back to heuristic: %s", exc
        )
        result = classify_heuristic(paragraphs)
        result.calibration["fallback_reason"] = f"llm_unexpected: {type(exc).__name__}"
        return result


__all__ = [
    "ParagraphClassification",
    "SegmentationResult",
    "classify_paragraphs",
    "SegmentationLLMError",
]
