from __future__ import annotations

from pathlib import Path

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


def test_migration_built_schema_has_every_orm_table_and_column(
    tmp_path, monkeypatch
) -> None:
    """Guard against model/migration drift (the class that broke `start-dev`).

    Production and dev build their schema via ``alembic upgrade head`` (the app's
    ``auto_create_tables`` defaults to False), while the test suite builds it via
    ``Base.metadata.create_all``. That split means a new ORM column/table without a
    matching migration passes every existing test yet 500s at runtime with
    ``OperationalError: no such column ...``. This test closes that gap: it builds a
    fresh DB purely from the migration chain and asserts every ORM-declared table and
    column is present. If this fails, write the missing Alembic migration.

    Scope is intentionally the hard-break class only (missing tables/columns). Softer
    diffs (NOT NULL / index / FK) are excluded because SQLite reflection reports them
    as benign false positives and they do not cause read-time 500s.
    """
    from alembic import command
    from alembic.config import Config

    from novel_system.db.session import reset_engine

    migrated_db = tmp_path / "migrated.db"
    monkeypatch.setenv("NOVEL_SYSTEM_DATABASE_URL", f"sqlite:///{migrated_db}")
    reset_engine()  # force env.py's get_settings().database_url to read the new URL

    # Keep the run hermetic: migration 0036 (drop legacy reference_learning) consults
    # `<repo>/backups/` — point it at a throwaway dir with a dummy backup so the test
    # never depends on (or touches) the real, gitignored backups directory.
    fake_root = tmp_path / "repo_root"
    (fake_root / "backups").mkdir(parents=True)
    (fake_root / "backups" / "style_reference_legacy_test.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("STYLE_REFERENCE_REPO_ROOT", str(fake_root))

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    try:
        command.upgrade(cfg, "head")

        engine = sa.create_engine(f"sqlite:///{migrated_db}")
        try:
            inspector = sa.inspect(engine)
            db_tables = set(inspector.get_table_names())
            drift: dict[str, object] = {}
            for table_name, table in Base.metadata.tables.items():
                if table_name not in db_tables:
                    drift[table_name] = "<entire table missing>"
                    continue
                db_cols = {col["name"] for col in inspector.get_columns(table_name)}
                missing_cols = {c.name for c in table.columns} - db_cols
                if missing_cols:
                    drift[table_name] = sorted(missing_cols)
        finally:
            engine.dispose()
    finally:
        reset_engine()  # restore engine singleton for subsequent tests

    assert not drift, (
        "Migration-built schema is missing ORM-declared tables/columns. "
        "An ORM model changed without a matching Alembic migration — write one. "
        f"Drift: {drift}"
    )
