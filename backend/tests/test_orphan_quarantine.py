from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from novel_system.tools import orphan_quarantine
from novel_system.tools.orphan_quarantine import (
    EvidenceConflictError,
    EvidenceValidationError,
    OrphanQuarantineError,
    apply_evidence,
    export_evidence,
    inspect_orphans,
    load_evidence,
    load_receipt,
    restore_from_receipt,
    scan_orphans,
)


def _make_orphan_database(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE alembic_version (version_num TEXT NOT NULL);
            INSERT INTO alembic_version VALUES ('20260715_0069');

            CREATE TABLE llm_calls (
                llm_call_id TEXT PRIMARY KEY,
                project_id TEXT,
                created_at TEXT
            );
            CREATE TABLE llm_call_attempts (
                attempt_id TEXT PRIMARY KEY,
                llm_call_id TEXT NOT NULL,
                provider_attempt_no INTEGER NOT NULL,
                accounting_status TEXT NOT NULL,
                error_text TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (llm_call_id) REFERENCES llm_calls(llm_call_id)
            );

            CREATE TABLE story_projects (project_id TEXT PRIMARY KEY);
            CREATE TABLE snowflake_step_runs (
                step_run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                step_key TEXT NOT NULL
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
                resolved_at TEXT
            );

            INSERT INTO llm_calls VALUES ('call-valid', 'p1', 'now');
            INSERT INTO llm_call_attempts VALUES
                ('attempt-valid', 'call-valid', 0, 'settled', NULL, 'now'),
                ('attempt-orphan', 'call-missing', 0, 'failed', 'transport', 'now');

            INSERT INTO story_projects VALUES ('p1'), ('p2');
            INSERT INTO snowflake_step_runs VALUES
                ('source-p1', 'p1', 'book_brief'),
                ('affected-p1', 'p1', 'scene_list'),
                ('source-p2', 'p2', 'book_brief');
            INSERT INTO snowflake_scene_plans VALUES ('scene-p1', 'p1');

            INSERT INTO snowflake_revision_links VALUES
                ('link-valid', 'p1', 'book_brief', 'source-p1',
                 'step_run', 'affected-p1', 'valid', 'open', 'now', NULL),
                ('link-missing-project', 'missing-project', 'book_brief', 'missing-source',
                 'step_run', 'missing-step', 'purged project', 'open', 'now', NULL),
                ('link-missing-source', 'p1', 'book_brief', 'missing-source',
                 'step_run', 'affected-p1', 'missing source', 'open', 'now', NULL),
                ('link-missing-scene', 'p1', 'book_brief', 'source-p1',
                 'scene_plan', 'missing-scene', 'missing target', 'open', 'now', NULL);
            """
        )


def _active_count(path, table: str) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _add_manual_review_rows(path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executemany(
            """
            INSERT INTO snowflake_revision_links VALUES (
                ?, 'p1', 'book_brief', ?, ?, ?,
                'manual review fixture', 'open', 'now', NULL
            )
            """,
            [
                (
                    "link-unsupported-kind",
                    "source-p1",
                    "future_kind",
                    "future-id",
                ),
                (
                    "link-source-project-mismatch",
                    "source-p2",
                    "step_run",
                    "affected-p1",
                ),
                (
                    "link-empty-affected-id",
                    "source-p1",
                    "step_run",
                    "",
                ),
            ],
        )


def test_export_is_read_only_complete_and_hash_verified(tmp_path) -> None:
    database_path = tmp_path / "orphan.db"
    evidence_path = tmp_path / "evidence.jsonl"
    _make_orphan_database(database_path)

    result = export_evidence(database_path, evidence_path)
    evidence = load_evidence(evidence_path)

    assert result["mode"] == "dry_run"
    assert result["status"] == "evidence_exported"
    assert result["would_delete"] == 4
    assert result["counts_by_table"] == {
        "llm_call_attempts": 1,
        "snowflake_revision_links": 3,
    }
    assert result["evidence_sha256"] == evidence["evidence_sha256"]
    assert evidence["header"]["parent_fabrication_allowed"] is False
    assert evidence["summary"]["record_count"] == 4
    assert evidence["summary"]["auto_delete_count"] == 4
    assert evidence["summary"]["manual_review_count"] == 0
    assert _active_count(database_path, "llm_call_attempts") == 2
    assert _active_count(database_path, "snowflake_revision_links") == 4
    assert not list(tmp_path.glob(f".{evidence_path.name}.*.tmp"))


def test_apply_requires_confirmed_hash_creates_backup_and_is_idempotent(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "orphan.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "before-apply.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)

    with pytest.raises(
        EvidenceValidationError, match="confirmed_evidence_sha256_mismatch"
    ):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256="0" * 64,
            backup_path=backup_path,
            receipt_path=receipt_path,
        )
    assert not backup_path.exists()
    assert not receipt_path.exists()

    original_prepare_backup = orphan_quarantine._prepare_backup_database

    def guarded_prepare_backup(connection, target):
        # Regression fence: sqlite3.Connection.backup on this same connection
        # would self-block if a BEGIN IMMEDIATE transaction had already started.
        assert connection.in_transaction is False
        return original_prepare_backup(connection, target)

    monkeypatch.setattr(
        orphan_quarantine,
        "_prepare_backup_database",
        guarded_prepare_backup,
    )

    applied = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )

    assert applied["status"] == "completed"
    assert applied["outcome"] == "applied"
    assert applied["success"] is True
    assert applied["deleted_count"] == 4
    assert applied["post_integrity"]["orphan_record_count"] == 0
    assert applied["post_integrity"]["foreign_key_check"]["count"] == 0
    assert backup_path.exists()
    assert receipt_path.exists()
    assert not Path(f"{backup_path}-wal").exists()
    assert not Path(f"{backup_path}-shm").exists()
    assert not list(tmp_path.glob(f".{backup_path.name}.*.tmp-wal"))
    assert not list(tmp_path.glob(f".{backup_path.name}.*.tmp-shm"))
    assert applied["backup_verification"]["integrity_check"] == "ok"
    assert applied["backup_verification"]["quick_check"] == "ok"
    assert applied["backup_verification"]["orphan_record_count"] == 4
    assert (
        applied["backup_sha256"] == hashlib.sha256(backup_path.read_bytes()).hexdigest()
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["backup_verification"] == applied["backup_verification"]
    unsigned_receipt = dict(receipt)
    receipt_sha256 = unsigned_receipt.pop("receipt_sha256")
    assert receipt_sha256 == orphan_quarantine._sha256_json(unsigned_receipt)
    with sqlite3.connect(backup_path) as backup:
        assert scan_orphans(backup)["record_count"] == 4
    assert _active_count(database_path, "llm_call_attempts") == 1
    assert _active_count(database_path, "snowflake_revision_links") == 1

    second = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=tmp_path / "before-second-apply.db",
        receipt_path=tmp_path / "second-receipt.json",
    )
    assert second["status"] == "completed"
    assert second["outcome"] == "no_op"
    assert second["success"] is True
    assert second["deleted_count"] == 0
    assert len(second["already_absent"]) == 4


def test_apply_fails_closed_when_any_exported_row_changed(tmp_path) -> None:
    database_path = tmp_path / "orphan.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE llm_call_attempts SET error_text = 'changed' WHERE attempt_id = ?",
            ("attempt-orphan",),
        )

    with pytest.raises(EvidenceConflictError, match="evidence_rows_changed=1"):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert not backup_path.exists()
    assert not receipt_path.exists()
    assert inspect_orphans(database_path)["record_count"] == 4


def test_apply_fails_closed_when_alembic_revision_changed_without_schema_change(
    tmp_path,
) -> None:
    database_path = tmp_path / "orphan.db"
    evidence_path = tmp_path / "evidence.jsonl"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE alembic_version SET version_num = ?",
            ("20260716_0070",),
        )

    assessment = orphan_quarantine.assess_evidence_file(
        database_path,
        evidence_path,
    )

    assert assessment["status"] == "evidence_mismatch"
    assert assessment["schema_matches"] is True
    assert assessment["source_alembic_revision"] == "20260715_0069"
    assert assessment["current_alembic_revision"] == "20260716_0070"
    assert assessment["alembic_revision_matches"] is False
    with pytest.raises(
        EvidenceConflictError,
        match="evidence_alembic_revision_mismatch",
    ):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=tmp_path / "backup.db",
            receipt_path=tmp_path / "receipt.json",
        )
    assert not (tmp_path / "backup.db").exists()
    assert not (tmp_path / "receipt.json").exists()


def test_scan_rejects_unsupported_affected_kind_and_empty_affected_id(
    tmp_path,
) -> None:
    database_path = tmp_path / "orphan.db"
    _make_orphan_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO snowflake_revision_links VALUES (
                ?, 'p1', 'book_brief', 'source-p1', ?, ?,
                'invalid affected reference', 'open', 'now', NULL
            )
            """,
            [
                ("link-unsupported-kind", "future_kind", "future-id"),
                ("link-empty-affected-id", "step_run", ""),
            ],
        )
        records = {
            record["primary_key"]: record
            for record in scan_orphans(connection)["records"]
        }

    assert records["link-unsupported-kind"]["reasons"] == [
        "unsupported_affected_kind"
    ]
    assert (
        records["link-unsupported-kind"]["disposition"]
        == "manual_review_required"
    )
    assert records["link-empty-affected-id"]["reasons"] == [
        "empty_affected_id",
        "missing_affected_step_run",
    ]
    assert (
        records["link-empty-affected-id"]["disposition"]
        == "manual_review_required"
    )


