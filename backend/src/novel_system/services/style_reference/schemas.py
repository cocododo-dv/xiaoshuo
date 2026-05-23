"""PR-1 范围:全枚举 + 11 张新表 row-shape Pydantic 契约。

仅落地与 ORM 列 1:1 的 Row 模型 + 所有枚举(后续 PR 命名约束基线)。
高阶契约 InjectionRequest / InjectionBundle / SystemPromptFragments /
ValidateRequest / ValidationReport / SemanticReport 等推迟到对应 PR。

依据《风格参考模块重构执行手册 v1.1》§4 / §5.1 / §5.2 / §6.5 / §7。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# 全枚举清单(PR-1 落齐,作为后续 PR 命名约束)
# ---------------------------------------------------------------------------


class ParagraphType(str, Enum):
    """8 类段落类型,LLM 分类器输出值域。来源:§4.3 stats_json / §6.5。"""

    DIALOGUE = "dialogue"
    NARRATION = "narration"
    PSYCHOLOGY = "psychology"
    DESCRIPTION_ENV = "description_env"
    DESCRIPTION_CHAR = "description_char"
    ACTION = "action"
    TRANSITION = "transition"
    FLASHBACK = "flashback"


class FindingKind(str, Enum):
    """正向观察 / 反向禁忌。来源:§4.3 findings.finding_kind / §6.5。"""

    OBSERVATION = "observation"
    FORBIDDEN_PATTERN = "forbidden_pattern"


class AnchorKind(str, Enum):
    """evidence 锚点类型。来源:§4.3 evidences.anchor_kind / §6.5。"""

    PARAGRAPH_QUOTE = "paragraph_quote"
    AUTHOR_AVOIDANCE = "author_avoidance"
    COUNTER_EXAMPLE = "counter_example"


class ConfidenceLevel(str, Enum):
    """finding / sub_dimension 置信度。来源:§4.3 profile_json.sub_dimensions。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BookStatus(str, Enum):
    PENDING = "pending"
    INGESTING = "ingesting"
    READY = "ready"
    FAILED = "failed"


class ExtractionStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class ExtractionPurpose(str, Enum):
    """两级重试链路追溯。来源:§4.3 extractions.purpose / §6.6。"""

    EXTRACT = "extract"
    SUPPLEMENT_EVIDENCE = "supplement_evidence"
    FULL_RETRY = "full_retry"


class FindingStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunPhase(str, Enum):
    INGEST = "ingest"
    EXTRACT = "extract"
    SYNTHESIZE = "synthesize"
    DONE = "done"


class ProfileStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class BindingScope(str, Enum):
    """注入绑定的目标范围。来源:§4.2 injection_bindings.scope / §8.1 ProfileApplyDialog。"""

    PROJECT = "project"
    SCENE = "scene"
    CHARACTER = "character"


class BindingStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class InjectionStrategy(str, Enum):
    """A=System Prompt / B=Few-shot / C=RAG / mixed。来源:§5.1 / §6 注入策略。"""

    A = "A"
    B = "B"
    C = "C"
    MIXED = "mixed"


class TaskType(str, Enum):
    """注入策略默认表的 key。来源:§5.1 TaskType。"""

    PROJECT_INIT = "project_init"
    SCENE_GENERATION = "scene_generation"
    FINE_TUNING = "fine_tuning"
    LONG_FORM_CONTINUATION = "long_form_continuation"
    KEY_CHAPTER = "key_chapter"


class ValidationVerdict(str, Enum):
    """来源:§7.5 _compute_verdict。"""

    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    PLAGIARISM = "plagiarism"


class ValidationMode(str, Enum):
    """来源:§4.3 validation_reports.mode_executed / §5.2 ValidateRequest.mode。"""

    SYNC_ONLY = "sync_only"
    ASYNC_FULL = "async_full"


class ValidationTargetKind(str, Enum):
    """来源:§5.2 ValidateRequest.target_kind。"""

    SCENE = "scene"
    CHAPTER = "chapter"
    MANUAL = "manual"


class BannedTermScope(str, Enum):
    """来源:§4.3 banned_terms.scope。"""

    GENERATION = "generation"
    EXTRACTION = "extraction"


class InputAssessmentLevel(str, Enum):
    """来源:§6.4 assess_input_size。"""

    SKIP = "skip"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CloudPolicy(str, Enum):
    """沿用仓库现有 cloud_policy 三档,不改语义。"""

    LOCAL_ONLY = "local_only"
    HYBRID = "hybrid"
    CLOUD_FULL = "cloud_full"


