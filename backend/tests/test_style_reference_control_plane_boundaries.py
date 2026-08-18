from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from novel_system.db.models import (
    StyleReferenceBook,
    StyleReferenceProfile,
    StyleReferenceRun,
    StyleReferenceValidationReport,
)
from novel_system.services.llm_accounting import LLMAccountingError
from novel_system.services.style_reference import segmentation
from novel_system.services.style_reference._llm_helper import LLMNodeError
from novel_system.services.style_reference.segmentation import llm as segmentation_llm
from novel_system.services.style_reference.validation import runner
from novel_system.services.style_reference.validation import core as validation_core
from novel_system.services.style_reference.validation import forbidden_local
from novel_system.services.style_reference.validation import forbidden_semantic
from novel_system.services.style_reference.validation import plagiarism
from novel_system.services.style_reference.validation import quantitative
from novel_system.services.style_reference.validation import semantic as validation_semantic
from novel_system.services.style_reference import policy


def test_segmentation_accounted_execution_preserves_control_plane_exception(
    session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = LLMAccountingError(
        "LLM_ACCOUNTING_CALL_EXISTS",
        "logical call already exists",
    )

    def raise_error(*_args: Any, **_kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(segmentation_llm, "execute_accounted_call", raise_error)

    with pytest.raises(LLMAccountingError) as exc_info:
        segmentation_llm._classify_via_node(
            [(0, 4, "text")],
            segmentation_llm.NODE_ANCHOR,
            object(),
            session=session,
            scope_id="sr_book_control_plane",
        )

    assert exc_info.value is error


@pytest.mark.parametrize(
    "error",
    [
        segmentation_llm.SegmentationLLMError(
            "LLM_USAGE_EXCEEDS_RESERVATION",
            "usage settlement invariant failed",
        ),
        LLMAccountingError(
            "LLM_ACCOUNTING_CALL_EXISTS",
            "logical call already exists",
        ),
    ],
    ids=("segmentation-error-catch", "generic-error-catch"),
)
def test_segmentation_dispatcher_never_uses_heuristic_for_control_plane_failure(
    session,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    heuristic_calls = 0

    def raise_error(*_args: Any, **_kwargs: Any) -> None:
        raise error

    def forbidden_heuristic(*_args: Any, **_kwargs: Any) -> None:
        nonlocal heuristic_calls
        heuristic_calls += 1
        raise AssertionError("control-plane failure must not use heuristic fallback")

    monkeypatch.setattr(segmentation, "classify_with_llm", raise_error)
    monkeypatch.setattr(segmentation, "classify_heuristic", forbidden_heuristic)

    with pytest.raises(type(error)) as exc_info:
        segmentation.classify_paragraphs(
            [(0, 4, "text")],
            llm_enabled=True,
            llm_client=object(),
            session=session,
            scope_id="sr_book_control_plane",
        )

    assert exc_info.value is error
    assert heuristic_calls == 0


def _seed_durable_validation_report(session, seed: str) -> str:
    book_id = f"sr_book_cp_{seed}"
    run_id = f"sr_run_cp_{seed}"
    profile_id = f"sr_profile_cp_{seed}"
    report_id = f"sr_report_cp_{seed}"
    session.add(
        StyleReferenceBook(
            book_id=book_id,
            title="control plane",
            source_kind="upload",
            cloud_policy="segments_only",
            text_checksum=f"checksum_cp_{seed}",
        )
    )
    session.add(
        StyleReferenceRun(
            run_id=run_id,
            book_id=book_id,
            status="done",
            phase="done",
        )
    )
    session.add(
        StyleReferenceProfile(
            profile_id=profile_id,
            book_id=book_id,
            run_id=run_id,
            title="control plane",
        )
    )
    session.add(
        StyleReferenceValidationReport(
            report_id=report_id,
            profile_id=profile_id,
            target_kind="manual",
            verdict="",
            status="queued",
            mode_executed="async_full",
        )
    )
    session.commit()
    return report_id


@pytest.mark.parametrize(
    "boundary",
    ["semantic", "forbidden", "outer"],
)
def test_validation_worker_persists_control_plane_failure_at_every_boundary(
    session,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    error: Exception
    if boundary == "semantic":
        error = LLMAccountingError(
            "LLM_ACCOUNTING_CALL_EXISTS",
            "logical call already exists",
        )
    else:
        class UsageInvariantError(RuntimeError):
            code = "LLM_USAGE_EXCEEDS_RESERVATION"

        error = UsageInvariantError("usage settlement invariant failed")

    def raise_error(*_args: Any, **_kwargs: Any) -> None:
        raise error

    semantic = raise_error if boundary == "semantic" else (lambda *_args, **_kwargs: [])
    forbidden = raise_error if boundary == "forbidden" else (lambda *_args, **_kwargs: [])
    corpus = raise_error if boundary == "outer" else None
    seed = f"{boundary}"
    report_id = _seed_durable_validation_report(session, seed)
    profile_id = f"sr_profile_cp_{seed}"
    monkeypatch.setattr(
        validation_core,
        "_load_plagiarism_corpus",
        corpus if corpus is not None else (lambda *_args: []),
    )
    monkeypatch.setattr(
        plagiarism,
        "check_plagiarism",
        lambda *_args: SimpleNamespace(passed=True, model_dump=lambda: {"passed": True}),
    )
    monkeypatch.setattr(quantitative, "check_quantitative", lambda *_args: [])
    monkeypatch.setattr(validation_semantic, "check_semantic", semantic)
    monkeypatch.setattr(forbidden_semantic, "check_forbidden_semantic", forbidden)
    monkeypatch.setattr(
        validation_core,
        "_compute_full_verdict",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("control-plane failure must not be degraded")
        ),
    )
    monkeypatch.setattr(forbidden_local, "check_forbidden_local", lambda *_args: [])
    monkeypatch.setattr(policy, "cloud_llm_allowed", lambda _book: True)

    runner._async_worker(
        report_id=report_id,
        profile_id=profile_id,
        generated_text="generated",
        llm_client=object(),
        llm_enabled=True,
    )

    session.expire_all()
    row = session.get(StyleReferenceValidationReport, report_id)
    assert row is not None
    assert row.verdict == "fail"
    assert row.status == "failed"
    assert row.error_code == "STYLE_REFERENCE_VALIDATION_CONTROL_PLANE_FAILED"
    assert row.retryable is True
    assert row.quantitative_json == []
    assert row.semantic_json == []


def test_validation_worker_still_degrades_explicit_provider_failure(
    session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    degraded: list[bool] = []

    def provider_failure(*_args: Any, **_kwargs: Any) -> None:
        raise LLMNodeError("provider failed", error_code="RuntimeError")

    def compute_verdict(**kwargs: Any) -> SimpleNamespace:
        degraded.append(kwargs["semantic_degraded"])
        return SimpleNamespace(value="partial")

    report_id = _seed_durable_validation_report(session, "provider_failure")
    profile_id = "sr_profile_cp_provider_failure"
    monkeypatch.setattr(validation_core, "_load_plagiarism_corpus", lambda *_args: [])
    monkeypatch.setattr(
        plagiarism,
        "check_plagiarism",
        lambda *_args: SimpleNamespace(passed=True, model_dump=lambda: {"passed": True}),
    )
    monkeypatch.setattr(quantitative, "check_quantitative", lambda *_args: [])
    monkeypatch.setattr(validation_semantic, "check_semantic", provider_failure)
    monkeypatch.setattr(forbidden_semantic, "check_forbidden_semantic", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(validation_core, "_compute_full_verdict", compute_verdict)
    monkeypatch.setattr(forbidden_local, "check_forbidden_local", lambda *_args: [])
    monkeypatch.setattr(policy, "cloud_llm_allowed", lambda _book: True)

    runner._async_worker(
        report_id=report_id,
        profile_id=profile_id,
        generated_text="generated",
        llm_client=object(),
        llm_enabled=True,
    )

    assert degraded == [True]
    session.expire_all()
    row = session.get(StyleReferenceValidationReport, report_id)
    assert row is not None
    assert row.verdict == "partial"
    assert row.status == "completed"
    assert row.error_code is None