def test_incomplete_scan_cannot_export_or_apply(tmp_path, capsys) -> None:
    database_path = tmp_path / "incomplete.db"
    evidence_path = tmp_path / "before-incomplete.jsonl"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP TABLE snowflake_scene_plans")

    inspected = inspect_orphans(database_path)
    assert inspected["status"] == "incomplete"
    assert inspected["complete"] is False
    assert inspected["missing_dependencies"] == {
        "snowflake_revision_links": ["snowflake_scene_plans"]
    }

    refused_export = tmp_path / "must-not-exist.jsonl"
    with pytest.raises(OrphanQuarantineError, match="orphan_scan_incomplete"):
        export_evidence(database_path, refused_export)
    assert not refused_export.exists()

    backup_path = tmp_path / "must-not-exist.db"
    receipt_path = tmp_path / "must-not-exist.json"
    with pytest.raises(OrphanQuarantineError, match="orphan_scan_incomplete"):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )
    assert not backup_path.exists()
    assert not receipt_path.exists()

    exit_code = orphan_quarantine._main([str(database_path)])
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert output["status"] == "incomplete"


def test_manual_review_rows_are_never_deleted_and_make_apply_unsuccessful(
    tmp_path,
    capsys,
) -> None:
    database_path = tmp_path / "manual-review.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    _add_manual_review_rows(database_path)

    inspected = inspect_orphans(database_path, include_all_keys=True)
    assert inspected["status"] == "manual_review_required"
    assert inspected["manual_review_count"] == 3
    exported = export_evidence(database_path, evidence_path)
    assert exported["would_delete"] == 4
    assert exported["manual_review_count"] == 3

    result = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )

    assert result["status"] == "completed"
    assert result["outcome"] == "applied_with_remaining_issues"
    assert result["success"] is False
    assert result["deleted_count"] == 4
    assert result["post_integrity"]["manual_review_count"] == 3
    assert result["post_integrity"]["foreign_key_check"]["count"] == 0
    deleted_keys = {item["primary_key"] for item in result["deleted"]}
    assert "link-unsupported-kind" not in deleted_keys
    assert "link-source-project-mismatch" not in deleted_keys
    assert "link-empty-affected-id" not in deleted_keys
    with sqlite3.connect(database_path) as connection:
        remaining = {
            str(row[0])
            for row in connection.execute(
                "SELECT revision_link_id FROM snowflake_revision_links"
            )
        }
    assert {
        "link-unsupported-kind",
        "link-source-project-mismatch",
        "link-empty-affected-id",
    } <= remaining

    cli_exit = orphan_quarantine._main(
        [
            str(database_path),
            "--apply-evidence",
            str(evidence_path),
            "--confirm-sha256",
            exported["evidence_sha256"],
            "--backup",
            str(backup_path),
            "--receipt",
            str(receipt_path),
        ]
    )
    cli_output = json.loads(capsys.readouterr().out)
    assert cli_exit == 1
    assert cli_output["status"] == "completed"
    assert cli_output["success"] is False


