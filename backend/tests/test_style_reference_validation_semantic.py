"""Semantic + forbidden_semantic validation 单测(PR-7)。"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference._llm_helper import LLMNodeError
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.validation.forbidden_semantic import (
    check_forbidden_semantic,
)
from novel_system.services.style_reference.validation.semantic import check_semantic


@dataclass
class _FakeProfile:
    profile_json: dict
    source_finding_ids_json: list[str]
    book_id: str = "sr_book_test"
    profile_id: str = "sr_profile_test"


def _profile_simple(style_features=None, narrative_summary="风格摘要") -> _FakeProfile:
    return _FakeProfile(
        profile_json={
            "style_features": style_features or ["短句", "白描"],
            "narrative_summary": narrative_summary,
        },
        source_finding_ids_json=[],
    )


class _StubResp:
    def __init__(self, structured: dict) -> None:
        self.structured_output = structured
        self.text = json.dumps(structured, ensure_ascii=False)
        self.usage: dict = {}
        self.finish_reason = "stop"
        self.provider = "fake"
        self.model = "fake"
        self.response_format = "json_object"
        self.request_id = None
        self.raw_response: dict = {}


def _fake_client_returning(structured):
    class _Cli:
        def generate(self, request):  # noqa: ANN001
            return _StubResp(structured)
    return _Cli()


def _fake_client_failing():
    class _Cli:
        def generate(self, request):  # noqa: ANN001
            raise RuntimeError("network down")
    return _Cli()


# ---------------------------------------------------------------------------
# Semantic
# ---------------------------------------------------------------------------


def test_semantic_with_quote_preserves_score() -> None:
    client = _fake_client_returning(
        {
            "dimension_scores": [
                {"dimension": "rhythm", "score": 8.5, "explanation": "节奏紧凑,如「他低头看着脚下的路」"},
            ]
        }
    )
    reports = check_semantic("生成文本", _profile_simple(), client)
    assert len(reports) == 1
    assert reports[0].quotes_found is True
    assert reports[0].score == 8.5


def test_semantic_no_quote_clips_score_to_4() -> None:
    client = _fake_client_returning(
        {
            "dimension_scores": [
                {"dimension": "tone", "score": 9.0, "explanation": "情绪克制流畅有质感"},
            ]
        }
    )
    reports = check_semantic("生成文本", _profile_simple(), client)
    assert reports[0].quotes_found is False
    assert reports[0].score == 4.0


def test_semantic_llm_failure_raises() -> None:
    """LLM 失败应 raise LLMNodeError(caller runner.py 负责降级)。"""
    client = _fake_client_failing()
    with pytest.raises(LLMNodeError):
        check_semantic("生成文本", _profile_simple(), client)


def test_semantic_multi_dimension_aggregated() -> None:
    client = _fake_client_returning(
        {
            "dimension_scores": [
                {"dimension": "rhythm", "score": 8.0, "explanation": "「短句」节奏"},
                {"dimension": "tone", "score": 7.0, "explanation": "「克制」基调"},
                {"dimension": "motif", "score": 5.0, "explanation": "意象「雪」反复"},
            ]
        }
    )
    reports = check_semantic("text", _profile_simple(), client)
    assert len(reports) == 3
    assert {r.dimension for r in reports} == {"rhythm", "tone", "motif"}


def test_semantic_empty_inputs() -> None:
    client = _fake_client_returning({"dimension_scores": []})
    assert check_semantic("", _profile_simple(), client) == []
    assert check_semantic("text", _profile_simple(), None) == []


# ---------------------------------------------------------------------------
# Forbidden semantic
# ---------------------------------------------------------------------------


def _seed_profile_with_forbidden(seed: str, forbidden_statements: list[str]) -> tuple[str, _FakeProfile]:
    """建一个最小 ORM 链路(book + run + extraction + forbidden_pattern findings)
    并返一个 stub profile。
    """
    finding_ids: list[str] = []
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        book_id = f"sr_book_{seed}"
        run_id = f"sr_run_{seed}"
        extraction_id = f"sr_ext_{seed}"
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy="local_only",
            text_checksum=f"chk_{seed}", total_chars=10, status="ready", stats_json={},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        repo.create_extraction(
            extraction_id=extraction_id, book_id=book_id, run_id=run_id,
            layer="language", sub_dimension="language.rhetoric",
            raw_payload_json={}, status="done", validation_errors_json=[], purpose="extract",
        )
        for i, statement in enumerate(forbidden_statements):
            fid = f"sr_find_{seed}_{i}"
            repo.create_finding(
                finding_id=fid, book_id=book_id, run_id=run_id, extraction_id=extraction_id,
                sub_dimension="language.rhetoric", finding_kind="forbidden_pattern",
                statement=statement, confidence="high", status="pending",
            )
            finding_ids.append(fid)
        session.commit()
    return book_id, _FakeProfile(
        profile_json={},
        source_finding_ids_json=finding_ids,
        book_id=book_id,
        profile_id=f"sr_profile_{seed}",
    )


def test_forbidden_semantic_always_triggered() -> None:
    _book, profile = _seed_profile_with_forbidden(
        "always_trig", ["禁堆华丽形容词", "禁中二独白"]
    )
    client = _fake_client_returning(
        {"triggered": True, "excerpt": "命中的句子", "reasoning": "match"}
    )
    with SessionLocal() as session:
        hits = check_forbidden_semantic("文本", profile, session, client)
    assert len(hits) == 2
    assert all(h.pattern_statement in {"禁堆华丽形容词", "禁中二独白"} for h in hits)


def test_forbidden_semantic_never_triggered() -> None:
    _book, profile = _seed_profile_with_forbidden(
        "never_trig", ["禁A", "禁B"]
    )
    client = _fake_client_returning(
        {"triggered": False, "excerpt": "", "reasoning": "no match"}
    )
    with SessionLocal() as session:
        hits = check_forbidden_semantic("文本", profile, session, client)
    assert hits == []


def test_forbidden_semantic_single_llm_failure_does_not_block_others() -> None:
    """LLM 在第 2 个 forbidden 上失败,第 1 个应仍正常返。"""
    _book, profile = _seed_profile_with_forbidden(
        "partial", ["禁第一", "禁第二", "禁第三"]
    )

    call_count = {"n": 0}

    class _PartialClient:
        def generate(self, request):  # noqa: ANN001
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("transient")
            return _StubResp({"triggered": True, "excerpt": "hit", "reasoning": "x"})

    with SessionLocal() as session:
        hits = check_forbidden_semantic("文本", profile, session, _PartialClient())
    # 3 个 finding 中 1 个失败 → 剩 2 个返
    assert len(hits) == 2


def test_forbidden_semantic_empty_profile_returns_empty() -> None:
    profile = _FakeProfile(
        profile_json={}, source_finding_ids_json=[],
        book_id="sr_book_empty", profile_id="sr_profile_empty",
    )
    client = _fake_client_returning({"triggered": False})
    with SessionLocal() as session:
        assert check_forbidden_semantic("文本", profile, session, client) == []
