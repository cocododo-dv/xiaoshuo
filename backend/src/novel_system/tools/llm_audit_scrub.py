"""Dry-run or execute bounded, irreversible LLM audit-payload redaction.

This is the operational companion to Alembic revision 0073.  It deliberately
reports counts only: no prompt, manuscript, model output, or provider error
body is emitted to stdout/stderr.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection, URL

from novel_system.services.llm_audit import (
    AUDIT_SCHEMA_VERSION,
    audit_error_text,
    bounded_identifier,
    fingerprint_identifier,
    json_fingerprint,
    sanitize_audit_summary,
)
from novel_system.tools.db_backup import resolve_sqlite_path


DEFAULT_BATCH_SIZE = 500
MAX_BATCH_SIZE = 5_000
_TABLES = ("llm_calls", "llm_call_attempts", "operation_logs")


def _columns(bind: Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(table_name)}


def _new_stats(*, dry_run: bool, batch_size: int) -> dict[str, Any]:
    return {
        "schema": "llm-audit-scrub-v1",
        "mode": "dry_run" if dry_run else "execute",
        "batch_size": batch_size,
        "tables": {
            table: {"scanned": 0, "would_change": 0, "changed": 0}
            for table in _TABLES
        },
        "totals": {"scanned": 0, "would_change": 0, "changed": 0},
    }


def _finish_stats(stats: dict[str, Any]) -> dict[str, Any]:
    for field in ("scanned", "would_change", "changed"):
        stats["totals"][field] = sum(
            int(table_stats[field]) for table_stats in stats["tables"].values()
        )
    return stats


def _commit_batch(
    bind: Connection,
    *,
    commit_batches: bool,
    dry_run: bool,
) -> None:
    if commit_batches and not dry_run:
        bind.commit()


def _redacted_operation_payload(payload: Any) -> Any:
    if not isinstance(payload, dict) or "request_payload" not in payload:
        return payload
    if payload.get("_request_payload_audit_version") == AUDIT_SCHEMA_VERSION:
        return payload

    redacted = dict(payload)
    request_payload = redacted.pop("request_payload")
    redacted["_request_payload_audit_version"] = AUDIT_SCHEMA_VERSION
    redacted["request_payload_summary"] = json_fingerprint(request_payload)
    recovery_payload = {
        key: bounded_identifier(request_payload.get(key))
        for key in ("review_id", "job_id")
        if isinstance(request_payload, dict) and request_payload.get(key) is not None
    }
    confirmation = (
        request_payload.get("risk_confirmation")
        if isinstance(request_payload, dict)
        else None
    )
    if isinstance(confirmation, dict):
        reason = confirmation.get("reason")
        if isinstance(reason, str) and reason.strip():
            reason = reason.strip()
            recovery_payload["risk_confirmation"] = {
                "acknowledged": confirmation.get("acknowledged") is True,
                "reason": reason[:512],
                "reason_sha256": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
                "reason_chars": len(reason),
                "reason_truncated": len(reason) > 512,
                "severity": str(confirmation.get("severity") or "high")[:32],
            }
    if recovery_payload:
        redacted["request_payload"] = recovery_payload
    return redacted


def scrub_llm_audit_data(
    bind: Connection,
    *,
    dry_run: bool,
    commit_batches: bool = False,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Scan or redact legacy audit data and return content-free statistics.

    In dry-run mode this function issues no UPDATE and no COMMIT.  In execute
    mode, callers may opt into one transaction per scanned page with
    ``commit_batches=True``.  With it false, transaction ownership remains with
    the caller (as required by Alembic and ORM tests).
    """

    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    if dry_run and commit_batches:
        raise ValueError("dry_run cannot commit batches")

    stats = _new_stats(dry_run=dry_run, batch_size=batch_size)
    call_columns = _columns(bind, "llm_calls")
    required_calls = {
        "llm_call_id",
        "request_payload_summary",
        "response_payload_summary",
        "native_reasoning_json",
    }
    if required_calls.issubset(call_columns):
        calls = sa.table(
            "llm_calls",
            sa.column("llm_call_id", sa.String),
            sa.column("request_payload_summary", sa.JSON),
            sa.column("response_payload_summary", sa.JSON),
            sa.column("native_reasoning_json", sa.JSON),
        )
        last_id: str | None = None
        while True:
            query = (
                sa.select(
                    calls.c.llm_call_id,
                    calls.c.request_payload_summary,
                    calls.c.response_payload_summary,
                    calls.c.native_reasoning_json,
                )
                .order_by(calls.c.llm_call_id)
                .limit(batch_size)
            )
            if last_id is not None:
                query = query.where(calls.c.llm_call_id > last_id)
            rows = list(bind.execute(query).mappings())
            if not rows:
                break
            table_stats = stats["tables"]["llm_calls"]
            for row in rows:
                table_stats["scanned"] += 1
                values = {
                    "request_payload_summary": (
                        sanitize_audit_summary(row["request_payload_summary"])
                        if row["request_payload_summary"] is not None
                        else None
                    ),
                    "response_payload_summary": (
                        sanitize_audit_summary(row["response_payload_summary"])
                        if row["response_payload_summary"] is not None
                        else None
                    ),
                    "native_reasoning_json": (
                        sanitize_audit_summary(row["native_reasoning_json"])
                        if row["native_reasoning_json"] is not None
                        else None
                    ),
                }
                if any(values[key] != row[key] for key in values):
                    table_stats["would_change"] += 1
                    if not dry_run:
                        bind.execute(
                            sa.update(calls)
                            .where(calls.c.llm_call_id == row["llm_call_id"])
                            .values(**values)
                        )
                        table_stats["changed"] += 1
            last_id = str(rows[-1]["llm_call_id"])
            _commit_batch(bind, commit_batches=commit_batches, dry_run=dry_run)

    attempt_columns = _columns(bind, "llm_call_attempts")
    required_attempts = {
        "attempt_id",
        "provider_request_id",
        "error_code",
        "error_text",
    }
    if required_attempts.issubset(attempt_columns):
        attempts = sa.table(
            "llm_call_attempts",
            sa.column("attempt_id", sa.String),
            sa.column("provider_request_id", sa.String),
            sa.column("error_code", sa.String),
            sa.column("error_text", sa.Text),
        )
        last_id = None
        while True:
            query = (
                sa.select(
                    attempts.c.attempt_id,
                    attempts.c.provider_request_id,
                    attempts.c.error_code,
                    attempts.c.error_text,
                )
                .order_by(attempts.c.attempt_id)
                .limit(batch_size)
            )
            if last_id is not None:
                query = query.where(attempts.c.attempt_id > last_id)
            rows = list(bind.execute(query).mappings())
            if not rows:
                break
            table_stats = stats["tables"]["llm_call_attempts"]
            for row in rows:
                table_stats["scanned"] += 1
                values = {
                    "provider_request_id": fingerprint_identifier(
                        row["provider_request_id"]
                    ),
                    "error_text": audit_error_text(
                        row["error_text"],
                        error_code=row["error_code"],
                    ),
                }
                if any(values[key] != row[key] for key in values):
                    table_stats["would_change"] += 1
                    if not dry_run:
                        bind.execute(
                            sa.update(attempts)
                            .where(attempts.c.attempt_id == row["attempt_id"])
                            .values(**values)
                        )
                        table_stats["changed"] += 1
            last_id = str(rows[-1]["attempt_id"])
            _commit_batch(bind, commit_batches=commit_batches, dry_run=dry_run)

    operation_columns = _columns(bind, "operation_logs")
    if {"operation_id", "payload_json"}.issubset(operation_columns):
        operations = sa.table(
            "operation_logs",
            sa.column("operation_id", sa.Integer),
            sa.column("payload_json", sa.JSON),
        )
        last_operation_id = 0
        while True:
            rows = list(
                bind.execute(
                    sa.select(operations.c.operation_id, operations.c.payload_json)
                    .where(operations.c.operation_id > last_operation_id)
                    .order_by(operations.c.operation_id)
                    .limit(batch_size)
                ).mappings()
            )
            if not rows:
                break
            table_stats = stats["tables"]["operation_logs"]
            for row in rows:
                table_stats["scanned"] += 1
                payload = row["payload_json"]
                redacted = _redacted_operation_payload(payload)
                if redacted != payload:
                    table_stats["would_change"] += 1
                    if not dry_run:
                        bind.execute(
                            sa.update(operations)
                            .where(operations.c.operation_id == row["operation_id"])
                            .values(payload_json=redacted)
                        )
                        table_stats["changed"] += 1
            last_operation_id = int(rows[-1]["operation_id"])
            _commit_batch(bind, commit_batches=commit_batches, dry_run=dry_run)

    return _finish_stats(stats)