def test_manual_disposition_cannot_be_relabelled_as_auto_delete(tmp_path) -> None:
    database_path = tmp_path / "classification-tamper.db"
    evidence_path = tmp_path / "evidence.jsonl"
    _make_orphan_database(database_path)
    _add_manual_review_rows(database_path)
    export_evidence(database_path, evidence_path)
    evidence = load_evidence(evidence_path)
    records = [dict(record) for record in evidence["records"]]
    target = next(
        record
        for record in records
        if record["primary_key"] == "link-unsupported-kind"
    )
    target["reasons"] = ["missing_story_project"]
    target["disposition"] = "auto_delete_eligible"
    payload = orphan_quarantine._jsonl_bytes(evidence["header"], records)
    evidence_path.write_bytes(payload)
    tampered = load_evidence(evidence_path)

    with pytest.raises(EvidenceConflictError, match="evidence_rows_changed=1"):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=tampered["evidence_sha256"],
            backup_path=tmp_path / "backup.db",
            receipt_path=tmp_path / "receipt.json",
        )
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            """
            SELECT COUNT(*) FROM snowflake_revision_links
            WHERE revision_link_id = 'link-unsupported-kind'
            """
        ).fetchone() == (1,)


def test_apply_only_deletes_exported_rows_and_reports_new_orphans(tmp_path) -> None:
    database_path = tmp_path / "orphan.db"
    evidence_path = tmp_path / "evidence.jsonl"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO llm_call_attempts VALUES
                ('attempt-new', 'call-new-missing', 0, 'failed', NULL, 'later')
            """
        )

    result = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=tmp_path / "backup.db",
        receipt_path=tmp_path / "receipt.json",
    )

    assert result["status"] == "completed"
    assert result["outcome"] == "applied_with_remaining_issues"
    assert result["success"] is False
    assert result["deleted_count"] == 4
    assert result["post_integrity"]["orphan_record_count"] == 1
    assert result["uncovered_active_orphans_before_apply"] == [
        {"table": "llm_call_attempts", "primary_key": "attempt-new"}
    ]


def test_post_apply_foreign_key_check_is_receipted_and_cli_returns_nonzero(
    tmp_path,
    capsys,
) -> None:
    database_path = tmp_path / "unknown-fk.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE unrelated_parents (parent_id TEXT PRIMARY KEY);
            CREATE TABLE unrelated_children (
                child_id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES unrelated_parents(parent_id)
            );
            INSERT INTO unrelated_children VALUES ('orphan-child', 'missing-parent');
            """
        )
    exported = export_evidence(database_path, evidence_path)

    exit_code = orphan_quarantine._main(
        [
            str(database_path),
            "--apply-evidence",
            str(evidence_path),
            "--confirm-sha256",
            exported["evidence_sha256"],
            "--backup",
            str(backup_path),
            "--receipt",
            str(receipt_path),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["status"] == "completed"
    assert output["outcome"] == "applied_with_remaining_issues"
    assert output["success"] is False
    assert output["post_integrity"]["orphan_record_count"] == 0
    assert output["post_integrity"]["foreign_key_check"]["count"] == 1
    persisted = load_receipt(receipt_path)
    assert persisted["post_integrity"]["foreign_key_check"]["count"] == 1


def test_apply_rolls_back_trigger_collateral_deletes(tmp_path) -> None:
    database_path = tmp_path / "trigger-collateral.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER trg_orphan_attempt_collateral
            AFTER DELETE ON llm_call_attempts
            WHEN OLD.attempt_id = 'attempt-orphan'
            BEGIN
                DELETE FROM llm_call_attempts
                WHERE attempt_id = 'attempt-valid';
            END
            """
        )
    exported = export_evidence(database_path, evidence_path)

    with pytest.raises(
        EvidenceConflictError,
        match="unexpected_database_delta_after_delete",
    ):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert load_receipt(receipt_path)["status"] == "prepared"
    with sqlite3.connect(database_path) as connection:
        remaining = {
            str(row[0])
            for row in connection.execute(
                "SELECT attempt_id FROM llm_call_attempts"
            )
        }
    assert remaining == {"attempt-valid", "attempt-orphan"}


def test_apply_refuses_schema_that_cannot_restore_deleted_rows(tmp_path) -> None:
    database_path = tmp_path / "insert-trigger-blocks-restore.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER trg_block_orphan_attempt_restore
            BEFORE INSERT ON llm_call_attempts
            WHEN NEW.attempt_id = 'attempt-orphan'
            BEGIN
                SELECT RAISE(ABORT, 'restore blocked by insert trigger');
            END
            """
        )
    exported = export_evidence(database_path, evidence_path)

    with pytest.raises(
        EvidenceConflictError,
        match="restore_round_trip_not_feasible",
    ):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert load_receipt(receipt_path)["status"] == "prepared"
    assert _active_count(database_path, "llm_call_attempts") == 2
    assert _active_count(database_path, "snowflake_revision_links") == 4


def test_commit_post_receipt_failure_reconciles_without_reapplying(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "post-commit-failure.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    original_replace = orphan_quarantine._replace_bytes_atomic
    injected = {"done": False}

    def fail_completed_receipt(target, payload):
        document = json.loads(payload.decode("utf-8"))
        if document.get("status") == "completed" and not injected["done"]:
            injected["done"] = True
            raise OSError("injected completed receipt replace failure")
        return original_replace(target, payload)

    monkeypatch.setattr(
        orphan_quarantine,
        "_replace_bytes_atomic",
        fail_completed_receipt,
    )
    with pytest.raises(OSError, match="injected completed receipt replace failure"):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert load_receipt(receipt_path)["status"] == "commit_ready"
    assert _active_count(database_path, "llm_call_attempts") == 1
    assert _active_count(database_path, "snowflake_revision_links") == 1

    competing_write = {"blocked": False}

    def verify_reconcile_holds_write_lock(target, payload):
        document = json.loads(payload.decode("utf-8"))
        if document.get("status") == "completed":
            try:
                with sqlite3.connect(database_path, timeout=0) as competing:
                    competing.execute(
                        "INSERT INTO story_projects VALUES ('racing-project')"
                    )
            except sqlite3.OperationalError as exc:
                assert "locked" in str(exc).lower()
                competing_write["blocked"] = True
            else:  # pragma: no cover - this is the regression being guarded
                pytest.fail("competing write entered during receipt reconciliation")
        return original_replace(target, payload)

    monkeypatch.setattr(
        orphan_quarantine,
        "_replace_bytes_atomic",
        verify_reconcile_holds_write_lock,
    )
    reconciled = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )

    assert reconciled["status"] == "completed"
    assert reconciled["outcome"] == "applied"
    assert reconciled["success"] is True
    assert reconciled["reconciled"] is True
    assert reconciled["reconciled_after_commit"] is True
    assert reconciled["deleted_count"] == 4
    assert competing_write["blocked"] is True


def test_post_commit_database_drift_cannot_publish_completed_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "post-commit-drift.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    original_commit = orphan_quarantine._commit_apply_transaction

    def commit_then_inject_valid_write(connection):
        original_commit(connection)
        with sqlite3.connect(database_path) as competing:
            competing.execute("INSERT INTO story_projects VALUES ('post-commit-project')")

    monkeypatch.setattr(
        orphan_quarantine,
        "_commit_apply_transaction",
        commit_then_inject_valid_write,
    )
    with pytest.raises(
        EvidenceConflictError,
        match="post_commit_state_changed_before_receipt",
    ):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert load_receipt(receipt_path)["status"] == "commit_ready"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM story_projects WHERE project_id = 'post-commit-project'"
        ).fetchone() == (1,)


