from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from novel_system.tools import database_preflight
from novel_system.tools.database_preflight import inspect_database


HEAD_REVISION = "20260713_0065"
PREVIOUS_REVISION = "20260712_0064"
EVIDENCE_GATE_REVISION = "20260715_0066"
PAIR_GENRE_REVISION = "20260715_0067"
NARRATIVE_POSITION_REVISION = "20260715_0068"
LATEST_REVISION = "20260715_0069"
QUALITY_EVIDENCE_REVISION = "20260715_0070"
BACKGROUND_RECOVERY_REVISION = "20260716_0071"
AUTHOR_PREFERENCE_CONSTRAINT_REVISION = "20260716_0072"
LLM_AUDIT_PRIVACY_REVISION = "20260716_0073"


def _migrate_database(
    path: Path,
    revision: str,
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from alembic import command
    from alembic.config import Config

    from novel_system.db.session import reset_engine

    fake_root = tmp_path / f"migration-root-{revision}"
    backups_dir = fake_root / "backups"
    backups_dir.mkdir(parents=True)
    (backups_dir / "style_reference_legacy_preflight.json").write_text(
        "[]",
        encoding="utf-8",
    )

    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    with monkeypatch.context() as migration_env:
        migration_env.setenv(
            "NOVEL_SYSTEM_DATABASE_URL",
            f"sqlite:///{path.as_posix()}",
        )
        migration_env.setenv("STYLE_REFERENCE_REPO_ROOT", str(fake_root))
        reset_engine()
        try:
            command.upgrade(config, revision)
        finally:
            reset_engine()


def _drop_columns(
    path: Path,
    columns_by_table: dict[str, tuple[str, ...]],
) -> None:
    with sqlite3.connect(path) as connection:
        for table_name, column_names in columns_by_table.items():
            table_identifier = database_preflight._quote_identifier(table_name)
            existing = {
                str(row[1])
                for row in connection.execute(f"PRAGMA table_info({table_identifier})")
            }
            for column_name in column_names:
                if column_name not in existing:
                    continue
                column_identifier = database_preflight._quote_identifier(column_name)
                connection.execute(
                    f"ALTER TABLE {table_identifier} DROP COLUMN {column_identifier}"
                )


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
    check_decoy: str | None = None,
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
        # Orphan governance scans these relations independently from the
        # minimum revision schema profile.  A database advertised as ready
        # must provide the complete scanner dependency graph.
        connection.executescript(
            """
            CREATE TABLE story_projects (project_id TEXT PRIMARY KEY);
            CREATE TABLE snowflake_step_runs (
                step_run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL
            );
            CREATE TABLE snowflake_scene_plans (
                scene_plan_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL
            );
            CREATE TABLE snowflake_revision_links (
                revision_link_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                source_step_key TEXT NOT NULL,
                source_step_run_id TEXT,
                affected_kind TEXT NOT NULL,
                affected_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (project_id) REFERENCES story_projects(project_id)
            );
            """
        )
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
            estimated_tokens_contract = (
                "CONSTRAINT ck_llm_calls_estimated_tokens_nonnegative "
                f"CHECK ({estimated_tokens_check}),"
            )
            decoy = (
                "CONSTRAINT ck_llm_calls_estimated_tokens_nonnegative "
                "CHECK (estimated_tokens >= 0)"
            )
            if check_decoy == "string":
                estimated_tokens_contract = f"decoy_text TEXT DEFAULT '{decoy}',"
            elif check_decoy == "line_comment":
                estimated_tokens_contract = f"-- {decoy}\n"
            elif check_decoy == "block_comment":
                estimated_tokens_contract = f"/* {decoy} */"
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
                    {estimated_tokens_contract}
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
                            'api_mode_degrade','structured_output_degrade',
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
    assert result["foreign_keys"] == 1
    assert result["orphan_integrity"]["blocking_missing_dependencies"] == {}
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


@pytest.mark.parametrize("decoy_kind", ["string", "line_comment", "block_comment"])
def test_c1b_preflight_ignores_named_check_decoys(tmp_path, decoy_kind):
    database_path = tmp_path / f"check-decoy-{decoy_kind}.db"
    _make_ready_database(database_path, check_decoy=decoy_kind)

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert {
        "kind": "check_constraint",
        "table": "llm_calls",
        "name": "ck_llm_calls_estimated_tokens_nonnegative",
        "expected": "estimated_tokens >= 0",
        "actual": [],
    } in result["schema_errors"]


@pytest.mark.parametrize(
    "quoted_name",
    [
        '"ck_llm_calls_estimated_tokens_nonnegative"',
        "`ck_llm_calls_estimated_tokens_nonnegative`",
        "[ck_llm_calls_estimated_tokens_nonnegative]",
    ],
)
def test_named_check_scanner_supports_quoted_names_and_nested_expression(quoted_name):
    constraint_name = "ck_llm_calls_estimated_tokens_nonnegative"
    sql = (
        "CREATE TABLE example (value INTEGER, note TEXT, CONSTRAINT "
        f"{quoted_name} CHECK ((value >= 0) AND note != 'right ) parenthesis'))"
    )

    assert database_preflight._named_check_expressions(sql, constraint_name) == [
        "(value >= 0) AND note != 'right ) parenthesis'"
    ]
    quoted_decoy = (
        'CREATE TABLE example ("CONSTRAINT '
        f'{constraint_name} CHECK (value >= 0)" TEXT)'
    )
    assert database_preflight._named_check_expressions(quoted_decoy, constraint_name) == []


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


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("0066", EVIDENCE_GATE_REVISION),
        ("0067", PAIR_GENRE_REVISION),
        ("0068", NARRATIVE_POSITION_REVISION),
        ("0069", LATEST_REVISION),
        ("0070", QUALITY_EVIDENCE_REVISION),
        ("0071", BACKGROUND_RECOVERY_REVISION),
        ("0072", AUTHOR_PREFERENCE_CONSTRAINT_REVISION),
        ("0073", LLM_AUDIT_PRIVACY_REVISION),
    ],
)
def test_new_revision_aliases_resolve_to_canonical_revisions(alias, canonical):
    assert database_preflight.REVISION_ALIASES[alias] == canonical
    assert database_preflight.REVISION_ALIASES[canonical] == canonical


