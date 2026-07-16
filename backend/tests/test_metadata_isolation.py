from __future__ import annotations

import logging
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
    assert "llm_call_attempts" in tables
    assert "reference_books" not in tables
    assert "reference_profiles" not in tables


def _schema_snapshot(engine) -> dict:
    """Reflect tables, per-table column names, and per-table named indexes.

    Both compared databases are reflected through the same SQLite inspector, so
    SQLite-specific reflection quirks (FK/nullable under-reporting) appear identically
    on both sides and cancel out. Auto-generated ``sqlite_autoindex_*`` entries are
    dropped (they track inline UNIQUE/PK constraints, not user-declared indexes).
    """
    inspector = sa.inspect(engine)
    tables = {t for t in inspector.get_table_names() if t != "alembic_version"}
    columns = {t: frozenset(c["name"] for c in inspector.get_columns(t)) for t in tables}
    indexes = {}
    for table_name in tables:
        rows = set()
        for index in inspector.get_indexes(table_name):
            name = index.get("name") or ""
            if name.startswith("sqlite_autoindex"):
                continue
            rows.add((name, tuple(index.get("column_names") or ()), bool(index.get("unique"))))
        indexes[table_name] = frozenset(rows)
    return {"tables": tables, "columns": columns, "indexes": indexes}


def test_migration_built_schema_matches_orm_models(tmp_path, monkeypatch) -> None:
    """Guard against model/migration drift (the class that broke ``start-dev``).

    Production and dev build their schema via ``alembic upgrade head`` (the app's
    ``auto_create_tables`` defaults to False), while the test suite builds it via
    ``Base.metadata.create_all``. When the two diverge — e.g. a new ORM column or a
    migration-only index — every existing test still passes (it runs on the ORM-built
    schema) yet runtime 500s (``OperationalError: no such column ...``) or silently
    loses a constraint. This builds the schema BOTH ways and diffs them, so either
    direction of drift fails loudly: write the missing migration, or declare the
    missing index on the model.

    Compared dimensions: tables, columns, and named indexes (incl. uniqueness). NOT
    NULL / FK reflection is intentionally not asserted — SQLite under-reports it, and
    it does not cause runtime breaks.
    """
    from alembic import command
    from alembic.config import Config

    from novel_system.db.session import reset_engine

    # Backup stub so migration 0036 (drop legacy reference_learning) passes its guard
    # without touching the real, gitignored backups directory.
    fake_root = tmp_path / "repo_root"
    (fake_root / "backups").mkdir(parents=True)
    (fake_root / "backups" / "style_reference_legacy_test.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("STYLE_REFERENCE_REPO_ROOT", str(fake_root))

    migrated_db = tmp_path / "migrated.db"
    create_all_db = tmp_path / "create_all.db"
    monkeypatch.setenv("NOVEL_SYSTEM_DATABASE_URL", f"sqlite:///{migrated_db}")
    reset_engine()  # force env.py's get_settings().database_url to read the new URL

    backend_dir = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    audit_logger = logging.getLogger(
        "novel_system.services.metadata_isolation_audit_sentinel"
    )
    original_logger_disabled = audit_logger.disabled
    audit_logger.disabled = False
    audit_logger_preserved = False
    try:
        command.upgrade(cfg, "head")
        audit_logger_preserved = not audit_logger.disabled
        migrated_engine = sa.create_engine(f"sqlite:///{migrated_db}")
        create_all_engine = sa.create_engine(f"sqlite:///{create_all_db}")
        try:
            Base.metadata.create_all(bind=create_all_engine)
            from_migrations = _schema_snapshot(migrated_engine)
            from_models = _schema_snapshot(create_all_engine)
        finally:
            migrated_engine.dispose()
            create_all_engine.dispose()
    finally:
        audit_logger.disabled = original_logger_disabled
        reset_engine()  # restore engine singleton for subsequent tests

    assert audit_logger_preserved, (
        "in-process Alembic migration disabled an existing application audit logger"
    )
    assert from_migrations["tables"] == from_models["tables"], (
        "Tables differ between migrations and ORM models. "
        f"only-in-migrations={sorted(from_migrations['tables'] - from_models['tables'])}, "
        f"only-in-models={sorted(from_models['tables'] - from_migrations['tables'])}"
    )

    column_drift = {
        t: sorted(from_migrations["columns"][t] ^ from_models["columns"][t])
        for t in from_migrations["tables"]
        if from_migrations["columns"][t] != from_models["columns"][t]
    }
    assert not column_drift, (
        "Column drift between migrations and ORM models — an ORM model changed without "
        f"a matching Alembic migration (or vice versa). Write one. Drift: {column_drift}"
    )

    index_drift = {
        t: {
            "only-in-migrations": sorted(from_migrations["indexes"][t] - from_models["indexes"][t]),
            "only-in-models": sorted(from_models["indexes"][t] - from_migrations["indexes"][t]),
        }
        for t in from_migrations["tables"]
        if from_migrations["indexes"][t] != from_models["indexes"][t]
    }
    assert not index_drift, (
        "Index drift between migrations and ORM models — declare the index on the model "
        f"(__table_args__) or add a migration. Drift: {index_drift}"
    )
