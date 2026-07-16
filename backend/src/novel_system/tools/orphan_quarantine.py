from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import stat
import sys
from collections.abc import Iterable
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EVIDENCE_SCHEMA_VERSION = 2
RECEIPT_VERSION = 2
TOOL_NAME = "novel_system.orphan_quarantine"
SUPPORTED_PRIMARY_KEYS = {
    "llm_call_attempts": "attempt_id",
    "snowflake_revision_links": "revision_link_id",
}
RELEVANT_TABLES = (
    "llm_calls",
    "llm_call_attempts",
    "story_projects",
    "snowflake_step_runs",
    "snowflake_scene_plans",
    "snowflake_revision_links",
)
AUTO_DELETE_REASONS = frozenset(
    {
        "missing_llm_call",
        "missing_story_project",
        "missing_source_step_run",
        "missing_affected_step_run",
        "missing_affected_scene_plan",
    }
)
MANUAL_REVIEW_REASONS = frozenset(
    {
        "unsupported_affected_kind",
        "empty_affected_id",
        "source_step_run_project_mismatch",
        "affected_step_run_project_mismatch",
        "affected_scene_plan_project_mismatch",
    }
)


class OrphanQuarantineError(RuntimeError):
    """Base error for a refused or invalid orphan quarantine operation."""


class EvidenceValidationError(OrphanQuarantineError):
    """The evidence bundle is malformed or no longer trustworthy."""


class EvidenceConflictError(OrphanQuarantineError):
    """The database no longer matches the exported row snapshots."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _database_path(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve()


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _open_immutable_snapshot(path: Path) -> sqlite3.Connection:
    """Open a fully materialized backup without creating WAL sidecars.

    This must only be used for backup snapshots produced by SQLite's backup
    API.  Active databases still use ``_open_read_only`` so committed WAL
    frames remain visible during evidence export and assessment.
    """

    connection = sqlite3.connect(
        f"{path.as_uri()}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


def _alembic_revision(connection: sqlite3.Connection, tables: set[str]) -> str | None:
    if "alembic_version" not in tables:
        return None
    rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    if len(rows) != 1:
        return None
    return str(rows[0][0])


def _schema_sha256(connection: sqlite3.Connection, tables: set[str]) -> str:
    del tables  # 保留调用签名；schema 指纹必须覆盖全部持久对象，而非仅扫描依赖。
    schema = [
        {
            "type": str(row[0]),
            "name": str(row[1]),
            "table": str(row[2]),
            "sql": None if row[3] is None else str(row[3]),
        }
        for row in connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'view', 'trigger')
            ORDER BY type, name, tbl_name
            """
        )
    ]
    return _sha256_json(schema)


def _assert_distinct_artifact_files(**paths: Path) -> None:
    normalized: dict[str, Path] = {
        name: _database_path(path) for name, path in paths.items()
    }
    names = sorted(normalized)
    for index, left_name in enumerate(names):
        left = normalized[left_name]
        for right_name in names[index + 1 :]:
            right = normalized[right_name]
            if os.path.normcase(str(left)) == os.path.normcase(str(right)):
                raise OrphanQuarantineError(
                    f"artifact_path_collision={left_name}:{right_name}"
                )
            if not left.exists() or not right.exists():
                continue
            try:
                same_file = os.path.samefile(left, right)
            except OSError as exc:
                raise OrphanQuarantineError(
                    f"artifact_identity_check_failed={left_name}:{right_name}"
                ) from exc
            if same_file:
                raise OrphanQuarantineError(
                    f"artifact_file_identity_collision={left_name}:{right_name}"
                )


def _record(
    *,
    table: str,
    primary_key_column: str,
    reasons: Iterable[str],
    row: dict[str, Any],
) -> dict[str, Any]:
    normalized_reasons = sorted(set(reasons))
    disposition = _disposition_for_reasons(normalized_reasons)
    return {
        "record_type": "orphan",
        "table": table,
        "primary_key_column": primary_key_column,
        "primary_key": str(row[primary_key_column]),
        "reasons": normalized_reasons,
        "disposition": disposition,
        "row": row,
        "row_sha256": _sha256_json(row),
    }


def _disposition_for_reasons(reasons: Iterable[str]) -> str:
    reason_set = {str(reason) for reason in reasons}
    if reason_set & MANUAL_REVIEW_REASONS:
        return "manual_review_required"
    if not reason_set or not reason_set <= AUTO_DELETE_REASONS:
        return "manual_review_required"
    return "auto_delete_eligible"


def _scan_llm_call_attempts(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT attempt.*
        FROM llm_call_attempts AS attempt
        LEFT JOIN llm_calls AS call
          ON call.llm_call_id = attempt.llm_call_id
        WHERE call.llm_call_id IS NULL
        ORDER BY attempt.attempt_id
        """
    ).fetchall()
    return [
        _record(
            table="llm_call_attempts",
            primary_key_column="attempt_id",
            reasons=("missing_llm_call",),
            row=dict(row),
        )
        for row in rows
    ]


def _scan_snowflake_revision_links(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            link.*,
            project.project_id IS NULL AS _missing_project,
            link.source_step_run_id IS NOT NULL
                AND source.step_run_id IS NULL AS _missing_source_step_run,
            source.step_run_id IS NOT NULL
                AND source.project_id <> link.project_id AS _source_project_mismatch,
            TRIM(COALESCE(link.affected_id, '')) = '' AS _empty_affected_id,
            COALESCE(link.affected_kind, '') NOT IN ('step_run', 'scene_plan')
                AS _unsupported_affected_kind,
            link.affected_kind = 'step_run'
                AND affected_step.step_run_id IS NULL AS _missing_affected_step_run,
            link.affected_kind = 'step_run'
                AND affected_step.step_run_id IS NOT NULL
                AND affected_step.project_id <> link.project_id
                AS _affected_step_project_mismatch,
            link.affected_kind = 'scene_plan'
                AND affected_scene.scene_plan_id IS NULL AS _missing_affected_scene_plan,
            link.affected_kind = 'scene_plan'
                AND affected_scene.scene_plan_id IS NOT NULL
                AND affected_scene.project_id <> link.project_id
                AS _affected_scene_project_mismatch
        FROM snowflake_revision_links AS link
        LEFT JOIN story_projects AS project
          ON project.project_id = link.project_id
        LEFT JOIN snowflake_step_runs AS source
          ON source.step_run_id = link.source_step_run_id
        LEFT JOIN snowflake_step_runs AS affected_step
          ON link.affected_kind = 'step_run'
         AND affected_step.step_run_id = link.affected_id
        LEFT JOIN snowflake_scene_plans AS affected_scene
          ON link.affected_kind = 'scene_plan'
         AND affected_scene.scene_plan_id = link.affected_id
        WHERE project.project_id IS NULL
           OR (link.source_step_run_id IS NOT NULL AND source.step_run_id IS NULL)
           OR (source.step_run_id IS NOT NULL AND source.project_id <> link.project_id)
           OR TRIM(COALESCE(link.affected_id, '')) = ''
           OR COALESCE(link.affected_kind, '') NOT IN ('step_run', 'scene_plan')
           OR (link.affected_kind = 'step_run' AND affected_step.step_run_id IS NULL)
           OR (
                link.affected_kind = 'step_run'
            AND affected_step.step_run_id IS NOT NULL
            AND affected_step.project_id <> link.project_id
           )
           OR (link.affected_kind = 'scene_plan' AND affected_scene.scene_plan_id IS NULL)
           OR (
                link.affected_kind = 'scene_plan'
            AND affected_scene.scene_plan_id IS NOT NULL
            AND affected_scene.project_id <> link.project_id
           )
        ORDER BY link.revision_link_id
        """
    ).fetchall()
    flag_reasons = (
        ("_missing_project", "missing_story_project"),
        ("_missing_source_step_run", "missing_source_step_run"),
        ("_source_project_mismatch", "source_step_run_project_mismatch"),
        ("_empty_affected_id", "empty_affected_id"),
        ("_unsupported_affected_kind", "unsupported_affected_kind"),
        ("_missing_affected_step_run", "missing_affected_step_run"),
        ("_affected_step_project_mismatch", "affected_step_run_project_mismatch"),
        ("_missing_affected_scene_plan", "missing_affected_scene_plan"),
        ("_affected_scene_project_mismatch", "affected_scene_plan_project_mismatch"),
    )
    records: list[dict[str, Any]] = []
    for result_row in rows:
        row = dict(result_row)
        reasons = [reason for flag, reason in flag_reasons if bool(row.pop(flag))]
        records.append(
            _record(
                table="snowflake_revision_links",
                primary_key_column="revision_link_id",
                reasons=reasons,
                row=row,
            )
        )
    return records


