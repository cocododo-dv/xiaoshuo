from __future__ import annotations

from novel_system.services.qc_constraints import (
    constraint_terms,
    contains_forbidden_term,
    issue_mentions_source,
    source_field_satisfied,
)


def test_constraint_terms_normalize_supported_delimiters_and_ignore_noise() -> None:
    assert constraint_terms("盐钟， 潮声; x\n旧名单") == ["盐钟", "潮声", "旧名单"]


def test_forbidden_and_required_checks_share_the_same_leaf_contract() -> None:
    assert contains_forbidden_term("盐钟、潮声", "他听见潮声") is True
    assert contains_forbidden_term(None, "潮声") is False
    assert source_field_satisfied("必须找回旧名单", "他终于找回旧名单，却没有打开") is True
    assert source_field_satisfied("必须找回旧名单", "他离开了码头") is False
    assert issue_mentions_source("缺少：找回旧名单", "必须找回旧名单") is True
