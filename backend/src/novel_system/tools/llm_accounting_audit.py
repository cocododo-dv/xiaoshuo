"""只读审计 LLM 父子账本的结构、scope、token 与恢复完整性。"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from novel_system.services.accounting_audit_schema import (
    ATTEMPT_TABLE,
    AUDIT_TABLES,
    BUDGET_TABLE,
    CALL_TABLE,
    REQUIRED_COLUMNS,
    REQUIRED_TABLES,
    TOKEN_COLUMNS,
)


REVISION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class LLMAccountingAuditError(RuntimeError):
    """可稳定序列化为 CLI JSON 的只读审计错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _open_read_only(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"{database.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _scalar(connection: sqlite3.Connection, sql: str) -> int:
    value = connection.execute(sql).fetchone()[0]
    return int(value or 0)


def _status_counts(
    connection: sqlite3.Connection,
    table: str,
    columns: set[str],
) -> dict[str, int]:
    if "accounting_status" not in columns:
        return {"<column_missing>": _scalar(connection, f'SELECT COUNT(*) FROM "{table}"')}
    return {
        str(row[0]) if row[0] is not None else "<null>": int(row[1])
        for row in connection.execute(
            f'SELECT accounting_status, COUNT(*) FROM "{table}" '
            "GROUP BY accounting_status ORDER BY accounting_status"
        )
    }


def _usage_counts(
    connection: sqlite3.Connection,
    table: str,
    columns: set[str],
) -> dict[str, int]:
    total = _scalar(connection, f'SELECT COUNT(*) FROM "{table}"')
    if "usage_is_estimate" not in columns:
        return {"actual": 0, "estimated": 0, "unknown": total}
    actual = _scalar(
        connection,
        f'SELECT COUNT(*) FROM "{table}" WHERE usage_is_estimate = 0',
    )
    estimated = _scalar(
        connection,
        f'SELECT COUNT(*) FROM "{table}" WHERE usage_is_estimate = 1',
    )
    return {"actual": actual, "estimated": estimated, "unknown": total - actual - estimated}


def _negative_rows(
    connection: sqlite3.Connection,
    table: str,
    columns: set[str],
) -> int:
    token_columns = [column for column in TOKEN_COLUMNS if column in columns]
    if not token_columns:
        return 0
    predicate = " OR ".join(f'"{column}" < 0' for column in token_columns)
    return _scalar(connection, f'SELECT COUNT(*) FROM "{table}" WHERE {predicate}')


def _stuck_reserved(
    connection: sqlite3.Connection,
    table: str,
    columns: set[str],
) -> int:
    if not {"accounting_status", "settled_at"}.issubset(columns):
        return 0
    return _scalar(
        connection,
        f'SELECT COUNT(*) FROM "{table}" '
        "WHERE accounting_status = 'reserved' AND settled_at IS NULL",
    )


def _validated_revision(connection: sqlite3.Connection) -> str:
    rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(rows) != 1:
        raise LLMAccountingAuditError(
            "AUDIT_REVISION_INVALID",
            "alembic_version 必须且只能包含一条 revision 记录",
        )
    revision = str(rows[0][0] or "")
    if REVISION_PATTERN.fullmatch(revision) is None:
        raise LLMAccountingAuditError(
            "AUDIT_REVISION_INVALID",
            f"非法 alembic revision: {revision!r}",
        )
    return revision


def audit_database(database: Path | str) -> dict[str, Any]:
    """以 SQLite read-only URI 打开数据库并返回稳定 JSON 审计结果。"""

    path = Path(database).resolve()
    connection: sqlite3.Connection | None = None
    try:
        connection = _open_read_only(path)
        tables = _tables(connection)
        missing_tables = sorted(REQUIRED_TABLES - tables)
        if missing_tables:
            raise LLMAccountingAuditError(
                "AUDIT_REQUIRED_TABLE_MISSING",
                "缺少审计必需表: " + ", ".join(missing_tables),
            )
        table_columns = {
            table: set(_columns(connection, table))
            for table in REQUIRED_COLUMNS
        }
        missing_required_columns = {
            table: sorted(set(REQUIRED_COLUMNS[table]) - table_columns[table])
            for table in REQUIRED_COLUMNS
            if set(REQUIRED_COLUMNS[table]) - table_columns[table]
        }
        if missing_required_columns:
            details = "; ".join(
                f"{table}: {', '.join(columns)}"
                for table, columns in sorted(missing_required_columns.items())
            )
            raise LLMAccountingAuditError(
                "AUDIT_REQUIRED_COLUMN_MISSING",
                "required accounting columns missing: " + details,
            )
        revision = _validated_revision(connection)
        table_report = {
            table: {
                "present": table in tables,
                "columns": sorted(table_columns[table]),
                "missing_required_columns": [],
            }
            for table in AUDIT_TABLES
        }
        counts = {
            table: _scalar(connection, f'SELECT COUNT(*) FROM "{table}"')
            for table in AUDIT_TABLES
        }

        call_columns = table_columns[CALL_TABLE]
        attempt_columns = table_columns[ATTEMPT_TABLE]
        scope_missing = (
            _scalar(
                connection,
                'SELECT COUNT(*) FROM "llm_calls" '
                "WHERE scope_type IS NULL OR trim(scope_type) = '' "
                "OR scope_id IS NULL OR trim(scope_id) = ''",
            )
            if CALL_TABLE in tables and {"scope_type", "scope_id"}.issubset(call_columns)
            else counts[CALL_TABLE]
        )
        attempt_orphans = (
            _scalar(
                connection,
                'SELECT COUNT(*) FROM "llm_call_attempts" a '
                'LEFT JOIN "llm_calls" c ON c.llm_call_id = a.llm_call_id '
                "WHERE c.llm_call_id IS NULL",
            )
            if {CALL_TABLE, ATTEMPT_TABLE}.issubset(tables)
            and "llm_call_id" in call_columns
            and "llm_call_id" in attempt_columns
            else counts[ATTEMPT_TABLE]
        )

        missing_status = (
            _scalar(connection, 'SELECT COUNT(*) FROM "llm_calls" WHERE accounting_status IS NULL')
            if CALL_TABLE in tables and "accounting_status" in call_columns
            else counts[CALL_TABLE]
        )
        missing_usage = (
            _scalar(connection, 'SELECT COUNT(*) FROM "llm_calls" WHERE usage_is_estimate IS NULL')
            if CALL_TABLE in tables and "usage_is_estimate" in call_columns
            else counts[CALL_TABLE]
        )
        calls_without_attempts = (
            _scalar(
                connection,
                'SELECT COUNT(*) FROM "llm_calls" c '
                'LEFT JOIN "llm_call_attempts" a ON a.llm_call_id = c.llm_call_id '
                "WHERE a.attempt_id IS NULL "
                "AND (c.accounting_status IS NULL OR c.usage_is_estimate IS NULL)",
            )
            if {CALL_TABLE, ATTEMPT_TABLE}.issubset(tables)
            and {"llm_call_id", "accounting_status", "usage_is_estimate"}.issubset(call_columns)
            and {"attempt_id", "llm_call_id"}.issubset(attempt_columns)
            else counts[CALL_TABLE]
        )
        legacy_unique = (
            _scalar(
                connection,
                'SELECT COUNT(*) FROM "llm_calls" c WHERE '
                "c.accounting_status IS NULL OR c.usage_is_estimate IS NULL "
                "OR c.scope_type IS NULL OR trim(c.scope_type) = '' "
                "OR c.scope_id IS NULL OR trim(c.scope_id) = ''",
            )
            if CALL_TABLE in tables
            and {"accounting_status", "usage_is_estimate", "scope_type", "scope_id"}.issubset(call_columns)
            else counts[CALL_TABLE]
        )

        return {
            "schema": "llm-accounting-audit-v1",
            "database": {
                "path": str(path),
                "read_only": True,
                "revision": revision,
            },
            "tables": table_report,
            "row_counts": counts,
            "integrity": {
                "scope_missing_or_blank": scope_missing,
                "negative_token_rows": {
                    table: (
                        _negative_rows(connection, table, table_columns[table])
                        if table in tables
                        else 0
                    )
                    for table in (CALL_TABLE, ATTEMPT_TABLE)
                },
                "stuck_reserved": {
                    table: (
                        _stuck_reserved(connection, table, table_columns[table])
                        if table in tables
                        else 0
                    )
                    for table in (CALL_TABLE, ATTEMPT_TABLE)
                },
                "attempt_orphans": attempt_orphans,
            },
            "status_counts": {
                table: (
                    _status_counts(connection, table, table_columns[table])
                    if table in tables
                    else {}
                )
                for table in (CALL_TABLE, ATTEMPT_TABLE)
            },
            "usage_provenance": {
                table: (
                    _usage_counts(connection, table, table_columns[table])
                    if table in tables
                    else {"actual": 0, "estimated": 0, "unknown": 0}
                )
                for table in (CALL_TABLE, ATTEMPT_TABLE)
            },
            "legacy_unreconstructable": {
                "calls_missing_accounting_status": missing_status,
                "calls_missing_usage_provenance": missing_usage,
                "calls_without_attempt_ledger": calls_without_attempts,
                "total_unique_calls": legacy_unique,
            },
        }
    except LLMAccountingAuditError:
        raise
    except sqlite3.Error as exc:
        raise LLMAccountingAuditError(
            "AUDIT_DATABASE_INVALID",
            f"无法只读审计 SQLite 数据库: {exc}",
        ) from exc
    finally:
        if connection is not None:
            connection.close()


def _emit_payload(payload: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)


def _error_payload(path: Path, error: LLMAccountingAuditError) -> dict[str, Any]:
    return {
        "schema": "llm-accounting-audit-error-v1",
        "ok": False,
        "database": {
            "path": str(path),
            "read_only": True,
        },
        "error": {
            "code": error.code,
            "message": str(error),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true", help="兼容证据命令；输出始终为 JSON")
    args = parser.parse_args(argv)
    database = args.database.resolve()
    output = args.output.resolve() if args.output is not None else None
    if output is not None and output == database:
        error = LLMAccountingAuditError(
            "AUDIT_OUTPUT_CONFLICT",
            "--output 解析后不得与 --database 指向同一路径",
        )
        _emit_payload(_error_payload(database, error), None)
        return 2
    try:
        payload = audit_database(database)
    except LLMAccountingAuditError as error:
        _emit_payload(_error_payload(database, error), output)
        return 2
    _emit_payload(payload, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
