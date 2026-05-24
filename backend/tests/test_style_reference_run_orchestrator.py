"""RunOrchestrator 单测:LLMRequiredError / book_not_found / 落 4 表行数(PR-3)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from novel_system.db.models import (
    StyleReferenceEvidence,
    StyleReferenceExtraction,
    StyleReferenceFinding,
    StyleReferenceQuote,
)
from novel_system.db.session import SessionLocal
from novel_system.services.errors import DomainError
from novel_system.services.style_reference.dimensions import Layer
from novel_system.services.style_reference.errors import LLMRequiredError
from novel_system.services.style_reference.ingest import IngestService
from novel_system.services.style_reference.run_orchestrator import RunOrchestrator


SAMPLE_TEXT = """这是叙述段落 0,介绍清晨场景与人物心情,长度足够触发分段。

他说:"我们走吧。"

我心里想着家中的事。

记得那年的春天。

雪花从天空飘落。
"""


def _ingest(book_seed: str = "s") -> str:
    with SessionLocal() as session:
        service = IngestService(session, llm_enabled=False)
        result = service.ingest_upload(
            raw_bytes=SAMPLE_TEXT.encode("utf-8"),
            file_name=f"book_{book_seed}.txt",
            title="t",
            author_label="t",
            cloud_policy="local_only",
        )
        session.commit()
        return result.book.book_id


# ---------------------------------------------------------------------------
# LLM 不可用
# ---------------------------------------------------------------------------


def test_run_orchestrator_raises_llm_required_when_disabled() -> None:
    book_id = _ingest("disabled")
    with SessionLocal() as session:
        orch = RunOrchestrator(session, llm_client=None, llm_enabled=False)
        with pytest.raises(LLMRequiredError):
            orch.start_extract_run(book_id)


def test_run_orchestrator_book_not_found(fake_extractor_llm) -> None:
    with SessionLocal() as session:
        orch = RunOrchestrator(
            session, llm_client=fake_extractor_llm("default"), llm_enabled=True
        )
        with pytest.raises(DomainError) as exc_info:
            orch.start_extract_run("sr_book_nonexistent")
        assert exc_info.value.code == "STYLE_REFERENCE_BOOK_NOT_FOUND"


def test_run_orchestrator_layer_not_supported(fake_extractor_llm) -> None:
    book_id = _ingest("layer_check")
    with SessionLocal() as session:
        orch = RunOrchestrator(
            session, llm_client=fake_extractor_llm("default"), llm_enabled=True
        )
        with pytest.raises(DomainError) as exc_info:
            orch.start_extract_run(book_id, layers=[Layer.SCENE])
        assert exc_info.value.code == "STYLE_REFERENCE_LAYER_NOT_SUPPORTED"


# ---------------------------------------------------------------------------
# happy path:8 sub_dim × default → 32 findings,落 4 表
# ---------------------------------------------------------------------------


def test_run_orchestrator_happy_path_writes_4_tables(fake_extractor_llm) -> None:
    book_id = _ingest("happy")
    with SessionLocal() as session:
        orch = RunOrchestrator(
            session, llm_client=fake_extractor_llm("default"), llm_enabled=True
        )
        result = orch.start_extract_run(book_id)
        session.commit()

    assert result.status == "done"
    assert set(result.layers) == {"language", "narrative"}
    assert len(result.sub_dim_results) == 8

    # 4 表行数断言
    with SessionLocal() as session:
        ext_count = session.scalar(
            select(func.count()).select_from(StyleReferenceExtraction)
        )
        find_count = session.scalar(
            select(func.count()).select_from(StyleReferenceFinding)
        )
        quote_count = session.scalar(
            select(func.count()).select_from(StyleReferenceQuote)
        )
        ev_count = session.scalar(
            select(func.count()).select_from(StyleReferenceEvidence)
        )

    # 8 sub_dim × 1 EXTRACT 行 = 8
    assert ext_count == 8
    # 8 sub_dim × (3 obs + 1 forbid) = 32
    assert find_count == 32
    # 32 finding × 2 evidence = 64 evidence/quote
    assert ev_count == 64
    assert quote_count == 64
