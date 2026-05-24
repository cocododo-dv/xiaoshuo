"""Style Reference v1.1 extractors。

参见《风格参考模块重构执行手册 v1.1》§6.5 / §6.6 / §6.7 与
plans/style-reference-v1-1-fancy-shannon.md。
"""

from __future__ import annotations

from novel_system.services.style_reference.extractors.base import (
    BaseExtractor,
    ExtractionRetryPolicy,
    ExtractionRunResult,
)
from novel_system.services.style_reference.extractors.language import LanguageExtractor
from novel_system.services.style_reference.extractors.narrative import NarrativeExtractor

__all__ = [
    "BaseExtractor",
    "ExtractionRetryPolicy",
    "ExtractionRunResult",
    "LanguageExtractor",
    "NarrativeExtractor",
]
