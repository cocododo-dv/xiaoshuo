from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


REQUIRED_TABLES = (
    "evaluation_experiments",
    "evaluation_pairs",
    "evaluation_votes",
    "scene_run_states",
)

REQUIRED_COLUMNS = {
    "scene_run_states": (
        "latest_valid_draft_row_id",
        "run_policy",
        "scene_token_budget",
        "scene_tokens_used",
    ),
}


def inspect_database(
    path: str | os.PathLike[str],
    expected_revision: str,
) -> dict[str, Any]:
    database_path = Path(path).expanduser().resolve()
    result: dict[str, Any] = {
        "path": str(database_path),
        "ready": False,
        "integrity": None,
        "revision": None,
        "expected_revision": expected_revision,
        "foreign_keys": None,
        "missing_tables": [],
        "missing_columns": {},
    }
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
            else:
                result["error"] = f"alembic_version_row_count={len(revision_rows)}"

        missing_tables = sorted(set(REQUIRED_TABLES) - tables)
        result["missing_tables"] = missing_tables
        missing_columns: dict[str, list[str]] = {}
        for table, required_columns in REQUIRED_COLUMNS.items():
            if table not in tables:
                continue
            columns = {
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            }
            missing = sorted(set(required_columns) - columns)
            if missing:
                missing_columns[table] = missing
        result["missing_columns"] = missing_columns

        foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
        foreign_keys = int(foreign_keys_row[0]) if foreign_keys_row else 0
        result["foreign_keys"] = foreign_keys
        result["ready"] = (
            integrity == "ok"
            and result["revision"] == expected_revision
            and not missing_tables
            and not missing_columns
            and "error" not in result
        )
    except sqlite3.Error as exc:
        result["error"] = str(exc)
    finally:
        if connection is not None:
            connection.close()
    return result


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查 SQLite 数据库是否已可供运行")
    parser.add_argument("path")
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args(argv)

    result = inspect_database(args.path, args.expected_revision)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