def _summarize_records(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    counts_by_table = {table: 0 for table in SUPPORTED_PRIMARY_KEYS}
    counts_by_reason: dict[str, int] = {}
    counts_by_disposition = {
        "auto_delete_eligible": 0,
        "manual_review_required": 0,
    }
    record_count = 0
    for record in records:
        record_count += 1
        table = str(record["table"])
        counts_by_table[table] = counts_by_table.get(table, 0) + 1
        disposition = str(record["disposition"])
        counts_by_disposition[disposition] = (
            counts_by_disposition.get(disposition, 0) + 1
        )
        for reason in record["reasons"]:
            counts_by_reason[str(reason)] = counts_by_reason.get(str(reason), 0) + 1
    return {
        "record_count": record_count,
        "counts_by_table": counts_by_table,
        "counts_by_reason": dict(sorted(counts_by_reason.items())),
        "counts_by_disposition": counts_by_disposition,
        "auto_delete_count": counts_by_disposition["auto_delete_eligible"],
        "manual_review_count": counts_by_disposition["manual_review_required"],
    }


def scan_orphans(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return active orphan snapshots without changing the connection or database."""

    previous_row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        tables = _table_names(connection)
        dependencies = {
            "llm_call_attempts": {"llm_calls", "llm_call_attempts"},
            "snowflake_revision_links": {
                "story_projects",
                "snowflake_step_runs",
                "snowflake_scene_plans",
                "snowflake_revision_links",
            },
        }
        missing_dependencies = {
            table: sorted(required - tables)
            for table, required in dependencies.items()
            if not required <= tables
        }
        records: list[dict[str, Any]] = []
        if "llm_call_attempts" not in missing_dependencies:
            records.extend(_scan_llm_call_attempts(connection))
        if "snowflake_revision_links" not in missing_dependencies:
            records.extend(_scan_snowflake_revision_links(connection))
        records.sort(key=lambda item: (str(item["table"]), str(item["primary_key"])))
        return {
            **_summarize_records(records),
            "records": records,
            "missing_dependencies": missing_dependencies,
            "complete": not missing_dependencies,
            "schema_sha256": _schema_sha256(connection, tables),
            "alembic_revision": _alembic_revision(connection, tables),
        }
    finally:
        connection.row_factory = previous_row_factory


def _require_complete_scan(scan: dict[str, Any]) -> None:
    missing = scan.get("missing_dependencies") or {}
    if not missing:
        return
    details = ";".join(
        f"{relation}:{','.join(columns)}"
        for relation, columns in sorted(missing.items())
    )
    raise OrphanQuarantineError(f"orphan_scan_incomplete={details}")


def inspect_orphans(
    path: str | os.PathLike[str],
    *,
    include_all_keys: bool = False,
) -> dict[str, Any]:
    database_path = _database_path(path)
    with closing(_open_read_only(database_path)) as connection:
        scan = scan_orphans(connection)
    orphan_keys = [
        {
            "table": record["table"],
            "primary_key": record["primary_key"],
            "reasons": record["reasons"],
            "disposition": record["disposition"],
        }
        for record in scan["records"]
    ]
    if scan["missing_dependencies"]:
        status = "incomplete"
    elif scan["manual_review_count"]:
        status = "manual_review_required"
    elif scan["record_count"]:
        status = "orphans_detected"
    else:
        status = "clean"
    result = {
        "mode": "dry_run",
        "status": status,
        "database_path": str(database_path),
        "would_delete": 0,
        **{key: value for key, value in scan.items() if key != "records"},
        "orphan_key_sample": orphan_keys[:20],
        "orphan_keys_truncated": len(orphan_keys) > 20,
    }
    if include_all_keys:
        result["orphan_keys"] = orphan_keys
    return result


def _jsonl_bytes(header: dict[str, Any], records: list[dict[str, Any]]) -> bytes:
    records_payload = b"".join(
        (_canonical_json(record) + "\n").encode("utf-8") for record in records
    )
    summary = {
        "record_type": "summary",
        **_summarize_records(records),
        "records_sha256": _sha256_bytes(records_payload),
    }
    lines = [header, *records, summary]
    return b"".join((_canonical_json(line) + "\n").encode("utf-8") for line in lines)


def _temporary_path(target: Path) -> Path:
    return target.parent / f".{target.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"


def _file_identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    return int(info.st_dev), int(info.st_ino)


def _remove_owned_publish_target(
    target: Path,
    expected_identity: tuple[int, int],
) -> None:
    try:
        if not target.exists() or _file_identity(target) != expected_identity:
            return
        os.chmod(
            target,
            stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH,
        )
        target.unlink()
    except OSError:
        # 原始发布失败仍应向上传播；无法证明/移除目标时保持 fail-closed。
        return


def _link_new_file_no_clobber(temporary: Path, target: Path) -> None:
    """Publish a same-filesystem temporary without ever replacing target."""

    source_identity = _file_identity(temporary)
    linked = False
    try:
        os.link(temporary, target)
        linked = True
        _flush_published_path(target)
    except FileExistsError as exc:
        raise OrphanQuarantineError(f"refusing_to_overwrite={target}") from exc
    except OSError as exc:
        if linked:
            _remove_owned_publish_target(target, source_identity)
        raise OrphanQuarantineError(
            f"atomic_no_clobber_publish_failed={target}"
        ) from exc


def _flush_published_path(target: Path) -> None:
    # Windows CRT 对只读 fd 的 fsync 会报 EBADF；制品均由本工具创建，
    # 使用不改内容的 r+b 句柄执行 FlushFileBuffers 等价刷新。
    with target.open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())
    if os.name == "nt":
        # Windows 的 os.open 不支持目录句柄 fsync；文件 flush 后依赖下方
        # backup/prepared/post-state 逻辑对账处理极端目录项回退。
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(target.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _artifact_lock_path(receipt_path: Path) -> Path:
    return receipt_path.parent / f".{receipt_path.name}.operation.lock"


@contextmanager
def _artifact_lock(receipt_path: Path):
    """Cross-process operation lock; the OS releases it automatically on crash."""

    lock_path = _artifact_lock_path(receipt_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise OrphanQuarantineError(
                    f"artifact_operation_lock_busy={lock_path}"
                ) from exc
            try:
                yield lock_path
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - Windows 是当前发布环境，保留 POSIX 等价语义
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise OrphanQuarantineError(
                    f"artifact_operation_lock_busy={lock_path}"
                ) from exc
            try:
                yield lock_path
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _write_new_bytes_atomic(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise OrphanQuarantineError(f"refusing_to_overwrite={target}")
    temporary = _temporary_path(target)
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _link_new_file_no_clobber(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_bytes_atomic(target: Path, payload: bytes) -> None:
    temporary = _temporary_path(target)
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _flush_published_path(target)
    finally:
        temporary.unlink(missing_ok=True)


def export_evidence(
    path: str | os.PathLike[str],
    evidence_path: str | os.PathLike[str],
) -> dict[str, Any]:
    database_path = _database_path(path)
    output_path = _database_path(evidence_path)
    with closing(_open_read_only(database_path)) as connection:
        scan = scan_orphans(connection)
        foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
    _require_complete_scan(scan)
    if not scan["alembic_revision"]:
        raise OrphanQuarantineError("source_alembic_revision_unavailable")
    header = {
        "record_type": "manifest",
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "generated_at": _utcnow(),
        "source_database_path": str(database_path),
        "source_alembic_revision": scan["alembic_revision"],
        "source_schema_sha256": scan["schema_sha256"],
        "source_foreign_keys_enabled": (
            int(foreign_keys_row[0]) if foreign_keys_row else 0
        ),
        "disposition": "file_quarantine_then_delete_matching_active_children",
        "parent_fabrication_allowed": False,
    }
    payload = _jsonl_bytes(header, scan["records"])
    _write_new_bytes_atomic(output_path, payload)
    return {
        "mode": "dry_run",
        "status": "evidence_exported",
        "database_path": str(database_path),
        "evidence_path": str(output_path),
        "evidence_sha256": _sha256_bytes(payload),
        "would_delete": scan["auto_delete_count"],
        **{key: value for key, value in scan.items() if key != "records"},
    }


def load_evidence(evidence_path: str | os.PathLike[str]) -> dict[str, Any]:
    path = _database_path(evidence_path)
    payload = path.read_bytes()
    try:
        lines = [json.loads(line) for line in payload.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("evidence_not_valid_utf8_jsonl") from exc
    if len(lines) < 2:
        raise EvidenceValidationError("evidence_requires_manifest_and_summary")
    header = lines[0]
    summary = lines[-1]
    records = lines[1:-1]
    if header.get("record_type") != "manifest":
        raise EvidenceValidationError("evidence_manifest_missing")
    if header.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise EvidenceValidationError("unsupported_evidence_schema_version")
    if header.get("tool") != TOOL_NAME:
        raise EvidenceValidationError("unexpected_evidence_tool")
    source_revision = header.get("source_alembic_revision")
    if not isinstance(source_revision, str) or not source_revision.strip():
        raise EvidenceValidationError("evidence_source_alembic_revision_missing")
    if header.get("parent_fabrication_allowed") is not False:
        raise EvidenceValidationError("evidence_parent_fabrication_policy_invalid")
    if summary.get("record_type") != "summary":
        raise EvidenceValidationError("evidence_summary_missing")

    seen: set[tuple[str, str]] = set()
    for record in records:
        if record.get("record_type") != "orphan":
            raise EvidenceValidationError("unexpected_evidence_record_type")
        table = str(record.get("table") or "")
        primary_key_column = str(record.get("primary_key_column") or "")
        primary_key = str(record.get("primary_key") or "")
        if SUPPORTED_PRIMARY_KEYS.get(table) != primary_key_column:
            raise EvidenceValidationError("unsupported_evidence_table_or_primary_key")
        if not primary_key or (table, primary_key) in seen:
            raise EvidenceValidationError("duplicate_or_empty_evidence_primary_key")
        seen.add((table, primary_key))
        row = record.get("row")
        if not isinstance(row, dict) or str(row.get(primary_key_column)) != primary_key:
            raise EvidenceValidationError("evidence_row_primary_key_mismatch")
        if record.get("row_sha256") != _sha256_json(row):
            raise EvidenceValidationError("evidence_row_hash_mismatch")
        reasons = record.get("reasons")
        if not isinstance(reasons, list) or not reasons:
            raise EvidenceValidationError("evidence_orphan_reasons_missing")
        expected_disposition = _disposition_for_reasons(reasons)
        if record.get("disposition") != expected_disposition:
            raise EvidenceValidationError("evidence_disposition_mismatch")

    records_payload = b"".join(
        (_canonical_json(record) + "\n").encode("utf-8") for record in records
    )
    expected_summary = {
        "record_type": "summary",
        **_summarize_records(records),
        "records_sha256": _sha256_bytes(records_payload),
    }
    if summary != expected_summary:
        raise EvidenceValidationError("evidence_summary_mismatch")
    return {
        "path": str(path),
        "evidence_sha256": _sha256_bytes(payload),
        "header": header,
        "records": records,
        "summary": summary,
    }


def _fetch_row(
    connection: sqlite3.Connection,
    *,
    table: str,
    primary_key_column: str,
    primary_key: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        f'SELECT * FROM "{table}" WHERE "{primary_key_column}" = ?',
        (primary_key,),
    ).fetchone()
    return dict(row) if row is not None else None


def _evidence_marker(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "table": str(record["table"]),
        "primary_key": str(record["primary_key"]),
        "row_sha256": str(record["row_sha256"]),
        "reasons": list(record["reasons"]),
        "disposition": str(record["disposition"]),
    }


def assess_evidence(
    connection: sqlite3.Connection,
    evidence: dict[str, Any],
    *,
    database_path: str | os.PathLike[str],
) -> dict[str, Any]:
    previous_row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        resolved_path = _database_path(database_path)
        scan = scan_orphans(connection)
        path_matches = str(resolved_path) == str(
            evidence["header"].get("source_database_path")
        )
        schema_matches = scan["schema_sha256"] == str(
            evidence["header"].get("source_schema_sha256") or ""
        )
        source_alembic_revision = str(
            evidence["header"].get("source_alembic_revision") or ""
        )
        current_alembic_revision = scan["alembic_revision"]
        alembic_revision_matches = (
            current_alembic_revision is not None
            and current_alembic_revision == source_alembic_revision
        )
        common = {
            "evidence_path": evidence["path"],
            "evidence_sha256": evidence["evidence_sha256"],
            "database_path_matches": path_matches,
            "schema_matches": schema_matches,
            "source_alembic_revision": source_alembic_revision,
            "current_alembic_revision": current_alembic_revision,
            "alembic_revision_matches": alembic_revision_matches,
            "captured_count": len(evidence["records"]),
            "active_record_count": scan["record_count"],
            "active_counts_by_table": scan["counts_by_table"],
            "active_counts_by_reason": scan["counts_by_reason"],
            "active_counts_by_disposition": scan["counts_by_disposition"],
            "active_manual_review_count": scan["manual_review_count"],
            "scan_complete": scan["complete"],
            "missing_dependencies": scan["missing_dependencies"],
        }
        if not scan["complete"]:
            return {
                "status": "incomplete",
                **common,
                "pending": [],
                "manual_review_required": [],
                "already_absent": [],
                "resolved_by_parent": [],
                "changed": [],
                "uncovered_active_orphans": [],
            }

        current = {
            (str(record["table"]), str(record["primary_key"])): record
            for record in scan["records"]
        }
        evidence_keys: set[tuple[str, str]] = set()
        pending: list[dict[str, Any]] = []
        manual_review_required: list[dict[str, Any]] = []
        already_absent: list[dict[str, Any]] = []
        resolved_by_parent: list[dict[str, Any]] = []
        changed: list[dict[str, Any]] = []
        for record in evidence["records"]:
            table = str(record["table"])
            primary_key_column = str(record["primary_key_column"])
            primary_key = str(record["primary_key"])
            key = (table, primary_key)
            evidence_keys.add(key)
            marker = _evidence_marker(record)
            actual = _fetch_row(
                connection,
                table=table,
                primary_key_column=primary_key_column,
                primary_key=primary_key,
            )
            if actual is None:
                already_absent.append(marker)
            elif (
                _sha256_json(actual) != record["row_sha256"] or actual != record["row"]
            ):
                changed.append(marker)
            elif key in current:
                current_record = current[key]
                if (
                    current_record["reasons"] != record["reasons"]
                    or current_record["disposition"] != record["disposition"]
                ):
                    changed.append(
                        {**marker, "conflict": "orphan_classification_mismatch"}
                    )
                elif record["disposition"] == "manual_review_required":
                    manual_review_required.append(marker)
                else:
                    pending.append(marker)
            else:
                resolved_by_parent.append(marker)

        uncovered = [
            {"table": table, "primary_key": primary_key}
            for table, primary_key in sorted(set(current) - evidence_keys)
        ]
        if not path_matches:
            status = "database_path_mismatch"
        elif not schema_matches or not alembic_revision_matches or changed:
            status = "evidence_mismatch"
        elif manual_review_required:
            status = "manual_review_required"
        elif pending and uncovered:
            status = "partially_exported"
        elif pending:
            status = "exported_pending_apply"
        elif uncovered:
            status = "new_unexported_orphans"
        else:
            status = "remediated_with_verified_export"
        return {
            "status": status,
            **common,
            "pending": pending,
            "manual_review_required": manual_review_required,
            "already_absent": already_absent,
            "resolved_by_parent": resolved_by_parent,
            "changed": changed,
            "uncovered_active_orphans": uncovered,
        }
    finally:
        connection.row_factory = previous_row_factory


def assess_evidence_file(
    database_path: str | os.PathLike[str],
    evidence_path: str | os.PathLike[str],
) -> dict[str, Any]:
    resolved_database_path = _database_path(database_path)
    evidence = load_evidence(evidence_path)
    with closing(_open_read_only(resolved_database_path)) as connection:
        return assess_evidence(
            connection,
            evidence,
            database_path=resolved_database_path,
        )


def _foreign_key_check(
    connection: sqlite3.Connection,
    *,
    sample_limit: int = 20,
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    counts_by_child_table: dict[str, int] = {}
    for row in connection.execute("PRAGMA foreign_key_check"):
        violation = {
            "child_table": str(row[0]),
            "rowid": row[1],
            "parent_table": str(row[2]),
            "foreign_key_index": int(row[3]),
        }
        violations.append(violation)
        child_table = violation["child_table"]
        counts_by_child_table[child_table] = (
            counts_by_child_table.get(child_table, 0) + 1
        )
    return {
        "count": len(violations),
        "counts_by_child_table": dict(sorted(counts_by_child_table.items())),
        "samples": violations[:sample_limit],
        "samples_truncated": len(violations) > sample_limit,
        "violations_sha256": _sha256_json(violations),
    }


def _integrity_snapshot(
    connection: sqlite3.Connection,
    *,
    expected_deletes: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    scan = scan_orphans(connection)
    tables = _table_names(connection)
    active_records = [
        {
            "table": record["table"],
            "primary_key": record["primary_key"],
            "row_sha256": record["row_sha256"],
            "reasons": record["reasons"],
            "disposition": record["disposition"],
        }
        for record in scan["records"]
    ]
    expected_delete_state: list[dict[str, Any]] = []
    for marker in expected_deletes:
        table = str(marker["table"])
        primary_key = str(marker["primary_key"])
        primary_key_column = SUPPORTED_PRIMARY_KEYS.get(table)
        if table not in tables or primary_key_column is None:
            state = "table_missing"
            row_sha256 = None
        else:
            row = _fetch_row(
                connection,
                table=table,
                primary_key_column=primary_key_column,
                primary_key=primary_key,
            )
            state = "absent" if row is None else "present"
            row_sha256 = None if row is None else _sha256_json(row)
        expected_delete_state.append(
            {
                "table": table,
                "primary_key": primary_key,
                "state": state,
                "row_sha256": row_sha256,
            }
        )
    snapshot = {
        "alembic_revision": scan["alembic_revision"],
        "schema_sha256": scan["schema_sha256"],
        "scan_complete": scan["complete"],
        "missing_dependencies": scan["missing_dependencies"],
        "orphan_record_count": scan["record_count"],
        "counts_by_table": scan["counts_by_table"],
        "counts_by_reason": scan["counts_by_reason"],
        "counts_by_disposition": scan["counts_by_disposition"],
        "manual_review_count": scan["manual_review_count"],
        "active_records": active_records,
        "expected_delete_state": expected_delete_state,
        "foreign_key_check": _foreign_key_check(connection),
    }
    return {**snapshot, "fingerprint_sha256": _sha256_json(snapshot)}


def _has_remaining_issues(snapshot: dict[str, Any]) -> bool:
    return bool(
        not snapshot["scan_complete"]
        or snapshot["orphan_record_count"]
        or snapshot["manual_review_count"]
        or snapshot["foreign_key_check"]["count"]
        or any(
            item["state"] != "absent"
            for item in snapshot["expected_delete_state"]
        )
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes_sha256": _sha256_bytes(value), "length": len(value)}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _database_aggregate_sha256(
    connection: sqlite3.Connection,
    *,
    excluded_primary_keys: Iterable[dict[str, Any]] = (),
) -> str:
    excluded_by_table: dict[str, set[str]] = {}
    for marker in excluded_primary_keys:
        table = str(marker["table"])
        primary_key = str(marker["primary_key"])
        if table not in SUPPORTED_PRIMARY_KEYS:
            raise EvidenceValidationError(
                f"aggregate_exclusion_table_not_supported={table}"
            )
        excluded_by_table.setdefault(table, set()).add(primary_key)
    previous_row_factory = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        table_payloads: list[dict[str, Any]] = []
        tables = _table_names(connection)
        for table in sorted(tables):
            quoted_table = table.replace('"', '""')
            columns = [
                str(row[1])
                for row in connection.execute(
                    f'PRAGMA table_info("{quoted_table}")'
                )
            ]
            row_hashes: list[str] = []
            excluded = excluded_by_table.get(table, set())
            primary_key_column = SUPPORTED_PRIMARY_KEYS.get(table)
            for row in connection.execute(f'SELECT * FROM "{quoted_table}"'):
                row_dict = dict(row)
                if (
                    excluded
                    and primary_key_column is not None
                    and str(row_dict[primary_key_column]) in excluded
                ):
                    continue
                row_hashes.append(_sha256_json(_json_safe(row_dict)))
            row_hashes.sort()
            table_payloads.append(
                {
                    "table": table,
                    "columns": columns,
                    "row_count": len(row_hashes),
                    "row_hashes_sha256": _sha256_json(row_hashes),
                }
            )
        schema_sha256 = _schema_sha256(connection, tables)
        persistent_pragmas = {
            "application_id": int(
                connection.execute("PRAGMA application_id").fetchone()[0]
            ),
            "user_version": int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            ),
            "auto_vacuum": int(
                connection.execute("PRAGMA auto_vacuum").fetchone()[0]
            ),
            "encoding": str(connection.execute("PRAGMA encoding").fetchone()[0]),
        }
        return _sha256_json(
            {
                "schema_sha256": schema_sha256,
                "persistent_pragmas": persistent_pragmas,
                "tables": table_payloads,
            }
        )
    finally:
        connection.row_factory = previous_row_factory


def _prepare_backup_database(
    connection: sqlite3.Connection,
    target: Path,
) -> tuple[Path, dict[str, Any]]:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise OrphanQuarantineError(f"refusing_to_overwrite={target}")
    temporary = _temporary_path(target)
    try:
        with closing(sqlite3.connect(temporary)) as destination:
            connection.backup(destination)
            destination.commit()
        with temporary.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
        with closing(_open_immutable_snapshot(temporary)) as backup:
            integrity_row = backup.execute("PRAGMA integrity_check").fetchone()
            quick_check_row = backup.execute("PRAGMA quick_check").fetchone()
            integrity = str(integrity_row[0]) if integrity_row else "unknown"
            quick_check = str(quick_check_row[0]) if quick_check_row else "unknown"
            if integrity != "ok" or quick_check != "ok":
                raise OrphanQuarantineError(
                    f"backup_integrity_failed=integrity:{integrity},quick:{quick_check}"
                )
            backup_tables = _table_names(backup)
            foreign_key_violation_count = sum(
                1 for _ in backup.execute("PRAGMA foreign_key_check")
            )
            backup_scan = scan_orphans(backup)
            verification = {
                "integrity_check": integrity,
                "quick_check": quick_check,
                "file_size_bytes": temporary.stat().st_size,
                "page_count": int(backup.execute("PRAGMA page_count").fetchone()[0]),
                "page_size": int(backup.execute("PRAGMA page_size").fetchone()[0]),
                "freelist_count": int(
                    backup.execute("PRAGMA freelist_count").fetchone()[0]
                ),
                "application_id": int(
                    backup.execute("PRAGMA application_id").fetchone()[0]
                ),
                "user_version": int(
                    backup.execute("PRAGMA user_version").fetchone()[0]
                ),
                "alembic_revision": _alembic_revision(backup, backup_tables),
                "schema_sha256": _schema_sha256(backup, backup_tables),
                "foreign_key_violation_count": foreign_key_violation_count,
                "orphan_record_count": backup_scan["record_count"],
                "orphan_counts_by_table": backup_scan["counts_by_table"],
                "orphan_counts_by_disposition": backup_scan[
                    "counts_by_disposition"
                ],
                "manual_review_count": backup_scan["manual_review_count"],
                "scan_complete": backup_scan["complete"],
                "missing_dependencies": backup_scan["missing_dependencies"],
                "database_aggregate_sha256": _database_aggregate_sha256(backup),
                "sha256": _sha256_file(temporary),
            }
        return temporary, verification
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _publish_prepared_backup(temporary: Path, target: Path) -> None:
    source_identity = _file_identity(temporary)
    _link_new_file_no_clobber(temporary, target)
    try:
        temporary.unlink()
        os.chmod(target, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        _remove_owned_publish_target(target, source_identity)
        if temporary.exists() and _file_identity(temporary) == source_identity:
            os.chmod(
                temporary,
                stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH,
            )
        raise


def _require_backup_read_only(backup_path: Path) -> None:
    writable_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    if backup_path.stat().st_mode & writable_bits:
        raise EvidenceConflictError("receipt_backup_not_read_only")


def _receipt_bytes(receipt: dict[str, Any]) -> bytes:
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    signed = {**unsigned, "receipt_sha256": _sha256_json(unsigned)}
    return (json.dumps(signed, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def load_receipt(receipt_path: str | os.PathLike[str]) -> dict[str, Any]:
    path = _database_path(receipt_path)
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("receipt_not_valid_utf8_json") from exc
    if not isinstance(receipt, dict):
        raise EvidenceValidationError("receipt_must_be_object")
    if receipt.get("tool") != TOOL_NAME:
        raise EvidenceValidationError("unexpected_receipt_tool")
    if receipt.get("receipt_version") != RECEIPT_VERSION:
        raise EvidenceValidationError("unsupported_receipt_version")
    actual_hash = str(receipt.get("receipt_sha256") or "")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    expected_hash = _sha256_json(unsigned)
    if not actual_hash or not secrets.compare_digest(actual_hash, expected_hash):
        raise EvidenceValidationError("receipt_sha256_mismatch")
    return {**receipt, "path": str(path)}


def _unsigned_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    unsigned.pop("path", None)
    return unsigned


def _sorted_markers(markers: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (dict(marker) for marker in markers),
        key=lambda marker: (str(marker["table"]), str(marker["primary_key"])),
    )


def _operation_binding_payload(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": receipt.get("tool"),
        "receipt_version": receipt.get("receipt_version"),
        "database_path": receipt.get("database_path"),
        "evidence_path": receipt.get("evidence_path"),
        "evidence_sha256": receipt.get("evidence_sha256"),
        "backup_path": receipt.get("backup_path"),
        "backup_sha256": receipt.get("backup_sha256"),
        "receipt_path": receipt.get("receipt_path"),
        "source_alembic_revision": receipt.get("source_alembic_revision"),
        "source_schema_sha256": receipt.get("source_schema_sha256"),
        "expected_deletes_sha256": receipt.get("expected_deletes_sha256"),
        "post_database_aggregate_sha256": receipt.get(
            "post_database_aggregate_sha256"
        ),
    }


def _verify_existing_backup(
    backup_path: Path,
    receipt: dict[str, Any],
    *,
    require_read_only: bool = True,
) -> dict[str, Any]:
    if not backup_path.exists():
        raise EvidenceConflictError("receipt_backup_missing")
    if require_read_only:
        _require_backup_read_only(backup_path)
    actual_sha256 = _sha256_file(backup_path)
    if not secrets.compare_digest(actual_sha256, str(receipt["backup_sha256"])):
        raise EvidenceConflictError("receipt_backup_sha256_mismatch")
    with closing(_open_immutable_snapshot(backup_path)) as backup:
        integrity_row = backup.execute("PRAGMA integrity_check").fetchone()
        quick_row = backup.execute("PRAGMA quick_check").fetchone()
        integrity = str(integrity_row[0]) if integrity_row else "unknown"
        quick_check = str(quick_row[0]) if quick_row else "unknown"
        tables = _table_names(backup)
        revision = _alembic_revision(backup, tables)
        schema_sha256 = _schema_sha256(backup, tables)
        aggregate_sha256 = _database_aggregate_sha256(backup)
    if integrity != "ok" or quick_check != "ok":
        raise EvidenceConflictError("receipt_backup_integrity_failed")
    if revision != receipt["source_alembic_revision"]:
        raise EvidenceConflictError("receipt_backup_revision_mismatch")
    if schema_sha256 != receipt["source_schema_sha256"]:
        raise EvidenceConflictError("receipt_backup_schema_mismatch")
    recorded_verification = receipt.get("backup_verification") or {}
    if recorded_verification.get("sha256") != actual_sha256:
        raise EvidenceConflictError("receipt_backup_verification_hash_mismatch")
    if (
        recorded_verification.get("database_aggregate_sha256")
        != aggregate_sha256
    ):
        raise EvidenceConflictError("receipt_backup_aggregate_mismatch")
    return {
        "sha256": actual_sha256,
        "integrity_check": integrity,
        "quick_check": quick_check,
        "alembic_revision": revision,
        "schema_sha256": schema_sha256,
        "database_aggregate_sha256": aggregate_sha256,
    }


def _validate_receipt_binding(
    receipt: dict[str, Any],
    *,
    database_path: Path,
    evidence: dict[str, Any],
    backup_path: Path,
    receipt_path: Path,
) -> None:
    _assert_distinct_artifact_files(
        database=database_path,
        evidence=_database_path(evidence["path"]),
        backup=backup_path,
        receipt=receipt_path,
    )
    expected_paths = {
        "database_path": str(database_path),
        "evidence_path": evidence["path"],
        "backup_path": str(backup_path),
        "receipt_path": str(receipt_path),
    }
    for key, expected in expected_paths.items():
        if str(receipt.get(key) or "") != expected:
            raise EvidenceConflictError(f"receipt_{key}_mismatch")
    if receipt.get("evidence_sha256") != evidence["evidence_sha256"]:
        raise EvidenceConflictError("receipt_evidence_sha256_mismatch")
    if (
        receipt.get("source_alembic_revision")
        != evidence["header"]["source_alembic_revision"]
    ):
        raise EvidenceConflictError("receipt_source_revision_mismatch")
    if (
        receipt.get("source_schema_sha256")
        != evidence["header"]["source_schema_sha256"]
    ):
        raise EvidenceConflictError("receipt_source_schema_mismatch")
    if receipt.get("status") not in {"prepared", "commit_ready", "completed"}:
        raise EvidenceValidationError("unexpected_receipt_status")

    expected_deletes = receipt.get("expected_deletes")
    if not isinstance(expected_deletes, list):
        raise EvidenceValidationError("receipt_expected_deletes_missing")
    seen: set[tuple[str, str]] = set()
    for marker in expected_deletes:
        if not isinstance(marker, dict):
            raise EvidenceValidationError("receipt_expected_delete_invalid")
        table = str(marker.get("table") or "")
        primary_key = str(marker.get("primary_key") or "")
        if (
            SUPPORTED_PRIMARY_KEYS.get(table) is None
            or not primary_key
            or (table, primary_key) in seen
            or marker.get("disposition") != "auto_delete_eligible"
        ):
            raise EvidenceValidationError("receipt_expected_delete_invalid")
        seen.add((table, primary_key))
    evidence_auto_markers = {
        (str(record["table"]), str(record["primary_key"])): _evidence_marker(record)
        for record in evidence["records"]
        if record["disposition"] == "auto_delete_eligible"
    }
    for marker in expected_deletes:
        key = (str(marker["table"]), str(marker["primary_key"]))
        if evidence_auto_markers.get(key) != marker:
            raise EvidenceValidationError("receipt_expected_delete_not_bound_to_evidence")
    expected_deletes_sha256 = _sha256_json(_sorted_markers(expected_deletes))
    if receipt.get("expected_deletes_sha256") != expected_deletes_sha256:
        raise EvidenceValidationError("receipt_expected_deletes_sha256_mismatch")
    expected_binding = _sha256_json(_operation_binding_payload(receipt))
    if receipt.get("operation_binding_sha256") != expected_binding:
        raise EvidenceValidationError("receipt_operation_binding_mismatch")
    if receipt.get("status") in {"commit_ready", "completed"}:
        deleted = receipt.get("deleted")
        if not isinstance(deleted, list):
            raise EvidenceValidationError("receipt_deleted_rows_missing")
        if _sorted_markers(deleted) != _sorted_markers(expected_deletes):
            raise EvidenceValidationError("receipt_deleted_rows_mismatch")
        if int(receipt.get("deleted_count", -1)) != len(deleted):
            raise EvidenceValidationError("receipt_deleted_count_mismatch")
    _verify_existing_backup(backup_path, receipt)


def _validate_assessment_for_apply(assessment: dict[str, Any]) -> None:
    if not assessment["scan_complete"]:
        _require_complete_scan(assessment)
    if not assessment["database_path_matches"]:
        raise EvidenceConflictError("evidence_database_path_mismatch")
    if not assessment["schema_matches"]:
        raise EvidenceConflictError("evidence_schema_mismatch")
    if not assessment["alembic_revision_matches"]:
        raise EvidenceConflictError("evidence_alembic_revision_mismatch")
    if assessment["changed"]:
        raise EvidenceConflictError(
            f"evidence_rows_changed={len(assessment['changed'])}"
        )


def _expected_deletes_match(
    expected: Iterable[dict[str, Any]],
    pending: Iterable[dict[str, Any]],
) -> bool:
    return _sorted_markers(expected) == _sorted_markers(pending)


def _delete_expected_rows(
    connection: sqlite3.Connection,
    expected_deletes: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    deleted: list[dict[str, Any]] = []
    for marker in _sorted_markers(expected_deletes):
        table = str(marker["table"])
        primary_key_column = SUPPORTED_PRIMARY_KEYS[table]
        primary_key = str(marker["primary_key"])
        actual = _fetch_row(
            connection,
            table=table,
            primary_key_column=primary_key_column,
            primary_key=primary_key,
        )
        if actual is None or _sha256_json(actual) != marker["row_sha256"]:
            raise EvidenceConflictError(
                f"delete_compare_and_swap_failed={table}:{primary_key}"
            )
        cursor = connection.execute(
            f'DELETE FROM "{table}" WHERE "{primary_key_column}" = ?',
            (primary_key,),
        )
        if cursor.rowcount != 1:
            raise EvidenceConflictError(
                f"delete_compare_and_swap_failed={table}:{primary_key}"
            )
        deleted.append(marker)
    return deleted


def _commit_apply_transaction(connection: sqlite3.Connection) -> None:
    connection.commit()


def _apply_outcome(
    deleted: list[dict[str, Any]],
    post_integrity: dict[str, Any],
) -> tuple[str, bool]:
    success = not _has_remaining_issues(post_integrity)
    if success:
        return ("applied" if deleted else "no_op"), True
    return (
        "applied_with_remaining_issues" if deleted else "remaining_issues",
        False,
    )


def _build_commit_ready_receipt(
    *,
    prepared_receipt: dict[str, Any],
    assessment: dict[str, Any],
    deleted: list[dict[str, Any]],
    post_integrity: dict[str, Any],
    post_database_aggregate_sha256: str,
    outcome: str,
    success: bool,
    resumed_from_status: str | None,
) -> dict[str, Any]:
    base = _unsigned_receipt(prepared_receipt)
    for key in (
        "commit_ready_at",
        "completed_at",
        "deleted",
        "deleted_count",
        "post_integrity",
        "post_database_aggregate_sha256",
        "outcome",
        "success",
        "reconciled_after_commit",
        "reconciled_after_power_loss",
    ):
        base.pop(key, None)
    commit_ready = {
        **base,
        "status": "commit_ready",
        "commit_ready_at": _utcnow(),
        "resumed_from_status": resumed_from_status,
        "deleted": deleted,
        "deleted_count": len(deleted),
        "already_absent": assessment["already_absent"],
        "resolved_by_parent": assessment["resolved_by_parent"],
        "manual_review_required": assessment["manual_review_required"],
        "uncovered_active_orphans_before_apply": assessment[
            "uncovered_active_orphans"
        ],
        "post_integrity": post_integrity,
        "post_database_aggregate_sha256": post_database_aggregate_sha256,
        "outcome": outcome,
        "success": success,
    }
    commit_ready["operation_binding_sha256"] = _sha256_json(
        _operation_binding_payload(commit_ready)
    )
    return commit_ready


def _execute_apply_transaction(
    connection: sqlite3.Connection,
    *,
    receipt_output: Path,
    prepared_receipt: dict[str, Any],
    assessment: dict[str, Any],
    resumed_from_status: str | None = None,
) -> dict[str, Any]:
    expected_deletes = list(prepared_receipt["expected_deletes"])
    if not _expected_deletes_match(expected_deletes, assessment["pending"]):
        raise EvidenceConflictError("receipt_expected_delete_set_mismatch")
    backup_path = _database_path(str(prepared_receipt["backup_path"]))
    _verify_existing_backup(backup_path, prepared_receipt)
    connection.execute("PRAGMA defer_foreign_keys=ON")
    pre_database_aggregate_sha256 = _database_aggregate_sha256(connection)
    backup_pre_aggregate = str(
        (prepared_receipt.get("backup_verification") or {}).get(
            "database_aggregate_sha256"
        )
        or ""
    )
    if not backup_pre_aggregate or not secrets.compare_digest(
        pre_database_aggregate_sha256,
        backup_pre_aggregate,
    ):
        raise EvidenceConflictError("backup_pre_state_mismatch_before_delete")
    expected_post_database_aggregate_sha256 = _database_aggregate_sha256(
        connection,
        excluded_primary_keys=expected_deletes,
    )
    deleted = _delete_expected_rows(connection, expected_deletes)
    first_post_aggregate = _database_aggregate_sha256(connection)
    if not secrets.compare_digest(
        first_post_aggregate,
        expected_post_database_aggregate_sha256,
    ):
        raise EvidenceConflictError("unexpected_database_delta_after_delete")

    # 在真实 COMMIT 前用正式恢复路径做 round-trip。这样 INSERT trigger、
    # 生成列、约束或恢复副作用会在删除仍可回滚时被发现。
    try:
        _restore_deleted_rows(
            connection,
            backup_path,
            deleted,
        )
    except sqlite3.Error as exc:
        raise EvidenceConflictError("restore_round_trip_not_feasible") from exc
    round_trip_aggregate = _database_aggregate_sha256(connection)
    if not secrets.compare_digest(
        round_trip_aggregate,
        pre_database_aggregate_sha256,
    ):
        raise EvidenceConflictError("restore_round_trip_changed_database")

    deleted = _delete_expected_rows(connection, expected_deletes)
    post_integrity = _integrity_snapshot(
        connection,
        expected_deletes=expected_deletes,
    )
    post_database_aggregate_sha256 = _database_aggregate_sha256(connection)
    if not secrets.compare_digest(
        post_database_aggregate_sha256,
        expected_post_database_aggregate_sha256,
    ):
        raise EvidenceConflictError("unexpected_database_delta_after_delete")
    outcome, success = _apply_outcome(deleted, post_integrity)

    commit_ready = _build_commit_ready_receipt(
        prepared_receipt=prepared_receipt,
        assessment=assessment,
        deleted=deleted,
        post_integrity=post_integrity,
        post_database_aggregate_sha256=post_database_aggregate_sha256,
        outcome=outcome,
        success=success,
        resumed_from_status=resumed_from_status,
    )
    _replace_bytes_atomic(receipt_output, _receipt_bytes(commit_ready))
    _verify_existing_backup(backup_path, commit_ready)
    _commit_apply_transaction(connection)

    # COMMIT 会释放 SQLite 写锁。重新取得写锁并复验整库，避免其他写入在
    # 数据提交与 completed 回执之间插入，造成“回执成功、实际状态已漂移”。
    connection.execute("BEGIN IMMEDIATE")
    committed_integrity = _integrity_snapshot(
        connection,
        expected_deletes=expected_deletes,
    )
    committed_aggregate = _database_aggregate_sha256(connection)
    if (
        committed_integrity["fingerprint_sha256"]
        != post_integrity["fingerprint_sha256"]
        or committed_aggregate != post_database_aggregate_sha256
    ):
        raise EvidenceConflictError("post_commit_state_changed_before_receipt")
    _verify_existing_backup(backup_path, commit_ready)

    completed = {
        **commit_ready,
        "status": "completed",
        "completed_at": _utcnow(),
    }
    _replace_bytes_atomic(receipt_output, _receipt_bytes(completed))
    persisted = load_receipt(receipt_output)
    connection.rollback()
    return {
        "mode": "apply",
        **persisted,
        "receipt_path": str(receipt_output),
    }


def _open_apply_connection(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA synchronous=FULL")
    synchronous_row = connection.execute("PRAGMA synchronous").fetchone()
    if not synchronous_row or int(synchronous_row[0]) < 2:
        connection.close()
        raise OrphanQuarantineError("sqlite_synchronous_not_full_for_apply")
    connection.execute("PRAGMA foreign_keys=ON")
    foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
    if not foreign_keys_row or int(foreign_keys_row[0]) != 1:
        connection.close()
        raise OrphanQuarantineError("foreign_keys_not_enabled_for_apply")
    return connection


def _build_prepared_receipt(
    *,
    database_path: Path,
    evidence: dict[str, Any],
    backup_output: Path,
    receipt_output: Path,
    backup_verification: dict[str, Any],
    source_data_version: int,
    expected_deletes: list[dict[str, Any]],
    assessment: dict[str, Any],
    recovered_from_backup_only: bool = False,
) -> dict[str, Any]:
    prepared_receipt = {
        "tool": TOOL_NAME,
        "receipt_version": RECEIPT_VERSION,
        "status": "prepared",
        "prepared_at": _utcnow(),
        "database_path": str(database_path),
        "evidence_path": evidence["path"],
        "evidence_sha256": evidence["evidence_sha256"],
        "backup_path": str(backup_output),
        "receipt_path": str(receipt_output),
        "backup_sha256": backup_verification["sha256"],
        "backup_verification": backup_verification,
        "source_alembic_revision": evidence["header"][
            "source_alembic_revision"
        ],
        "source_schema_sha256": evidence["header"]["source_schema_sha256"],
        "source_data_version": source_data_version,
        "expected_deletes": expected_deletes,
        "expected_deletes_sha256": _sha256_json(expected_deletes),
        "pending_delete_count": len(expected_deletes),
        "captured_manual_review_required": assessment[
            "manual_review_required"
        ],
        "recovered_from_backup_only": recovered_from_backup_only,
    }
    prepared_receipt["operation_binding_sha256"] = _sha256_json(
        _operation_binding_payload(prepared_receipt)
    )
    return prepared_receipt


def _verify_unreceipted_backup(
    backup_output: Path,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if not backup_output.exists():
        raise EvidenceConflictError("unreceipted_backup_missing")
    backup_sha256 = _sha256_file(backup_output)
    with closing(_open_immutable_snapshot(backup_output)) as backup:
        backup_aggregate = _database_aggregate_sha256(backup)
    provisional_receipt = {
        "backup_sha256": backup_sha256,
        "source_alembic_revision": evidence["header"][
            "source_alembic_revision"
        ],
        "source_schema_sha256": evidence["header"]["source_schema_sha256"],
        "backup_verification": {
            "sha256": backup_sha256,
            "database_aggregate_sha256": backup_aggregate,
        },
    }
    verification = _verify_existing_backup(
        backup_output,
        provisional_receipt,
        require_read_only=False,
    )
    try:
        _require_backup_read_only(backup_output)
    except EvidenceConflictError:
        _flush_published_path(backup_output)
        os.chmod(
            backup_output,
            stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH,
        )
        _require_backup_read_only(backup_output)
    return verification


def _expected_deletes_and_post_from_backup(
    *,
    backup_output: Path,
    evidence: dict[str, Any],
    database_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    with closing(_open_immutable_snapshot(backup_output)) as backup:
        backup_assessment = assess_evidence(
            backup,
            evidence,
            database_path=database_path,
        )
        _validate_assessment_for_apply(backup_assessment)
        expected_deletes = _sorted_markers(backup_assessment["pending"])
        expected_post_aggregate = _database_aggregate_sha256(
            backup,
            excluded_primary_keys=expected_deletes,
        )
    return backup_assessment, expected_deletes, expected_post_aggregate


def _finalize_reconciled_post_state(
    connection: sqlite3.Connection,
    *,
    receipt_output: Path,
    prepared_receipt: dict[str, Any],
    decision_assessment: dict[str, Any],
    expected_deletes: list[dict[str, Any]],
    current_post_aggregate: str,
    resumed_from_status: str,
) -> dict[str, Any]:
    post_integrity = _integrity_snapshot(
        connection,
        expected_deletes=expected_deletes,
    )
    outcome, success = _apply_outcome(expected_deletes, post_integrity)
    commit_ready = _build_commit_ready_receipt(
        prepared_receipt=prepared_receipt,
        assessment=decision_assessment,
        deleted=expected_deletes,
        post_integrity=post_integrity,
        post_database_aggregate_sha256=current_post_aggregate,
        outcome=outcome,
        success=success,
        resumed_from_status=resumed_from_status,
    )
    commit_ready["reconciled_after_power_loss"] = True
    _replace_bytes_atomic(receipt_output, _receipt_bytes(commit_ready))
    completed = {
        **commit_ready,
        "status": "completed",
        "completed_at": _utcnow(),
    }
    _replace_bytes_atomic(receipt_output, _receipt_bytes(completed))
    persisted = load_receipt(receipt_output)
    connection.rollback()
    return {
        "mode": "apply",
        **persisted,
        "receipt_path": str(receipt_output),
        "reconciled": True,
    }


def _resume_from_backup_only(
    database_path: Path,
    evidence: dict[str, Any],
    backup_output: Path,
    receipt_output: Path,
) -> dict[str, Any]:
    if receipt_output.exists() or not backup_output.exists():
        raise EvidenceConflictError("unexpected_backup_only_artifact_state")
    backup_verification = _verify_unreceipted_backup(backup_output, evidence)
    connection = _open_apply_connection(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        scan = scan_orphans(connection)
        _require_complete_scan(scan)
        assessment = assess_evidence(
            connection,
            evidence,
            database_path=database_path,
        )
        _validate_assessment_for_apply(assessment)
        current_aggregate = _database_aggregate_sha256(connection)
        backup_assessment, expected_deletes, expected_post_aggregate = (
            _expected_deletes_and_post_from_backup(
                backup_output=backup_output,
                evidence=evidence,
                database_path=database_path,
            )
        )
        is_pre_state = secrets.compare_digest(
            current_aggregate,
            str(backup_verification["database_aggregate_sha256"]),
        )
        is_post_state = secrets.compare_digest(
            current_aggregate,
            expected_post_aggregate,
        )
        if not is_pre_state and not is_post_state:
            raise EvidenceConflictError("unreceipted_backup_state_mismatch")
        prepared_receipt = _build_prepared_receipt(
            database_path=database_path,
            evidence=evidence,
            backup_output=backup_output,
            receipt_output=receipt_output,
            backup_verification=backup_verification,
            source_data_version=int(
                connection.execute("PRAGMA data_version").fetchone()[0]
            ),
            expected_deletes=expected_deletes,
            assessment=backup_assessment,
            recovered_from_backup_only=True,
        )
        _write_new_bytes_atomic(receipt_output, _receipt_bytes(prepared_receipt))
        if is_post_state:
            return _finalize_reconciled_post_state(
                connection,
                receipt_output=receipt_output,
                prepared_receipt=prepared_receipt,
                decision_assessment=backup_assessment,
                expected_deletes=expected_deletes,
                current_post_aggregate=current_aggregate,
                resumed_from_status="backup_only_post_state",
            )
        return _execute_apply_transaction(
            connection,
            receipt_output=receipt_output,
            prepared_receipt=prepared_receipt,
            assessment=assessment,
            resumed_from_status="backup_only",
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _resume_apply_evidence(
    database_path: Path,
    evidence: dict[str, Any],
    backup_output: Path,
    receipt_output: Path,
) -> dict[str, Any]:
    if not backup_output.exists() or not receipt_output.exists():
        raise EvidenceConflictError("incomplete_existing_apply_artifacts")
    receipt = load_receipt(receipt_output)
    _validate_receipt_binding(
        receipt,
        database_path=database_path,
        evidence=evidence,
        backup_path=backup_output,
        receipt_path=receipt_output,
    )
    connection = _open_apply_connection(database_path)
    try:
        # 所有幂等与故障恢复判断都必须在同一写锁快照内完成；否则其他连接
        # 可在“校验通过”和“completed 回执落盘”之间插入新孤儿。
        connection.execute("BEGIN IMMEDIATE")
        expected_deletes = list(receipt["expected_deletes"])
        current_integrity = _integrity_snapshot(
            connection,
            expected_deletes=expected_deletes,
        )
        expected_post = receipt.get("post_integrity")
        integrity_matches = bool(
            isinstance(expected_post, dict)
            and secrets.compare_digest(
                str(current_integrity["fingerprint_sha256"]),
                str(expected_post.get("fingerprint_sha256") or ""),
            )
        )
        expected_post_aggregate = str(
            receipt.get("post_database_aggregate_sha256") or ""
        )
        aggregate_matches = bool(
            expected_post_aggregate
            and secrets.compare_digest(
                _database_aggregate_sha256(connection),
                expected_post_aggregate,
            )
        )
        post_matches = integrity_matches and aggregate_matches

        if receipt["status"] == "prepared":
            backup_assessment, backup_expected_deletes, derived_post_aggregate = (
                _expected_deletes_and_post_from_backup(
                    backup_output=backup_output,
                    evidence=evidence,
                    database_path=database_path,
                )
            )
            current_aggregate = _database_aggregate_sha256(connection)
            if (
                _expected_deletes_match(
                    expected_deletes,
                    backup_expected_deletes,
                )
                and secrets.compare_digest(
                    current_aggregate,
                    derived_post_aggregate,
                )
            ):
                current_assessment = assess_evidence(
                    connection,
                    evidence,
                    database_path=database_path,
                )
                _validate_assessment_for_apply(current_assessment)
                return _finalize_reconciled_post_state(
                    connection,
                    receipt_output=receipt_output,
                    prepared_receipt=receipt,
                    decision_assessment=backup_assessment,
                    expected_deletes=expected_deletes,
                    current_post_aggregate=current_aggregate,
                    resumed_from_status="prepared_post_state",
                )

        if receipt["status"] == "completed":
            if not post_matches:
                raise EvidenceConflictError("completed_receipt_post_state_mismatch")
            connection.rollback()
            return {
                "mode": "apply",
                **receipt,
                "receipt_path": str(receipt_output),
                "reconciled": True,
            }

        if receipt["status"] == "commit_ready" and post_matches:
            completed = {
                **_unsigned_receipt(receipt),
                "status": "completed",
                "completed_at": _utcnow(),
                "reconciled_after_commit": True,
            }
            _replace_bytes_atomic(receipt_output, _receipt_bytes(completed))
            persisted = load_receipt(receipt_output)
            connection.rollback()
            return {
                "mode": "apply",
                **persisted,
                "receipt_path": str(receipt_output),
                "reconciled": True,
            }

        locked_assessment = assess_evidence(
            connection,
            evidence,
            database_path=database_path,
        )
        _validate_assessment_for_apply(locked_assessment)
        if not _expected_deletes_match(
            expected_deletes,
            locked_assessment["pending"],
        ):
            raise EvidenceConflictError("receipt_resume_state_ambiguous")
        return _execute_apply_transaction(
            connection,
            receipt_output=receipt_output,
            prepared_receipt=receipt,
            assessment=locked_assessment,
            resumed_from_status=str(receipt["status"]),
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _apply_evidence_locked(
    path: str | os.PathLike[str],
    evidence_path: str | os.PathLike[str],
    *,
    confirm_sha256: str,
    backup_path: str | os.PathLike[str],
    receipt_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Delete only exact, still-orphaned child snapshots from a verified bundle."""

    database_path = _database_path(path)
    backup_output = _database_path(backup_path)
    receipt_output = _database_path(receipt_path)
    evidence_output = _database_path(evidence_path)
    _assert_distinct_artifact_files(
        database=database_path,
        evidence=evidence_output,
        backup=backup_output,
        receipt=receipt_output,
    )
    evidence = load_evidence(evidence_output)
    if not secrets.compare_digest(
        evidence["evidence_sha256"], confirm_sha256.strip().lower()
    ):
        raise EvidenceValidationError("confirmed_evidence_sha256_mismatch")
    if backup_output.exists() and not receipt_output.exists():
        return _resume_from_backup_only(
            database_path,
            evidence,
            backup_output,
            receipt_output,
        )
    if receipt_output.exists() and not backup_output.exists():
        raise EvidenceConflictError("incomplete_existing_apply_artifacts")
    if backup_output.exists() and receipt_output.exists():
        return _resume_apply_evidence(
            database_path,
            evidence,
            backup_output,
            receipt_output,
        )

    connection = _open_apply_connection(database_path)
    prepared_backup: Path | None = None
    try:
        _require_complete_scan(scan_orphans(connection))
        initial_assessment = assess_evidence(
            connection,
            evidence,
            database_path=database_path,
        )
        _validate_assessment_for_apply(initial_assessment)

        data_version_before = int(
            connection.execute("PRAGMA data_version").fetchone()[0]
        )
        prepared_backup, backup_verification = _prepare_backup_database(
            connection,
            backup_output,
        )
        data_version_after = int(
            connection.execute("PRAGMA data_version").fetchone()[0]
        )
        if data_version_after != data_version_before:
            raise EvidenceConflictError("database_changed_during_backup")

        connection.execute("BEGIN IMMEDIATE")
        data_version_locked = int(
            connection.execute("PRAGMA data_version").fetchone()[0]
        )
        if data_version_locked != data_version_after:
            raise EvidenceConflictError("database_changed_before_write_lock")
        assessment = assess_evidence(
            connection,
            evidence,
            database_path=database_path,
        )
        _validate_assessment_for_apply(assessment)
        _publish_prepared_backup(prepared_backup, backup_output)
        prepared_backup = None
        expected_deletes = _sorted_markers(assessment["pending"])
        prepared_receipt = _build_prepared_receipt(
            database_path=database_path,
            evidence=evidence,
            backup_output=backup_output,
            receipt_output=receipt_output,
            backup_verification=backup_verification,
            source_data_version=data_version_locked,
            expected_deletes=expected_deletes,
            assessment=assessment,
        )
        _write_new_bytes_atomic(receipt_output, _receipt_bytes(prepared_receipt))
        return _execute_apply_transaction(
            connection,
            receipt_output=receipt_output,
            prepared_receipt=prepared_receipt,
            assessment=assessment,
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        if prepared_backup is not None:
            prepared_backup.unlink(missing_ok=True)
        connection.close()


def apply_evidence(
    path: str | os.PathLike[str],
    evidence_path: str | os.PathLike[str],
    *,
    confirm_sha256: str,
    backup_path: str | os.PathLike[str],
    receipt_path: str | os.PathLike[str],
) -> dict[str, Any]:
    database_path = _database_path(path)
    receipt_output = _database_path(receipt_path)
    lock_path = _artifact_lock_path(receipt_output)
    _assert_distinct_artifact_files(
        database=database_path,
        receipt=receipt_output,
        operation_lock=lock_path,
    )
    with _artifact_lock(receipt_output):
        return _apply_evidence_locked(
            path,
            evidence_path,
            confirm_sha256=confirm_sha256,
            backup_path=backup_path,
            receipt_path=receipt_path,
        )


def _restore_deleted_rows(
    connection: sqlite3.Connection,
    backup_path: Path,
    deleted: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    restored: list[dict[str, Any]] = []
    with closing(_open_immutable_snapshot(backup_path)) as backup:
        backup.row_factory = sqlite3.Row
        for marker in _sorted_markers(deleted):
            table = str(marker["table"])
            primary_key_column = SUPPORTED_PRIMARY_KEYS[table]
            primary_key = str(marker["primary_key"])
            if (
                _fetch_row(
                    connection,
                    table=table,
                    primary_key_column=primary_key_column,
                    primary_key=primary_key,
                )
                is not None
            ):
                raise EvidenceConflictError(
                    f"restore_target_row_not_absent={table}:{primary_key}"
                )
            source_row = _fetch_row(
                backup,
                table=table,
                primary_key_column=primary_key_column,
                primary_key=primary_key,
            )
            if source_row is None or _sha256_json(source_row) != marker["row_sha256"]:
                raise EvidenceConflictError(
                    f"restore_backup_row_mismatch={table}:{primary_key}"
                )
            columns = list(source_row)
            quoted_columns = ", ".join(
                f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns
            )
            placeholders = ", ".join("?" for _ in columns)
            quoted_table = table.replace('"', '""')
            connection.execute(
                f'INSERT INTO "{quoted_table}" ({quoted_columns}) VALUES ({placeholders})',
                tuple(source_row[column] for column in columns),
            )
            restored.append(marker)
    return restored


def _verify_rows_restored_from_backup(
    connection: sqlite3.Connection,
    backup_path: Path,
    deleted: Iterable[dict[str, Any]],
) -> int:
    verified = 0
    with closing(_open_immutable_snapshot(backup_path)) as backup:
        backup.row_factory = sqlite3.Row
        for marker in _sorted_markers(deleted):
            table = str(marker["table"])
            primary_key_column = SUPPORTED_PRIMARY_KEYS[table]
            primary_key = str(marker["primary_key"])
            current_row = _fetch_row(
                connection,
                table=table,
                primary_key_column=primary_key_column,
                primary_key=primary_key,
            )
            backup_row = _fetch_row(
                backup,
                table=table,
                primary_key_column=primary_key_column,
                primary_key=primary_key,
            )
            if (
                current_row is None
                or backup_row is None
                or current_row != backup_row
                or _sha256_json(current_row) != marker["row_sha256"]
            ):
                raise EvidenceConflictError(
                    f"restored_row_verification_failed={table}:{primary_key}"
                )
            verified += 1
    return verified


def _commit_restore_transaction(connection: sqlite3.Connection) -> None:
    connection.commit()


def _restore_from_receipt_locked(
    path: str | os.PathLike[str],
    receipt_path: str | os.PathLike[str],
    *,
    confirm_receipt_sha256: str,
) -> dict[str, Any]:
    """Restore the receipt-bound pre-apply backup after explicit confirmation."""

    database_path = _database_path(path)
    receipt_output = _database_path(receipt_path)
    if not database_path.exists():
        raise OrphanQuarantineError("restore_target_database_missing")
    receipt = load_receipt(receipt_output)
    if not secrets.compare_digest(
        str(receipt["receipt_sha256"]),
        confirm_receipt_sha256.strip().lower(),
    ):
        raise EvidenceValidationError("confirmed_receipt_sha256_mismatch")
    evidence = load_evidence(str(receipt.get("evidence_path") or ""))
    backup_path = _database_path(str(receipt.get("backup_path") or ""))
    _validate_receipt_binding(
        receipt,
        database_path=database_path,
        evidence=evidence,
        backup_path=backup_path,
        receipt_path=receipt_output,
    )
    backup_verification = _verify_existing_backup(backup_path, receipt)
    expected_post_aggregate = str(
        receipt.get("post_database_aggregate_sha256") or ""
    )
    if receipt.get("status") not in {"commit_ready", "completed"}:
        raise EvidenceConflictError("restore_receipt_has_no_committed_post_state")
    if not expected_post_aggregate:
        raise EvidenceValidationError("receipt_post_database_aggregate_missing")

    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=30000")
    connection.execute("PRAGMA synchronous=FULL")
    synchronous_row = connection.execute("PRAGMA synchronous").fetchone()
    if not synchronous_row or int(synchronous_row[0]) < 2:
        connection.close()
        raise OrphanQuarantineError("sqlite_synchronous_not_full_for_restore")
    connection.execute("PRAGMA foreign_keys=OFF")
    foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
    if not foreign_keys_row or int(foreign_keys_row[0]) != 0:
        connection.close()
        raise OrphanQuarantineError("foreign_keys_not_disabled_for_restore")
    reconciled = False
    restored_rows: list[dict[str, Any]] = []
    verified_restored_row_count = 0
    try:
        # 锁内完成“校验当前 post-state → 恢复本次删除行 → 复算整库”。
        # 不再替换数据库文件，因此不存在校验与 os.replace 之间的丢写窗口。
        # SQLite sidecar files are not proof of a live writer.  In particular, a
        # process crash during the previous restore can leave a hot rollback
        # journal which SQLite must be allowed to recover when this transaction
        # acquires its lock.  BEGIN EXCLUSIVE is the authority boundary: it
        # either recovers stale state and locks the database, or fails while a
        # real competing writer/reader still owns an incompatible lock.
        try:
            connection.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise OrphanQuarantineError(
                f"restore_target_busy_or_unrecoverable={exc}"
            ) from exc
        current_tables = _table_names(connection)
        current_revision = _alembic_revision(connection, current_tables)
        current_schema = _schema_sha256(connection, current_tables)
        current_aggregate = _database_aggregate_sha256(connection)
        if current_revision != receipt["source_alembic_revision"]:
            raise EvidenceConflictError("restore_target_revision_mismatch")
        if current_schema != receipt["source_schema_sha256"]:
            raise EvidenceConflictError("restore_target_schema_mismatch")
        deleted = list(receipt["deleted"])
        backup_aggregate = str(backup_verification["database_aggregate_sha256"])
        if secrets.compare_digest(current_aggregate, backup_aggregate):
            verified_restored_row_count = _verify_rows_restored_from_backup(
                connection,
                backup_path,
                deleted,
            )
            restored_aggregate = current_aggregate
            reconciled = True
            connection.rollback()
        else:
            if not secrets.compare_digest(
                current_aggregate,
                expected_post_aggregate,
            ):
                raise EvidenceConflictError("restore_target_post_state_mismatch")
            restored_rows = _restore_deleted_rows(connection, backup_path, deleted)
            restored_aggregate = _database_aggregate_sha256(connection)
            integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
            quick_row = connection.execute("PRAGMA quick_check").fetchone()
            integrity = str(integrity_row[0]) if integrity_row else "unknown"
            quick_check = str(quick_row[0]) if quick_row else "unknown"
            if integrity != "ok" or quick_check != "ok":
                raise OrphanQuarantineError("restore_candidate_integrity_failed")
            if restored_aggregate != backup_aggregate:
                raise EvidenceConflictError("restore_candidate_aggregate_mismatch")
            verified_restored_row_count = _verify_rows_restored_from_backup(
                connection,
                backup_path,
                deleted,
            )
            _commit_restore_transaction(connection)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "mode": "restore",
        "status": "already_restored" if reconciled else "restored",
        "success": True,
        "reconciled": reconciled,
        "database_path": str(database_path),
        "receipt_path": str(receipt_output),
        "receipt_sha256": receipt["receipt_sha256"],
        "backup_path": str(backup_path),
        "backup_sha256": backup_verification["sha256"],
        "source_alembic_revision": receipt["source_alembic_revision"],
        "source_schema_sha256": receipt["source_schema_sha256"],
        "pre_restore_database_aggregate_sha256": current_aggregate,
        "expected_post_database_aggregate_sha256": expected_post_aggregate,
        "restored_database_aggregate_sha256": restored_aggregate,
        "restored_row_count": len(restored_rows),
        "verified_restored_row_count": verified_restored_row_count,
    }


def restore_from_receipt(
    path: str | os.PathLike[str],
    receipt_path: str | os.PathLike[str],
    *,
    confirm_receipt_sha256: str,
) -> dict[str, Any]:
    database_path = _database_path(path)
    receipt_output = _database_path(receipt_path)
    lock_path = _artifact_lock_path(receipt_output)
    _assert_distinct_artifact_files(
        database=database_path,
        receipt=receipt_output,
        operation_lock=lock_path,
    )
    with _artifact_lock(receipt_output):
        return _restore_from_receipt_locked(
            path,
            receipt_path,
            confirm_receipt_sha256=confirm_receipt_sha256,
        )


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="审计并隔离历史孤儿；默认只读，apply 必须使用先前导出的证据",
    )
    parser.add_argument("path", help="SQLite 数据库路径")
    parser.add_argument(
        "--export", dest="evidence_output", help="导出不可覆盖的 JSONL 证据"
    )
    parser.add_argument("--apply-evidence", help="显式应用先前导出的 JSONL 证据")
    parser.add_argument("--confirm-sha256", help="apply 时人工回填证据文件 SHA256")
    parser.add_argument("--backup", help="apply 前创建的不可覆盖 SQLite 副本")
    parser.add_argument("--receipt", help="apply 审计回执 JSON")
    parser.add_argument(
        "--restore-receipt",
        help="从严格校验的 orphan apply 回执恢复其绑定的操作前备份",
    )
    parser.add_argument(
        "--confirm-receipt-sha256",
        help="restore 时显式回填回执内 receipt_sha256",
    )
    parser.add_argument(
        "--list-keys",
        action="store_true",
        help="仅默认 dry-run 时完整列出孤儿主键；默认只显示前 20 条样本",
    )
    args = parser.parse_args(argv)
    operation_count = sum(
        bool(value)
        for value in (
            args.evidence_output,
            args.apply_evidence,
            args.restore_receipt,
        )
    )
    if operation_count > 1:
        parser.error("--export、--apply-evidence、--restore-receipt 不能同时使用")
    if args.apply_evidence and not (
        args.confirm_sha256 and args.backup and args.receipt
    ):
        parser.error(
            "--apply-evidence 必须同时提供 --confirm-sha256、--backup、--receipt"
        )
    if not args.apply_evidence and (args.confirm_sha256 or args.backup or args.receipt):
        parser.error("--confirm-sha256、--backup、--receipt 仅用于显式 apply")
    if args.restore_receipt and not args.confirm_receipt_sha256:
        parser.error("--restore-receipt 必须同时提供 --confirm-receipt-sha256")
    if not args.restore_receipt and args.confirm_receipt_sha256:
        parser.error("--confirm-receipt-sha256 仅用于显式 restore")
    if args.list_keys and (
        args.evidence_output or args.apply_evidence or args.restore_receipt
    ):
        parser.error("--list-keys 仅用于不带 --export/--apply-evidence 的 dry-run")

    try:
        if args.restore_receipt:
            result = restore_from_receipt(
                args.path,
                args.restore_receipt,
                confirm_receipt_sha256=args.confirm_receipt_sha256,
            )
        elif args.apply_evidence:
            result = apply_evidence(
                args.path,
                args.apply_evidence,
                confirm_sha256=args.confirm_sha256,
                backup_path=args.backup,
                receipt_path=args.receipt,
            )
        elif args.evidence_output:
            result = export_evidence(args.path, args.evidence_output)
        else:
            result = inspect_orphans(args.path, include_all_keys=args.list_keys)
        if args.apply_evidence:
            exit_code = (
                0
                if result.get("status") == "completed"
                and result.get("success") is True
                else 1
            )
        elif args.restore_receipt:
            exit_code = 0 if result.get("success") is True else 1
        elif not args.evidence_output and result.get("status") in {
            "incomplete",
            "manual_review_required",
        }:
            exit_code = 1
        else:
            exit_code = 0
    except (OSError, sqlite3.Error, OrphanQuarantineError) as exc:
        result = {
            "mode": (
                "restore"
                if args.restore_receipt
                else "apply" if args.apply_evidence else "dry_run"
            ),
            "status": "refused",
            "error": str(exc),
        }
        exit_code = 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(_main())
