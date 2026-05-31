from __future__ import annotations

import sqlalchemy as sa

from novel_system.db.base import Base
from novel_system.settings import get_settings


def test_settings_disable_auto_create_tables_by_default(monkeypatch) -> None:
    monkeypatch.delenv("NOVEL_SYSTEM_AUTO_CREATE_TABLES", raising=False)

    settings = get_settings(include_runtime_config=False)

    assert settings.auto_create_tables is False


def test_primary_metadata_excludes_legacy_reference_tables() -> None:
    assert "style_reference_books" in Base.metadata.tables
    assert "style_reference_profiles" in Base.metadata.tables
    assert "reference_books" not in Base.metadata.tables
    assert "reference_profiles" not in Base.metadata.tables


def test_create_all_only_builds_main_schema(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "metadata_isolation.db"
    monkeypatch.setenv("NOVEL_SYSTEM_DATABASE_URL", f"sqlite:///{db_path}")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    try:
        Base.metadata.create_all(bind=engine)
        tables = set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert "style_reference_books" in tables
    assert "style_reference_profiles" in tables
    assert "reference_books" not in tables
    assert "reference_profiles" not in tables
