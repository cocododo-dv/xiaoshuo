"""两级重试机制单测(PR-3 §6.6)。

5 路径:
- 初次通过(default rule)
- 第一级定向补抽通过(fail_then_pass rule:obs 仅 1 evidence,supplement 补 1)
- 第二级 / 丢弃(evidence_short rule:始终 1 evidence,补抽也无效;最终丢弃 + warning)
- 空结果重抽(empty_then_default rule:初次返回合法空数组,full_retry 拿到内容)
- 持续空结果(always_empty rule:只重抽一次即接受空结果,不死循环)
"""

from __future__ import annotations

from sqlalchemy import select

import pytest

from novel_system.db.models import StyleReferenceExtraction
from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.extractors import (
    ExtractionRetryPolicy,
    LanguageExtractor,
)
from novel_system.services.style_reference.ingest import IngestService
from novel_system.services.style_reference.repository import StyleReferenceRepository


SAMPLE_TEXT = """这是一段比较长的叙述文字,用于让 ingest 能切出多个段落。

他说:"你好啊。"

我心里想着昨天的事,觉得有些不安。

记得那年她还在的时候。

天空忽然变暗了。
"""


def _ingest_and_run(book_seed: str) -> tuple[str, str]:
    with SessionLocal() as session:
        service = IngestService(session, llm_enabled=False)
        result = service.ingest_upload(
            raw_bytes=SAMPLE_TEXT.encode("utf-8"),
            file_name=f"sample_{book_seed}.txt",
            title="t",
            author_label="t",
            cloud_policy="local_only",
        )
        repo = StyleReferenceRepository(session)
        run_id = f"sr_run_{book_seed}"
        repo.create_run(
            run_id=run_id,
            book_id=result.book.book_id,
            status="running",
            phase="extract",
            coverage_json={},
        )
        session.commit()
        return result.book.book_id, run_id


def _extractions_for_run(run_id: str) -> list[StyleReferenceExtraction]:
    with SessionLocal() as session:
        return list(
            session.execute(
                select(StyleReferenceExtraction).where(
                    StyleReferenceExtraction.run_id == run_id
                )
            ).scalars().all()
        )


# ---------------------------------------------------------------------------
# 路径 1:初次通过(default rule)
# ---------------------------------------------------------------------------


def test_retry_path_initial_pass(fake_extractor_llm) -> None:
    book_id, run_id = _ingest_and_run("p1")
    client = fake_extractor_llm("default")

    with SessionLocal() as session:
        extractor = LanguageExtractor(
            session, client, run_id=run_id, book_id=book_id
        )
        results = extractor.extract_all_sub_dimensions()
        session.commit()

    # 4 sub_dim 各产出 4 findings(3 obs + 1 forbid),共 16
    total = sum(len(r.findings) for r in results)
    assert total == 16

    # extractions:4 sub_dim × 1 EXTRACT 行 = 4
    extractions = _extractions_for_run(run_id)
    purposes = [e.purpose for e in extractions]
    assert purposes.count("extract") == 4
    # supplement / full_retry 没出现
    assert "supplement_evidence" not in purposes
    assert "full_retry" not in purposes


# ---------------------------------------------------------------------------
# 路径 2:第一级定向补抽通过(fail_then_pass)
# ---------------------------------------------------------------------------


def test_retry_path_first_level_supplement(fake_extractor_llm) -> None:
    book_id, run_id = _ingest_and_run("p2")
    client = fake_extractor_llm("fail_then_pass")

    with SessionLocal() as session:
        extractor = LanguageExtractor(
            session, client, run_id=run_id, book_id=book_id
        )
        results = extractor.extract_all_sub_dimensions()
        session.commit()

    # 每 sub_dim 初次仅 1 obs(1 evidence)→ supplement 补 1 → 通过
    total = sum(len(r.findings) for r in results)
    assert total >= 4, "每 sub_dim 应至少 1 个 finding 在第一级补抽后存活"

    # extractions 应含 SUPPLEMENT_EVIDENCE 行
    extractions = _extractions_for_run(run_id)
    purposes = [e.purpose for e in extractions]
    assert "supplement_evidence" in purposes


# ---------------------------------------------------------------------------
# 路径 3:第二级 full_retry — evidence_short 始终仅 1,full_retry 也是 1
# ---------------------------------------------------------------------------


def test_retry_path_full_retry_and_drop(fake_extractor_llm) -> None:
    book_id, run_id = _ingest_and_run("p3")
    client = fake_extractor_llm("evidence_short")
    policy = ExtractionRetryPolicy(max_targeted_retries=0, max_full_retries=1)

    with SessionLocal() as session:
        extractor = LanguageExtractor(
            session,
            client,
            run_id=run_id,
            book_id=book_id,
            retry_policy=policy,
        )
        results = extractor.extract_all_sub_dimensions()
        session.commit()

    # 全部 finding 被 drop(evidence 始终 < 2,full_retry 也短)
    total = sum(len(r.findings) for r in results)
    assert total == 0, f"应全部丢弃,实际 {total}"

    # extractions 应含 full_retry 行
    extractions = _extractions_for_run(run_id)
    purposes = [e.purpose for e in extractions]
    assert "full_retry" in purposes, f"应有 full_retry 行,实际 {purposes}"


# ---------------------------------------------------------------------------
# 路径 4:空结果重抽 — 初次返回合法空数组(弱模型"产出薄"),full_retry 拿到内容
# ---------------------------------------------------------------------------


def test_retry_path_empty_result_full_retry(fake_extractor_llm) -> None:
    book_id, run_id = _ingest_and_run("p4")
    client = fake_extractor_llm("empty_then_default")

    with SessionLocal() as session:
        extractor = LanguageExtractor(
            session, client, run_id=run_id, book_id=book_id
        )
        results = extractor.extract_all_sub_dimensions()
        session.commit()

    # 每 sub_dim 初次空 → full_retry 第二次拿到 3 obs + 1 forbid,共 16
    total = sum(len(r.findings) for r in results)
    assert total == 16, f"空结果重抽后应拿到 16 findings,实际 {total}"

    extractions = _extractions_for_run(run_id)
    purposes = [e.purpose for e in extractions]
    assert purposes.count("full_retry") == 4, f"每 sub_dim 应 1 次 full_retry,实际 {purposes}"


# ---------------------------------------------------------------------------
# 路径 5:持续空结果 — 只重抽一次(受 max_full_retries 预算),之后接受空结果
# ---------------------------------------------------------------------------


def test_retry_path_always_empty_accepts_after_one_retry(fake_extractor_llm) -> None:
    book_id, run_id = _ingest_and_run("p5")
    client = fake_extractor_llm("always_empty")

    with SessionLocal() as session:
        extractor = LanguageExtractor(
            session, client, run_id=run_id, book_id=book_id
        )
        results = extractor.extract_all_sub_dimensions()
        session.commit()

    total = sum(len(r.findings) for r in results)
    assert total == 0

    # 每 sub_dim 恰好 2 次 LLM 调用(初抽 + 1 次空结果重抽),不得死循环
    assert client.call_count == 8, f"4 sub_dim × 2 次调用,实际 {client.call_count}"

    extractions = _extractions_for_run(run_id)
    purposes = [e.purpose for e in extractions]
    assert purposes.count("full_retry") == 4, f"应各 1 次 full_retry,实际 {purposes}"
