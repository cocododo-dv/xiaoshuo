from __future__ import annotations

import pytest

from novel_system.services.library_derive import LibraryDeriveService
from novel_system.services.llm_accounting import (
    LLMAccountingError,
    LLMAccountingRejected,
)
from novel_system.services.longform_tower import LongformTowerService
from novel_system.services.style_reference import _llm_helper
from novel_system.services.style_reference._llm_helper import LLMNodeError


def _receipt() -> dict:
    return {
        "chapter_no": 1,
        "contract": {"constraints": []},
        "anchor_hits": [],
        "anchor_misses": [],
    }


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: LLMAccountingRejected(
            "LLM_ACCOUNTING_HOOK_UNSUPPORTED",
            "accounting rejected",
        ),
        lambda: LLMAccountingError(
            "LLM_USAGE_EXCEEDS_RESERVATION",
            "budget settlement rejected",
        ),
        lambda: LLMAccountingError(
            "LLM_ACCOUNTING_CALL_EXISTS",
            "logical call already exists",
        ),
    ],
    ids=("rejected", "budget", "call-exists"),
)
def test_library_and_longform_never_degrade_accounting_control_plane_failures(
    session,
    monkeypatch,
    error_factory,
) -> None:
    expected = error_factory()

    def raise_expected(*args, **kwargs):
        raise expected

    monkeypatch.setattr(_llm_helper, "call_llm_node", raise_expected)

    with pytest.raises(type(expected)) as library_error:
        LibraryDeriveService(session, llm_client=object())._extract(
            "project-control-plane",
            "chapter-control-plane",
            "chapter text",
        )
    assert library_error.value is expected

    expected = error_factory()
    with pytest.raises(type(expected)) as longform_error:
        LongformTowerService(session)._adjudicate_violations(
            "project-control-plane",
            "chapter-control-plane",
            _receipt(),
            object(),
        )
    assert longform_error.value is expected


def test_library_and_longform_still_degrade_provider_business_failures(
    session,
    monkeypatch,
) -> None:
    def raise_provider_failure(*args, **kwargs):
        raise LLMNodeError(
            "provider failed",
            error_code="LLM_PROVIDER_TRANSPORT_ERROR",
        )

    monkeypatch.setattr(_llm_helper, "call_llm_node", raise_provider_failure)

    assert LibraryDeriveService(session, llm_client=object())._extract(
        "project-provider-failure",
        "chapter-provider-failure",
        "chapter text",
    ) == []
    assert LongformTowerService(session)._adjudicate_violations(
        "project-provider-failure",
        "chapter-provider-failure",
        _receipt(),
        object(),
    ) == []
