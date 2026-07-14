from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from novel_system.services.outcome_evidence import (
    EvidenceArtifact,
    EvidenceCommand,
    EvidenceGate,
    EvidenceProvenanceError,
    OutcomeEvidenceManifest,
    artifact_from_path,
    read_manifest,
    require_provenance,
    validate_c1b_gate_profile,
    validate_manifest_evidence,
    write_manifest,
)
from novel_system.tools.outcome_evidence import _main
from novel_system.tools.llm_accounting_audit import REQUIRED_COLUMNS


def _manifest(
    *,
    artifact: EvidenceArtifact | None = None,
    artifacts: list[EvidenceArtifact] | None = None,
    commands: list[EvidenceCommand] | None = None,
    gates: list[EvidenceGate] | None = None,
    config_hashes: dict[str, str] | None = None,
    model_routes: dict[str, object] | None = None,
    run_id: str = "c0-test",
    git_commit: str = "deadbeef",
    database_revision: str = "20260712_0064",
    provenance: str = "offline",
    created_at: str | None = None,
) -> OutcomeEvidenceManifest:
    payload: dict[str, object] = {
        "run_id": run_id,
        "git_commit": git_commit,
        "database_revision": database_revision,
        "config_hashes": config_hashes or {},
        "model_routes": model_routes or {},
        "provenance": provenance,
        "commands": (
            commands
            if commands is not None
            else [
                EvidenceCommand(
                    command="pytest",
                    exit_code=0,
                    expected_exit_codes=[0],
                    started_at="2026-07-13T00:00:00Z",
                    ended_at="2026-07-13T00:00:01Z",
                )
            ]
        ),
        "artifacts": (
            artifacts
            if artifacts is not None
            else [
                artifact
                or EvidenceArtifact(path="report.json", sha256="0" * 64)
            ]
        ),
        "gates": (
            gates
            if gates is not None
            else [EvidenceGate(code="DATABASE_HEAD_MATCH", passed=True)]
        ),
    }
    if created_at is not None:
        payload["created_at"] = created_at
    return OutcomeEvidenceManifest(**payload)


def _write_cli_manifest(
    tmp_path: Path,
    *,
    commands: list[EvidenceCommand] | None = None,
    gates: list[EvidenceGate] | None = None,
) -> tuple[Path, Path]:
    report_path = tmp_path / "report.json"
    report_path.write_text('{"ok":true}', encoding="utf-8")
    manifest_path = tmp_path / "outcome-evidence.json"
    write_manifest(
        _manifest(
            artifact=artifact_from_path(report_path, root=tmp_path),
            commands=commands,
            gates=gates,
        ),
        manifest_path,
    )
    return manifest_path, report_path


def _validation_errors_for_gates(
    tmp_path: Path,
    gates: list[EvidenceGate],
) -> list[str]:
    manifest_path, _ = _write_cli_manifest(tmp_path, gates=gates)
    return validate_manifest_evidence(read_manifest(manifest_path), tmp_path)


C0_REQUIRED_GATE_CODES = (
    "RUNTIME_PROCESS_CLEAR",
    "BACKUP_VERIFIED",
    "DRILL_MIGRATION_HEAD_MATCH",
    "ACTUAL_MIGRATION_HEAD_MATCH",
    "SCHEMA_READY",
    "ORPHANS_ZERO",
    "FOCUSED_REGRESSION_PASS",
    "C0_REGRESSION_PASS",
)


def _complete_c0_gates() -> list[EvidenceGate]:
    ready_preflight = {
        "ready": True,
        "revision": "20260712_0064",
        "integrity": "ok",
    }
    schema_preflight = {
        "ready": True,
        "missing_tables": [],
        "missing_columns": {},
    }
    clean_orphan_report = {"clean": True, "total_orphans": 0}
    return [
        EvidenceGate(
            code="RUNTIME_PROCESS_CLEAR",
            passed=True,
            details={"report": {"match_count": 0}},
        ),
        EvidenceGate(
            code="BACKUP_VERIFIED",
            passed=True,
            details={
                "verify": {
                    "ok": True,
                    "integrity": "ok",
                    "checksum_ok": True,
                },
                "pre_migration_backup_preflight": {
                    "integrity": "ok",
                    "revision": "20260712_0064",
                },
            },
        ),
        EvidenceGate(
            code="DRILL_MIGRATION_HEAD_MATCH",
            passed=True,
            details={"preflight": ready_preflight},
        ),
        EvidenceGate(
            code="ACTUAL_MIGRATION_HEAD_MATCH",
            passed=True,
            details={"actual_preflight": ready_preflight},
        ),
        EvidenceGate(
            code="SCHEMA_READY",
            passed=True,
            details={
                "drill_preflight": schema_preflight,
                "actual_preflight": schema_preflight,
            },
        ),
        EvidenceGate(
            code="ORPHANS_ZERO",
            passed=True,
            details={
                "drill_report": clean_orphan_report,
                "actual_report": clean_orphan_report,
            },
        ),
        EvidenceGate(
            code="FOCUSED_REGRESSION_PASS",
            passed=True,
            details={"report": {"passed": 7, "failed": 0}},
        ),
        EvidenceGate(
            code="C0_REGRESSION_PASS",
            passed=True,
            details={"report": {"passed": 14, "failed": 0}},
        ),
    ]


C1B_REQUIRED_GATE_CODES = (
    "ALL_PRODUCTION_LLM_OUTLETS_ACCOUNTED",
    "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED",
    "MISSING_USAGE_ESTIMATED",
    "FAILED_CALLS_CHARGED",
    "RETRY_AND_DEGRADE_BUDGETED",
    "ATOMIC_RESERVATION_NO_OVERSPEND",
    "BASELINE_CALLS_BUDGETED",
    "LIFECYCLE_BUDGET_NOT_RESET",
    "CHECKPOINT_RESUME_NO_REPLAY",
    "QUEUED_CANCEL_NO_CALL",
    "RUNNING_CANCEL_STOPS_NEXT_NODE",
    "CANCEL_CAS_LINEARIZABLE",
    "CANCEL_PRESERVES_DRAFT_AND_LEDGER",
)

C1B_REQUIRED_ARTIFACT_PATHS = (
    "process-scan.json",
    "database-before-0065.db",
    "database-before-0065.db.meta.json",
    "drill-preflight.json",
    "migration-drill-accounting.json",
    "migration-focused.junit.xml",
    "actual-preflight-after.json",
    "actual-accounting.json",
    "llm-outlet-inventory.json",
    "c1b-gates.junit.xml",
    "backend-full.junit.xml",
    "frontend.junit.xml",
    "frontend-build.log",
)