def scrub_database(
    database: Path,
    *,
    dry_run: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Run the scrubber against an existing SQLite file."""

    path = database.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    engine = sa.create_engine(URL.create("sqlite", database=str(path)), future=True)
    try:
        with engine.connect() as bind:
            stats = scrub_llm_audit_data(
                bind,
                dry_run=dry_run,
                commit_batches=not dry_run,
                batch_size=batch_size,
            )
            # Each page is committed in execute mode.  The final empty-page
            # SELECT starts one last transaction, so close it explicitly.
            if bind.in_transaction():
                if dry_run:
                    bind.rollback()
                else:
                    bind.commit()
    finally:
        engine.dispose()
    return {"database": str(path), **stats}


def _database_path(value: str) -> Path:
    return Path(resolve_sqlite_path(value))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="检查或不可逆脱敏历史 LLM 审计载荷（只输出统计）"
    )
    parser.add_argument("--database", required=True, type=_database_path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只统计，不写入或提交")
    mode.add_argument("--execute", action="store_true", help="分批提交不可逆脱敏")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args(argv)
    try:
        result = scrub_database(
            args.database,
            dry_run=bool(args.dry_run),
            batch_size=args.batch_size,
        )
    except (FileNotFoundError, OSError, ValueError, sa.exc.SQLAlchemyError) as exc:
        print(
            json.dumps(
                {
                    "schema": "llm-audit-scrub-error-v1",
                    "ok": False,
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
