from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from novel_system.tools.llm_accounting_audit import audit_database, main as audit_main
from novel_system.tools.llm_outlet_inventory import inventory_report


SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "novel_system"


def _fingerprint(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    return (
        stat.st_size,
        stat.st_mtime_ns,
        hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def _create_empty_audit_database(path: Path, *, revision: str = "test_revision") -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE alembic_version (version_num TEXT NOT NULL);
        CREATE TABLE llm_calls (
          llm_call_id TEXT PRIMARY KEY,
          scope_type TEXT,
          scope_id TEXT,
          prompt_tokens INTEGER,
          completion_tokens INTEGER,
          total_tokens INTEGER,
          estimated_tokens INTEGER,
          reserved_tokens INTEGER,
          budget_charged_tokens INTEGER,
          latency_ms INTEGER,
          usage_is_estimate INTEGER,
          accounting_status TEXT,
          request_dispatched_at TEXT,
          settled_at TEXT
        );
        CREATE TABLE llm_call_attempts (
          attempt_id TEXT PRIMARY KEY,
          llm_call_id TEXT,
          provider_attempt_no INTEGER,
          prompt_tokens INTEGER,
          completion_tokens INTEGER,
          total_tokens INTEGER,
          estimated_tokens INTEGER,
          reserved_tokens INTEGER,
          budget_charged_tokens INTEGER,
          latency_ms INTEGER,
          usage_is_estimate INTEGER,
          accounting_status TEXT,
          request_dispatched_at TEXT,
          settled_at TEXT
        );
        CREATE TABLE scene_run_states (
          scene_id TEXT PRIMARY KEY,
          attempt_budget INTEGER,
          total_attempt_count INTEGER,
          scene_token_budget INTEGER,
          scene_tokens_used INTEGER,
          scene_tokens_reserved INTEGER,
          provider_attempts_used INTEGER,
          provider_attempt_budget INTEGER
        );
        """
    )
    connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
    connection.commit()
    connection.close()


def _drop_column(path: Path, table: str, column: str) -> None:
    connection = sqlite3.connect(path)
    connection.execute(f'ALTER TABLE "{table}" DROP COLUMN "{column}"')
    connection.commit()
    connection.close()


def test_outlet_inventory_is_json_ready_and_reports_no_unified_boundary_bypass() -> None:
    report = inventory_report(SRC_ROOT)

    assert report["schema"] == "llm-outlet-inventory-v1"
    assert report["summary"]["application_outlets"] > 0
    assert report["summary"]["unified"] == report["summary"]["application_outlets"]
    assert report["summary"]["unaccounted"] == 0
    assert all(
        set(item)
        == {
            "identity",
            "path",
            "qualname",
            "line",
            "kind",
            "expression",
            "unified",
        }
        for item in report["outlets"]
    )


def test_accounting_audit_is_read_only_and_counts_integrity_defects(tmp_path: Path) -> None:
    database = tmp_path / "audit.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE alembic_version (version_num TEXT NOT NULL);
        INSERT INTO alembic_version VALUES ('test_revision');
        CREATE TABLE llm_calls (
          llm_call_id TEXT PRIMARY KEY,
          scope_type TEXT,
          scope_id TEXT,
          prompt_tokens INTEGER,
          completion_tokens INTEGER,
          total_tokens INTEGER,
          estimated_tokens INTEGER,
          reserved_tokens INTEGER,
          budget_charged_tokens INTEGER,
          latency_ms INTEGER,
          usage_is_estimate INTEGER,
          accounting_status TEXT,
          request_dispatched_at TEXT,
          settled_at TEXT,
          created_at TEXT
        );
        CREATE TABLE llm_call_attempts (
          attempt_id TEXT PRIMARY KEY,
          llm_call_id TEXT,
          provider_attempt_no INTEGER,
          request_max_output_tokens INTEGER,
          prompt_tokens INTEGER,
          completion_tokens INTEGER,
          total_tokens INTEGER,
          estimated_tokens INTEGER,
          reserved_tokens INTEGER,
          budget_charged_tokens INTEGER,
          latency_ms INTEGER,
          usage_is_estimate INTEGER,
          accounting_status TEXT,
          request_dispatched_at TEXT,
          settled_at TEXT,
          created_at TEXT
        );
        CREATE TABLE scene_run_states (
          scene_id TEXT PRIMARY KEY,
          attempt_budget INTEGER,
          total_attempt_count INTEGER,
          scene_token_budget INTEGER,
          scene_tokens_used INTEGER,
          scene_tokens_reserved INTEGER,
          provider_attempts_used INTEGER,
          provider_attempt_budget INTEGER
        );
        INSERT INTO llm_calls VALUES
          ('good', 'project', 'P1', 4, 2, 6, 7, 10, 6, 5, 0, 'settled', '2026-01-01', '2026-01-01', '2026-01-01'),
          ('bad', '', 'P2', -1, 0, -1, 7, 10, 0, 0, 1, 'failed', '2026-01-01', '2026-01-01', '2026-01-01'),
          ('stuck', 'system', 'provider_probe', 0, 0, 0, 7, 10, 0, 0, 1, 'reserved', NULL, NULL, '2000-01-01'),
          ('legacy', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2000-01-01');
        INSERT INTO llm_call_attempts VALUES
          ('a-good', 'good', 0, 8, 4, 2, 6, 7, 10, 6, 5, 0, 'settled', '2026-01-01', '2026-01-01', '2026-01-01'),
          ('a-bad', 'bad', 0, 8, -1, 0, -1, 7, 10, 0, 0, 1, 'failed', '2026-01-01', '2026-01-01', '2026-01-01'),
          ('a-stuck', 'stuck', 0, 8, 0, 0, 0, 7, 10, 0, 0, 1, 'reserved', NULL, NULL, '2000-01-01'),
          ('a-orphan', 'missing', 0, 8, 0, 0, 0, 7, 10, 0, 0, 0, 'settled', '2026-01-01', '2026-01-01', '2026-01-01');
        """
    )
    connection.commit()
    connection.close()
    before = _fingerprint(database)

    report = audit_database(database)

    assert _fingerprint(database) == before
    assert report["schema"] == "llm-accounting-audit-v1"
    assert report["database"]["read_only"] is True
    assert report["database"]["revision"] == "test_revision"
    assert report["tables"]["llm_calls"]["present"] is True
    assert report["tables"]["llm_call_attempts"]["present"] is True
    assert report["tables"]["scene_run_states"]["present"] is True
    assert report["integrity"]["scope_missing_or_blank"] == 2
    assert report["integrity"]["negative_token_rows"] == {
        "llm_calls": 1,
        "llm_call_attempts": 1,
    }
    assert report["integrity"]["stuck_reserved"] == {
        "llm_calls": 1,
        "llm_call_attempts": 1,
    }
    assert report["integrity"]["attempt_orphans"] == 1
    assert report["legacy_unreconstructable"]["calls_missing_accounting_status"] == 1
    assert report["legacy_unreconstructable"]["calls_missing_usage_provenance"] == 1
    assert report["legacy_unreconstructable"]["calls_without_attempt_ledger"] == 1
    assert report["status_counts"]["llm_calls"]["<null>"] == 1
    assert report["usage_provenance"]["llm_calls"]["unknown"] == 1


def test_accounting_audit_percent_encodes_read_only_uri_and_closes_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "space # percent %.db"
    _create_empty_audit_database(database)
    before = _fingerprint(database)
    original_connect = sqlite3.connect
    opened_uris: list[str] = []

    def recording_connect(database_uri: str, *args: object, **kwargs: object) -> sqlite3.Connection:
        opened_uris.append(database_uri)
        return original_connect(database_uri, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", recording_connect)

    report = audit_database(database)

    assert report["database"]["path"] == str(database.resolve())
    assert len(opened_uris) == 1
    assert "%20" in opened_uris[0]
    assert "%23" in opened_uris[0]
    assert "%25" in opened_uris[0]
    assert opened_uris[0].endswith("?mode=ro")
    assert _fingerprint(database) == before
    renamed = database.with_name("renamed.db")
    database.rename(renamed)
    renamed.unlink()


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("llm_calls", "scope_id"),
        ("llm_call_attempts", "provider_attempt_no"),
        ("scene_run_states", "scene_tokens_reserved"),
    ],
    ids=("parent", "attempt", "budget"),
)
def test_accounting_audit_cli_fails_closed_when_required_column_is_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    table: str,
    column: str,
) -> None:
    database = tmp_path / f"missing-{table}-{column}.db"
    _create_empty_audit_database(database)
    _drop_column(database, table, column)
    before = _fingerprint(database)

    exit_code = audit_main(["--database", str(database), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["schema"] == "llm-accounting-audit-error-v1"
    assert payload["ok"] is False
    assert payload["database"] == {
        "path": str(database.resolve()),
        "read_only": True,
    }
    assert payload["error"]["code"] == "AUDIT_REQUIRED_COLUMN_MISSING"
    assert table in payload["error"]["message"]
    assert column in payload["error"]["message"]
    assert _fingerprint(database) == before
    renamed = database.with_suffix(".renamed")
    database.rename(renamed)
    renamed.unlink()


@pytest.mark.parametrize(
    ("database_kind", "error_code"),
    [
        ("corrupt", "AUDIT_DATABASE_INVALID"),
        ("missing_tables", "AUDIT_REQUIRED_TABLE_MISSING"),
        ("invalid_revision", "AUDIT_REVISION_INVALID"),
    ],
)
def test_accounting_audit_cli_returns_stable_json_error_without_writing_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    database_kind: str,
    error_code: str,
) -> None:
    database = tmp_path / f"{database_kind}.db"
    if database_kind == "corrupt":
        database.write_bytes(b"not a sqlite database")
    elif database_kind == "missing_tables":
        connection = sqlite3.connect(database)
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('test_revision')")
        connection.commit()
        connection.close()
    else:
        _create_empty_audit_database(database, revision="bad revision!")
    before = _fingerprint(database)

    exit_code = audit_main(["--database", str(database), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert payload == {
        "schema": "llm-accounting-audit-error-v1",
        "ok": False,
        "database": {
            "path": str(database.resolve()),
            "read_only": True,
        },
        "error": {
            "code": error_code,
            "message": payload["error"]["message"],
        },
    }
    assert payload["error"]["message"]
    assert _fingerprint(database) == before
    renamed = database.with_suffix(".renamed")
    database.rename(renamed)
    renamed.unlink()


def test_accounting_audit_rejects_output_that_resolves_to_database_before_opening(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "audit.db"
    _create_empty_audit_database(database)
    before = _fingerprint(database)

    exit_code = audit_main(
        [
            "--database",
            str(database),
            "--output",
            str(database.parent / "." / database.name),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert payload["error"]["code"] == "AUDIT_OUTPUT_CONFLICT"
    assert _fingerprint(database) == before
    connection = sqlite3.connect(database)
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
        "test_revision",
    )
    connection.close()


def test_accounting_audit_cli_success_writes_only_the_separate_output_and_closes_db(
    tmp_path: Path,
) -> None:
    database = tmp_path / "source # %.db"
    output = tmp_path / "reports" / "audit.json"
    _create_empty_audit_database(database)
    before = _fingerprint(database)

    exit_code = audit_main(
        ["--database", str(database), "--output", str(output), "--json"]
    )

    assert exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["schema"] == (
        "llm-accounting-audit-v1"
    )
    assert _fingerprint(database) == before
    renamed = database.with_name("source-renamed.db")
    database.rename(renamed)
    renamed.unlink()