def test_commit_ready_before_commit_failure_rolls_back_and_resumes(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "pre-commit-failure.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    original_commit = orphan_quarantine._commit_apply_transaction

    def fail_before_commit(_connection):
        raise RuntimeError("injected failure before commit")

    monkeypatch.setattr(
        orphan_quarantine,
        "_commit_apply_transaction",
        fail_before_commit,
    )
    with pytest.raises(RuntimeError, match="injected failure before commit"):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert load_receipt(receipt_path)["status"] == "commit_ready"
    assert _active_count(database_path, "llm_call_attempts") == 2
    assert _active_count(database_path, "snowflake_revision_links") == 4

    monkeypatch.setattr(
        orphan_quarantine,
        "_commit_apply_transaction",
        original_commit,
    )
    resumed = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )

    assert resumed["status"] == "completed"
    assert resumed["outcome"] == "applied"
    assert resumed["success"] is True
    assert resumed["resumed_from_status"] == "commit_ready"
    assert _active_count(database_path, "llm_call_attempts") == 1
    assert _active_count(database_path, "snowflake_revision_links") == 1


def test_backup_only_failure_window_recovers_with_same_artifact_paths(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "backup-only-window.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    original_write_new = orphan_quarantine._write_new_bytes_atomic
    injected = {"done": False}

    def fail_first_receipt_write(target, payload):
        if target == receipt_path.resolve() and not injected["done"]:
            injected["done"] = True
            raise OSError("injected prepared receipt write failure")
        return original_write_new(target, payload)

    monkeypatch.setattr(
        orphan_quarantine,
        "_write_new_bytes_atomic",
        fail_first_receipt_write,
    )
    with pytest.raises(OSError, match="injected prepared receipt write failure"):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert backup_path.exists()
    assert not receipt_path.exists()
    assert _active_count(database_path, "llm_call_attempts") == 2
    assert _active_count(database_path, "snowflake_revision_links") == 4

    monkeypatch.setattr(
        orphan_quarantine,
        "_write_new_bytes_atomic",
        original_write_new,
    )
    resumed = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )

    assert resumed["status"] == "completed"
    assert resumed["success"] is True
    assert resumed["recovered_from_backup_only"] is True
    assert resumed["resumed_from_status"] == "backup_only"
    assert _active_count(database_path, "llm_call_attempts") == 1
    assert _active_count(database_path, "snowflake_revision_links") == 1


