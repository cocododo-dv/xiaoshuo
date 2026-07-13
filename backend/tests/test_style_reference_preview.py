"""PreviewService 单测(PR-4)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from novel_system.db.models import StyleReferenceValidationReport
from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.errors import LLMRequiredError
from novel_system.services.style_reference.preview import PreviewService
from novel_system.services.style_reference.repository import StyleReferenceRepository


def _seed_profile(seed: str, scene_samples_text: str = "他低头看着路") -> str:
    """建一个最小 profile + 1 个 quote(dialogue paragraph_type)。"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        book_id = f"sr_book_{seed}"
        run_id = f"sr_run_{seed}"
        profile_id = f"sr_profile_{seed}"
        repo.create_book(
            book_id=book_id,
            title="t",
            source_kind="upload",
            cloud_policy="segments_only",
            text_checksum=f"chk_{seed}",
            total_chars=10,
            status="ready",
            stats_json={"rights_declaration": {
                "declared": True, "analysis_rights": True, "send_rights": True,
            }},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        quote_id = f"sr_q_{seed}_dlg"
        repo.create_quote(
            quote_id=quote_id,
            book_id=book_id,
            paragraph_id=None,
            span_start=0,
            span_end=len(scene_samples_text),
            quote_text=scene_samples_text,
            illustrates_dims=[],
            extracted_features={"paragraph_type": "dialogue"},
        )
        repo.create_profile(
            profile_id=profile_id,
            book_id=book_id,
            run_id=run_id,
            title="t",
            status="active",
            profile_json={
                "narrative_summary": "短句 + 反讽",
                "scene_samples_index": {"dialogue": [quote_id]},
                "style_features": ["善用短句"],
            },
            coverage_json={},
            source_finding_ids_json=[],
        )
        session.commit()
        return profile_id


def _fake_preview_client(sample_text: str = "这是一段生成的示例文本,展示语言层风格。"):
    class _Resp:
        def __init__(self):
            self.structured_output = {"sample_text": sample_text, "paragraph_type": "dialogue"}
            self.text = json.dumps(self.structured_output, ensure_ascii=False)
            self.usage = {}
            self.finish_reason = "stop"
            self.provider = "fake"
            self.model = "fake"
            self.response_format = "json_object"
            self.request_id = None
            self.raw_response = {}

    class _Client:
        def __init__(self):
            self.calls = 0

        def generate(self, request):  # noqa: ANN001
            self.calls += 1
            return _Resp()

    return _Client()


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_preview_llm_required_when_disabled() -> None:
    profile_id = _seed_profile("disabled")
    with SessionLocal() as session:
        svc = PreviewService(session, llm_client=None, llm_enabled=False)
        with pytest.raises(LLMRequiredError):
            svc.generate(profile_id)


def test_preview_returns_3_samples_and_writes_reports() -> None:
    profile_id = _seed_profile("happy")
    client = _fake_preview_client()
    with SessionLocal() as session:
        svc = PreviewService(session, llm_client=client, llm_enabled=True)
        results = svc.generate(profile_id)
        session.commit()

    # 3 个 paragraph_type
    assert len(results) == 3
    for r in results:
        assert r.error is None
        assert r.sample_text
        assert r.report_id
        assert r.verdict == "pass"

    # validation_reports 表写入 3 行
    with SessionLocal() as session:
        count = session.scalar(
            select(func.count()).select_from(StyleReferenceValidationReport)
            .where(StyleReferenceValidationReport.profile_id == profile_id)
        )
    assert count == 3


def test_preview_plagiarism_verdict_triggers_on_overlap() -> None:
    """LLM 返回的 sample_text 与 profile quote 有 ≥12 字符连续重叠时 verdict=plagiarism。"""
    seed_text = "暮色四合,街口的雾气还没散尽,行人三三两两走过。"
    profile_id = _seed_profile("plag", scene_samples_text=seed_text)
    overlap_text = "今儿是个好天气。" + seed_text  # 与 profile quote 完全相同的子串
    client = _fake_preview_client(sample_text=overlap_text)
    with SessionLocal() as session:
        svc = PreviewService(session, llm_client=client, llm_enabled=True)
        results = svc.generate(profile_id)
        session.commit()

    plagiarism_results = [r for r in results if r.verdict == "plagiarism"]
    assert plagiarism_results, "至少应有一个 sample 因 8-gram 重叠触发 plagiarism"


def test_preview_llm_failure_per_sample_does_not_block_others() -> None:
    """单个 paragraph_type 的 LLM 调用失败,该 sample error 标记,其他继续生成。"""
    profile_id = _seed_profile("partial")

    call_state = {"count": 0}

    class _PartialClient:
        def generate(self, request):  # noqa: ANN001
            call_state["count"] += 1
            # 第 2 次调用失败,其他成功
            if call_state["count"] == 2:
                raise RuntimeError("fake network error")

            class _Resp:
                structured_output = {"sample_text": "好示例文本"}
                text = '{"sample_text": "好示例文本"}'
                usage = {}
                finish_reason = "stop"
                provider = "fake"
                model = "fake"
                response_format = "json_object"
                request_id = None
                raw_response = {}

            return _Resp()

    with SessionLocal() as session:
        svc = PreviewService(session, llm_client=_PartialClient(), llm_enabled=True)
        results = svc.generate(profile_id)
        session.commit()

    assert len(results) == 3
    error_ones = [r for r in results if r.error == "llm_call_failed"]
    assert len(error_ones) == 1
    happy = [r for r in results if r.error is None]
    assert len(happy) == 2
    for r in happy:
        assert r.report_id
        assert r.verdict
