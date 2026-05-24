"""RunOrchestrator — Style Reference 抽取 run 编排。

§14 PR-3:启动 run + LLMRequiredError + 按 layers 调度 LanguageExtractor /
NarrativeExtractor;PR-3 内只支持 language / narrative;scene / theme 在 PR-6 加。
"""

from __future__ import annotations

import logging
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from novel_system.services.errors import DomainError
from novel_system.services.style_reference.dimensions import Layer
from novel_system.services.style_reference.errors import LLMRequiredError
from novel_system.services.style_reference.extractors import (
    BaseExtractor,
    ExtractionRetryPolicy,
    ExtractionRunResult,
    LanguageExtractor,
    NarrativeExtractor,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import RunPhase, RunStatus

logger = logging.getLogger(__name__)


# layer.value → BaseExtractor 子类
_LAYER_EXTRACTOR_MAP: dict[Layer, type[BaseExtractor]] = {
    Layer.LANGUAGE: LanguageExtractor,
    Layer.NARRATIVE: NarrativeExtractor,
}


@dataclass
class RunResult:
    """run 编排执行后的摘要。"""

    run_id: str
    book_id: str
    status: str
    layers: list[str] = field(default_factory=list)
    sub_dim_results: list[ExtractionRunResult] = field(default_factory=list)


class RunOrchestrator:
    """启动 run + 按 layers 调度 extractors + 落 4 表 + 更新 run.status。"""

    def __init__(
        self,
        session: Session,
        *,
        llm_client: Any | None = None,
        llm_enabled: bool | None = None,
        retry_policy: ExtractionRetryPolicy | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.session = session
        self.repo = StyleReferenceRepository(session)
        self._llm_client = llm_client
        if llm_enabled is None:
            from novel_system.settings import get_settings

            llm_enabled = bool(get_settings().llm_enabled)
        self._llm_enabled = llm_enabled
        self._retry_policy = retry_policy or ExtractionRetryPolicy()
        self._rng = rng or random.Random()

    def start_extract_run(
        self,
        book_id: str,
        *,
        layers: list[Layer] | None = None,
        idempotency_key: str | None = None,  # noqa: ARG002 (预留 PR-4 路由层接入)
    ) -> RunResult:
        """启动一次抽取 run;LLM 不可用 raise DomainError(STYLE_REFERENCE_LLM_REQUIRED)。"""
        if not self._llm_enabled or self._llm_client is None:
            raise LLMRequiredError(operation="start_extract_run")

        book = self.repo.get_book(book_id)
        if book is None:
            raise DomainError(
                "STYLE_REFERENCE_BOOK_NOT_FOUND",
                f"book {book_id!r} not found",
                status_code=404,
            )

        layers = layers or [Layer.LANGUAGE, Layer.NARRATIVE]
        unknown = [layer for layer in layers if layer not in _LAYER_EXTRACTOR_MAP]
        if unknown:
            raise DomainError(
                "STYLE_REFERENCE_LAYER_NOT_SUPPORTED",
                f"PR-3 only supports language + narrative;{unknown!r} 推迟到 PR-6",
                status_code=400,
            )

        run_id = f"sr_run_{uuid.uuid4().hex[:12]}"
        self.repo.create_run(
            run_id=run_id,
            book_id=book_id,
            status=RunStatus.RUNNING.value,
            phase=RunPhase.EXTRACT.value,
            coverage_json={},
        )

        sub_dim_results: list[ExtractionRunResult] = []
        try:
            for layer in layers:
                extractor_cls = _LAYER_EXTRACTOR_MAP[layer]
                extractor = extractor_cls(
                    self.session,
                    self._llm_client,
                    run_id=run_id,
                    book_id=book_id,
                    retry_policy=self._retry_policy,
                    rng=self._rng,
                )
                sub_dim_results.extend(extractor.extract_all_sub_dimensions())
        except Exception:
            self.repo.update_run(run_id, status=RunStatus.FAILED.value)
            raise

        self.repo.update_run(
            run_id,
            status=RunStatus.DONE.value,
            phase=RunPhase.DONE.value,
            coverage_json={
                "sub_dimensions": {
                    r.sub_dimension.value: {
                        "findings": len(r.findings),
                        "extractions": r.extractions_created,
                    }
                    for r in sub_dim_results
                }
            },
        )

        return RunResult(
            run_id=run_id,
            book_id=book_id,
            status=RunStatus.DONE.value,
            layers=[layer.value for layer in layers],
            sub_dim_results=sub_dim_results,
        )