def test_backup_publish_chmod_failure_cleans_owned_target_for_retry(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "backup-chmod-failure.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    original_chmod = orphan_quarantine.os.chmod
    injected = {"done": False}

    def fail_first_backup_chmod(path, mode):
        if Path(path) == backup_path.resolve() and not injected["done"]:
            injected["done"] = True
            raise OSError("injected backup chmod failure")
        return original_chmod(path, mode)

    monkeypatch.setattr(orphan_quarantine.os, "chmod", fail_first_backup_chmod)
    with pytest.raises(OSError, match="injected backup chmod failure"):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert not backup_path.exists()
    assert not receipt_path.exists()
    monkeypatch.setattr(orphan_quarantine.os, "chmod", original_chmod)
    retried = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    assert retried["success"] is True


def test_backup_post_link_flush_failure_cleans_owned_target_for_retry(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "backup-flush-failure.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    original_flush = orphan_quarantine._flush_published_path
    injected = {"done": False}

    def fail_first_backup_flush(path):
        if Path(path) == backup_path.resolve() and not injected["done"]:
            injected["done"] = True
            raise OSError("injected backup publish flush failure")
        return original_flush(path)

    monkeypatch.setattr(
        orphan_quarantine,
        "_flush_published_path",
        fail_first_backup_flush,
    )
    with pytest.raises(
        OrphanQuarantineError,
        match="atomic_no_clobber_publish_failed",
    ):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert not backup_path.exists()
    assert not receipt_path.exists()
    monkeypatch.setattr(
        orphan_quarantine,
        "_flush_published_path",
        original_flush,
    )
    retried = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    assert retried["success"] is True


def test_prepared_receipt_and_post_state_reconcile_after_power_loss(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "prepared-power-loss.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    original_write_new = orphan_quarantine._write_new_bytes_atomic
    captured: dict[str, bytes] = {}

    def capture_prepared_receipt(target, payload):
        document = json.loads(payload.decode("utf-8"))
        if document.get("status") == "prepared":
            captured["prepared"] = payload
        return original_write_new(target, payload)

    monkeypatch.setattr(
        orphan_quarantine,
        "_write_new_bytes_atomic",
        capture_prepared_receipt,
    )
    applied = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    assert applied["success"] is True
    receipt_path.write_bytes(captured["prepared"])

    reconciled = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )

    assert reconciled["status"] == "completed"
    assert reconciled["success"] is True
    assert reconciled["reconciled"] is True
    assert reconciled["reconciled_after_power_loss"] is True
    assert reconciled["deleted_count"] == 4
    assert reconciled["already_absent"] == []


def test_backup_only_and_post_state_rebuild_receipt_after_power_loss(
    tmp_path,
) -> None:
    database_path = tmp_path / "backup-only-post.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    applied = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    assert applied["success"] is True
    receipt_path.unlink()

    reconciled = apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )

    assert reconciled["status"] == "completed"
    assert reconciled["success"] is True
    assert reconciled["reconciled"] is True
    assert reconciled["reconciled_after_power_loss"] is True
    assert reconciled["recovered_from_backup_only"] is True
    assert reconciled["deleted_count"] == 4
    assert reconciled["already_absent"] == []


def test_apply_revalidates_backup_immediately_before_delete(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "backup-mutated-before-delete.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    original_execute = orphan_quarantine._execute_apply_transaction

    def mutate_backup_then_execute(connection, **kwargs):
        os.chmod(backup_path, stat.S_IREAD | stat.S_IWRITE)
        with sqlite3.connect(backup_path) as backup:
            backup.execute("INSERT INTO story_projects VALUES ('backup-tamper')")
        return original_execute(connection, **kwargs)

    monkeypatch.setattr(
        orphan_quarantine,
        "_execute_apply_transaction",
        mutate_backup_then_execute,
    )
    with pytest.raises(
        EvidenceConflictError,
        match="receipt_backup_(not_read_only|sha256_mismatch)",
    ):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_path,
            receipt_path=receipt_path,
        )

    assert _active_count(database_path, "llm_call_attempts") == 2
    assert _active_count(database_path, "snowflake_revision_links") == 4
    assert load_receipt(receipt_path)["status"] == "prepared"


def test_receipt_bound_restore_requires_confirmation_and_restores_backup(
    tmp_path,
) -> None:
    database_path = tmp_path / "restore.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    receipt = load_receipt(receipt_path)
    assert receipt["post_database_aggregate_sha256"]

    with pytest.raises(
        EvidenceValidationError,
        match="confirmed_receipt_sha256_mismatch",
    ):
        restore_from_receipt(
            database_path,
            receipt_path,
            confirm_receipt_sha256="0" * 64,
        )

    restored = restore_from_receipt(
        database_path,
        receipt_path,
        confirm_receipt_sha256=receipt["receipt_sha256"],
    )

    assert restored["status"] == "restored"
    assert restored["success"] is True
    assert restored["backup_sha256"] == hashlib.sha256(
        backup_path.read_bytes()
    ).hexdigest()
    assert _active_count(database_path, "llm_call_attempts") == 2
    assert _active_count(database_path, "snowflake_revision_links") == 4
    with sqlite3.connect(database_path) as connection:
        assert scan_orphans(connection)["record_count"] == 4


def test_receipt_bound_restore_refuses_database_drift_after_apply(tmp_path) -> None:
    database_path = tmp_path / "restore-drift.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    receipt = load_receipt(receipt_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("INSERT INTO story_projects VALUES ('post-apply-project')")

    with pytest.raises(
        EvidenceConflictError,
        match="restore_target_post_state_mismatch",
    ):
        restore_from_receipt(
            database_path,
            receipt_path,
            confirm_receipt_sha256=receipt["receipt_sha256"],
        )

    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM story_projects WHERE project_id = 'post-apply-project'"
        ).fetchone() == (1,)


