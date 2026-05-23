"""cleanup.purge_legacy_review_items + backup_legacy_to_json 单测。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from novel_system.db.models import ReferenceBook, ReferenceLearningRun, ReferenceProfile, ReviewItem
from novel_system.db.session import SessionLocal
from novel_system.services.style_reference.cleanup import (
    backup_legacy_to_json,
    purge_legacy_review_items,
)


def _insert_review(session, *, review_id: str, source: str | None) -> None:
    payload = {"source": source} if source is not None else {}
    review = ReviewItem(
        review_id=review_id,
        item_type="style_observation",
        status="pending",
        candidate_text="x",
        candidate_payload_json=payload,
        active_on_approve=0,
    )
    session.add(review)


def test_purge_clears_three_legacy_buckets() -> None:
    with SessionLocal() as session:
        _insert_review(session, review_id="review_reffind_abc_1", source="reference_book_learning")
        _insert_review(session, review_id="review_apply_xyz_style", source="reference_profile_apply")
        _insert_review(session, review_id="orphan_id_1", source="reference_book_learning")
        _insert_review(session, review_id="legit_unrelated_review_1", source="snowflake_workspace")
        session.flush()

        counts = purge_legacy_review_items(session)
        session.commit()

        assert counts["review_reffind_"] == 1
        assert counts["review_apply_"] == 1
        assert counts["orphan_source"] == 1

        remaining = session.execute(text("SELECT review_id FROM review_items")).scalars().all()
        assert list(remaining) == ["legit_unrelated_review_1"]


def test_purge_is_idempotent() -> None:
    with SessionLocal() as session:
        _insert_review(session, review_id="review_reffind_a", source=None)
        session.flush()

        first = purge_legacy_review_items(session)
        second = purge_legacy_review_items(session)
        session.commit()

        assert first["review_reffind_"] == 1
        assert second["review_reffind_"] == 0


def test_backup_when_legacy_table_missing_returns_zero_rows(tmp_path: Path) -> None:
    # 旧 reference_profiles 表在 conftest 的 create_all 不会创建(ORM 已不再映射它).
    # backup_legacy_to_json 应捕获 OperationalError 并返回 0 行,且仍写入 JSON 文件.
    with SessionLocal() as session:
        path, row_count = backup_legacy_to_json(session, backup_dir=tmp_path)
    assert row_count == 0
    assert path.exists()
    text_content = path.read_text(encoding="utf-8")
    assert '"row_count": 0' in text_content
    assert '"source_table": "reference_profiles"' in text_content


def test_backup_when_legacy_table_present(tmp_path: Path) -> None:
    """conftest 的 create_all 已建好旧 ORM 表;插一行 reference_profiles 验证 dump."""
    with SessionLocal() as session:
        session.add(
            ReferenceBook(
                book_id="legacy_book_1",
                title="legacy 鲁迅集",
                source_kind="upload",
                cloud_policy="local_only",
                text_checksum="legacy_sha",
                status="ready",
            )
        )
        session.add(
            ReferenceLearningRun(
                run_id="legacy_run_1",
                book_id="legacy_book_1",
                status="done",
            )
        )
        session.add(
            ReferenceProfile(
                profile_id="legacy_profile_1",
                book_id="legacy_book_1",
                run_id="legacy_run_1",
                title="legacy 鲁迅风格",
                status="ready",
                profile_json={"narrative_summary": "白描"},
                coverage_json={},
                source_finding_ids_json=[],
            )
        )
        session.commit()

        path, row_count = backup_legacy_to_json(session, backup_dir=tmp_path)

    assert row_count == 1
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "legacy 鲁迅风格" in content
    assert '"row_count": 1' in content


