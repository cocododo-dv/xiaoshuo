from __future__ import annotations

import argparse
import json
import os
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
