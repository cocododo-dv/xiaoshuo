from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sqlite3
import sys
from pathlib import Path
from typing import Any


LEGACY_REQUIRED_TABLES = (
    "evaluation_experiments",
    "evaluation_pairs",
    "evaluation_votes",
    "scene_run_states",
)

LEGACY_REQUIRED_COLUMNS = {
    "scene_run_states": (
        "latest_valid_draft_row_id",
        "run_policy",
        "scene_token_budget",
        "scene_tokens_used",
    ),
}

LEGACY_REVISION = "20260712_0064"
C1B_REVISION = "20260713_0065"
REVISION_ALIASES = {
    "0064": LEGACY_REVISION,
    LEGACY_REVISION: LEGACY_REVISION,
    "0065": C1B_REVISION,
    C1B_REVISION: C1B_REVISION,
}
C1B_REQUIRED_TABLES = LEGACY_REQUIRED_TABLES + (
    "llm_calls",
    "llm_call_attempts",
    "chapter_run_jobs",
)
C1B_REQUIRED_COLUMNS = {
    **LEGACY_REQUIRED_COLUMNS,
    "scene_run_states": LEGACY_REQUIRED_COLUMNS["scene_run_states"]
    + (
        "scene_tokens_reserved",
        "scene_budget_basis_json",
        "provider_attempts_used",
        "provider_attempt_budget",
        "active_execution_id",
        "run_execution_status",
        "run_checkpoint",
        "run_checkpoint_json",
        "active_run_job_id",
    ),
    "llm_calls": (
        "scope_type",
        "scope_id",
        "run_job_id",
        "execution_id",
        "execution_step_key",
        "estimated_tokens",
        "reserved_tokens",
        "budget_charged_tokens",
        "usage_is_estimate",
        "accounting_status",
        "request_dispatched_at",
        "settled_at",
    ),
    "llm_call_attempts": (
        "attempt_id",
        "llm_call_id",
        "provider_attempt_no",
        "dispatch_kind",
        "request_max_output_tokens",
        "provider_request_id",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_tokens",
        "reserved_tokens",
        "budget_charged_tokens",
        "usage_is_estimate",
        "accounting_status",
        "request_dispatched_at",
        "settled_at",
        "latency_ms",
        "error_code",
        "error_text",
        "created_at",
    ),
    "chapter_run_jobs": ("scene_id", "created_at"),
}

C1B_COLUMN_CONTRACTS = {
    "scene_run_states": {
        "scene_tokens_reserved": {"not_null": True, "default": "0"},
        "provider_attempts_used": {"not_null": True, "default": "0"},
        "provider_attempt_budget": {"not_null": True, "default": "32"},
    },
    "llm_calls": {
        "scope_type": {"not_null": True, "default": None},
        "scope_id": {"not_null": True, "default": None},
        "estimated_tokens": {"not_null": True, "default": "0"},
        "reserved_tokens": {"not_null": True, "default": "0"},
        "budget_charged_tokens": {"not_null": True, "default": "0"},
        "usage_is_estimate": {"not_null": True, "default": "1"},
        "accounting_status": {"not_null": True, "default": "reserved"},
    },
    "llm_call_attempts": {
        "llm_call_id": {"not_null": True, "default": None},
        "provider_attempt_no": {"not_null": True, "default": None},
        "dispatch_kind": {"not_null": True, "default": None},
        "request_max_output_tokens": {"not_null": True, "default": "0"},
        "prompt_tokens": {"not_null": True, "default": "0"},
        "completion_tokens": {"not_null": True, "default": "0"},
        "total_tokens": {"not_null": True, "default": "0"},
        "estimated_tokens": {"not_null": True, "default": "0"},
        "reserved_tokens": {"not_null": True, "default": "0"},
        "budget_charged_tokens": {"not_null": True, "default": "0"},
        "usage_is_estimate": {"not_null": True, "default": "1"},
        "accounting_status": {"not_null": True, "default": None},
        "latency_ms": {"not_null": True, "default": "0"},
        "created_at": {"not_null": True, "default": None},
    },
}