def test_restore_commit_then_raise_reconciles_on_same_receipt(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "restore-commit-ambiguity.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    receipt = load_receipt(receipt_path)
    original_commit = orphan_quarantine._commit_restore_transaction

    def commit_then_raise(connection):
        original_commit(connection)
        raise OSError("injected failure after restore commit")

    monkeypatch.setattr(
        orphan_quarantine,
        "_commit_restore_transaction",
        commit_then_raise,
    )
    with pytest.raises(OSError, match="injected failure after restore commit"):
        restore_from_receipt(
            database_path,
            receipt_path,
            confirm_receipt_sha256=receipt["receipt_sha256"],
        )

    monkeypatch.setattr(
        orphan_quarantine,
        "_commit_restore_transaction",
        original_commit,
    )
    reconciled = restore_from_receipt(
        database_path,
        receipt_path,
        confirm_receipt_sha256=receipt["receipt_sha256"],
    )

    assert reconciled["status"] == "already_restored"
    assert reconciled["success"] is True
    assert reconciled["reconciled"] is True
    assert reconciled["restored_row_count"] == 0
    assert reconciled["verified_restored_row_count"] == 4
    assert _active_count(database_path, "llm_call_attempts") == 2
    assert _active_count(database_path, "snowflake_revision_links") == 4


def test_restore_recovers_hot_journal_after_process_crash(tmp_path) -> None:
    database_path = tmp_path / "restore-hot-journal.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    receipt = load_receipt(receipt_path)
    backend_root = Path(__file__).resolve().parents[1]
    crash_script = r"""
import os
import sys

sys.path.insert(0, sys.argv[1])
from novel_system.tools import orphan_quarantine

original_restore = orphan_quarantine._restore_deleted_rows

def restore_then_crash(connection, backup_path, deleted):
    original_restore(connection, backup_path, deleted)
    os._exit(97)

orphan_quarantine._restore_deleted_rows = restore_then_crash
orphan_quarantine.restore_from_receipt(
    sys.argv[2],
    sys.argv[3],
    confirm_receipt_sha256=sys.argv[4],
)
"""
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            crash_script,
            str(backend_root / "src"),
            str(database_path),
            str(receipt_path),
            receipt["receipt_sha256"],
        ],
        cwd=backend_root,
        check=False,
        timeout=30,
    )

    assert crashed.returncode == 97
    assert Path(f"{database_path}-journal").exists()

    restored = restore_from_receipt(
        database_path,
        receipt_path,
        confirm_receipt_sha256=receipt["receipt_sha256"],
    )

    assert restored["status"] == "restored"
    assert restored["success"] is True
    assert restored["restored_row_count"] == 4
    assert not Path(f"{database_path}-journal").exists()
    assert _active_count(database_path, "llm_call_attempts") == 2
    assert _active_count(database_path, "snowflake_revision_links") == 4


