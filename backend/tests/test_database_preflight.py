from __future__ import annotations

import json
import sqlite3

import pytest

from novel_system.tools import database_preflight
from novel_system.tools.database_preflight import inspect_database


HEAD_REVISION = "20260713_0065"
PREVIOUS_REVISION = "20260712_0064"


def _make_ready_database(
    path,
    *,
    revision: str = HEAD_REVISION,
    c1b: bool = True,
    structural_contract: bool = True,
    primary_key_contract: bool = True,
    ordinal_unique_contract: bool = True,
    scope_index_variant: str = "plain",
    weaken_llm_check: bool = False,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (revision,),
        )
        scene_columns = """
            scene_id TEXT NOT NULL PRIMARY KEY,
            latest_valid_draft_row_id INTEGER,
            run_policy TEXT,
            scene_token_budget INTEGER,
            scene_tokens_used INTEGER NOT NULL DEFAULT 0
        """
        if c1b:
            if structural_contract:
                scene_columns += """,
                    scene_tokens_reserved INTEGER NOT NULL DEFAULT 0,
                    scene_budget_basis_json JSON,
                    provider_attempts_used INTEGER NOT NULL DEFAULT 0,
                    provider_attempt_budget INTEGER NOT NULL DEFAULT 32,
                    active_execution_id TEXT,
                    run_execution_status TEXT,
                    run_checkpoint TEXT,
                    run_checkpoint_json JSON,
                    active_run_job_id TEXT,
                    CONSTRAINT ck_scene_run_states_tokens_reserved_nonnegative
                        CHECK (scene_tokens_reserved >= 0),
                    CONSTRAINT ck_scene_run_states_provider_attempts_used_nonnegative
                        CHECK (provider_attempts_used >= 0),
                    CONSTRAINT ck_scene_run_states_provider_attempt_budget_nonnegative
                        CHECK (provider_attempt_budget >= 0)
                """
            else:
                scene_columns += """,
                    scene_tokens_reserved INTEGER,
                    scene_budget_basis_json JSON,
                    provider_attempts_used INTEGER,
                    provider_attempt_budget INTEGER,
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
            if not structural_contract:
                connection.executescript(
                    """
                    CREATE TABLE llm_calls (
                        llm_call_id TEXT NOT NULL PRIMARY KEY,
                        scope_type TEXT,
                        scope_id TEXT,
                        run_job_id TEXT,
                        execution_id TEXT,
                        execution_step_key TEXT,
                        estimated_tokens INTEGER,
                        reserved_tokens INTEGER,
                        budget_charged_tokens INTEGER,
                        usage_is_estimate BOOLEAN,
                        accounting_status TEXT,
                        request_dispatched_at TEXT,
                        settled_at TEXT,
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE llm_call_attempts (
                        attempt_id TEXT NOT NULL PRIMARY KEY,
                        llm_call_id TEXT,
                        provider_attempt_no INTEGER,
                        dispatch_kind TEXT,
                        request_max_output_tokens INTEGER,
                        provider_request_id TEXT,
                        prompt_tokens INTEGER,
                        completion_tokens INTEGER,
                        total_tokens INTEGER,
                        estimated_tokens INTEGER,
                        reserved_tokens INTEGER,
                        budget_charged_tokens INTEGER,
                        usage_is_estimate BOOLEAN,
                        accounting_status TEXT,
                        request_dispatched_at TEXT,
                        settled_at TEXT,
                        latency_ms INTEGER,
                        error_code TEXT,
                        error_text TEXT,
                        created_at TEXT
                    );
                    CREATE TABLE chapter_run_jobs (
                        job_id TEXT NOT NULL PRIMARY KEY,
                        scene_id TEXT,
                        created_at TEXT
                    );
                    """
                )
                return
            id_nullability = "NOT NULL" if primary_key_contract else ""
            llm_call_primary_key = (
                "CONSTRAINT pk_llm_calls PRIMARY KEY (llm_call_id)"
                if primary_key_contract
                else "CONSTRAINT pk_llm_calls_wrong PRIMARY KEY (scope_id)"
            )
            attempt_primary_key = (
                "CONSTRAINT pk_llm_call_attempts PRIMARY KEY (attempt_id)"
                if primary_key_contract
                else (
                    "CONSTRAINT pk_llm_call_attempts_wrong "
                    "PRIMARY KEY (llm_call_id, provider_attempt_no)"
                )
            )
            ordinal_unique_clause = (
                ", CONSTRAINT uq_llm_call_attempts_call_ordinal "
                "UNIQUE (llm_call_id, provider_attempt_no)"
                if ordinal_unique_contract
                else ""
            )
            estimated_tokens_check = (
                "estimated_tokens >= 0 OR 1 = 1"
                if weaken_llm_check
                else "estimated_tokens >= 0"
            )
            connection.execute(
                f"""
                CREATE TABLE llm_calls (
                    llm_call_id TEXT {id_nullability},
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    run_job_id TEXT,
                    execution_id TEXT,
                    execution_step_key TEXT,
                    estimated_tokens INTEGER NOT NULL DEFAULT 0,
                    reserved_tokens INTEGER NOT NULL DEFAULT 0,
                    budget_charged_tokens INTEGER NOT NULL DEFAULT 0,
                    usage_is_estimate BOOLEAN NOT NULL DEFAULT 1,
                    accounting_status TEXT NOT NULL DEFAULT 'reserved',
                    request_dispatched_at TEXT,
                    settled_at TEXT,
                    created_at TEXT NOT NULL,
                    CONSTRAINT ck_llm_calls_estimated_tokens_nonnegative
                        CHECK ({estimated_tokens_check}),
                    CONSTRAINT ck_llm_calls_reserved_tokens_nonnegative
                        CHECK (reserved_tokens >= 0),
                    CONSTRAINT ck_llm_calls_budget_charged_tokens_nonnegative
                        CHECK (budget_charged_tokens >= 0),
                    CONSTRAINT ck_llm_calls_budget_charged_within_reservation
                        CHECK (budget_charged_tokens <= reserved_tokens),
                    CONSTRAINT ck_llm_calls_accounting_status
                        CHECK (accounting_status IN (
                            'reserved','settled','failed','released','rejected',
                            'usage_exceeds_reservation'
                        )),
                    {llm_call_primary_key}
                )
                """
            )
            connection.execute(
                f"""
                CREATE TABLE llm_call_attempts (
                    attempt_id TEXT {id_nullability},
                    llm_call_id TEXT NOT NULL,
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
                    created_at TEXT NOT NULL,
                    CONSTRAINT ck_llm_call_attempts_provider_attempt_no_nonnegative
                        CHECK (provider_attempt_no >= 0),
                    CONSTRAINT ck_llm_call_attempts_request_max_output_tokens_nonnegative
                        CHECK (request_max_output_tokens >= 0),
                    CONSTRAINT ck_llm_call_attempts_prompt_tokens_nonnegative
                        CHECK (prompt_tokens >= 0),
                    CONSTRAINT ck_llm_call_attempts_completion_tokens_nonnegative
                        CHECK (completion_tokens >= 0),
                    CONSTRAINT ck_llm_call_attempts_total_tokens_nonnegative
                        CHECK (total_tokens >= 0),
                    CONSTRAINT ck_llm_call_attempts_estimated_tokens_nonnegative
                        CHECK (estimated_tokens >= 0),
                    CONSTRAINT ck_llm_call_attempts_reserved_tokens_nonnegative
                        CHECK (reserved_tokens >= 0),
                    CONSTRAINT ck_llm_call_attempts_budget_charged_tokens_nonnegative
                        CHECK (budget_charged_tokens >= 0),
                    CONSTRAINT ck_llm_call_attempts_budget_charged_within_reservation
                        CHECK (budget_charged_tokens <= reserved_tokens),
                    CONSTRAINT ck_llm_call_attempts_latency_ms_nonnegative
                        CHECK (latency_ms >= 0),
                    CONSTRAINT ck_llm_call_attempts_accounting_status
                        CHECK (accounting_status IN (
                            'reserved','settled','failed','released','rejected',
                            'usage_exceeds_reservation'
                        )),
                    CONSTRAINT ck_llm_call_attempts_dispatch_kind
                        CHECK (dispatch_kind IN (
                            'initial','transport_retry','response_parse_retry',
                            'missing_text_degrade','system_probe'
                        )),
                    CONSTRAINT fk_llm_call_attempts_call
                        FOREIGN KEY (llm_call_id) REFERENCES llm_calls(llm_call_id)
                        ON UPDATE NO ACTION ON DELETE NO ACTION
                    {ordinal_unique_clause},
                    {attempt_primary_key}
                )
                """
            )
            if not ordinal_unique_contract:
                connection.execute(
                    """
                    CREATE UNIQUE INDEX uq_llm_call_attempts_call_ordinal_partial
                    ON llm_call_attempts (llm_call_id, provider_attempt_no)
                    WHERE accounting_status = 'settled'
                    """
                )
            connection.execute(
                """
                CREATE TABLE chapter_run_jobs (
                    job_id TEXT NOT NULL PRIMARY KEY,
                    scene_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            scope_index_prefix = (
                "CREATE UNIQUE INDEX"
                if scope_index_variant == "unique"
                else "CREATE INDEX"
            )
            scope_index_where = (
                " WHERE scope_type IS NOT NULL"
                if scope_index_variant == "partial"
                else ""
            )
            connection.executescript(
                f"""
                {scope_index_prefix} ix_llm_calls_scope_created
                    ON llm_calls (scope_type, scope_id, created_at){scope_index_where};
                CREATE INDEX ix_llm_calls_run_job ON llm_calls (run_job_id);
                CREATE INDEX ix_llm_calls_execution_step
                    ON llm_calls (execution_id, execution_step_key);
                CREATE INDEX ix_llm_calls_accounting_status
                    ON llm_calls (accounting_status);
                CREATE INDEX ix_llm_call_attempts_call_status
                    ON llm_call_attempts (llm_call_id, accounting_status);
                CREATE INDEX ix_chapter_run_jobs_scene_created
                    ON chapter_run_jobs (scene_id, created_at);
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
    assert result["schema_errors"] == []
    assert result["llm_call_attempt_orphan_count"] == 0


def test_c1b_preflight_rejects_column_complete_schema_without_structural_contract(tmp_path):
    database_path = tmp_path / "columns-only.db"
    _make_ready_database(database_path, structural_contract=False)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert result["schema_errors"] == inspect_database(
        database_path, HEAD_REVISION
    )["schema_errors"]
    assert len(result["schema_errors"]) == len(
        {json.dumps(error, sort_keys=True) for error in result["schema_errors"]}
    )
    error_kinds = {error["kind"] for error in result["schema_errors"]}
    assert {
        "column_contract",
        "check_constraint",
        "foreign_key",
        "unique_constraint",
        "index",
    } <= error_kinds
    assert any(
        error["kind"] == "column_contract"
        and error["expected"].get("default") is not None
        for error in result["schema_errors"]
    )


def test_c1b_preflight_rejects_same_index_name_with_wrong_column_order(tmp_path):
    database_path = tmp_path / "wrong-index-order.db"
    _make_ready_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX ix_llm_calls_scope_created")
        connection.execute(
            """
            CREATE INDEX ix_llm_calls_scope_created
            ON llm_calls (scope_id, scope_type, created_at)
            """
        )

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert {
        "kind": "index",
        "table": "llm_calls",
        "name": "ix_llm_calls_scope_created",
        "expected": {
            "columns": ["scope_type", "scope_id", "created_at"],
            "unique": False,
            "origin": "c",
            "partial": False,
        },
        "actual": {
            "columns": ["scope_id", "scope_type", "created_at"],
            "unique": False,
            "origin": "c",
            "partial": False,
        },
    } in result["schema_errors"]


def test_c1b_preflight_rejects_missing_or_incorrect_primary_keys(tmp_path):
    database_path = tmp_path / "wrong-primary-keys.db"
    _make_ready_database(database_path, primary_key_contract=False)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert {
        "kind": "primary_key",
        "table": "llm_calls",
        "expected": ["llm_call_id"],
        "actual": ["scope_id"],
    } in result["schema_errors"]
    assert {
        "kind": "primary_key",
        "table": "llm_call_attempts",
        "expected": ["attempt_id"],
        "actual": ["llm_call_id", "provider_attempt_no"],
    } in result["schema_errors"]
    assert {
        (error.get("table"), error.get("column"))
        for error in result["schema_errors"]
        if error["kind"] == "column_contract"
    } >= {
        ("llm_calls", "llm_call_id"),
        ("llm_call_attempts", "attempt_id"),
    }


def test_c1b_preflight_rejects_partial_unique_index_as_attempt_ordinal_constraint(tmp_path):
    database_path = tmp_path / "partial-ordinal-unique.db"
    _make_ready_database(database_path, ordinal_unique_contract=False)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert any(
        error["kind"] == "unique_constraint"
        and error["table"] == "llm_call_attempts"
        and error["expected"] == {
            "columns": ["llm_call_id", "provider_attempt_no"],
            "unique": True,
            "origin": "u",
            "partial": False,
        }
        for error in result["schema_errors"]
    )


@pytest.mark.parametrize(
    ("variant", "actual_unique", "actual_partial"),
    [("unique", True, False), ("partial", False, True)],
)
def test_c1b_preflight_rejects_required_index_with_wrong_semantics(
    tmp_path,
    variant,
    actual_unique,
    actual_partial,
):
    database_path = tmp_path / f"scope-index-{variant}.db"
    _make_ready_database(database_path, scope_index_variant=variant)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert {
        "kind": "index",
        "table": "llm_calls",
        "name": "ix_llm_calls_scope_created",
        "expected": {
            "columns": ["scope_type", "scope_id", "created_at"],
            "unique": False,
            "origin": "c",
            "partial": False,
        },
        "actual": {
            "columns": ["scope_type", "scope_id", "created_at"],
            "unique": actual_unique,
            "origin": "c",
            "partial": actual_partial,
        },
    } in result["schema_errors"]


def test_c1b_preflight_rejects_named_check_with_weakened_expression(tmp_path):
    database_path = tmp_path / "weakened-check.db"
    _make_ready_database(database_path, weaken_llm_check=True)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert {
        "kind": "check_constraint",
        "table": "llm_calls",
        "name": "ck_llm_calls_estimated_tokens_nonnegative",
        "expected": "estimated_tokens >= 0",
        "actual": "estimated_tokens >= 0 OR 1 = 1",
    } in result["schema_errors"]


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
    assert result["schema_errors"] == []
    assert "llm_call_attempt_orphan_count" not in result


def test_revision_aliases_select_the_canonical_schema_profiles(tmp_path):
    legacy_path = tmp_path / "alias-0064.db"
    c1b_path = tmp_path / "alias-0065.db"
    _make_ready_database(
        legacy_path,
        revision=PREVIOUS_REVISION,
        c1b=False,
    )
    _make_ready_database(c1b_path)

    legacy = inspect_database(legacy_path, "0064")
    c1b = inspect_database(c1b_path, "0065")

    assert legacy["ready"] is True
    assert legacy["expected_revision_canonical"] == PREVIOUS_REVISION
    assert c1b["ready"] is True
    assert c1b["expected_revision_canonical"] == HEAD_REVISION
    assert c1b["llm_call_attempt_orphan_count"] == 0


def test_unknown_expected_revision_fails_closed_even_when_database_stamp_matches(tmp_path):
    database_path = tmp_path / "unknown-revision.db"
    _make_ready_database(
        database_path,
        revision="20990101_9999",
        c1b=False,
    )

    result = inspect_database(database_path, "20990101_9999")

    assert result["ready"] is False
    assert result["error"] == "unsupported_expected_revision=20990101_9999"


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
    assert result["schema_errors"] == []


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