C1B_GATE_TEST_SELECTORS = {
    "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED": (
        "test_online_wrapper_forwards_attempt_hook_and_is_fully_accounted",
        "test_transport_retry_aggregates_each_physical_attempt_exactly_once",
        "test_missing_text_degrade_uses_new_larger_reservation_and_aggregates_actual_usage",
        "test_structured_degrade_recomputes_reservation_for_rewritten_messages",
        "test_responses_to_chat_degrade_has_a_distinct_durable_attempt_kind",
        "test_provider_failure_persists_failed_attempt_and_parent_with_conservative_charge",
        "test_unexpected_post_exception_settles_accounting_without_reservation_leak",
    ),
    "MISSING_USAGE_ESTIMATED": (
        "test_real_client_missing_raw_usage_is_estimated_and_never_charged_as_zero",
        "test_missing_partial_inconsistent_or_invalid_usage_falls_back_conservatively",
    ),
    "FAILED_CALLS_CHARGED": (
        "test_provider_failure_persists_failed_attempt_and_parent_with_conservative_charge",
        "test_unexpected_post_exception_settles_accounting_without_reservation_leak",
    ),
    "RETRY_AND_DEGRADE_BUDGETED": (
        "test_transport_retry_aggregates_each_physical_attempt_exactly_once",
        "test_llm_client_attempt_hook_wraps_response_parse_retry",
        "test_missing_text_degrade_uses_new_larger_reservation_and_aggregates_actual_usage",
    ),
    "ATOMIC_RESERVATION_NO_OVERSPEND": (
        "test_scene_budget_fence_allows_one_inflight_post_and_loser_retries_after_settlement",
        "test_concurrent_same_execution_step_has_one_parent_and_never_double_posts",
        "test_public_scene_budget_initialization_creates_missing_state_once_under_two_sessions",
    ),
    "BASELINE_CALLS_BUDGETED": (
        "test_scene_online_call_initializes_missing_budget_before_parent_and_dispatch",
        "test_null_scene_token_budget_is_initialized_before_online_attempt",
        "test_missing_scene_run_state_is_initialized_before_online_attempt",
    ),
    "LIFECYCLE_BUDGET_NOT_RESET": (
        "test_rerun_accumulates_and_never_resets",
        "test_prepare_state_for_rerun_preserves_all_lifecycle_accounting_counters",
    ),
    "CHECKPOINT_RESUME_NO_REPLAY": (
        "test_same_execution_resumes_after_last_durable_checkpoint",
        "test_committed_neutral_and_style_checkpoint_resume_without_new_call_or_charge",
    ),
    "QUEUED_CANCEL_NO_CALL": (
        "test_queued_cancel_is_terminal_idempotent_and_fully_audited",
        "test_cancel_before_next_reservation_makes_zero_provider_calls",
    ),
    "RUNNING_CANCEL_STOPS_NEXT_NODE": (
        "test_running_cancel_only_requests_and_does_not_clear_owner_or_active_lock",
        "test_running_cancel_settles_current_call_preserves_product_and_blocks_next",
    ),
    "CANCEL_CAS_LINEARIZABLE": (
        "test_reservation_claim_and_cancel_start_on_barrier_have_one_linearized_outcome",
        "test_claim_and_cancel_race_is_linearized_by_database_cas",
    ),
    "CANCEL_PRESERVES_DRAFT_AND_LEDGER": (
        "test_author_cancel_preserves_accounting_hard_checkpoint_fence",
        "test_running_cancel_settles_current_call_preserves_product_and_blocks_next",
    ),
}


def _complete_c1b_gates() -> list[EvidenceGate]:
    specifications = {
        "ALL_PRODUCTION_LLM_OUTLETS_ACCOUNTED": {
            "production_outlets": 8,
            "accounted_outlets": 8,
            "unaccounted_outlets": 0,
        },
        "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED": {
            "physical_attempts": 7,
            "accounted_attempts": 7,
            "unaccounted_attempts": 0,
        },
        "MISSING_USAGE_ESTIMATED": {
            "missing_usage_attempts": 2,
            "estimated_usage_attempts": 2,
            "unestimated_usage_attempts": 0,
        },
        "FAILED_CALLS_CHARGED": {
            "failed_attempts": 2,
            "charged_failed_attempts": 2,
            "zero_charge_failed_attempts": 0,
        },
        "RETRY_AND_DEGRADE_BUDGETED": {
            "retry_attempts": 2,
            "degrade_attempts": 1,
            "unbudgeted_attempts": 0,
        },
        "ATOMIC_RESERVATION_NO_OVERSPEND": {
            "reservation_cases": 3,
            "overspend_violations": 0,
        },
        "BASELINE_CALLS_BUDGETED": {
            "baseline_calls": 3,
            "unbudgeted_baseline_calls": 0,
        },
        "LIFECYCLE_BUDGET_NOT_RESET": {
            "lifecycle_cases": 2,
            "budget_reset_violations": 0,
        },
        "CHECKPOINT_RESUME_NO_REPLAY": {
            "resume_cases": 2,
            "replayed_completed_nodes": 0,
        },
        "QUEUED_CANCEL_NO_CALL": {
            "queued_cancel_cases": 2,
            "provider_calls_after_cancel": 0,
        },
        "RUNNING_CANCEL_STOPS_NEXT_NODE": {
            "running_cancel_cases": 2,
            "next_nodes_started_after_cancel": 0,
        },
        "CANCEL_CAS_LINEARIZABLE": {
            "cancel_race_cases": 2,
            "linearizability_violations": 0,
        },
        "CANCEL_PRESERVES_DRAFT_AND_LEDGER": {
            "cancellation_cases": 2,
            "lost_drafts": 0,
            "lost_ledger_rows": 0,
        },
    }
    gates: list[EvidenceGate] = []
    for code, counts in specifications.items():
        if code in C1B_GATE_TEST_SELECTORS:
            counts["evidence_cases"] = len(C1B_GATE_TEST_SELECTORS[code])
        details: dict[str, object] = {
            "counts": counts,
            "artifact_refs": [
                "llm-outlet-inventory.json"
                if code == "ALL_PRODUCTION_LLM_OUTLETS_ACCOUNTED"
                else "c1b-gates.junit.xml"
            ],
        }
        if code == "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED":
            counts["legacy_unreconstructable_count"] = 51
            details["enforced_for_new_calls"] = True
        gates.append(EvidenceGate(code=code, passed=True, details=details))
    return gates


def _c1b_accounting_audit_payload(
    database_path: str,
) -> dict[str, object]:
    return {
        "schema": "llm-accounting-audit-v1",
        "database": {
            "path": database_path,
            "read_only": True,
            "revision": "20260713_0065",
        },
        "row_counts": {
            "llm_calls": 51,
            "llm_call_attempts": 7,
            "scene_run_states": 1,
        },
        "tables": {
            table: {
                "present": True,
                "columns": list(REQUIRED_COLUMNS[table]),
                "missing_required_columns": [],
            }
            for table in ("llm_calls", "llm_call_attempts", "scene_run_states")
        },
        "integrity": {
            "scope_missing_or_blank": 0,
            "negative_token_rows": {"llm_calls": 0, "llm_call_attempts": 0},
            "stuck_reserved": {"llm_calls": 0, "llm_call_attempts": 0},
            "attempt_orphans": 0,
        },
        "status_counts": {
            "llm_calls": {"<null>": 51},
            "llm_call_attempts": {"settled": 5, "failed": 2},
        },
        "usage_provenance": {
            "llm_calls": {"actual": 0, "estimated": 0, "unknown": 51},
            "llm_call_attempts": {
                "actual": 5,
                "estimated": 2,
                "unknown": 0,
            },
        },
        "legacy_unreconstructable": {
            "calls_missing_accounting_status": 51,
            "calls_missing_usage_provenance": 51,
            "calls_without_attempt_ledger": 51,
            "total_unique_calls": 51,
        },
    }