def test_fresh_0069_database_passes_head_preflight(tmp_path, monkeypatch):
    database_path = tmp_path / "fresh-0069.db"
    _migrate_database(
        database_path,
        LATEST_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    result = inspect_database(database_path, "0069")

    assert result["revision"] == LATEST_REVISION
    assert result["expected_revision_canonical"] == LATEST_REVISION
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {}
    assert result["schema_errors"] == []
    assert result["ready"] is True, result


def test_fresh_0070_database_passes_quality_evidence_preflight(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "fresh-0070.db"
    _migrate_database(
        database_path,
        QUALITY_EVIDENCE_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    result = inspect_database(database_path, "0070")

    assert result["revision"] == QUALITY_EVIDENCE_REVISION
    assert result["expected_revision_canonical"] == QUALITY_EVIDENCE_REVISION
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {}
    assert result["schema_errors"] == []
    assert result["foreign_keys"] == 1
    assert result["ready"] is True, result


def test_fresh_0073_database_passes_llm_audit_privacy_preflight(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "fresh-0073.db"
    _migrate_database(
        database_path,
        LLM_AUDIT_PRIVACY_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )

    result = inspect_database(database_path, "0073")

    assert result["revision"] == LLM_AUDIT_PRIVACY_REVISION
    assert result["expected_revision_canonical"] == LLM_AUDIT_PRIVACY_REVISION
    assert result["missing_tables"] == []
    assert result["missing_columns"] == {}
    assert result["schema_errors"] == []
    assert result["foreign_keys"] == 1
    assert result["ready"] is True, result


def test_0070_preflight_rejects_missing_quality_evidence_index(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "0070-missing-quality-index.db"
    _migrate_database(
        database_path,
        QUALITY_EVIDENCE_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX ix_quality_benchmark_manifests_hash")

    result = inspect_database(database_path, QUALITY_EVIDENCE_REVISION)

    assert result["ready"] is False
    assert {
        "kind": "index",
        "table": "quality_benchmark_manifests",
        "name": "ix_quality_benchmark_manifests_hash",
        "expected": {
            "columns": ["manifest_hash"],
            "unique": True,
            "origin": "c",
            "partial": False,
        },
        "actual": None,
    } in result["schema_errors"]


def test_0070_preflight_rejects_column_only_quality_evidence_table(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "0070-column-only-quality-table.db"
    _migrate_database(
        database_path,
        QUALITY_EVIDENCE_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DROP TABLE quality_value_observations")
        connection.execute(
            """
            CREATE TABLE quality_value_observations (
                observation_id VARCHAR NOT NULL,
                result_id VARCHAR NOT NULL,
                reviewer_ref VARCHAR NOT NULL,
                provenance VARCHAR NOT NULL,
                source_text_hash VARCHAR,
                edited_text_hash VARCHAR,
                human_edit_distance INTEGER,
                human_edit_distance_ratio FLOAT,
                first_usable BOOLEAN,
                follow_read_intent INTEGER,
                created_at VARCHAR NOT NULL
            )
            """
        )

    result = inspect_database(database_path, QUALITY_EVIDENCE_REVISION)

    assert result["ready"] is False
    errors = [
        error
        for error in result["schema_errors"]
        if error.get("table") == "quality_value_observations"
    ]
    assert {error["kind"] for error in errors} == {
        "primary_key",
        "check_constraint",
        "foreign_key",
        "unique_constraint",
        "index",
    }


@pytest.mark.parametrize(
    ("runtime_policy", "expected_error", "valid"),
    [
        ("off", "sqlite_foreign_key_runtime_policy_disabled", True),
        ("not-a-boolean", "sqlite_foreign_key_runtime_policy_invalid", False),
    ],
)
def test_preflight_rejects_disabled_or_invalid_runtime_fk_policy(
    tmp_path,
    monkeypatch,
    runtime_policy,
    expected_error,
    valid,
):
    database_path = tmp_path / f"runtime-fk-{runtime_policy}.db"
    _migrate_database(
        database_path,
        QUALITY_EVIDENCE_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    monkeypatch.setenv("NOVEL_SYSTEM_SQLITE_FOREIGN_KEYS_ENABLED", runtime_policy)

    result = inspect_database(database_path, QUALITY_EVIDENCE_REVISION)
    # The suite-wide database fixture tears its engine down before pytest
    # unwinds this test's monkeypatch fixture.  Restore the strict setting here
    # so an intentionally malformed value cannot poison fixture teardown.
    monkeypatch.delenv("NOVEL_SYSTEM_SQLITE_FOREIGN_KEYS_ENABLED", raising=False)

    assert result["ready"] is False
    assert result["error"] == expected_error
    assert result["foreign_keys"] == 1
    assert result["runtime_foreign_key_policy"] == {
        "enabled": False,
        "valid": valid,
        "source": "environment",
        "raw": runtime_policy,
    }


def test_0070_preflight_rejects_missing_generation_policy_hash(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "0070-missing-generation-policy-hash.db"
    _migrate_database(
        database_path,
        QUALITY_EVIDENCE_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    _drop_columns(
        database_path,
        {"quality_benchmark_runs": ("generation_policy_hash",)},
    )

    result = inspect_database(database_path, QUALITY_EVIDENCE_REVISION)

    assert result["ready"] is False
    assert "generation_policy_hash" in result["missing_columns"][
        "quality_benchmark_runs"
    ]


def test_0069_preflight_rejects_missing_canonical_columns(tmp_path, monkeypatch):
    database_path = tmp_path / "0069-missing-canonical-column.db"
    _migrate_database(
        database_path,
        LATEST_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    _drop_columns(database_path, {"final_scenes": ("content_hash",)})

    result = inspect_database(database_path, LATEST_REVISION)

    assert result["ready"] is False
    assert "content_hash" in result["missing_columns"]["final_scenes"]
    assert result["schema_errors"] == []


def test_0069_preflight_rejects_missing_narrative_index(tmp_path, monkeypatch):
    database_path = tmp_path / "0069-missing-narrative-index.db"
    _migrate_database(
        database_path,
        LATEST_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX ix_narrative_events_project_entity_scene")

    result = inspect_database(database_path, LATEST_REVISION)

    assert result["ready"] is False
    assert {
        "kind": "index",
        "table": "narrative_events",
        "name": "ix_narrative_events_project_entity_scene",
        "expected": {
            "columns": ["project_id", "entity_id", "scene_id"],
            "unique": False,
            "origin": "c",
            "partial": False,
        },
        "actual": None,
    } in result["schema_errors"]


def test_0068_profile_does_not_require_0069_columns(tmp_path, monkeypatch):
    database_path = tmp_path / "fresh-0068.db"
    _migrate_database(
        database_path,
        NARRATIVE_POSITION_REVISION,
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
    )
    _drop_columns(
        database_path,
        {
            table_name: tuple(contracts)
            for table_name, contracts in (
                database_preflight.AUTHOR_CANONICAL_COLUMN_CONTRACTS.items()
            )
        },
    )
    with sqlite3.connect(database_path) as connection:
        final_scene_columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(final_scenes)")
        }
    assert "content_hash" not in final_scene_columns

    result = inspect_database(database_path, "0068")

    assert result["ready"] is True
    assert result["foreign_keys"] == 1
    assert result["orphan_integrity"]["blocking_missing_dependencies"] == {}
    assert result["expected_revision_canonical"] == NARRATIVE_POSITION_REVISION
    assert result["missing_columns"] == {}
    assert result["schema_errors"] == []


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


def test_preflight_fails_closed_for_unknown_foreign_key_orphans(tmp_path):
    database_path = tmp_path / "unknown-fk-orphan.db"
    _make_ready_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE unrelated_parents (
                parent_id TEXT PRIMARY KEY
            );
            CREATE TABLE unrelated_children (
                child_id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES unrelated_parents(parent_id)
            );
            INSERT INTO unrelated_children VALUES ('child-orphan', 'missing-parent');
            """
        )

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert result["llm_call_attempt_orphan_count"] == 0
    assert result["orphan_integrity"]["active_record_count"] == 0
    assert result["foreign_key_violations"]["count"] == 1
    assert result["foreign_key_violations"]["by_child_table"] == {
        "unrelated_children": 1
    }
    assert result["error"] == "foreign_key_violations=1"


def test_preflight_distinguishes_exported_and_remediated_orphans(tmp_path):
    from novel_system.tools.orphan_quarantine import apply_evidence, export_evidence

    database_path = tmp_path / "snowflake-orphan.db"
    evidence_path = tmp_path / "orphan-evidence.jsonl"
    _make_ready_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO snowflake_revision_links VALUES (
                'revision-orphan', 'missing-project', 'book_brief', NULL,
                'scene_plan', 'future-id', 'project was purged', 'open', 'now', NULL
            )
            """
        )

    unhandled = inspect_database(database_path, HEAD_REVISION)
    exported = export_evidence(database_path, evidence_path)
    pending = inspect_database(
        database_path,
        HEAD_REVISION,
        orphan_evidence_path=evidence_path,
    )

    assert unhandled["ready"] is False
    assert unhandled["snowflake_revision_link_orphan_count"] == 1
    assert unhandled["orphan_integrity"]["status"] == "unhandled"
    assert unhandled["foreign_key_violations"]["count"] == 1
    assert pending["ready"] is False
    assert pending["orphan_integrity"]["status"] == "exported_pending_apply"

    apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=tmp_path / "pre-apply.db",
        receipt_path=tmp_path / "apply-receipt.json",
    )
    remediated = inspect_database(
        database_path,
        HEAD_REVISION,
        orphan_evidence_path=evidence_path,
    )

    assert remediated["ready"] is True
    assert remediated["snowflake_revision_link_orphan_count"] == 0
    assert remediated["foreign_key_violations"]["count"] == 0
    assert (
        remediated["orphan_integrity"]["status"]
        == "remediated_with_verified_export"
    )


def test_preflight_fails_closed_when_orphan_scanner_dependency_is_missing(tmp_path):
    database_path = tmp_path / "missing-scan-dependency.db"
    _make_ready_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE snowflake_scene_plans")

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert result["orphan_integrity"]["missing_dependencies"] == {
        "snowflake_revision_links": ["snowflake_scene_plans"]
    }
    assert result["orphan_integrity"]["blocking_missing_dependencies"] == {
        "snowflake_revision_links": ["snowflake_scene_plans"]
    }
    assert result["error"] == (
        "orphan_scan_missing_dependencies=snowflake_revision_links"
    )


def test_preflight_rejects_unsupported_snowflake_affected_kind(tmp_path):
    database_path = tmp_path / "unsupported-affected-kind.db"
    _make_ready_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("INSERT INTO story_projects VALUES ('p1')")
        connection.execute(
            """
            INSERT INTO snowflake_revision_links VALUES (
                'revision-unsupported', 'p1', 'book_brief', NULL,
                'future_kind', 'future-id', 'unknown target type', 'open', 'now', NULL
            )
            """
        )

    result = inspect_database(database_path, HEAD_REVISION)

    assert result["ready"] is False
    assert result["snowflake_revision_link_orphan_count"] == 1
    assert result["orphan_integrity"]["active_counts_by_reason"] == {
        "unsupported_affected_kind": 1
    }
    assert result["foreign_key_violations"]["count"] == 0