def test_restore_holds_exclusive_lock_until_deleted_rows_are_restored(
    tmp_path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "restore-lock.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    receipt = load_receipt(receipt_path)
    original_restore_rows = orphan_quarantine._restore_deleted_rows
    competing_write = {"blocked": False}

    def restore_while_competing(connection, bound_backup, deleted):
        try:
            with sqlite3.connect(database_path, timeout=0) as competing:
                competing.execute("INSERT INTO story_projects VALUES ('restore-race')")
        except sqlite3.OperationalError as exc:
            assert "locked" in str(exc).lower()
            competing_write["blocked"] = True
        else:  # pragma: no cover - this is the regression being guarded
            pytest.fail("competing write entered during exclusive restore")
        return original_restore_rows(connection, bound_backup, deleted)

    monkeypatch.setattr(
        orphan_quarantine,
        "_restore_deleted_rows",
        restore_while_competing,
    )
    restored = restore_from_receipt(
        database_path,
        receipt_path,
        confirm_receipt_sha256=receipt["receipt_sha256"],
    )

    assert restored["success"] is True
    assert restored["restored_row_count"] == 4
    assert competing_write["blocked"] is True
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM story_projects WHERE project_id = 'restore-race'"
        ).fetchone() == (0,)


def test_restore_refuses_schema_and_header_pragma_drift(tmp_path) -> None:
    database_path = tmp_path / "restore-metadata-drift.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    receipt = load_receipt(receipt_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE INDEX idx_story_projects_restore_drift ON story_projects(project_id)"
        )
        connection.execute("PRAGMA user_version=73")

    with pytest.raises(
        EvidenceConflictError,
        match="restore_target_(schema|post_state)_mismatch",
    ):
        restore_from_receipt(
            database_path,
            receipt_path,
            confirm_receipt_sha256=receipt["receipt_sha256"],
        )
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (73,)
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name=?",
            ("idx_story_projects_restore_drift",),
        ).fetchone() == (1,)