def _c1b_junit_payload(relative_path: str) -> bytes:
    if relative_path == "c1b-gates.junit.xml":
        selectors = sorted(
            {
                selector
                for gate_selectors in C1B_GATE_TEST_SELECTORS.values()
                for selector in gate_selectors
            }
        )
        testcases = "".join(
            f'<testcase classname="c1b" name="{selector}" />'
            for selector in selectors
        )
        return (
            f'<testsuites tests="{len(selectors)}" failures="0" errors="0" '
            f'skipped="0"><testsuite name="c1b">{testcases}</testsuite>'
            "</testsuites>"
        ).encode()
    if relative_path == "backend-full.junit.xml":
        passed = "".join(
            f'<testcase classname="backend" name="test_backend_pass_{index}" />'
            for index in range(1000)
        )
        return (
            '<testsuite name="backend" tests="1001" failures="0" errors="0" '
            f'skipped="1">{passed}<testcase '
            'classname="tests.test_consistency_validation_realistic" '
            'name="test_suspense_pov_no_early_action_release_gate">'
            '<skipped type="pytest.skip" message="悬疑 POV LLM 对照属 §9.3 '
            '发布门 lane，需真实 LLM 额度；离线跳过（golden 覆盖逻辑门）" />'
            "</testcase></testsuite>"
        ).encode()
    if relative_path == "migration-focused.junit.xml":
        return (
            '<testsuite name="migration" tests="3" failures="0" errors="0">'
            '<testcase name="test_metadata_isolation" />'
            '<testcase name="test_generation_persistence" />'
            '<testcase name="test_database_preflight" /></testsuite>'
        ).encode()
    frontend = "".join(
        f'<testcase classname="frontend" name="frontend test {index}" />'
        for index in range(122)
    )
    return (
        '<testsuites tests="122" failures="0" errors="0"><testsuite '
        f'name="frontend" tests="122" failures="0" errors="0">{frontend}'
        "</testsuite></testsuites>"
    ).encode()


