"""Alembic 0036 / 0037 双向 migration + glob 断言失败路径单测。

参见 plans/style-reference-v1-1-fancy-shannon.md §"测试策略"。

本文件覆盖父 conftest 的 `isolated_database` autouse fixture(它会调
Base.metadata.create_all,与 alembic up/down 互相干扰),改用一个仅
monkeypatch DATABASE_URL 的轻量替代。
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

REVISION_BASE = "20260515_0035"
REVISION_DROP_LEGACY = "20260523_0036"
REVISION_NEW_SCHEMA = "20260523_0037"

NEW_TABLES = [
    "style_reference_books",
    "style_reference_paragraphs",
    "style_reference_runs",
    "style_reference_extractions",
    "style_reference_quotes",
    "style_reference_findings",
    "style_reference_evidences",
    "style_reference_profiles",
    "style_reference_injection_bindings",
    "style_reference_validation_reports",
    "style_reference_banned_terms",
]

LEGACY_TABLES = [
    "reference_books",
    "reference_book_segments",
    "reference_learning_runs",
    "reference_learning_rounds",
    "reference_findings",
    "reference_profiles",
]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(_backend_root() / "alembic.ini"))
    cfg.set_main_option("script_location", str(_backend_root() / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture(autouse=True)
def isolated_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Path, None, None]:
    """覆盖父 conftest 的同名 fixture:仅设 DB URL,不调 create_all。"""
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("NOVEL_SYSTEM_DATABASE_URL", db_url)
    monkeypatch.setenv("NOVEL_SYSTEM_VECTOR_BACKEND", "memory")
    monkeypatch.setenv("NOVEL_SYSTEM_CHROMA_DIR", str(tmp_path / "chroma"))
    from novel_system.db.session import reset_engine

    reset_engine()
    yield db_path
    reset_engine()


@pytest.fixture
def fake_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """伪造 backups/style_reference_legacy_*.json,让 0036 的 glob 断言通过。

    0036 的 `_repo_root()` 优先读 `STYLE_REFERENCE_REPO_ROOT` 环境变量,
    便于测试与真实 backups/ 隔离。
    """
    fake_root = tmp_path / "fake_repo"
    fake_root.mkdir()
    backup_dir = fake_root / "backups"
    backup_dir.mkdir()
    (backup_dir / "style_reference_legacy_20260523_000000.json").write_text(
        '{"row_count": 0, "profiles": []}',
        encoding="utf-8",
    )
    monkeypatch.setenv("STYLE_REFERENCE_REPO_ROOT", str(fake_root))
    return fake_root


def _existing_tables(db_url: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _list_indexes(db_url: str, table_name: str) -> set[str]:
    engine = sa.create_engine(db_url)
    try:
        return {idx["name"] for idx in sa.inspect(engine).get_indexes(table_name)}
    finally:
        engine.dispose()


def test_upgrade_creates_eleven_new_tables(
    isolated_database: Path,
    fake_backup: Path,
) -> None:
    db_url = f"sqlite:///{isolated_database}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")

    tables = _existing_tables(db_url)
    for tbl in NEW_TABLES:
        assert tbl in tables, f"{tbl} 未创建"
    # 旧表已被 0036 drop
    for tbl in LEGACY_TABLES:
        assert tbl not in tables, f"{tbl} 应已被 0036 drop"


def test_indexes_present(isolated_database: Path, fake_backup: Path) -> None:
    db_url = f"sqlite:///{isolated_database}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")

    assert "ix_style_reference_books_status_updated_at" in _list_indexes(
        db_url, "style_reference_books"
    )
    assert "ix_style_reference_findings_book_sub_kind" in _list_indexes(
        db_url, "style_reference_findings"
    )
    assert "ix_style_reference_extractions_book_layer_sub" in _list_indexes(
        db_url, "style_reference_extractions"
    )


def test_upgrade_without_backup_raises(
    isolated_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 覆盖 session-scoped backup stub:指向一个空目录,让 0036 的 glob 断言失败
    empty_root = tmp_path / "no_backup_repo"
    empty_root.mkdir()
    monkeypatch.setenv("STYLE_REFERENCE_REPO_ROOT", str(empty_root))

    db_url = f"sqlite:///{isolated_database}"
    cfg = _alembic_config(db_url)
    with pytest.raises(RuntimeError, match=r"backups/style_reference_legacy_"):
        command.upgrade(cfg, "head")


def test_downgrade_drops_new_tables_then_recreates_legacy(
    isolated_database: Path,
    fake_backup: Path,
) -> None:
    db_url = f"sqlite:///{isolated_database}"
    cfg = _alembic_config(db_url)
    command.upgrade(cfg, "head")
    assert "style_reference_books" in _existing_tables(db_url)

    # 退到 0036(11 张新表消失,旧表仍不存在)
    command.downgrade(cfg, REVISION_DROP_LEGACY)
    tables_after_drop_new = _existing_tables(db_url)
    for tbl in NEW_TABLES:
        assert tbl not in tables_after_drop_new
    for tbl in LEGACY_TABLES:
        assert tbl not in tables_after_drop_new

    # 退到 0035(0036 downgrade 重建空旧表)
    command.downgrade(cfg, REVISION_BASE)
    tables_after_full_down = _existing_tables(db_url)
    for tbl in NEW_TABLES:
        assert tbl not in tables_after_full_down
    for tbl in LEGACY_TABLES:
        assert tbl in tables_after_full_down, f"{tbl} 应被 0036.downgrade 重建"

    # 再次升至 head 应成功
    command.upgrade(cfg, "head")
    tables_after_up = _existing_tables(db_url)
    for tbl in NEW_TABLES:
        assert tbl in tables_after_up
