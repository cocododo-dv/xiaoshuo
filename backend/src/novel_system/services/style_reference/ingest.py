"""Style Reference v1.1 导入服务。

依据《风格参考模块重构执行手册 v1.1》§6.2 / §6.4。

流程:
  1. 解码 + 清洗 → normalized text
  2. SHA256 checksum 计算 → book_id = "sr_book_{checksum[:12]}"
  3. 去重检测(同 checksum 已存在则 raise DuplicateBookError)
  4. cloud_policy 校验(Pydantic CloudPolicy)
  5. source_safety.scan_source_safety(text) 扫描(blocked_terms / risks)
  6. assess_input_size(total_chars) → stats_json.input_assessment
  7. split_paragraphs(text) → list of (start, end, body)
  8. segmentation.classify_paragraphs(...) → SegmentationResult
  9. MetricsEngine.compute_with_variance(records) → stats_json.metrics
 10. 落 style_reference_books + style_reference_paragraphs 表
 11. book.status = "ready"

`idempotency_key` 参数预留;PR-4 加 route 时由路由层包装
`execute_with_idempotency` 实际接入。本 service 不直接调用幂等机制。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from novel_system.db.models import StyleReferenceBook, StyleReferenceParagraph
from novel_system.services.errors import DomainError
from novel_system.services.source_safety import scan_source_safety
from novel_system.services.style_reference.config_loader import load_yaml_config
from novel_system.services.style_reference.errors import DuplicateBookError, EmptyBookError
from novel_system.services.style_reference.metrics import MetricsEngine, ParagraphRecord
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import CloudPolicy
from novel_system.services.style_reference.segmentation import classify_paragraphs
from novel_system.services.style_reference.text_utils import (
    compute_text_checksum,
    decode_text,
    normalize_text,
    split_paragraphs,
)


@dataclass
class IngestResult:
    """ingest_path / ingest_upload 的返回结构。"""

    book: StyleReferenceBook
    paragraphs_count: int
    safety_payload: dict[str, Any]


def assess_input_size(total_chars: int) -> dict[str, str]:
    """按 input_thresholds.yaml 把总字数映射到 4 层级。

    返回 {"language": "skip"|"low"|"medium"|"high", ...} 4 个 layer。
    """
    thresholds = load_yaml_config("input_thresholds")
    result: dict[str, str] = {}
    for layer in ("language", "narrative", "scene", "theme"):
        cfg = thresholds.get(layer, {})
        skip = int(cfg.get("skip", 0))
        low = int(cfg.get("low", skip))
        high = int(cfg.get("high", low))
        if total_chars < skip:
            level = "skip"
        elif total_chars < low:
            level = "low"
        elif total_chars < high:
            level = "medium"
        else:
            level = "high"
        result[layer] = level
    return result


class IngestService:
    """Style Reference 书籍导入服务。"""

    def __init__(self, session: Session, *, llm_client: Any | None = None, llm_enabled: bool | None = None) -> None:
        self.session = session
        self.repo = StyleReferenceRepository(session)
        self._llm_client = llm_client
        if llm_enabled is None:
            from novel_system.settings import get_settings

            llm_enabled = bool(get_settings().llm_enabled)
        self._llm_enabled = llm_enabled
        self._metrics_engine: MetricsEngine | None = None

    # ------------------------------------------------------------------ public

    def ingest_path(
        self,
        file_path: str | Path,
        *,
        title: str,
        author_label: str | None,
        cloud_policy: str | CloudPolicy,
        idempotency_key: str | None = None,  # noqa: ARG002 (预留 PR-4 用)
    ) -> IngestResult:
        path = Path(file_path)
        if not path.exists():
            raise DomainError(
                "STYLE_REFERENCE_BOOK_PATH_NOT_FOUND",
                f"reference book path does not exist: {path}",
                status_code=404,
            )
        raw = path.read_bytes()
        return self._ingest_bytes(
            raw_bytes=raw,
            source_kind="path",
            source_path=str(path),
            title=title,
            author_label=author_label,
            cloud_policy=cloud_policy,
        )

    def ingest_upload(
        self,
        raw_bytes: bytes,
        *,
        file_name: str | None,
        title: str,
        author_label: str | None,
        cloud_policy: str | CloudPolicy,
        idempotency_key: str | None = None,  # noqa: ARG002 (预留 PR-4 用)
    ) -> IngestResult:
        if file_name:
            suffix = Path(file_name).suffix.lower()
            if suffix and suffix not in {".txt", ".md", ".markdown"}:
                raise DomainError(
                    "STYLE_REFERENCE_BOOK_FORMAT_UNSUPPORTED",
                    "only TXT and MD reference books are supported",
                    status_code=400,
                )
        return self._ingest_bytes(
            raw_bytes=raw_bytes,
            source_kind="upload",
            source_path=file_name,
            title=title,
            author_label=author_label,
            cloud_policy=cloud_policy,
        )

    # ----------------------------------------------------------------- private

    def _ingest_bytes(
        self,
        *,
        raw_bytes: bytes,
        source_kind: str,
        source_path: str | None,
        title: str,
        author_label: str | None,
        cloud_policy: str | CloudPolicy,
    ) -> IngestResult:
        normalized = normalize_text(decode_text(raw_bytes))
        if not normalized:
            raise EmptyBookError("normalize")

        # cloud_policy Pydantic 校验
        policy = CloudPolicy(cloud_policy) if isinstance(cloud_policy, str) else cloud_policy

        checksum = compute_text_checksum(normalized)
        book_id = f"sr_book_{checksum[:12]}"

        existing = self.repo.get_book(book_id)
        if existing is not None:
            raise DuplicateBookError(book_id=book_id, checksum=checksum)

        # Safety 扫描(通用 source_safety,与 reference_safety 解耦)
        safety_payload = scan_source_safety(normalized)

        # 段落切分
        paragraph_spans = split_paragraphs(normalized)
        if not paragraph_spans:
            raise EmptyBookError("segmentation")

        # LLM / 启发式分类
        seg_result = classify_paragraphs(
            paragraph_spans,
            llm_enabled=self._llm_enabled,
            llm_client=self._llm_client,
        )

        # 构造 ParagraphRecord 用于 MetricsEngine
        records = [
            ParagraphRecord(
                text=body,
                paragraph_type=c.paragraph_type,
            )
            for (_s, _e, body), c in zip(paragraph_spans, seg_result.classifications)
        ]

        engine = self._get_metrics_engine()
        metrics_with_var = engine.compute_with_variance(records)
        sample_count = len(records)
        metrics_block: dict[str, dict[str, float | int]] = {
            name: {"mean": float(mean), "std": float(std), "sample_count": sample_count}
            for name, (mean, std) in metrics_with_var.items()
        }

        input_assessment = assess_input_size(len(normalized))
        type_counter = Counter(c.paragraph_type for c in seg_result.classifications)
        type_distribution = {
            ptype: round(count / sample_count, 4)
            for ptype, count in type_counter.items()
        } if sample_count else {}

        stats_json = {
            "metrics": metrics_block,
            "input_assessment": input_assessment,
            "classifier_calibration": seg_result.calibration,
            "paragraph_type_distribution": type_distribution,
            "safety": safety_payload,
        }

        book = self.repo.create_book(
            book_id=book_id,
            title=title,
            author_label=author_label,
            source_kind=source_kind,
            source_path=source_path,
            cloud_policy=policy.value,
            text_checksum=checksum,
            total_chars=len(normalized),
            status="ready",
            stats_json=stats_json,
        )

        # 落段落表
        for idx, ((start, end, body), c) in enumerate(zip(paragraph_spans, seg_result.classifications)):
            self.repo.create_paragraph(
                paragraph_id=f"sr_para_{checksum[:8]}_{idx:04d}",
                book_id=book_id,
                paragraph_index=idx,
                paragraph_type=c.paragraph_type,
                start_offset=start,
                end_offset=end,
                text=body,
                char_count=len(body),
                classifier_confidence=float(c.confidence),
            )

        return IngestResult(
            book=book,
            paragraphs_count=len(paragraph_spans),
            safety_payload=safety_payload,
        )

    def _get_metrics_engine(self) -> MetricsEngine:
        if self._metrics_engine is None:
            self._metrics_engine = MetricsEngine()
        return self._metrics_engine