def _write_c1b_artifact(
    tmp_path: Path,
    relative_path: str,
    index: int,
) -> Path:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if relative_path == "database-before-0065.db":
        path.unlink(missing_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute(
                "CREATE TABLE alembic_version (version_num TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO alembic_version VALUES ('20260712_0064')"
            )
            connection.executescript(
                """
                CREATE TABLE evaluation_experiments (id INTEGER PRIMARY KEY);
                CREATE TABLE evaluation_pairs (id INTEGER PRIMARY KEY);
                CREATE TABLE evaluation_votes (id INTEGER PRIMARY KEY);
                CREATE TABLE scene_run_states (
                    id INTEGER PRIMARY KEY,
                    latest_valid_draft_row_id INTEGER,
                    run_policy TEXT,
                    scene_token_budget INTEGER,
                    scene_tokens_used INTEGER
                );
                CREATE TABLE evidence_padding (payload BLOB);
                INSERT INTO evidence_padding VALUES (zeroblob(1100000));
                """
            )
            connection.commit()
        finally:
            connection.close()
        return path
    if relative_path == "database-before-0065.db.meta.json":
        database_path = tmp_path / "database-before-0065.db"
        if database_path.exists():
            connection = sqlite3.connect(database_path)
            try:
                page_count = int(
                    connection.execute("PRAGMA page_count").fetchone()[0]
                )
            finally:
                connection.close()
            checksum = hashlib.sha256(database_path.read_bytes()).hexdigest()
        else:
            page_count = 1
            checksum = "0" * 64
        payload: object = {
            "source": r"E:\codex\xiaoshuo\codex\backend\novel_system.db",
            "checksum": checksum,
            "page_count": page_count,
            "integrity": "ok",
            "created_at": "2026-07-13T00:00:00Z",
            "tool": "db_backup.v1",
        }
    elif relative_path == "process-scan.json":
        payload = {
            "captured_at_utc": "2026-07-13T00:00:00Z",
            "actual_database": (
                r"E:\codex\xiaoshuo\codex\backend\novel_system.db"
            ),
            "wal_size_bytes": 0,
            "writer_matches": [],
            "listening_connections": [],
        }
    elif relative_path in {
        "drill-preflight.json",
        "actual-preflight-after.json",
    }:
        database_path = (
            r"C:\evidence\migration-drill.db"
            if relative_path == "drill-preflight.json"
            else r"E:\codex\xiaoshuo\codex\backend\novel_system.db"
        )
        payload = {
            "path": database_path,
            "ready": True,
            "integrity": "ok",
            "revision": "20260713_0065",
            "expected_revision": "20260713_0065",
            "expected_revision_canonical": "20260713_0065",
            "foreign_keys": 0,
            "missing_tables": [],
            "missing_columns": {},
            "schema_errors": [],
            "llm_call_attempt_orphan_count": 0,
        }
    elif relative_path in {
        "migration-drill-accounting.json",
        "actual-accounting.json",
    }:
        database_path = (
            r"C:\evidence\migration-drill.db"
            if relative_path == "migration-drill-accounting.json"
            else r"E:\codex\xiaoshuo\codex\backend\novel_system.db"
        )
        payload = _c1b_accounting_audit_payload(database_path)
    elif relative_path == "llm-outlet-inventory.json":
        payload = {
            "schema": "llm-outlet-inventory-v1",
            "source_root": r"C:\workspace\backend\src\novel_system",
            "summary": {
                "application_outlets": 8,
                "unified": 8,
                "unaccounted": 0,
            },
            "outlets": [
                {
                    "identity": f"outlet-{outlet}",
                    "path": f"module_{outlet}.py",
                    "qualname": f"outlet_{outlet}",
                    "line": outlet + 1,
                    "kind": "generate",
                    "expression": "client.generate()",
                    "unified": True,
                }
                for outlet in range(8)
            ],
        }
    elif relative_path.endswith(".junit.xml"):
        path.write_bytes(_c1b_junit_payload(relative_path))
        return path
    elif relative_path == "frontend-build.log":
        path.write_bytes(
            b"vite v6.1.0 building for production...\n"
            b"42 modules transformed.\nbuilt in 1.23s\n"
        )
        return path
    else:
        payload = {"artifact": index, "path": relative_path}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _complete_c1b_commands() -> list[EvidenceCommand]:
    command_strings = [
        "python -m novel_system.tools.db_backup --backup actual "
        "database-before-0065.db",
        "python -m alembic upgrade head > drill-alembic.log",
        "python -m alembic upgrade head > actual-alembic.log",
        "python -m novel_system.tools.database_preflight drill "
        "--output drill-preflight.json",
        "python -m novel_system.tools.llm_accounting_audit drill "
        "--output migration-drill-accounting.json",
        "pytest migration --junitxml=migration-focused.junit.xml",
        "python -m novel_system.tools.database_preflight actual "
        "--output actual-preflight-after.json",
        "python -m novel_system.tools.llm_accounting_audit actual "
        "--output actual-accounting.json",
        "python -m novel_system.tools.llm_outlet_inventory "
        "--output llm-outlet-inventory.json",
        "pytest c1b --junitxml=c1b-gates.junit.xml",
        "pytest tests --junitxml=backend-full.junit.xml",
        "npm test --outputFile=frontend.junit.xml",
        "npm run build > frontend-build.log",
    ]
    return [
        EvidenceCommand(
            command=command,
            exit_code=0,
            expected_exit_codes=[0],
            started_at="2026-07-13T00:00:00Z",
            ended_at="2026-07-13T00:00:01Z",
        )
        for command in command_strings
    ]


def _write_c1b_manifest(
    tmp_path: Path,
    *,
    gates: list[EvidenceGate] | None = None,
    artifact_paths: tuple[str, ...] = C1B_REQUIRED_ARTIFACT_PATHS,
    git_commit: str = "a" * 40,
    database_revision: str = "20260713_0065",
    provenance: str = "offline",
    created_at: str = "2026-07-13T00:00:02Z",
    commands: list[EvidenceCommand] | None = None,
) -> tuple[Path, list[Path]]:
    artifacts: list[EvidenceArtifact] = []
    created_paths: list[Path] = []
    for index, relative_path in enumerate(artifact_paths):
        path = _write_c1b_artifact(tmp_path, relative_path, index)
        payload = path.read_bytes()
        artifacts.append(
            EvidenceArtifact.model_validate(
                {
                    "path": relative_path,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
            )
        )
        created_paths.append(path)
    manifest = _manifest(
        artifacts=artifacts,
        commands=commands if commands is not None else _complete_c1b_commands(),
        gates=gates if gates is not None else _complete_c1b_gates(),
        config_hashes={
            "models.yaml": "1" * 64,
            "prompts.yaml": "2" * 64,
            "pricing.yaml": "3" * 64,
        },
        run_id="20260713-c1b-test",
        git_commit=git_commit,
        database_revision=database_revision,
        provenance=provenance,
        created_at=created_at,
    )
    manifest_path = tmp_path / "c1b-manifest.json"
    write_manifest(manifest, manifest_path)
    return manifest_path, created_paths


def test_manifest_round_trip_hashes_artifact(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text('{"ok":true}', encoding="utf-8")
    artifact = artifact_from_path(report_path, root=tmp_path)
    manifest = _manifest(artifact=artifact)
    manifest_path = tmp_path / "outcome-evidence.json"

    write_manifest(manifest, manifest_path)
    restored = read_manifest(manifest_path)
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert restored == manifest
    assert restored.artifacts[0].path == "report.json"
    assert len(restored.artifacts[0].sha256) == 64
    assert raw_manifest["schema"] == "outcome-evidence-v1"
    assert raw_manifest["commands"][0]["expected_exit_codes"] == [0]
    assert "schema_version" not in raw_manifest


def test_manifest_round_trip_preserves_nested_model_routes(tmp_path: Path) -> None:
    model_routes = {
        "writer": {
            "provider": "x",
            "model": "y",
        }
    }
    manifest = _manifest(model_routes=model_routes)
    manifest_path = tmp_path / "outcome-evidence.json"

    write_manifest(manifest, manifest_path)

    assert read_manifest(manifest_path).model_routes == model_routes


def test_write_manifest_creates_missing_parent_directories(tmp_path: Path) -> None:
    manifest = _manifest()
    manifest_path = tmp_path / "new" / "nested" / "outcome-evidence.json"

    write_manifest(manifest, manifest_path)

    assert read_manifest(manifest_path) == manifest


def test_manifest_rejects_duplicate_gate_codes() -> None:
    with pytest.raises(ValueError, match="duplicate gate code"):
        _manifest(
            gates=[
                EvidenceGate(code="SAME", passed=True),
                EvidenceGate(code="SAME", passed=False),
            ]
        )


def test_offline_manifest_cannot_satisfy_human_gate() -> None:
    with pytest.raises(EvidenceProvenanceError):
        require_provenance(_manifest(), {"human"})


def test_validate_command_rejects_missing_required_provenance(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_cli_manifest(tmp_path)

    assert _main(
        ["validate", str(manifest_path), "--require-provenance", "human"]
    ) == 1


def test_validate_command_accepts_complete_offline_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_cli_manifest(tmp_path)

    result = _main(
        ["validate", str(manifest_path), "--require-provenance", "offline"]
    )
    captured = capsys.readouterr()

    assert result == 0
    assert json.loads(captured.out) == {"valid": True, "run_id": "c0-test"}
    assert captured.err == ""


def test_validate_command_rejects_manifest_without_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = _manifest()
    manifest.artifacts.clear()
    manifest_path = tmp_path / "outcome-evidence.json"
    write_manifest(manifest, manifest_path)

    result = _main(["validate", str(manifest_path)])
    captured = capsys.readouterr()

    assert result == 1
    assert "artifact" in captured.err.lower()


def test_validate_command_rejects_tampered_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, report_path = _write_cli_manifest(tmp_path)
    report_path.write_text('{"ok":false}', encoding="utf-8")

    result = _main(["validate", str(manifest_path)])
    captured = capsys.readouterr()

    assert result == 1
    assert "sha256" in captured.err.lower()


def test_validate_command_rejects_unexpected_command_exit_code(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_cli_manifest(
        tmp_path,
        commands=[
            EvidenceCommand(
                command="pytest",
                exit_code=1,
                expected_exit_codes=[0],
                started_at="2026-07-13T00:00:00Z",
                ended_at="2026-07-13T00:00:01Z",
            )
        ],
    )

    assert _main(["validate", str(manifest_path)]) == 1


def test_validate_command_rejects_failed_gate(tmp_path: Path) -> None:
    manifest_path, _ = _write_cli_manifest(
        tmp_path,
        gates=[EvidenceGate(code="DATABASE_HEAD_MATCH", passed=False)],
    )

    assert _main(["validate", str(manifest_path)]) == 1


def test_validate_manifest_rejects_focused_gate_with_invalid_counts(
    tmp_path: Path,
) -> None:
    errors = _validation_errors_for_gates(
        tmp_path,
        [
            EvidenceGate(
                code="FOCUSED_REGRESSION_PASS",
                passed=True,
                details={"report": {"passed": 0, "failed": 999}},
            )
        ],
    )

    assert any("FOCUSED_REGRESSION_PASS" in error for error in errors)


def test_validate_manifest_rejects_runtime_gate_with_process_matches(
    tmp_path: Path,
) -> None:
    errors = _validation_errors_for_gates(
        tmp_path,
        [
            EvidenceGate(
                code="RUNTIME_PROCESS_CLEAR",
                passed=True,
                details={"report": {"match_count": 1}},
            )
        ],
    )

    assert any("RUNTIME_PROCESS_CLEAR" in error for error in errors)


@pytest.mark.parametrize(
    "actual_preflight",
    [
        {
            "ready": False,
            "revision": "20260712_0064",
            "integrity": "ok",
        },
        {"ready": True, "revision": "wrong", "integrity": "ok"},
    ],
    ids=["not-ready", "wrong-revision"],
)
def test_validate_manifest_rejects_inconsistent_actual_migration_gate(
    tmp_path: Path,
    actual_preflight: dict[str, object],
) -> None:
    errors = _validation_errors_for_gates(
        tmp_path,
        [
            EvidenceGate(
                code="ACTUAL_MIGRATION_HEAD_MATCH",
                passed=True,
                details={"actual_preflight": actual_preflight},
            )
        ],
    )

    assert any("ACTUAL_MIGRATION_HEAD_MATCH" in error for error in errors)


def test_validate_manifest_accepts_complete_known_c0_gate_evidence(
    tmp_path: Path,
) -> None:
    errors = _validation_errors_for_gates(
        tmp_path,
        _complete_c0_gates(),
    )

    assert errors == []


def test_validate_manifest_accepts_unknown_future_gate_evidence(
    tmp_path: Path,
) -> None:
    errors = _validation_errors_for_gates(
        tmp_path,
        [
            EvidenceGate(
                code="C1_FUTURE_GATE",
                passed=True,
                details={"future": {"shape": "is-compatible"}},
            )
        ],
    )

    assert errors == []


@pytest.mark.parametrize("missing_code", C0_REQUIRED_GATE_CODES)
def test_validate_c0_profile_requires_every_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing_code: str,
) -> None:
    gates = [gate for gate in _complete_c0_gates() if gate.code != missing_code]
    manifest_path, _ = _write_cli_manifest(tmp_path, gates=gates)

    result = _main(["validate", str(manifest_path), "--profile", "c0"])
    captured = capsys.readouterr()

    assert result == 1
    assert missing_code in captured.err


def test_validate_c0_profile_lists_all_missing_gates_for_unknown_only_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_cli_manifest(
        tmp_path,
        gates=[EvidenceGate(code="C1_FUTURE_GATE", passed=True)],
    )

    result = _main(["validate", str(manifest_path), "--profile", "c0"])
    captured = capsys.readouterr()

    assert result == 1
    for required_code in C0_REQUIRED_GATE_CODES:
        assert required_code in captured.err


@pytest.mark.parametrize("include_unknown_gate", [False, True])
def test_validate_c0_profile_accepts_complete_required_gates(
    tmp_path: Path,
    include_unknown_gate: bool,
) -> None:
    gates = _complete_c0_gates()
    if include_unknown_gate:
        gates.append(EvidenceGate(code="C1_FUTURE_GATE", passed=True))
    manifest_path, _ = _write_cli_manifest(tmp_path, gates=gates)

    assert _main(["validate", str(manifest_path), "--profile", "c0"]) == 0


def test_validate_without_profile_accepts_unknown_only_manifest(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_cli_manifest(
        tmp_path,
        gates=[EvidenceGate(code="C1_FUTURE_GATE", passed=True)],
    )

    assert _main(["validate", str(manifest_path)]) == 0


def test_validate_help_documents_available_profiles(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        _main(["validate", "--help"])

    captured = capsys.readouterr()
    assert raised.value.code == 0
    assert "--profile {c0,c1b}" in captured.out


def test_validate_command_rejects_missing_command_timestamps(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_cli_manifest(
        tmp_path,
        commands=[
            EvidenceCommand(
                command="pytest",
                exit_code=0,
                expected_exit_codes=[0],
            )
        ],
    )

    assert _main(["validate", str(manifest_path)]) == 1


def test_validate_command_reports_damaged_json_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "outcome-evidence.json"
    manifest_path.write_text("{not-json", encoding="utf-8")

    result = _main(["validate", str(manifest_path)])
    captured = capsys.readouterr()

    assert result == 1
    assert json.loads(captured.err)["valid"] is False
    assert "traceback" not in captured.err.lower()


def _read_raw_manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_raw_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _rehash_manifest_artifact(
    manifest_path: Path,
    artifact_root: Path,
    relative_path: str,
) -> None:
    raw = _read_raw_manifest(manifest_path)
    payload = (artifact_root / relative_path).read_bytes()
    artifact = next(
        item for item in raw["artifacts"] if item["path"] == relative_path
    )
    artifact["sha256"] = hashlib.sha256(payload).hexdigest()
    artifact["size_bytes"] = len(payload)
    _write_raw_manifest(manifest_path, raw)


def _validate_c1b(
    manifest_path: Path,
    artifact_root: Path,
    *,
    require_offline: bool = False,
) -> int:
    arguments = [
        "validate",
        str(manifest_path),
        "--profile",
        "c1b",
        "--artifact-root",
        str(artifact_root),
    ]
    if require_offline:
        arguments.extend(["--require-provenance", "offline"])
    return _main(arguments)


def test_validate_c1b_profile_accepts_complete_read_only_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, artifact_paths = _write_c1b_manifest(tmp_path)
    observed_paths = [manifest_path, *artifact_paths]
    snapshots = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in observed_paths
    }

    result = _validate_c1b(
        manifest_path,
        tmp_path,
        require_offline=True,
    )
    captured = capsys.readouterr()

    assert result == 0
    assert json.loads(captured.out) == {
        "valid": True,
        "run_id": "20260713-c1b-test",
        "profile": "c1b",
        "conclusion": "C1B_OFFLINE_EVIDENCE_VALIDATED",
    }
    assert captured.err == ""
    assert snapshots == {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in observed_paths
    }


@pytest.mark.parametrize(
    ("relative_path", "mutate", "expected_error"),
    [
        (
            "process-scan.json",
            lambda payload: payload.update(
                {"writer_matches": [{"process_id": 123}]}
            ),
            "writer_matches",
        ),
        (
            "process-scan.json",
            lambda payload: payload.update(
                {"captured_at_utc": "2000-01-01T00:00:00Z"}
            ),
            "5 minutes",
        ),
        (
            "drill-preflight.json",
            lambda payload: payload.update({"ready": False}),
            "ready",
        ),
        (
            "actual-accounting.json",
            lambda payload: payload["integrity"]["negative_token_rows"].update(
                {"llm_calls": 1}
            ),
            "negative_token_rows",
        ),
        (
            "llm-outlet-inventory.json",
            lambda payload: payload["summary"].update({"unaccounted": 1}),
            "outlet counts",
        ),
        (
            "llm-outlet-inventory.json",
            lambda payload: payload.update({"source_root": "C:/temp/fake"}),
            "source_root",
        ),
    ],
)
def test_validate_c1b_profile_recomputes_structured_json_artifacts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    relative_path: str,
    mutate: object,
    expected_error: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    artifact_path = tmp_path / relative_path
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    mutate(payload)  # type: ignore[operator]
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _rehash_manifest_artifact(manifest_path, tmp_path, relative_path)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert expected_error in captured.err


def test_validate_c1b_profile_rejects_arbitrary_text_with_matching_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    inventory_path = tmp_path / "llm-outlet-inventory.json"
    inventory_path.write_text("arbitrary evidence", encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "llm-outlet-inventory.json",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "invalid JSON" in captured.err


def test_validate_c1b_profile_rejects_failed_junit_with_matching_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    junit_path = tmp_path / "c1b-gates.junit.xml"
    payload = junit_path.read_text(encoding="utf-8").replace(
        "</testcase>",
        "<failure>failed</failure></testcase>",
        1,
    )
    if "</testcase>" not in junit_path.read_text(encoding="utf-8"):
        payload = payload.replace(" />", "><failure>failed</failure></testcase>", 1)
    junit_path.write_text(payload, encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "c1b-gates.junit.xml",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "failed/error tests" in captured.err


def test_validate_c1b_profile_rejects_unapproved_backend_skip_with_matching_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    junit_path = tmp_path / "backend-full.junit.xml"
    payload = junit_path.read_text(encoding="utf-8").replace(
        "test_suspense_pov_no_early_action_release_gate",
        "test_arbitrary_critical_case",
        1,
    )
    junit_path.write_text(payload, encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "backend-full.junit.xml",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "unapproved skipped test" in captured.err
    assert "test_arbitrary_critical_case" in captured.err


def test_validate_c1b_profile_rejects_spoofed_backend_skip_reason(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    junit_path = tmp_path / "backend-full.junit.xml"
    payload = junit_path.read_text(encoding="utf-8").replace(
        "悬疑 POV LLM 对照属 §9.3 发布门 lane，需真实 LLM 额度；"
        "离线跳过（golden 覆盖逻辑门）",
        "arbitrary skipped test",
        1,
    )
    junit_path.write_text(payload, encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "backend-full.junit.xml",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "audited skip reason" in captured.err


def test_validate_c1b_profile_rejects_parameterized_skip_allowlist_spoof(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    junit_path = tmp_path / "backend-full.junit.xml"
    payload = junit_path.read_text(encoding="utf-8")
    testcase_start = payload.index(
        '<testcase classname="tests.test_consistency_validation_realistic"'
    )
    testcase_end = payload.index("</testcase>", testcase_start) + len(
        "</testcase>"
    )
    spoofed_skips = "".join(
        '<testcase classname="evil.prefix.test_style_reference_local_corpus" '
        f'name="test_local_corpus_ingests_with_full_stats[{index}]">'
        '<skipped type="pytest.skip" message="arbitrary failure '
        'NOVEL_SYSTEM_STYLE_REF_LOCAL_CORPUS" /></testcase>'
        for index in range(6)
    )
    payload = payload[:testcase_start] + spoofed_skips + payload[testcase_end:]
    payload = payload.replace('tests="1001"', 'tests="1006"', 1)
    payload = payload.replace('skipped="1"', 'skipped="6"', 1)
    junit_path.write_text(payload, encoding="utf-8")
    _rehash_manifest_artifact(manifest_path, tmp_path, "backend-full.junit.xml")

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "unapproved skipped test" in captured.err


def test_validate_c1b_profile_rejects_missing_gate_test_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    junit_path = tmp_path / "c1b-gates.junit.xml"
    selector = C1B_GATE_TEST_SELECTORS["QUEUED_CANCEL_NO_CALL"][0]
    payload = junit_path.read_text(encoding="utf-8").replace(
        selector,
        "test_unrelated_case",
        1,
    )
    junit_path.write_text(payload, encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "c1b-gates.junit.xml",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert selector in captured.err


def test_validate_c1b_profile_binds_inventory_counts_to_gate_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["gates"][0]["details"]["counts"]["production_outlets"] = 9
    raw["gates"][0]["details"]["counts"]["accounted_outlets"] = 9
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "recomputed" in captured.err


def test_validate_c1b_profile_binds_legacy_disclosure_to_both_audits(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    drill_path = tmp_path / "migration-drill-accounting.json"
    payload = json.loads(drill_path.read_text(encoding="utf-8"))
    payload["legacy_unreconstructable"]["total_unique_calls"] = 50
    drill_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "migration-drill-accounting.json",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "legacy_unreconstructable" in captured.err


def test_validate_c1b_profile_requires_honest_legacy_boundary_flag_and_count(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    details = raw["gates"][1]["details"]
    details["enforced_for_new_calls"] = False
    details["counts"]["legacy_unreconstructable_count"] = 0
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "enforced_for_new_calls" in captured.err
    assert "legacy_unreconstructable_count" in captured.err


@pytest.mark.parametrize(
    ("relative_path", "mutate", "expected_error"),
    [
        (
            "drill-preflight.json",
            lambda payload: payload.update({"foreign_keys": 1}),
            "foreign_keys",
        ),
        (
            "actual-preflight-after.json",
            lambda payload: payload.pop("llm_call_attempt_orphan_count"),
            "llm_call_attempt_orphan_count",
        ),
        (
            "actual-accounting.json",
            lambda payload: payload["status_counts"]["llm_call_attempts"].update(
                {"failed": 999}
            ),
            "must sum to row_counts",
        ),
        (
            "actual-accounting.json",
            lambda payload: payload["usage_provenance"]["llm_calls"].update(
                {"estimated": 999}
            ),
            "must sum to row_counts",
        ),
        (
            "llm-outlet-inventory.json",
            lambda payload: payload["outlets"][1].update(
                {"identity": payload["outlets"][0]["identity"]}
            ),
            "outlet counts",
        ),
    ],
)
def test_validate_c1b_profile_rejects_internal_artifact_count_contradictions(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    relative_path: str,
    mutate: object,
    expected_error: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    artifact_path = tmp_path / relative_path
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    mutate(payload)  # type: ignore[operator]
    artifact_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _rehash_manifest_artifact(manifest_path, tmp_path, relative_path)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert expected_error in captured.err


def test_validate_c1b_profile_rejects_sensitive_claim_inside_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    artifact_path = tmp_path / "actual-accounting.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["release_gate_status"] = "passed"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "actual-accounting.json",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "release_gate_status" in captured.err


def test_validate_c1b_profile_rejects_sensitive_claim_inside_build_log(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    artifact_path = tmp_path / "frontend-build.log"
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8")
        + "release_gate_status=passed\n",
        encoding="utf-8",
    )
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "frontend-build.log",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "release_gate_status" in captured.err


def test_validate_c1b_profile_rejects_sensitive_claim_inside_optional_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_paths = (*C1B_REQUIRED_ARTIFACT_PATHS, "commands.json")
    manifest_path, _ = _write_c1b_manifest(
        tmp_path,
        artifact_paths=artifact_paths,
    )
    artifact_path = tmp_path / "commands.json"
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload["release_gate_status"] = "passed"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    _rehash_manifest_artifact(manifest_path, tmp_path, "commands.json")

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "release_gate_status" in captured.err


def test_validate_c1b_profile_rejects_name_value_claim_inside_optional_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_paths = (*C1B_REQUIRED_ARTIFACT_PATHS, "commands.json")
    manifest_path, _ = _write_c1b_manifest(
        tmp_path,
        artifact_paths=artifact_paths,
    )
    artifact_path = tmp_path / "commands.json"
    artifact_path.write_text(
        json.dumps({"name": "release_gate_status", "value": "passed"}),
        encoding="utf-8",
    )
    _rehash_manifest_artifact(manifest_path, tmp_path, "commands.json")

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "release_gate_status" in captured.err


@pytest.mark.parametrize(
    ("name_key", "value_key"),
    [("Name", "Value"), ("NAME", "value")],
)
def test_validate_c1b_profile_rejects_casefolded_name_value_claim(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    name_key: str,
    value_key: str,
) -> None:
    artifact_paths = (*C1B_REQUIRED_ARTIFACT_PATHS, "commands.json")
    manifest_path, _ = _write_c1b_manifest(
        tmp_path,
        artifact_paths=artifact_paths,
    )
    artifact_path = tmp_path / "commands.json"
    artifact_path.write_text(
        json.dumps({name_key: "release_gate_status", value_key: "passed"}),
        encoding="utf-8",
    )
    _rehash_manifest_artifact(manifest_path, tmp_path, "commands.json")

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "release_gate_status" in captured.err


def test_validate_c1b_profile_rejects_name_value_claim_inside_junit_xml(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    artifact_path = tmp_path / "backend-full.junit.xml"
    payload = artifact_path.read_text(encoding="utf-8").replace(
        "</testsuite>",
        '<properties><property name="release_gate_status" '
        'value="passed" /></properties></testsuite>',
        1,
    )
    artifact_path.write_text(payload, encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "backend-full.junit.xml",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "release_gate_status" in captured.err


def test_validate_c1b_profile_allows_ordinary_release_reservation_text(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    artifact_path = tmp_path / "frontend-build.log"
    artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8")
        + "release_reservation=1\n",
        encoding="utf-8",
    )
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "frontend-build.log",
    )

    assert _validate_c1b(manifest_path, tmp_path) == 0


@pytest.mark.parametrize(
    ("artifact_name", "field", "value"),
    [
        ("drill-preflight.json", "ready", 1),
        ("actual-preflight-after.json", "foreign_keys", False),
    ],
)
def test_validate_c1b_profile_rejects_bool_int_preflight_aliases(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    artifact_name: str,
    field: str,
    value: object,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    artifact_path = tmp_path / artifact_name
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload[field] = value
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")
    _rehash_manifest_artifact(manifest_path, tmp_path, artifact_name)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert field in captured.err


def test_validate_c1b_profile_recomputes_junit_aggregate_attributes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    junit_path = tmp_path / "c1b-gates.junit.xml"
    payload = junit_path.read_text(encoding="utf-8").replace(
        'failures="0"',
        'failures="99"',
        1,
    )
    junit_path.write_text(payload, encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "c1b-gates.junit.xml",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "does not match recomputed" in captured.err


def test_validate_c1b_profile_does_not_accept_selector_as_substring(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    junit_path = tmp_path / "c1b-gates.junit.xml"
    selector = C1B_GATE_TEST_SELECTORS["QUEUED_CANCEL_NO_CALL"][0]
    payload = junit_path.read_text(encoding="utf-8").replace(
        selector,
        f"not_{selector}",
        1,
    )
    junit_path.write_text(payload, encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "c1b-gates.junit.xml",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert selector in captured.err


def test_validate_c1b_profile_rejects_fake_build_log_with_matching_hash(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    build_path = tmp_path / "frontend-build.log"
    build_path.write_text("build failed", encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "frontend-build.log",
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "Vite production build completion" in captured.err


def test_validate_c1b_profile_accepts_utf16_vite_build_log(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    build_path = tmp_path / "frontend-build.log"
    build_path.write_text(
        "vite v6.1 building for production...\n\u2713 built in 1.23s\n",
        encoding="utf-16",
    )
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "frontend-build.log",
    )

    assert _validate_c1b(manifest_path, tmp_path) == 0


def test_validate_c1b_profile_binds_artifacts_to_successful_commands(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands = [
        command
        for command in _complete_c1b_commands()
        if "frontend-build.log" not in command.command
    ]
    manifest_path, _ = _write_c1b_manifest(tmp_path, commands=commands)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "frontend-build.log" in captured.err


@pytest.mark.parametrize(
    ("gate_index", "count_key"),
    [
        (1, "physical_attempts"),
        (5, "reservation_cases"),
        (9, "queued_cancel_cases"),
    ],
)
def test_validate_c1b_profile_binds_primary_counts_to_junit_coverage(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    gate_index: int,
    count_key: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["gates"][gate_index]["details"]["counts"][count_key] = 999
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert count_key in captured.err


def test_validate_c1b_semantics_use_the_hashed_byte_snapshot(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    inventory_path = tmp_path / "llm-outlet-inventory.json"
    invalid_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    invalid_inventory["summary"]["unaccounted"] = 1
    inventory_path.write_text(json.dumps(invalid_inventory), encoding="utf-8")
    _rehash_manifest_artifact(
        manifest_path,
        tmp_path,
        "llm-outlet-inventory.json",
    )
    manifest = read_manifest(manifest_path, c1b_strict=True)
    snapshots: dict[str, bytes] = {}

    assert validate_manifest_evidence(
        manifest,
        tmp_path,
        profile="c1b",
        snapshot_sink=snapshots,
    ) == []
    _write_c1b_artifact(
        tmp_path,
        "llm-outlet-inventory.json",
        C1B_REQUIRED_ARTIFACT_PATHS.index("llm-outlet-inventory.json"),
    )

    errors = validate_c1b_gate_profile(manifest, snapshots)

    assert any("outlet counts" in error for error in errors)


@pytest.mark.parametrize("missing_code", C1B_REQUIRED_GATE_CODES)
def test_validate_c1b_profile_requires_every_planned_gate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing_code: str,
) -> None:
    gates = [
        gate for gate in _complete_c1b_gates() if gate.code != missing_code
    ]
    manifest_path, _ = _write_c1b_manifest(tmp_path, gates=gates)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert missing_code in captured.err


@pytest.mark.parametrize("missing_path", C1B_REQUIRED_ARTIFACT_PATHS)
def test_validate_c1b_profile_requires_every_planned_artifact_type(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    missing_path: str,
) -> None:
    artifact_paths = tuple(
        path for path in C1B_REQUIRED_ARTIFACT_PATHS if path != missing_path
    )
    manifest_path, _ = _write_c1b_manifest(
        tmp_path,
        artifact_paths=artifact_paths,
    )

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert missing_path in captured.err


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "outcome-evidence-v2"),
        ("database_revision", "0065"),
        ("git_commit", "abc123"),
        ("git_commit", "A" * 40),
        ("provenance", "real_model"),
    ],
)
def test_validate_c1b_profile_rejects_wrong_manifest_identity(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw[field] = value
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert json.loads(captured.err)["valid"] is False


@pytest.mark.parametrize(
    "gate_mutator",
    [
        lambda gates: gates[0].update({"passed": False}),
        lambda gates: gates[0].update({"details": {}}),
        lambda gates: gates[0].update({"details": {"result": "passed"}}),
        lambda gates: gates.append(
            {"code": "UNPLANNED_GATE", "passed": True, "details": {}}
        ),
        lambda gates: gates.append(dict(gates[0])),
    ],
    ids=["false", "empty-details", "generic-result", "extra", "duplicate"],
)
def test_validate_c1b_profile_rejects_non_exact_gate_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    gate_mutator: object,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw_gates = raw["gates"]
    assert isinstance(raw_gates, list)
    gate_mutator(raw_gates)  # type: ignore[operator]
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert json.loads(captured.err)["valid"] is False


@pytest.mark.parametrize(
    ("gate_index", "count_key", "value"),
    [
        (0, "accounted_outlets", 7),
        (0, "unaccounted_outlets", 1),
        (4, "retry_attempts", 0),
        (5, "overspend_violations", 1),
        (12, "lost_ledger_rows", 1),
    ],
)
def test_validate_c1b_profile_rejects_non_recomputable_gate_counts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    gate_index: int,
    count_key: str,
    value: int,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    gates = raw["gates"]
    assert isinstance(gates, list)
    details = gates[gate_index]["details"]
    details["counts"][count_key] = value
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert count_key in captured.err


def test_validate_c1b_profile_rejects_unknown_artifact_reference(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["gates"][0]["details"]["artifact_refs"] = ["not-present.json"]
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "not-present.json" in captured.err


def test_validate_without_profile_cannot_emit_c1b_conclusion(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)

    result = _main(
        [
            "validate",
            str(manifest_path),
            "--artifact-root",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()

    assert result == 0
    assert json.loads(captured.out) == {
        "valid": True,
        "run_id": "20260713-c1b-test",
    }
    assert "C1B" not in captured.out


def test_validate_c0_profile_cannot_impersonate_c1b(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)

    assert _main(
        [
            "validate",
            str(manifest_path),
            "--profile",
            "c0",
            "--artifact-root",
            str(tmp_path),
        ]
    ) == 1


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing-size", "size_bytes"),
        ("wrong-size", "size_bytes"),
        ("string-size", "size_bytes"),
        ("uppercase-hash", "sha256"),
        ("duplicate-path", "duplicate artifact path"),
    ],
)
def test_validate_c1b_profile_rejects_invalid_artifact_metadata(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
    expected_error: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    artifacts = raw["artifacts"]
    assert isinstance(artifacts, list)
    if mutation == "missing-size":
        artifacts[0].pop("size_bytes", None)
    elif mutation == "wrong-size":
        artifacts[0]["size_bytes"] += 1
    elif mutation == "string-size":
        artifacts[0]["size_bytes"] = str(artifacts[0]["size_bytes"])
    elif mutation == "uppercase-hash":
        artifacts[0]["sha256"] = artifacts[0]["sha256"].upper()
    else:
        artifacts[1]["path"] = artifacts[0]["path"]
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert expected_error in captured.err


def test_validate_c1b_profile_rejects_artifact_path_traversal(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    outside_path = tmp_path.parent / f"outside-{tmp_path.name}.bin"
    outside_payload = b"outside"
    outside_path.write_bytes(outside_payload)
    raw = _read_raw_manifest(manifest_path)
    raw["artifacts"][0] = {
        "path": f"../{outside_path.name}",
        "sha256": hashlib.sha256(outside_payload).hexdigest(),
        "size_bytes": len(outside_payload),
    }
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "artifact root" in captured.err.lower()


def test_validate_c1b_profile_rejects_symlink_escape(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, artifact_paths = _write_c1b_manifest(tmp_path)
    linked_path = artifact_paths[0]
    payload = linked_path.read_bytes()
    outside_path = tmp_path.parent / f"symlink-target-{tmp_path.name}.bin"
    outside_path.write_bytes(payload)
    linked_path.unlink()
    try:
        linked_path.symlink_to(outside_path)
    except OSError as exc:
        pytest.skip(f"symlinks are unavailable: {exc}")

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "artifact root" in captured.err.lower()


def test_validate_c1b_profile_accepts_windows_relative_path_spelling(
    tmp_path: Path,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["artifacts"][-1]["path"] = ".\\frontend-build.log"
    _write_raw_manifest(manifest_path, raw)

    assert _validate_c1b(manifest_path, tmp_path) == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("started_at", ""),
        ("started_at", "not-a-time"),
        ("started_at", "2999-01-01T00:00:00Z"),
        ("ended_at", "2026-07-12T23:59:59Z"),
    ],
)
def test_validate_c1b_profile_rejects_invalid_command_times(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["commands"][0][field] = value
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert field in captured.err


def test_validate_c1b_profile_rejects_future_created_at(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["created_at"] = "2999-01-01T00:00:00Z"
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "created_at" in captured.err


def test_validate_c1b_profile_rejects_created_at_before_command_end(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["created_at"] = "2026-07-12T00:00:00Z"
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "later than created_at" in captured.err


@pytest.mark.parametrize("field", ["schema", "created_at"])
def test_validate_c1b_profile_requires_explicit_manifest_timestamps_and_schema(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw.pop(field)
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert field in captured.err


def test_validate_c1b_profile_rejects_empty_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, artifact_paths = _write_c1b_manifest(tmp_path)
    artifact_paths[0].write_bytes(b"")
    raw = _read_raw_manifest(manifest_path)
    raw["artifacts"][0]["sha256"] = hashlib.sha256(b"").hexdigest()
    raw["artifacts"][0]["size_bytes"] = 0
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "size_bytes must be positive" in captured.err


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("real_gate_status", "passed"),
        ("release_gate_status", "passed"),
        ("production_provider_billing_status", "verified"),
        ("real_provider_billing_status", "pending"),
    ],
)
def test_validate_c1b_offline_profile_rejects_real_or_release_claims(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    claim: str,
    value: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["gates"][0]["details"][claim] = value
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert claim in captured.err


def test_validate_c1b_profile_rejects_unknown_top_level_claim(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["release_gate_status"] = "passed"
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "release_gate_status" in captured.err


@pytest.mark.parametrize(
    ("container", "claim", "value"),
    [
        ("config_hashes", "release_gate_status", "passed"),
        ("model_routes", "real_provider_billing_status", "verified"),
        ("model_routes", "production_release_approved", True),
    ],
)
def test_validate_c1b_profile_rejects_claims_in_open_manifest_maps(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    container: str,
    claim: str,
    value: object,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw[container][claim] = value
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert claim in captured.err


@pytest.mark.parametrize(
    "mutation",
    ["string-exit", "string-expected-exit", "string-passed", "command-extra", "gate-extra"],
)
def test_validate_c1b_profile_rejects_coerced_or_extra_nested_fields(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    if mutation == "string-exit":
        raw["commands"][0]["exit_code"] = "0"
    elif mutation == "string-expected-exit":
        raw["commands"][0]["expected_exit_codes"] = ["0"]
    elif mutation == "string-passed":
        raw["gates"][0]["passed"] = "true"
    elif mutation == "command-extra":
        raw["commands"][0]["release_approved"] = True
    else:
        raw["gates"][0]["real_gate_status"] = "passed"
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert json.loads(captured.err)["valid"] is False


@pytest.mark.parametrize("location", ["top-level", "nested"])
def test_validate_c1b_profile_rejects_duplicate_json_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    location: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    payload = manifest_path.read_text(encoding="utf-8")
    if location == "top-level":
        payload = payload.replace(
            '"provenance": "offline",',
            '"provenance": "real_model",\n  "provenance": "offline",',
            1,
        )
    else:
        payload = payload.replace(
            '"exit_code": 0,',
            '"exit_code": 1,\n      "exit_code": 0,',
            1,
        )
    manifest_path.write_text(payload, encoding="utf-8")

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "duplicate JSON key" in captured.err


def test_validate_c1b_profile_rejects_nonstandard_json_constants(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    payload = manifest_path.read_text(encoding="utf-8").replace(
        '"model_routes": {},',
        '"model_routes": {"score": NaN},',
        1,
    )
    manifest_path.write_text(payload, encoding="utf-8")

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "non-standard JSON constant" in captured.err


@pytest.mark.parametrize(
    "device_path",
    ["CON", "con.txt", "NUL", "COM1.log", "LPT1"],
)
def test_validate_c1b_profile_rejects_reserved_windows_device_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    device_path: str,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)
    raw = _read_raw_manifest(manifest_path)
    raw["artifacts"].append(
        {"path": device_path, "sha256": "0" * 64, "size_bytes": 1}
    )
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "reserved Windows device" in captured.err


def test_validate_c1b_profile_rejects_hardlinked_artifact(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path, artifact_paths = _write_c1b_manifest(tmp_path)
    duplicate_path = tmp_path / "duplicate-hardlink.bin"
    try:
        os.link(artifact_paths[0], duplicate_path)
    except OSError as exc:
        pytest.skip(f"hardlinks are unavailable: {exc}")
    raw = _read_raw_manifest(manifest_path)
    raw["artifacts"].append(
        {
            "path": duplicate_path.name,
            "sha256": raw["artifacts"][0]["sha256"],
            "size_bytes": raw["artifacts"][0]["size_bytes"],
        }
    )
    _write_raw_manifest(manifest_path, raw)

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert "hard-linked artifacts are not allowed" in captured.err


def test_validate_c1b_reports_resolve_runtime_error_as_stable_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path, _ = _write_c1b_manifest(tmp_path)

    def fail_resolve(self: Path, *, strict: bool = False) -> Path:
        raise RuntimeError("symlink loop")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert json.loads(captured.err)["valid"] is False
    assert "traceback" not in captured.err.lower()


def test_validate_c1b_reports_missing_manifest_as_stable_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "missing.json"

    result = _validate_c1b(manifest_path, tmp_path)
    captured = capsys.readouterr()

    assert result == 1
    assert json.loads(captured.err)["valid"] is False
    assert "traceback" not in captured.err.lower()


def test_outcome_evidence_module_imports_without_warnings() -> None:
    backend_root = Path(__file__).parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(backend_root / "src")

    completed = subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            "import novel_system.services.outcome_evidence",
        ],
        cwd=backend_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
