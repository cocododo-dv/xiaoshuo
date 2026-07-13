from __future__ import annotations

import json
import sqlite3

from novel_system.tools import database_preflight
from novel_system.tools.database_preflight import inspect_database


HEAD_REVISION = "20260712_0064"


def _make_ready_database(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (HEAD_REVISION,),
        )
        connection.execute(
            """
            CREATE TABLE scene_run_states (
                latest_valid_draft_row_id INTEGER,
                run_policy TEXT,
                scene_token_budget INTEGER,
                scene_tokens_used INTEGER
            )
            """
        )
        connection.execute("CREATE TABLE evaluation_experiments (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE evaluation_pairs (id INTEGER PRIMARY KEY)")
        connection.execute("CREATE TABLE evaluation_votes (id INTEGER PRIMARY KEY)")


def test_ready_database_matches_required_schema_and_revision(tmp_path):
    database_path = tmp_path / "ready.db"
    _make_ready_database(database_path)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is True
    assert result["integrity"] == "ok"
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {}


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
