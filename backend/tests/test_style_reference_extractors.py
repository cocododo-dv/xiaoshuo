"""LanguageExtractor + NarrativeExtractor 抽取 happy path 与边界(PR-3)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.extractors import (
    LanguageExtractor,
    NarrativeExtractor,
)
from novel_system.services.style_reference.ingest import IngestService
from novel_system.services.style_reference.repository import StyleReferenceRepository


SAMPLE_TEXT = """第一段是一段比较长的叙述文字,描绘清晨雾气弥漫的街口与零星行人的脚步声,气氛安静而略带寒意。

他说:"今天天气真好,看来要出太阳了。"

我心里想着昨天的事情,觉得一阵难以言说的不安,暗忖该如何回应他。

记得那年她还在的时候,我们一起去过河边,看稻穗在风中起伏,鸭子在水里游动。

天空忽然暗了下来。

他低头看着脚下的路,脸色一阵苍白,眼神疲惫。

她转身,推开木门,跑出院子,沿着小路一路向前。

屋外的山脚下,雪花静静地飘落,覆盖了远处的村庄、树林和河面。
"""


def _ingest_book(book_id_seed: str = "x") -> str:
    """便利函数:用 IngestService 在当前 session 中导入一份 placeholder。"""
    with SessionLocal() as session:
        service = IngestService(session, llm_enabled=False)
        result = service.ingest_upload(
            raw_bytes=SAMPLE_TEXT.encode("utf-8"),
            file_name=f"sample_{book_id_seed}.txt",
            title="测试样本",
            author_label="测试",
            cloud_policy="local_only",
        )
        session.commit()
        return result.book.book_id


def _make_run(book_id: str) -> str:
    """便利函数:建一个 run 行供 extractor 关联。"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        run_id = "sr_run_test_1"
        repo.create_run(
            run_id=run_id,
            book_id=book_id,
            status="running",
            phase="extract",
            coverage_json={},
        )
        session.commit()
    return run_id


# ---------------------------------------------------------------------------
# LanguageExtractor happy path
# ---------------------------------------------------------------------------


def test_language_extractor_happy_path(fake_extractor_llm) -> None:
    book_id = _ingest_book("lang_happy")
    run_id = _make_run(book_id)
    client = fake_extractor_llm("default")

    with SessionLocal() as session:
        extractor = LanguageExtractor(
            session, client, run_id=run_id, book_id=book_id
        )
        results = extractor.extract_all_sub_dimensions()
        session.commit()

    assert len(results) == 4, "language 层 4 sub_dim"
    # 每 sub_dim default rule 应产出 3 obs + 1 forbid
    for r in results:
        kinds = [f.finding_kind for f in r.findings]
        observations = [k for k in kinds if k.value == "observation"]
        forbids = [k for k in kinds if k.value == "forbidden_pattern"]
        assert len(observations) == 3, f"{r.sub_dimension.value} obs count {len(observations)}"
        assert len(forbids) == 1, f"{r.sub_dimension.value} forbid count {len(forbids)}"


def test_narrative_extractor_happy_path(fake_extractor_llm) -> None:
    book_id = _ingest_book("narr_happy")
    run_id = _make_run(book_id)
    client = fake_extractor_llm("default")

    with SessionLocal() as session:
        extractor = NarrativeExtractor(
            session, client, run_id=run_id, book_id=book_id
        )
        results = extractor.extract_all_sub_dimensions()
        session.commit()

    assert len(results) == 4, "narrative 层 4 sub_dim"
    # 验证写入了 findings 表
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        findings = repo.list_findings(book_id=book_id)
        # 4 sub_dim * 4 findings = 16
        assert len(findings) == 16


# ---------------------------------------------------------------------------
# BannedAdjective:命中即丢弃
# ---------------------------------------------------------------------------


def test_extractor_drops_banned_adjective_findings(fake_extractor_llm) -> None:
    book_id = _ingest_book("banned")
    run_id = _make_run(book_id)
    client = fake_extractor_llm("all_banned")

    with SessionLocal() as session:
        extractor = LanguageExtractor(
            session, client, run_id=run_id, book_id=book_id
        )
        results = extractor.extract_all_sub_dimensions()
        session.commit()

    # 所有 obs 被丢弃 → findings 数 = 0
    for r in results:
        assert len(r.findings) == 0, (
            f"{r.sub_dimension.value} 应因 banned_adjective 全部丢弃,实际 {len(r.findings)}"
        )


# ---------------------------------------------------------------------------
# metrics_anchor 注入(LLM call_log 验证 user_msg 含 metrics_anchor 字段)
# ---------------------------------------------------------------------------


def test_metrics_anchor_injected_into_prompt(fake_extractor_llm, monkeypatch) -> None:
    book_id = _ingest_book("metrics_anchor")
    run_id = _make_run(book_id)
    client = fake_extractor_llm("default")
    captured: list[str] = []

    original_generate = client.generate

    def _spy_generate(request):  # noqa: ANN001
        captured.append(request.messages[-1]["content"])
        return original_generate(request)

    client.generate = _spy_generate  # type: ignore[method-assign]

    with SessionLocal() as session:
        extractor = LanguageExtractor(
            session, client, run_id=run_id, book_id=book_id
        )
        extractor.extract_all_sub_dimensions()
        session.commit()

    assert captured, "应至少有一次 LLM 调用"
    # extract_language 调用的 user_msg 必含 metrics_anchor 字段
    extract_calls = [
        c for c in captured if '"metrics_anchor"' in c
    ]
    assert extract_calls, "user_msg 应注入 metrics_anchor 字段"
