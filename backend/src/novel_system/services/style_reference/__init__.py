"""Style Reference (style_reference) service package.

PR-1 scope: schema 落地 only. 仅导出枚举 / 错误体系 / 仓储 / cleanup。
业务编排(extract / inject / validate)在后续 PR 中分别落地。

参见 plans/style-reference-v1-1-fancy-shannon.md 与
《风格参考模块重构执行手册 v1.1》§4 / §14。
"""

from __future__ import annotations

from novel_system.services.style_reference.dimensions import (
    LAYER_TO_SUB_DIMS,
    Layer,
    SubDimension,
)
from novel_system.services.style_reference.errors import (
    BannedAdjectiveError,
    DuplicateBookError,
    EmptyBookError,
    EvidenceShortError,
    EvidenceSpanError,
    LegacyBackupMissingError,
    StyleReferenceError,
)
from novel_system.services.style_reference.ingest import IngestResult, IngestService, assess_input_size
from novel_system.services.style_reference.metrics import (
    METRIC_NAMES,
    MetricName,
    MetricsEngine,
    ParagraphRecord,
)
from novel_system.services.style_reference.segmentation import (
    ParagraphClassification,
    SegmentationLLMError,
    SegmentationResult,
    classify_paragraphs,
)
from novel_system.services.style_reference.schemas import (
    AnchorKind,
    BannedTermScope,
    BindingScope,
    BindingStatus,
    BookStatus,
    CloudPolicy,
    ExtractionPurpose,
    ExtractionStatus,
    FindingKind,
    FindingStatus,
    InjectionStrategy,
    InputAssessmentLevel,
    ParagraphType,
    ProfileStatus,
    RunPhase,
    RunStatus,
    StyleReferenceBannedTermRow,
    StyleReferenceBookRow,
    StyleReferenceEvidenceRow,
    StyleReferenceExtractionRow,
    StyleReferenceFindingRow,
    StyleReferenceInjectionBindingRow,
    StyleReferenceParagraphRow,
    StyleReferenceProfileRow,
    StyleReferenceQuoteRow,
    StyleReferenceRunRow,
    StyleReferenceValidationReportRow,
    TaskType,
    ValidationMode,
    ValidationTargetKind,
    ValidationVerdict,
)

__all__ = [
    "Layer",
    "SubDimension",
    "LAYER_TO_SUB_DIMS",
    "ParagraphType",
    "FindingKind",
    "AnchorKind",
    "BookStatus",
    "ExtractionStatus",
    "ExtractionPurpose",
    "FindingStatus",
    "RunStatus",
    "RunPhase",
    "ProfileStatus",
    "BindingScope",
    "BindingStatus",
    "InjectionStrategy",
    "TaskType",
    "ValidationVerdict",
    "ValidationMode",
    "ValidationTargetKind",
    "BannedTermScope",
    "InputAssessmentLevel",
    "CloudPolicy",
    "StyleReferenceError",
    "BannedAdjectiveError",
    "EvidenceShortError",
    "EvidenceSpanError",
    "LegacyBackupMissingError",
    "DuplicateBookError",
    "EmptyBookError",
    "IngestService",
    "IngestResult",
    "assess_input_size",
    "MetricsEngine",
    "ParagraphRecord",
    "MetricName",
    "METRIC_NAMES",
    "classify_paragraphs",
    "ParagraphClassification",
    "SegmentationResult",
    "SegmentationLLMError",
    "StyleReferenceBookRow",
    "StyleReferenceParagraphRow",
    "StyleReferenceExtractionRow",
    "StyleReferenceQuoteRow",
    "StyleReferenceEvidenceRow",
    "StyleReferenceFindingRow",
    "StyleReferenceRunRow",
    "StyleReferenceProfileRow",
    "StyleReferenceInjectionBindingRow",
    "StyleReferenceValidationReportRow",
    "StyleReferenceBannedTermRow",
]
