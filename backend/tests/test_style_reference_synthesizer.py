"""ProfileSynthesizer 单测(PR-4)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import json

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.errors import LLMRequiredError
from novel_system.services.style_reference.ingest import IngestService
from novel_system.services.style_reference.profile_synthesizer import (
    ProfileSynthesizer,
    SynthesizeError,
)
from novel_system.services.style_reference.repository import StyleReferenceRepository


SAMPLE_TEXT = """这是一段叙述,介绍清晨场景。

他说:"今天天气真好。"

我心里想着昨日的对话。

记得那年她还在的时候。

雪从天上飘下来。
"""


def _ingest_with_finding(book_seed: str) -> tuple[str, str]:
    """建一本书 + 一个 run + 若干 finding(模拟 PR-3 抽取后的状态)。"""
    with SessionLocal() as session:
        ingest = IngestService(session, llm_enabled=False)
        result = ingest.ingest_upload(
            raw_bytes=SAMPLE_TEXT.encode("utf-8"),
            file_name=f"book_{book_seed}.txt",
            title="测试书",
            author_label="作者",
            cloud_policy="segments_only",
        )
        book_id = result.book.book_id
        repo = StyleReferenceRepository(session)
        run_id = f"sr_run_{book_seed}"
        repo.create_run(
            run_id=run_id, book_id=book_id, status="done", phase="done"
        )
        # 各 sub_dim 加 1 obs + 1 forbid
        extraction_id = f"sr_ext_{book_seed}"
        repo.create_extraction(
            extraction_id=extraction_id,
            book_id=book_id,
            run_id=run_id,
            layer="language",
            sub_dimension="language.rhetoric",
            raw_payload_json={},
            status="done",
            validation_errors_json=[],
            purpose="extract",
        )
        for kind in ("observation", "forbidden_pattern"):
            repo.create_finding(
                finding_id=f"sr_find_{book_seed}_{kind}",
                book_id=book_id,
                run_id=run_id,
                extraction_id=extraction_id,
                sub_dimension="language.rhetoric",
                finding_kind=kind,
                statement=f"测试 {kind} 描述",
                confidence="high",
                status="pending",
            )
        # 1 个 quote
        repo.create_quote(
            quote_id=f"sr_quote_{book_seed}",
            book_id=book_id,
            paragraph_id=None,
            span_start=0,
            span_end=20,
            quote_text="他低头看着脚下的路",
            illustrates_dims=["language.rhetoric"],
            extracted_features={"paragraph_type": "narration"},
        )
        session.commit()
        return book_id, run_id


def _fake_llm_with_response(response_dict: dict):
    class _Resp:
        structured_output = response_dict
        text = json.dumps(response_dict, ensure_ascii=False)
        usage = {}
        finish_reason = "stop"
        provider = "fake"
        model = "fake"
        response_format = "json_object"
        request_id = None
        raw_response = {}

    class _Client:
        def generate(self, request):  # noqa: ANN001
            return _Resp()

    return _Client()


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_synthesize_llm_required_when_disabled() -> None:
    book_id, run_id = _ingest_with_finding("disabled")
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=None, llm_enabled=False)
        with pytest.raises(LLMRequiredError):
            synth.synthesize(book_id, run_id)


def test_synthesize_happy_path() -> None:
    book_id, run_id = _ingest_with_finding("happy")
    client = _fake_llm_with_response(
        {
            "profile_title": "鲁迅风格 v1",
            "narrative_summary": "短句+反讽+冷静叙述,克制情感",
            "style_features": ["善用短句", "反讽点缀", "白描+留白"],
            "narrative_patterns": ["人物对话引出冲突", "环境暗示情绪"],
            "banned_replication_rules": ["禁止堆砌华丽形容词"],
            "calibration_guidance": ["每场景至少一处白描"],
        }
    )
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=client, llm_enabled=True)
        profile = synth.synthesize(book_id, run_id)
        session.commit()

    assert profile.title == "鲁迅风格 v1"
    assert profile.status == "draft"
    pj = profile.profile_json
    # profile_json 4 类应用建议 + narrative_summary + metrics_baseline + scene_samples_index + sub_dimensions
    assert pj["narrative_summary"]
    assert "metrics_baseline" in pj
    assert "scene_samples_index" in pj
    assert "sub_dimensions" in pj
    assert pj["style_features"] == ["善用短句", "反讽点缀", "白描+留白"]
    assert pj["banned_replication_rules"] == ["禁止堆砌华丽形容词"]
    # source_finding_ids_json 含所有 finding
    assert len(profile.source_finding_ids_json) == 2


def test_synthesize_pydantic_validation_failure() -> None:
    book_id, run_id = _ingest_with_finding("pyderr")
    # LLM 返回缺 narrative_summary,Pydantic min_length=1 不通过
    client = _fake_llm_with_response(
        {
            "profile_title": "x",
            "narrative_summary": "",  # 违反 min_length=1
            "style_features": [],
            "narrative_patterns": [],
            "banned_replication_rules": [],
        }
    )
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=client, llm_enabled=True)
        with pytest.raises(SynthesizeError):
            synth.synthesize(book_id, run_id)


def test_synthesize_excludes_rejected_findings() -> None:
    """PR-23 — rejected finding 不进 LLM 聚合 payload,也不进 source_finding_ids_json。"""
    book_id, run_id = _ingest_with_finding("rej")
    rejected_statement = "被驳回的观察描述不应出现在聚合里"
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_finding(
            finding_id="sr_find_rej_rejected",
            book_id=book_id,
            run_id=run_id,
            extraction_id="sr_ext_rej",
            sub_dimension="language.rhetoric",
            finding_kind="observation",
            statement=rejected_statement,
            confidence="high",
            status="rejected",
        )
        session.commit()

    captured: list[str] = []
    response_dict = {
        "profile_title": "t",
        "narrative_summary": "s",
        "style_features": ["f"],
        "narrative_patterns": ["p"],
        "banned_replication_rules": ["b"],
    }

    class _Resp:
        structured_output = response_dict
        text = json.dumps(response_dict, ensure_ascii=False)
        usage = {}
        finish_reason = "stop"
        provider = "fake"
        model = "fake"
        response_format = "json_object"
        request_id = None
        raw_response = {}

    class _CapturingClient:
        def generate(self, request):  # noqa: ANN001
            captured.append(request.messages[-1]["content"])
            return _Resp()

    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=_CapturingClient(), llm_enabled=True)
        profile = synth.synthesize(book_id, run_id)
        session.commit()

    # statement 不在 LLM payload(sample_quotes)里
    assert captured and rejected_statement not in captured[0]
    # finding_id 不在 source_finding_ids_json;原 2 条 pending finding 保留
    assert "sr_find_rej_rejected" not in profile.source_finding_ids_json
    assert len(profile.source_finding_ids_json) == 2


def test_synthesize_scene_samples_index_buckets_by_paragraph_type() -> None:
    """scene_samples_index 应按 paragraph_type 分桶(从 quote.extracted_features 读)。"""
    book_id, run_id = _ingest_with_finding("buckets")
    # 多加 1 个 dialogue paragraph_type 的 quote
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        repo.create_quote(
            quote_id=f"sr_quote_dlg_buckets",
            book_id=book_id,
            paragraph_id=None,
            span_start=0,
            span_end=10,
            quote_text="对话引文",
            illustrates_dims=[],
            extracted_features={"paragraph_type": "dialogue"},
        )
        session.commit()

    client = _fake_llm_with_response(
        {
            "profile_title": "t",
            "narrative_summary": "s",
            "style_features": ["f"],
            "narrative_patterns": ["p"],
            "banned_replication_rules": ["b"],
        }
    )
    with SessionLocal() as session:
        synth = ProfileSynthesizer(session, llm_client=client, llm_enabled=True)
        profile = synth.synthesize(book_id, run_id)
        session.commit()
    index = profile.profile_json["scene_samples_index"]
    assert "narration" in index
    assert "dialogue" in index
    assert any(qid.startswith("sr_quote_dlg") for qid in index["dialogue"])
