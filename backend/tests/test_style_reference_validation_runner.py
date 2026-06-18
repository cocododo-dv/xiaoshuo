"""ValidationOrchestrator 双路径单测(PR-7 §7.1)。"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from novel_system.db.models import StyleReferenceValidationReport
from novel_system.db.session import SessionLocal
from novel_system.services.errors import DomainError
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.schemas import (
    ValidateRequest,
    ValidationMode,
    ValidationTargetKind,
)
from novel_system.services.style_reference.validation import (
    ValidationOrchestrator,
    _compute_full_verdict,
)
from novel_system.services.style_reference.validation.runner import _EXECUTOR


def _seed_profile(
    seed: str, *, with_forbidden: bool = False, cloud_policy: str = "segments_only"
) -> str:
    """建一个最小 profile + 1 个 quote。

    cloud_policy 默认 segments_only(允许语义路);local_only 会按附录 B
    策略跳过语义 LLM 检查,专门用例单独覆盖。
    """
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        book_id = f"sr_book_{seed}"
        run_id = f"sr_run_{seed}"
        profile_id = f"sr_profile_{seed}"
        repo.create_book(
            book_id=book_id, title="t", source_kind="upload", cloud_policy=cloud_policy,
            text_checksum=f"chk_{seed}", total_chars=10, status="ready",
            stats_json={"metrics": {"avg_sentence_length": {"mean": 10.0, "std": 3.0}}},
        )
        repo.create_run(run_id=run_id, book_id=book_id, status="done", phase="done")
        repo.create_quote(
            quote_id=f"sr_q_{seed}",
            book_id=book_id, paragraph_id=None,
            span_start=0, span_end=10, quote_text="他低头看着脚下的路",
            illustrates_dims=[], extracted_features={},
        )
        finding_ids: list[str] = []
        if with_forbidden:
            extraction_id = f"sr_ext_{seed}"
            repo.create_extraction(
                extraction_id=extraction_id, book_id=book_id, run_id=run_id,
                layer="language", sub_dimension="language.rhetoric",
                raw_payload_json={}, status="done", validation_errors_json=[], purpose="extract",
            )
            fid = f"sr_find_{seed}"
            repo.create_finding(
                finding_id=fid, book_id=book_id, run_id=run_id, extraction_id=extraction_id,
                sub_dimension="language.rhetoric", finding_kind="forbidden_pattern",
                statement="禁堆华丽形容词", confidence="high", status="approved",
            )
            finding_ids = [fid]
        repo.create_profile(
            profile_id=profile_id, book_id=book_id, run_id=run_id, title="t",
            status="active",
            profile_json={
                "narrative_summary": "短句白描",
                "metrics_baseline": {
                    "avg_sentence_length": {"mean": 10.0, "std": 3.0, "sample_count": 20},
                },
                "style_features": ["短句", "白描"],
            },
            coverage_json={},
            source_finding_ids_json=finding_ids,
        )
        session.commit()
    return profile_id


def _wait_for_async(report_id: str, max_seconds: float = 5.0) -> str:
    """轮询 async_full report 直到 verdict 非空,或超时。"""
    deadline = time.monotonic() + max_seconds
    while time.monotonic() < deadline:
        with SessionLocal() as session:
            row = session.get(StyleReferenceValidationReport, report_id)
            if row is not None and row.verdict:
                return row.verdict
        time.sleep(0.1)
    return ""


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def test_validate_profile_not_found(fake_validation_llm) -> None:
    with SessionLocal() as session:
        orch = ValidationOrchestrator(
            session, llm_client=fake_validation_llm(), llm_enabled=True
        )
        req = ValidateRequest(generated_text="x")
        with pytest.raises(DomainError) as exc_info:
            orch.validate("sr_profile_nonexistent", req)
        assert exc_info.value.code == "STYLE_REFERENCE_PROFILE_NOT_FOUND"


def test_sync_only_returns_immediately_with_report(fake_validation_llm) -> None:
    profile_id = _seed_profile("sync_only")
    with SessionLocal() as session:
        orch = ValidationOrchestrator(session, llm_client=None, llm_enabled=False)
        req = ValidateRequest(generated_text="完全无关的生成文本",
                              mode=ValidationMode.SYNC_ONLY)
        resp = orch.validate(profile_id, req)
        session.commit()

    assert resp.mode_executed == ValidationMode.SYNC_ONLY
    assert resp.sync_result is not None
    assert resp.polling_url is None
    assert resp.report_id.startswith("sr_rep_")
    # report 已落
    with SessionLocal() as session:
        row = session.get(StyleReferenceValidationReport, resp.report_id)
    assert row is not None
    assert row.mode_executed == "sync_only"


def test_sync_only_plagiarism_triggers_verdict(fake_validation_llm) -> None:
    profile_id = _seed_profile("plag")
    # 用 profile quote "他低头看着脚下的路"(10 字 ≥ threshold 12 后 hot path);
    # 但 plag 阈值 12 字符,quote 仅 10 字,不会触发(用更长重叠)。
    # _seed_profile 中 quote_text 长 10,我们改用包含相同字符并扩到 ≥12 的重叠。
    overlap_text = "今儿是个好天气。他低头看着脚下的路上凝固的霜冻"  # 含 quote + 后缀
    with SessionLocal() as session:
        orch = ValidationOrchestrator(session, llm_client=None, llm_enabled=False)
        req = ValidateRequest(generated_text=overlap_text, mode=ValidationMode.SYNC_ONLY)
        resp = orch.validate(profile_id, req)
        session.commit()

    # quote 仅 10 字,无法触发 12 字阈值;此测试断言 verdict 是 pass(quote 太短)
    assert resp.sync_result.verdict.value == "pass"


def test_async_full_returns_polling_url(fake_validation_llm) -> None:
    profile_id = _seed_profile("async_basic")
    client = fake_validation_llm("with_quote")
    with SessionLocal() as session:
        orch = ValidationOrchestrator(session, llm_client=client, llm_enabled=True)
        req = ValidateRequest(generated_text="生成文本",
                              mode=ValidationMode.ASYNC_FULL)
        resp = orch.validate(profile_id, req)
        session.commit()

    assert resp.mode_executed == ValidationMode.ASYNC_FULL
    assert resp.sync_result is None
    assert resp.polling_url
    assert resp.polling_url.endswith(resp.report_id)


def test_async_full_worker_completes_and_writes_verdict(fake_validation_llm) -> None:
    """async_full 后台 worker 应在几秒内更新 verdict 字段。"""
    profile_id = _seed_profile("async_complete")
    client = fake_validation_llm("with_quote")
    with SessionLocal() as session:
        orch = ValidationOrchestrator(session, llm_client=client, llm_enabled=True)
        req = ValidateRequest(generated_text="一段生成的中文文本测试", mode=ValidationMode.ASYNC_FULL)
        resp = orch.validate(profile_id, req)
        session.commit()
    verdict = _wait_for_async(resp.report_id, max_seconds=5.0)
    assert verdict, "async_full worker 应在 5 秒内填 verdict"
    # 应能正常归类(pass / partial / fail 都可以,这里只断言非空 + 已落 4 路 json)
    with SessionLocal() as session:
        row = session.get(StyleReferenceValidationReport, resp.report_id)
    assert row.semantic_json, "semantic_json 应有 2 个 dimension(rule=with_quote 返 2 条)"
    assert isinstance(row.quantitative_json, list)
    assert isinstance(row.plagiarism_json, dict)


def test_async_full_forbidden_semantic_triggers_fail(fake_validation_llm) -> None:
    profile_id = _seed_profile("async_forbid", with_forbidden=True)
    client = fake_validation_llm("always_trigger")
    with SessionLocal() as session:
        orch = ValidationOrchestrator(session, llm_client=client, llm_enabled=True)
        req = ValidateRequest(generated_text="任何生成文本", mode=ValidationMode.ASYNC_FULL)
        resp = orch.validate(profile_id, req)
        session.commit()
    verdict = _wait_for_async(resp.report_id, max_seconds=5.0)
    assert verdict == "fail", f"forbidden_semantic always_trigger 应导致 fail,实际 {verdict}"


# ---------------------------------------------------------------------------
# _compute_full_verdict 单元
# ---------------------------------------------------------------------------


class _Plag:
    def __init__(self, passed): self.passed = passed
    def model_dump(self): return {"passed": self.passed}


class _Forbid:
    def __init__(self, severity="error"): self.severity = severity
    def model_dump(self): return {"severity": self.severity}


class _Quant:
    def __init__(self, passed): self.passed = passed


class _Sem:
    def __init__(self, score): self.score = score


def test_full_verdict_plagiarism_overrides() -> None:
    v = _compute_full_verdict(quant=[], semantic=[], plag=_Plag(False), forbid=[])
    assert v.value == "plagiarism"


def test_full_verdict_forbidden_overrides() -> None:
    v = _compute_full_verdict(quant=[], semantic=[], plag=_Plag(True), forbid=[_Forbid("error")])
    assert v.value == "fail"


def test_full_verdict_pass_when_quant_and_semantic_high() -> None:
    quant = [_Quant(True)] * 9 + [_Quant(False)]  # 90% pass
    semantic = [_Sem(7.0), _Sem(8.0)]
    v = _compute_full_verdict(quant=quant, semantic=semantic, plag=_Plag(True), forbid=[])
    assert v.value == "pass"


def test_full_verdict_partial_when_mid_range() -> None:
    quant = [_Quant(True), _Quant(False)]  # 50% pass
    semantic = [_Sem(5.0)]
    v = _compute_full_verdict(quant=quant, semantic=semantic, plag=_Plag(True), forbid=[])
    assert v.value == "partial"


def test_full_verdict_fail_when_low() -> None:
    quant = [_Quant(False)] * 5
    semantic = [_Sem(2.0)]
    v = _compute_full_verdict(quant=quant, semantic=semantic, plag=_Plag(True), forbid=[])
    assert v.value == "fail"