# ---------------------------------------------------------------------------
# 11 张新表 row-shape Pydantic(字段与 ORM 列 1:1)
# ---------------------------------------------------------------------------


class _StyleReferenceRowBase(BaseModel):
    """所有 row 模型基类:允许从 ORM 实例直接 model_validate。"""

    model_config = ConfigDict(from_attributes=True, use_enum_values=True, extra="forbid")


class StyleReferenceBookRow(_StyleReferenceRowBase):
    book_id: str
    title: str
    author_label: str | None = None
    source_kind: str
    source_path: str | None = None
    cloud_policy: CloudPolicy
    text_checksum: str
    total_chars: int = 0
    status: BookStatus = BookStatus.PENDING
    stats_json: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class StyleReferenceParagraphRow(_StyleReferenceRowBase):
    paragraph_id: str
    book_id: str
    paragraph_index: int
    paragraph_type: ParagraphType
    start_offset: int
    end_offset: int
    text: str
    char_count: int
    classifier_confidence: float
    created_at: str


class StyleReferenceExtractionRow(_StyleReferenceRowBase):
    extraction_id: str
    book_id: str
    run_id: str
    layer: str
    sub_dimension: str
    llm_call_id: str | None = None
    raw_payload_json: dict[str, Any] = Field(default_factory=dict)
    status: ExtractionStatus = ExtractionStatus.PENDING
    validation_errors_json: list[dict[str, Any]] = Field(default_factory=list)
    purpose: ExtractionPurpose = ExtractionPurpose.EXTRACT
    created_at: str
    updated_at: str


class StyleReferenceQuoteRow(_StyleReferenceRowBase):
    quote_id: str
    book_id: str
    paragraph_id: str | None = None
    span_start: int
    span_end: int
    quote_text: str
    illustrates_dims: list[str] = Field(default_factory=list)
    extracted_features: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class StyleReferenceEvidenceRow(_StyleReferenceRowBase):
    evidence_id: str
    finding_id: str
    quote_id: str
    anchor_kind: AnchorKind
    is_synthetic: int = 0
    created_at: str


class StyleReferenceFindingRow(_StyleReferenceRowBase):
    finding_id: str
    book_id: str
    run_id: str
    extraction_id: str
    sub_dimension: str
    finding_kind: FindingKind
    statement: str
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    status: FindingStatus = FindingStatus.PENDING
    review_id: str | None = None
    created_at: str
    updated_at: str


class StyleReferenceRunRow(_StyleReferenceRowBase):
    run_id: str
    book_id: str
    status: RunStatus = RunStatus.PENDING
    phase: RunPhase = RunPhase.INGEST
    coverage_json: dict[str, Any] = Field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None
    created_at: str
    updated_at: str


class StyleReferenceProfileRow(_StyleReferenceRowBase):
    profile_id: str
    book_id: str
    run_id: str
    title: str
    status: ProfileStatus = ProfileStatus.DRAFT
    profile_json: dict[str, Any] = Field(default_factory=dict)
    coverage_json: dict[str, Any] = Field(default_factory=dict)
    source_finding_ids_json: list[str] = Field(default_factory=list)
    version_tag: str | None = None
    created_at: str
    updated_at: str


class StyleReferenceInjectionBindingRow(_StyleReferenceRowBase):
    binding_id: str
    profile_id: str
    scope: BindingScope
    scope_ref_id: str | None = None
    task_type: TaskType
    strategy: InjectionStrategy
    config_json: dict[str, Any] = Field(default_factory=dict)
    status: BindingStatus = BindingStatus.ACTIVE
    created_at: str
    updated_at: str


class StyleReferenceValidationReportRow(_StyleReferenceRowBase):
    report_id: str
    profile_id: str
    target_kind: ValidationTargetKind
    target_ref_id: str | None = None
    verdict: ValidationVerdict
    quantitative_json: list[dict[str, Any]] = Field(default_factory=list)
    semantic_json: list[dict[str, Any]] = Field(default_factory=list)
    plagiarism_json: dict[str, Any] = Field(default_factory=dict)
    forbidden_hits_json: list[dict[str, Any]] = Field(default_factory=list)
    mode_executed: ValidationMode = ValidationMode.ASYNC_FULL
    created_at: str


class StyleReferenceBannedTermRow(_StyleReferenceRowBase):
    term_id: str
    profile_id: str
    term: str
    replacement_hint: str | None = None
    source: str
    scope: BannedTermScope = BannedTermScope.GENERATION
    created_at: str
    updated_at: str
