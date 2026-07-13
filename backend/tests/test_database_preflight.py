from __future__ import annotations

import json
import sqlite3

from novel_system.tools import database_preflight
from novel_system.tools.database_preflight import inspect_database


HEAD_REVISION = "20260713_0065"
PREVIOUS_REVISION = "20260712_0064"


def _make_ready_database(path, *, revision: str = HEAD_REVISION, c1b: bool = True) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )
        scene_columns = """
            latest_valid_draft_row_id INTEGER,
            run_policy TEXT,
            scene_token_budget INTEGER,
            scene_tokens_used INTEGER
        """
        if c1b:
            scene_columns += """,
                scene_tokens_reserved INTEGER NOT NULL DEFAULT 0,
                scene_budget_basis_json JSON,
                provider_attempts_used INTEGER NOT NULL DEFAULT 0,
                provider_attempt_budget INTEGER NOT NULL DEFAULT 32,
                active_execution_id TEXT,
                run_execution_status TEXT,
                run_checkpoint TEXT,
                run_checkpoint_json JSON,
                active_run_job_id TEXT
            """
        connection.execute(f"CREATE TABLE scene_run_states ({scene_columns})")
        connection.execute("CREATE TABLE evaluation_experiments (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE evaluation_pairs (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE evaluation_votes (id INTEGER PRIMARY KEY)")
        if c1b:
            connection.execute(
                """
                CREATE TABLE llm_calls (
                    llm_call_id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    run_job_id TEXT,
                    execution_id TEXT,
                    execution_step_key TEXT,
                    estimated_tokens INTEGER NOT NULL DEFAULT 0,
                    reserved_tokens INTEGER NOT NULL DEFAULT 0,
                    budget_charged_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_is_estimate BOOLEAN NOT NULL DEFAULT 1,
                    accounting_status TEXT NOT NULL,
                    request_dispatched_at TEXT,
                    settled_at TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE llm_call_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    llm_call_id TEXT NOT NULL REFERENCES llm_calls(llm_call_id),
                    provider_attempt_no INTEGER NOT NULL,
                    dispatch_kind TEXT NOT NULL,
                    request_max_output_tokens INTEGER NOT NULL DEFAULT 0,
                    provider_request_id TEXT,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_tokens INTEGER NOT NULL DEFAULT 0,
                    reserved_tokens INTEGER NOT NULL DEFAULT 0,
                    budget_charged_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_is_estimate BOOLEAN NOT NULL DEFAULT 1,
                    accounting_status TEXT NOT NULL,
                    request_dispatched_at TEXT,
                    settled_at TEXT,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_text TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE chapter_run_jobs (
                    job_id TEXT PRIMARY KEY,
                    scene_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )


def test_ready_database_matches_required_schema_and_revision(tmp_path):
    database_path = tmp_path / "ready.db"
    _make_ready_database(database_path)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is True
    assert result["integrity"] == "ok"
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {}
    assert result["llm_call_attempt_orphan_count"] == 0


def test_previous_revision_uses_legacy_schema_profile(tmp_path):
    database_path = tmp_path / "ready-0064.db"
    _make_ready_database(
        database_path,
        revision=PREVIOUS_REVISION,
        c1b=False,
    )

    result = inspect_database(database_path, PREVIOUS_REVISION)

    assert result["ready"] is True
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {}
    assert "llm_call_attempt_orphan_count" not in result


def test_c1b_revision_rejects_legacy_schema_profile(tmp_path):
    database_path = tmp_path / "0065-with-legacy-schema.db"
    _make_ready_database(database_path, c1b=False)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert "llm_call_attempts" in result["missing_tables"]
    assert "scene_tokens_reserved" in result["missing_columns"]["scene_run_states"]


def test_c1b_preflight_detects_attempt_orphans_when_foreign_keys_are_disabled(tmp_path):
    database_path = tmp_path / "attempt-orphan.db"
    _make_ready_database(database_path)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (0,)
        connection.execute(
            """
            INSERT INTO llm_call_attempts (
                attempt_id, llm_call_id, provider_attempt_no, dispatch_kind,
                accounting_status, created_at
            ) VALUES ('attempt-orphan', 'missing-call', 1, 'initial', 'failed', 'now')
            """
        )

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert result["llm_call_attempt_orphan_count"] == 1
    assert result["error"] == "llm_call_attempt_orphans=1"


def test_empty_database_reports_missing_governance_tables(tmp_path):
    database_path = tmp_path / "empty.db"
    sqlite3.connect(database_path).close()

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert result["revision"] is None
    assert "evaluation_experiments" in result["missing_tables"]
    assert "scene_run_states" in result["missing_tables"]


def test_multiple_alembic_revisions_fail_closed(tmp_path):
    database_path = tmp_path / "multiple-revisions.db"
    _make_ready_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            ("extra_revision",),
        )

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert result["revision"] is None
    assert result["error"] == "alembic_version_row_count=2"


def test_cli_reports_missing_database_as_json_without_creating_it(tmp_path, capsys):
    database_path = tmp_path / "missing.db"

    exit_code = database_preflight._main(
        [str(database_path), "--expected-revision", HEAD_REVISION]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["ready"] is False
    assert output["error"]
    assert database_path.exists() is False


def test_cli_atomically_writes_utf8_json_output(tmp_path, capsys):
    database_path = tmp_path / "ready.db"
    output_path = tmp_path / "nested" / "preflight.json"
    _make_ready_database(database_path)

    exit_code = database_preflight._main(
        [
            str(database_path),
            "--expected-revision",
            HEAD_REVISION,
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["ready"] is True
    raw = output_path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["ready"] is True
    assert list(output_path.parent.glob(f".{output_path.name}.*.tmp")) == []