C1B_CHECK_CONTRACTS = {
    "scene_run_states": (
        "scene_tokens_reserved >= 0",
        "provider_attempts_used >= 0",
        "provider_attempt_budget >= 0",
    ),
    "llm_calls": (
        "estimated_tokens >= 0",
        "reserved_tokens >= 0",
        "budget_charged_tokens >= 0",
        "budget_charged_tokens <= reserved_tokens",
        "accounting_status IN ('reserved','settled','failed','released','rejected','usage_exceeds_reservation')",
    ),
    "llm_call_attempts": (
        "provider_attempt_no >= 0",
        "request_max_output_tokens >= 0",
        "prompt_tokens >= 0",
        "completion_tokens >= 0",
        "total_tokens >= 0",
        "estimated_tokens >= 0",
        "reserved_tokens >= 0",
        "budget_charged_tokens >= 0",
        "budget_charged_tokens <= reserved_tokens",
        "latency_ms >= 0",
        "accounting_status IN ('reserved','settled','failed','released','rejected','usage_exceeds_reservation')",
        "dispatch_kind IN ('initial','transport_retry','response_parse_retry','missing_text_degrade','system_probe')",
    ),
}

C1B_INDEX_CONTRACTS = {
    "ix_llm_calls_scope_created": ("llm_calls", ("scope_type", "scope_id", "created_at")),
    "ix_llm_calls_run_job": ("llm_calls", ("run_job_id",)),
    "ix_llm_calls_execution_step": ("llm_calls", ("execution_id", "execution_step_key")),
    "ix_llm_calls_accounting_status": ("llm_calls", ("accounting_status",)),
    "ix_llm_call_attempts_call_status": (
        "llm_call_attempts",
        ("llm_call_id", "accounting_status"),
    ),
    "ix_chapter_run_jobs_scene_created": (
        "chapter_run_jobs",
        ("scene_id", "created_at"),
    ),
}


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _normalized_default(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized.strip("'\"").lower()


def _normalized_sql(value: str) -> str:
    return re.sub(r'[\s"`\[\]\(\)]', "", value).lower()


def _table_sql(connection: sqlite3.Connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _index_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> dict[str, tuple[bool, list[str]]]:
    indexes: dict[str, tuple[bool, list[str]]] = {}
    for row in connection.execute(f"PRAGMA index_list({_quote_identifier(table_name)})"):
        name = str(row[1])
        columns = [
            str(column[2])
            for column in connection.execute(f"PRAGMA index_info({_quote_identifier(name)})")
        ]
        indexes[name] = (bool(row[2]), columns)
    return indexes


def _inspect_c1b_schema(
    connection: sqlite3.Connection,
    tables: set[str],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for table_name, contracts in C1B_COLUMN_CONTRACTS.items():
        if table_name not in tables:
            continue
        columns = {
            str(row[1]): {
                "not_null": bool(row[3]),
                "default": _normalized_default(row[4]),
            }
            for row in connection.execute(
                f"PRAGMA table_info({_quote_identifier(table_name)})"
            )
        }
        for column_name, expected in contracts.items():
            actual = columns.get(column_name)
            if actual is not None and actual != expected:
                errors.append(
                    {
                        "kind": "column_contract",
                        "table": table_name,
                        "column": column_name,
                        "expected": expected,
                        "actual": actual,
                    }
                )

    for table_name, expressions in C1B_CHECK_CONTRACTS.items():
        if table_name not in tables:
            continue
        normalized_table_sql = _normalized_sql(_table_sql(connection, table_name))
        for expression in expressions:
            if "check" + _normalized_sql(expression) not in normalized_table_sql:
                errors.append(
                    {
                        "kind": "check_constraint",
                        "table": table_name,
                        "expected": expression,
                        "actual": "missing",
                    }
                )

    if "llm_call_attempts" in tables:
        expected_fk = {
            "table": "llm_calls",
            "from": "llm_call_id",
            "to": "llm_call_id",
            "on_update": "NO ACTION",
            "on_delete": "NO ACTION",
        }
        actual_fks = [
            {
                "table": str(row[2]),
                "from": str(row[3]),
                "to": str(row[4]),
                "on_update": str(row[5]).upper(),
                "on_delete": str(row[6]).upper(),
            }
            for row in connection.execute("PRAGMA foreign_key_list(llm_call_attempts)")
        ]
        if actual_fks != [expected_fk]:
            errors.append(
                {
                    "kind": "foreign_key",
                    "table": "llm_call_attempts",
                    "expected": expected_fk,
                    "actual": actual_fks,
                }
            )

        attempt_indexes = _index_columns(connection, "llm_call_attempts")
        expected_unique = ["llm_call_id", "provider_attempt_no"]
        actual_unique = [
            columns for unique, columns in attempt_indexes.values() if unique
        ]
        if expected_unique not in actual_unique:
            errors.append(
                {
                    "kind": "unique_constraint",
                    "table": "llm_call_attempts",
                    "expected": expected_unique,
                    "actual": actual_unique,
                }
            )

    index_cache: dict[str, dict[str, tuple[bool, list[str]]]] = {}
    for name, (table_name, expected_columns) in C1B_INDEX_CONTRACTS.items():
        if table_name not in tables:
            continue
        if table_name not in index_cache:
            index_cache[table_name] = _index_columns(connection, table_name)
        indexes = index_cache[table_name]
        actual = indexes.get(name)
        actual_columns = None if actual is None else actual[1]
        if actual_columns != list(expected_columns):
            errors.append(
                {
                    "kind": "index",
                    "table": table_name,
                    "name": name,
                    "expected": list(expected_columns),
                    "actual": actual_columns,
                }
            )
    return errors


def _schema_profile(canonical_revision: str | None) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    if canonical_revision == C1B_REVISION:
        return C1B_REQUIRED_TABLES, C1B_REQUIRED_COLUMNS
    return LEGACY_REQUIRED_TABLES, LEGACY_REQUIRED_COLUMNS


def inspect_database(
    path: str | os.PathLike[str],
    expected_revision: str,
) -> dict[str, Any]:
    database_path = Path(path).expanduser().resolve()
    canonical_revision = REVISION_ALIASES.get(expected_revision)
    result: dict[str, Any] = {
        "path": str(database_path),
        "ready": False,
        "integrity": None,
        "revision": None,
        "expected_revision": expected_revision,
        "expected_revision_canonical": canonical_revision,
        "foreign_keys": None,
        "missing_tables": [],
        "missing_columns": {},
        "schema_errors": [],
    }
    if canonical_revision is None:
        result["error"] = f"unsupported_expected_revision={expected_revision}"
    required_tables, required_columns = _schema_profile(canonical_revision)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
        integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "unknown"
        result["integrity"] = integrity
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        if "alembic_version" in tables:
            revision_rows = connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchall()
            if len(revision_rows) == 1:
                result["revision"] = str(revision_rows[0][0])
            elif "error" not in result:
                result["error"] = f"alembic_version_row_count={len(revision_rows)}"

        missing_tables = sorted(set(required_tables) - tables)
        result["missing_tables"] = missing_tables
        missing_columns: dict[str, list[str]] = {}
        for table, table_required_columns in required_columns.items():
            if table not in tables:
                continue
            columns = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            missing = sorted(set(table_required_columns) - columns)
            if missing:
                missing_columns[table] = missing
        result["missing_columns"] = missing_columns
        schema_errors: list[dict[str, Any]] = []
        if canonical_revision == C1B_REVISION:
            schema_errors = _inspect_c1b_schema(connection, tables)
        result["schema_errors"] = schema_errors

        attempt_orphan_count: int | None = None
        if canonical_revision == C1B_REVISION and {
            "llm_calls",
            "llm_call_attempts",
        } <= tables:
            attempt_orphan_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM llm_call_attempts AS attempt
                    LEFT JOIN llm_calls AS call
                      ON call.llm_call_id = attempt.llm_call_id
                    WHERE call.llm_call_id IS NULL
                    """
                ).fetchone()[0]
            )
            result["llm_call_attempt_orphan_count"] = attempt_orphan_count
            if attempt_orphan_count and "error" not in result:
                result["error"] = f"llm_call_attempt_orphans={attempt_orphan_count}"

        foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
        foreign_keys = int(foreign_keys_row[0]) if foreign_keys_row else 0
        result["foreign_keys"] = foreign_keys
        result["ready"] = (
            integrity == "ok"
            and canonical_revision is not None
            and result["revision"] == canonical_revision
            and not missing_tables
            and not missing_columns
            and not schema_errors
            and attempt_orphan_count in {None, 0}
            and "error" not in result
        )
    except sqlite3.Error as exc:
        result["error"] = str(exc)
    finally:
        if connection is not None:
            connection.close()
    return result


def _write_json_atomic(path: str | os.PathLike[str], payload: str) -> None:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.parent / (
        f".{output_path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    )
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 SQLite 数据库是否已可供运行")
    parser.add_argument("path")
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    result = inspect_database(args.path, args.expected_revision)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        _write_json_atomic(args.output, payload)
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