def test_apply_rejects_hardlink_alias_for_database_backup(tmp_path) -> None:
    database_path = tmp_path / "hardlink-source.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_alias = tmp_path / "hardlink-backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    os.link(database_path, backup_alias)
    before = hashlib.sha256(database_path.read_bytes()).hexdigest()

    with pytest.raises(
        OrphanQuarantineError,
        match="artifact_file_identity_collision",
    ):
        apply_evidence(
            database_path,
            evidence_path,
            confirm_sha256=exported["evidence_sha256"],
            backup_path=backup_alias,
            receipt_path=receipt_path,
        )

    assert os.path.samefile(database_path, backup_alias)
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == before
    assert not receipt_path.exists()


def test_atomic_new_file_publish_never_clobbers_racing_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    target = tmp_path / "no-clobber.json"
    original_link = os.link
    injected = {"done": False}

    def inject_competing_target(source, destination):
        if Path(destination) == target and not injected["done"]:
            injected["done"] = True
            target.write_bytes(b"competing-artifact")
        return original_link(source, destination)

    monkeypatch.setattr(orphan_quarantine.os, "link", inject_competing_target)
    with pytest.raises(OrphanQuarantineError, match="refusing_to_overwrite"):
        orphan_quarantine._write_new_bytes_atomic(target, b"tool-artifact")

    assert injected["done"] is True
    assert target.read_bytes() == b"competing-artifact"


def test_receipt_operation_lock_rejects_concurrent_owner(tmp_path) -> None:
    receipt_path = tmp_path / "shared-receipt.json"

    with orphan_quarantine._artifact_lock(receipt_path):
        with pytest.raises(
            OrphanQuarantineError,
            match="artifact_operation_lock_busy",
        ):
            with orphan_quarantine._artifact_lock(receipt_path):
                pytest.fail("second operation unexpectedly acquired receipt lock")


def test_receipt_bound_restore_cli(tmp_path, capsys) -> None:
    database_path = tmp_path / "restore-cli.db"
    evidence_path = tmp_path / "evidence.jsonl"
    backup_path = tmp_path / "backup.db"
    receipt_path = tmp_path / "receipt.json"
    _make_orphan_database(database_path)
    exported = export_evidence(database_path, evidence_path)
    apply_evidence(
        database_path,
        evidence_path,
        confirm_sha256=exported["evidence_sha256"],
        backup_path=backup_path,
        receipt_path=receipt_path,
    )
    receipt = load_receipt(receipt_path)

    exit_code = orphan_quarantine._main(
        [
            str(database_path),
            "--restore-receipt",
            str(receipt_path),
            "--confirm-receipt-sha256",
            receipt["receipt_sha256"],
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["status"] == "restored"
    assert output["success"] is True
    assert _active_count(database_path, "llm_call_attempts") == 2


def test_tampered_jsonl_is_refused_before_database_access(tmp_path) -> None:
    database_path = tmp_path / "orphan.db"
    evidence_path = tmp_path / "evidence.jsonl"
    _make_orphan_database(database_path)
    export_evidence(database_path, evidence_path)
    lines = evidence_path.read_text(encoding="utf-8").splitlines()
    orphan = json.loads(lines[1])
    orphan["row"]["error_text"] = "tampered"
    lines[1] = json.dumps(
        orphan, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    evidence_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(EvidenceValidationError, match="evidence_row_hash_mismatch"):
        load_evidence(evidence_path)


def test_cli_defaults_to_dry_run_and_does_not_create_files(tmp_path, capsys) -> None:
    database_path = tmp_path / "orphan.db"
    _make_orphan_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO llm_call_attempts VALUES (?, ?, 0, 'failed', NULL, 'now')
            """,
            [
                (f"attempt-bulk-{index:02d}", f"missing-call-{index:02d}")
                for index in range(25)
            ],
        )

    exit_code = orphan_quarantine._main([str(database_path)])
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert result["mode"] == "dry_run"
    assert result["status"] == "orphans_detected"
    assert result["would_delete"] == 0
    assert "orphan_keys" not in result
    assert result["record_count"] == 29
    assert len(result["orphan_key_sample"]) == 20
    assert result["orphan_keys_truncated"] is True
    assert not (tmp_path / "evidence.jsonl").exists()
    assert not (tmp_path / "backup.db").exists()
    assert not (tmp_path / "receipt.json").exists()

    list_exit_code = orphan_quarantine._main([str(database_path), "--list-keys"])
    listed = json.loads(capsys.readouterr().out)
    assert list_exit_code == 0
    assert len(listed["orphan_keys"]) == 29
