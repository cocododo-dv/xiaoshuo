"""Dependency-free result types for paragraph segmentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParagraphClassification:
    paragraph_index: int
    paragraph_type: str
    confidence: float
    classifier_confidence_level: str = "medium"


@dataclass
class SegmentationResult:
    classifications: list[ParagraphClassification]
    calibration: dict[str, Any] = field(default_factory=dict)
