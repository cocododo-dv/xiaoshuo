from __future__ import annotations

from types import SimpleNamespace

import pytest

from novel_system.services.style_reference import errors
from novel_system.services.style_reference.errors import CloudPolicyBlockedError
from novel_system.services.style_reference.policy import (
    cloud_llm_allowed,
    ensure_cloud_llm_allowed,
)


def _book(*, cloud_policy: str, rights_declaration: object) -> SimpleNamespace:
    return SimpleNamespace(
        book_id="sr_book_policy",
        cloud_policy=cloud_policy,
        stats_json={"rights_declaration": rights_declaration},
    )


@pytest.mark.parametrize(
    "rights_declaration",
    [
        None,
        {},
        {"declared": False, "send_rights": True},
        {"declared": True, "send_rights": False},
        {"declared": "true", "send_rights": True},
        {"declared": True, "send_rights": "true"},
        {"declared": 1, "send_rights": True},
        {"declared": True, "send_rights": 1},
    ],
    ids=(
        "missing",
        "empty",
        "declared-false",
        "send-false",
        "declared-string",
        "send-string",
        "declared-int",
        "send-int",
    ),
)
def test_nonlocal_policy_requires_strict_declared_send_rights(
    rights_declaration: object,
) -> None:
    book = _book(
        cloud_policy="segments_only",
        rights_declaration=rights_declaration,
    )

    assert cloud_llm_allowed(book) is False

    expected_error = errors.CloudSendRightsBlockedError
    with pytest.raises(expected_error) as caught:
        ensure_cloud_llm_allowed(book, operation="synthesize_profile")

    err = caught.value
    assert err.code == "STYLE_REFERENCE_SEND_RIGHTS_REQUIRED"
    assert err.status_code == 409
    assert err.details["book_id"] == "sr_book_policy"
    assert err.details["operation"] == "synthesize_profile"
    assert err.details["cloud_policy"] == "segments_only"
    assert err.details["author_action"]["action"] == "redeclare_send_rights"


@pytest.mark.parametrize("cloud_policy", ["segments_only", "allow_full_cloud"])
def test_nonlocal_policy_allows_explicit_declared_send_rights(
    cloud_policy: str,
) -> None:
    book = _book(
        cloud_policy=cloud_policy,
        rights_declaration={"declared": True, "send_rights": True},
    )

    assert cloud_llm_allowed(book) is True
    ensure_cloud_llm_allowed(book, operation="preview")


def test_local_only_uses_cloud_policy_error_even_with_send_rights() -> None:
    book = _book(
        cloud_policy="local_only",
        rights_declaration={"declared": True, "send_rights": True},
    )

    assert cloud_llm_allowed(book) is False

    with pytest.raises(CloudPolicyBlockedError) as caught:
        ensure_cloud_llm_allowed(book, operation="start_extract_run")

    err = caught.value
    assert err.code == "STYLE_REFERENCE_CLOUD_POLICY_BLOCKED"
    assert err.details["book_id"] == "sr_book_policy"
    assert err.details["operation"] == "start_extract_run"
    assert err.details["cloud_policy"] == "local_only"


@pytest.mark.parametrize("cloud_policy", ["", "legacy_cloud", " segments_only"])
def test_unknown_cloud_policy_is_fail_closed_even_with_send_rights(
    cloud_policy: str,
) -> None:
    book = _book(
        cloud_policy=cloud_policy,
        rights_declaration={"declared": True, "send_rights": True},
    )

    assert cloud_llm_allowed(book) is False

    expected_error = errors.CloudPolicyInvalidError
    with pytest.raises(expected_error) as caught:
        ensure_cloud_llm_allowed(book, operation="generate_preview")

    err = caught.value
    assert err.code == "STYLE_REFERENCE_CLOUD_POLICY_INVALID"
    assert err.status_code == 409
    assert err.details["book_id"] == "sr_book_policy"
    assert err.details["operation"] == "generate_preview"
    assert err.details["cloud_policy"] == cloud_policy
    assert err.details["author_action"]["action"] == "review_cloud_policy"


def test_none_book_keeps_caller_not_found_behavior() -> None:
    assert cloud_llm_allowed(None) is True
    ensure_cloud_llm_allowed(None, operation="caller_handles_not_found")
