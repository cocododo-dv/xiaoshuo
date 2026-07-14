from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from novel_system.services.llm_accounting import LLMAccountingError
from novel_system.services.style_reference import segmentation
from novel_system.services.style_reference import validation
from novel_system.services.style_reference._llm_helper import LLMNodeError
from novel_system.services.style_reference.segmentation import llm as segmentation_llm
from novel_system.services.style_reference.validation import runner
from novel_system.services.style_reference.validation import forbidden_local
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


class _FakeSession:
    def __init__(self, row: SimpleNamespace) -> None:
        self.row = row
        self.flushes = 0
        self.commits = 0

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1

    def get(self, *_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return self.row


class _FakeRepository:
    def __init__(self, row: SimpleNamespace) -> None:
        self.row = row
        self.profile = SimpleNamespace(
            profile_id="sr_profile_control_plane",
            book_id="sr_book_control_plane",
        )

    def get_profile(self, _profile_id: str) -> SimpleNamespace:
        return self.profile

    def get_book(self, _book_id: str) -> SimpleNamespace:
        return SimpleNamespace(cloud_policy="segments_only")

    def get_validation_report(self, _report_id: str) -> SimpleNamespace:
        return self.row


def _patch_worker_shell(
    monkeypatch: pytest.MonkeyPatch,
    *,
    semantic: Any,
    forbidden: Any,
    corpus: Any | None = None,
    verdict: Any | None = None,
) -> tuple[_FakeSession, SimpleNamespace]:
    row = SimpleNamespace(
        verdict="",
        quantitative_json=[],
        semantic_json=[],
        plagiarism_json={},
        forbidden_hits_json=[],
    )
    fake_session = _FakeSession(row)
    fake_repo = _FakeRepository(row)
    monkeypatch.setattr(runner, "SessionLocal", lambda: fake_session)
    monkeypatch.setattr(runner, "StyleReferenceRepository", lambda _session: fake_repo)
    monkeypatch.setattr(
        validation,
        "_load_plagiarism_corpus",
        corpus if corpus is not None else (lambda *_args: []),
    )
    monkeypatch.setattr(
        validation,
        "check_plagiarism",
        lambda *_args: SimpleNamespace(passed=True, model_dump=lambda: {"passed": True}),
    )
    monkeypatch.setattr(validation, "check_quantitative", lambda *_args: [])
    monkeypatch.setattr(validation, "check_semantic", semantic)
    monkeypatch.setattr(validation, "check_forbidden_semantic", forbidden)
    monkeypatch.setattr(
        validation,
        "_compute_full_verdict",
        verdict
        if verdict is not None
        else lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("control-plane failure must not be degraded")
        ),
    )
    monkeypatch.setattr(forbidden_local, "check_forbidden_local", lambda *_args: [])
    monkeypatch.setattr(policy, "cloud_llm_allowed", lambda _book: True)
    return fake_session, row


@pytest.mark.parametrize(
    "boundary",
    ["semantic", "forbidden", "outer"],
)
def test_validation_worker_preserves_control_plane_exception_at_every_boundary(
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
    fake_session, row = _patch_worker_shell(
        monkeypatch,
        semantic=semantic,
        forbidden=forbidden,
        corpus=corpus,
    )

    with pytest.raises(type(error)) as exc_info:
        runner._async_worker(
            report_id="sr_report_control_plane",
            profile_id="sr_profile_control_plane",
            generated_text="generated",
            llm_client=object(),
            llm_enabled=True,
        )

    assert exc_info.value is error
    assert row.verdict == ""
    assert fake_session.flushes == 0
    assert fake_session.commits == 0


def test_validation_worker_still_degrades_explicit_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    degraded: list[bool] = []

    def provider_failure(*_args: Any, **_kwargs: Any) -> None:
        raise LLMNodeError("provider failed", error_code="RuntimeError")

    def compute_verdict(**kwargs: Any) -> SimpleNamespace:
        degraded.append(kwargs["semantic_degraded"])
        return SimpleNamespace(value="partial")

    fake_session, row = _patch_worker_shell(
        monkeypatch,
        semantic=provider_failure,
        forbidden=lambda *_args, **_kwargs: [],
        verdict=compute_verdict,
    )

    runner._async_worker(
        report_id="sr_report_provider_failure",
        profile_id="sr_profile_control_plane",
        generated_text="generated",
        llm_client=object(),
        llm_enabled=True,
    )

    assert degraded == [True]
    assert row.verdict == "partial"
    assert fake_session.flushes == 1
    assert fake_session.commits == 1
