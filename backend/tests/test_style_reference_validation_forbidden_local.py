"""字面 banned_terms 扫描单测(PR-4)。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

import pytest

from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.repository import StyleReferenceRepository
from novel_system.services.style_reference.validation.forbidden_local import (
    check_forbidden_local,
)


def _seed_profile_and_terms(profile_id: str, terms: list[tuple[str, str]]) -> None:
    """terms = [(term_text, scope), ...]"""
    with SessionLocal() as session:
        repo = StyleReferenceRepository(session)
        # 建 book + run + profile(最小骨架)
        repo.create_book(
            book_id=f"sr_book_{profile_id[:6]}",
            title="x",
            source_kind="upload",
            cloud_policy="local_only",
            text_checksum=f"chk_{profile_id}",
            total_chars=10,
            status="ready",
            stats_json={},
        )
        repo.create_run(
            run_id=f"sr_run_{profile_id[:6]}",
            book_id=f"sr_book_{profile_id[:6]}",
            status="done",
            phase="done",
        )
        repo.create_profile(
            profile_id=profile_id,
            book_id=f"sr_book_{profile_id[:6]}",
            run_id=f"sr_run_{profile_id[:6]}",
            title="t",
            status="active",
            profile_json={},
            coverage_json={},
            source_finding_ids_json=[],
        )
        for i, (term, scope) in enumerate(terms):
            repo.create_banned_term(
                term_id=f"sr_term_{profile_id[:6]}_{i}",
                profile_id=profile_id,
                term=term,
                replacement_hint=None,
                source="user",
                scope=scope,
            )
        session.commit()


def test_forbidden_hit_single_term() -> None:
    _seed_profile_and_terms("sr_profile_1", [("江南", "generation")])
    with SessionLocal() as session:
        hits = check_forbidden_local("龙族的故事由江南创作", "sr_profile_1", session)
    assert len(hits) == 1
    assert hits[0].pattern_statement == "江南"
    assert hits[0].severity == "error"


def test_forbidden_scope_extraction_not_triggered() -> None:
    """scope=extraction 不应在 generation 扫描中触发。"""
    _seed_profile_and_terms("sr_profile_2", [("江南", "extraction")])
    with SessionLocal() as session:
        hits = check_forbidden_local("龙族的故事由江南创作", "sr_profile_2", session)
    assert hits == []


def test_forbidden_multi_terms_aggregated() -> None:
    _seed_profile_and_terms(
        "sr_profile_3",
        [("江南", "generation"), ("龙族", "generation"), ("路明非", "generation")],
    )
    with SessionLocal() as session:
        hits = check_forbidden_local(
            "龙族的主角路明非由江南塑造", "sr_profile_3", session
        )
    assert len(hits) == 3
    matched = {h.pattern_statement for h in hits}
    assert matched == {"江南", "龙族", "路明非"}


def test_forbidden_empty_term_table() -> None:
    _seed_profile_and_terms("sr_profile_4", [])
    with SessionLocal() as session:
        hits = check_forbidden_local("任何文本", "sr_profile_4", session)
    assert hits == []
