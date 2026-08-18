from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_system.services.accounting_audit_schema import (
    REQUIRED_COLUMNS as ACCOUNTING_AUDIT_REQUIRED_COLUMNS,
)


EvidenceProvenance = Literal["synthetic", "offline", "real_model", "human"]

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

C1B_DATABASE_REVISION = "20260713_0065"
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
C1B_ALLOWED_OPTIONAL_ARTIFACT_PATHS = (
    "commands.json",
    "artifacts.json",
    "actual-preflight-before.json",
    "migration-drill.db",
    "drill-alembic.log",
    "actual-alembic.log",
)

_C1B_GATE_COUNT_RULES: dict[str, dict[str, object]] = {
    "ALL_PRODUCTION_LLM_OUTLETS_ACCOUNTED": {
        "keys": (
            "production_outlets",
            "accounted_outlets",
            "unaccounted_outlets",
        ),
        "positive": ("production_outlets", "accounted_outlets"),
        "zero": ("unaccounted_outlets",),
        "equal": (("production_outlets", "accounted_outlets"),),
        "artifact": "llm-outlet-inventory.json",
    },
    "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED": {
        "keys": (
            "physical_attempts",
            "accounted_attempts",
            "unaccounted_attempts",
        ),
        "positive": ("physical_attempts", "accounted_attempts"),
        "zero": ("unaccounted_attempts",),
        "equal": (("physical_attempts", "accounted_attempts"),),
        "artifact": "c1b-gates.junit.xml",
    },
    "MISSING_USAGE_ESTIMATED": {
        "keys": (
            "missing_usage_attempts",
            "estimated_usage_attempts",
            "unestimated_usage_attempts",
        ),
        "positive": ("missing_usage_attempts", "estimated_usage_attempts"),
        "zero": ("unestimated_usage_attempts",),
        "equal": (("missing_usage_attempts", "estimated_usage_attempts"),),
        "artifact": "c1b-gates.junit.xml",
    },
    "FAILED_CALLS_CHARGED": {
        "keys": (
            "failed_attempts",
            "charged_failed_attempts",
            "zero_charge_failed_attempts",
        ),
        "positive": ("failed_attempts", "charged_failed_attempts"),
        "zero": ("zero_charge_failed_attempts",),
        "equal": (("failed_attempts", "charged_failed_attempts"),),
        "artifact": "c1b-gates.junit.xml",
    },
    "RETRY_AND_DEGRADE_BUDGETED": {
        "keys": ("retry_attempts", "degrade_attempts", "unbudgeted_attempts"),
        "positive": ("retry_attempts", "degrade_attempts"),
        "zero": ("unbudgeted_attempts",),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
    "ATOMIC_RESERVATION_NO_OVERSPEND": {
        "keys": ("reservation_cases", "overspend_violations"),
        "positive": ("reservation_cases",),
        "zero": ("overspend_violations",),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
    "BASELINE_CALLS_BUDGETED": {
        "keys": ("baseline_calls", "unbudgeted_baseline_calls"),
        "positive": ("baseline_calls",),
        "zero": ("unbudgeted_baseline_calls",),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
    "LIFECYCLE_BUDGET_NOT_RESET": {
        "keys": ("lifecycle_cases", "budget_reset_violations"),
        "positive": ("lifecycle_cases",),
        "zero": ("budget_reset_violations",),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
    "CHECKPOINT_RESUME_NO_REPLAY": {
        "keys": ("resume_cases", "replayed_completed_nodes"),
        "positive": ("resume_cases",),
        "zero": ("replayed_completed_nodes",),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
    "QUEUED_CANCEL_NO_CALL": {
        "keys": ("queued_cancel_cases", "provider_calls_after_cancel"),
        "positive": ("queued_cancel_cases",),
        "zero": ("provider_calls_after_cancel",),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
    "RUNNING_CANCEL_STOPS_NEXT_NODE": {
        "keys": (
            "running_cancel_cases",
            "next_nodes_started_after_cancel",
        ),
        "positive": ("running_cancel_cases",),
        "zero": ("next_nodes_started_after_cancel",),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
    "CANCEL_CAS_LINEARIZABLE": {
        "keys": ("cancel_race_cases", "linearizability_violations"),
        "positive": ("cancel_race_cases",),
        "zero": ("linearizability_violations",),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
    "CANCEL_PRESERVES_DRAFT_AND_LEDGER": {
        "keys": ("cancellation_cases", "lost_drafts", "lost_ledger_rows"),
        "positive": ("cancellation_cases",),
        "zero": ("lost_drafts", "lost_ledger_rows"),
        "equal": (),
        "artifact": "c1b-gates.junit.xml",
    },
}

_WINDOWS_RESERVED_DEVICE_PATTERN = re.compile(
    r"^(?:CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|"
    r"COM[1-9\u00b9\u00b2\u00b3]|LPT[1-9\u00b9\u00b2\u00b3])$",
    re.IGNORECASE,
)
_HASH_CHUNK_SIZE = 1024 * 1024
_C1B_MAX_MANIFEST_BYTES = 4 * 1024 * 1024
_C1B_MAX_STRUCTURED_ARTIFACT_BYTES = 16 * 1024 * 1024
_C1B_MAX_SQLITE_ARTIFACT_BYTES = 256 * 1024 * 1024
_C1B_CANONICAL_ACTUAL_DATABASE = (
    r"E:\codex\xiaoshuo\codex\backend\novel_system.db"
)
_C1B_GATE_TEST_SELECTORS: dict[str, tuple[str, ...]] = {
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
for _gate_code, _selectors in _C1B_GATE_TEST_SELECTORS.items():
    _rule = _C1B_GATE_COUNT_RULES[_gate_code]
    _rule["keys"] = (*_rule["keys"], "evidence_cases")
    _rule["positive"] = (*_rule["positive"], "evidence_cases")
_physical_rule = _C1B_GATE_COUNT_RULES[
    "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED"
]
_physical_rule["keys"] = (
    *_physical_rule["keys"],
    "legacy_unreconstructable_count",
)
_C1B_PRIMARY_CASE_COUNT_KEYS = {
    "ATOMIC_RESERVATION_NO_OVERSPEND": "reservation_cases",
    "BASELINE_CALLS_BUDGETED": "baseline_calls",
    "LIFECYCLE_BUDGET_NOT_RESET": "lifecycle_cases",
    "CHECKPOINT_RESUME_NO_REPLAY": "resume_cases",
    "QUEUED_CANCEL_NO_CALL": "queued_cancel_cases",
    "RUNNING_CANCEL_STOPS_NEXT_NODE": "running_cancel_cases",
    "CANCEL_CAS_LINEARIZABLE": "cancel_race_cases",
    "CANCEL_PRESERVES_DRAFT_AND_LEDGER": "cancellation_cases",
}
_C1B_COMMAND_ARTIFACT_TOKENS = {
    "database-before-0065.db": ("db_backup", "--backup"),
    "drill-preflight.json": ("database_preflight",),
    "migration-drill-accounting.json": ("llm_accounting_audit",),
    "migration-focused.junit.xml": ("pytest", "junit"),
    "actual-preflight-after.json": ("database_preflight",),
    "actual-accounting.json": ("llm_accounting_audit",),
    "llm-outlet-inventory.json": ("llm_outlet_inventory",),
    "c1b-gates.junit.xml": ("pytest", "junit"),
    "backend-full.junit.xml": ("pytest", "junit"),
    "frontend.junit.xml": ("npm", "test"),
    "frontend-build.log": ("npm", "build"),
}
_C1B_JUNIT_MIN_TESTS = {
    "migration-focused.junit.xml": 3,
    "c1b-gates.junit.xml": len(
        {selector for selectors in _C1B_GATE_TEST_SELECTORS.values() for selector in selectors}
    ),
    "backend-full.junit.xml": 1000,
    "frontend.junit.xml": 122,
}
_C1B_BACKEND_ALLOWED_SKIPS = {
    "test_suspense_pov_no_early_action_release_gate": (
        "tests.test_consistency_validation_realistic",
        "悬疑 POV LLM 对照属 §9.3 发布门 lane，需真实 LLM 额度；"
        "离线跳过（golden 覆盖逻辑门）",
        "exact",
    ),
    "test_local_corpus_ingests_with_full_stats": (
        "tests.test_style_reference_local_corpus",
        "NOVEL_SYSTEM_STYLE_REF_LOCAL_CORPUS 未设置或文件不存在"
        "(本地私有语料通道,可选)",
        "exact",
    ),
    "test_local_corpus_self_plagiarism_detected": (
        "tests.test_style_reference_local_corpus",
        "NOVEL_SYSTEM_STYLE_REF_LOCAL_CORPUS 未设置或文件不存在"
        "(本地私有语料通道,可选)",
        "exact",
    ),
    "test_local_corpus_original_text_passes": (
        "tests.test_style_reference_local_corpus",
        "NOVEL_SYSTEM_STYLE_REF_LOCAL_CORPUS 未设置或文件不存在"
        "(本地私有语料通道,可选)",
        "exact",
    ),
    "test_validate_c1b_profile_rejects_symlink_escape": (
        "tests.test_outcome_evidence",
        "symlinks are unavailable",
        "prefix",
    ),
    "test_validate_c1b_profile_rejects_hardlinked_artifact": (
        "tests.test_outcome_evidence",
        "hardlinks are unavailable",
        "prefix",
    ),
}


class EvidenceProvenanceError(ValueError):
    """Raised when a manifest's provenance is not allowed."""


class EvidenceCommand(BaseModel):
    command: str
    exit_code: int
    expected_exit_codes: list[int] = Field(default_factory=lambda: [0])
    started_at: str | None = None
    ended_at: str | None = None


class EvidenceArtifact(BaseModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0, strict=True)


class EvidenceGate(BaseModel):
    code: str
    passed: bool
    details: dict[str, object] = Field(default_factory=dict)


def _utc_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _hash_regular_file(
    path: Path,
    *,
    capture_limit: int | None = None,
) -> tuple[str, int, os.stat_result, bytes | None]:
    digest = hashlib.sha256()
    captured = bytearray() if capture_limit is not None else None
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("path is not a regular disk file")
        total_size = 0
        while chunk := handle.read(_HASH_CHUNK_SIZE):
            digest.update(chunk)
            total_size += len(chunk)
            if captured is not None:
                if total_size > capture_limit:
                    captured = None
                else:
                    captured.extend(chunk)
        after = os.fstat(handle.fileno())
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or total_size != after.st_size:
        raise RuntimeError("file changed while it was being hashed")
    return (
        digest.hexdigest(),
        total_size,
        after,
        bytes(captured) if captured is not None else None,
    )


class OutcomeEvidenceManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal["outcome-evidence-v1"] = Field(
        default="outcome-evidence-v1",
        alias="schema",
    )
    run_id: str
    git_commit: str
    database_revision: str
    config_hashes: dict[str, str] = Field(default_factory=dict)
    model_routes: dict[str, Any] = Field(default_factory=dict)
    provenance: EvidenceProvenance
    created_at: str = Field(default_factory=_utc_iso_z)
    commands: list[EvidenceCommand] = Field(default_factory=list)
    artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    gates: list[EvidenceGate] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_gate_codes(self) -> Self:
        gate_codes = [gate.code for gate in self.gates]
        if len(gate_codes) != len(set(gate_codes)):
            raise ValueError("duplicate gate code")
        return self


def artifact_from_path(
    path: str | Path,
    *,
    root: str | Path | None = None,
) -> EvidenceArtifact:
    source_path = Path(path)
    digest, size_bytes, _, _ = _hash_regular_file(source_path)
    artifact_path = (
        source_path.relative_to(Path(root)).as_posix()
        if root is not None
        else source_path.as_posix()
    )
    return EvidenceArtifact(
        path=artifact_path,
        sha256=digest,
        size_bytes=size_bytes,
    )


def require_provenance(
    manifest: OutcomeEvidenceManifest,
    allowed: set[EvidenceProvenance],
) -> None:
    if manifest.provenance not in allowed:
        raise EvidenceProvenanceError(
            f"provenance {manifest.provenance!r} is not allowed"
        )


def _gate_detail_group(gate: EvidenceGate, key: str) -> dict[str, object]:
    value = gate.details.get(key)
    return value if isinstance(value, dict) else {}


def _is_exact_int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _validate_known_gate_details(
    gate: EvidenceGate,
    database_revision: str,
) -> list[str]:
    errors: list[str] = []
    prefix = f"gate {gate.code!r}"

    if gate.code == "RUNTIME_PROCESS_CLEAR":
        report = _gate_detail_group(gate, "report")
        if not _is_exact_int(report.get("match_count"), 0):
            errors.append(
                f"{prefix}: details.report.match_count must be integer 0"
            )

    elif gate.code == "BACKUP_VERIFIED":
        verify = _gate_detail_group(gate, "verify")
        preflight = _gate_detail_group(
            gate, "pre_migration_backup_preflight"
        )
        if verify.get("ok") is not True:
            errors.append(f"{prefix}: details.verify.ok must be true")
        if verify.get("integrity") != "ok":
            errors.append(f"{prefix}: details.verify.integrity must be 'ok'")
        if verify.get("checksum_ok") is not True:
            errors.append(f"{prefix}: details.verify.checksum_ok must be true")
        if preflight.get("integrity") != "ok":
            errors.append(
                f"{prefix}: details.pre_migration_backup_preflight.integrity "
                "must be 'ok'"
            )
        revision = preflight.get("revision")
        if not isinstance(revision, str) or not revision:
            errors.append(
                f"{prefix}: details.pre_migration_backup_preflight.revision "
                "is required"
            )

    elif gate.code == "DRILL_MIGRATION_HEAD_MATCH":
        preflight = _gate_detail_group(gate, "preflight")
        if preflight.get("ready") is not True:
            errors.append(f"{prefix}: details.preflight.ready must be true")
        if preflight.get("revision") != database_revision:
            errors.append(
                f"{prefix}: details.preflight.revision must equal "
                "manifest database_revision"
            )
        if preflight.get("integrity") != "ok":
            errors.append(
                f"{prefix}: details.preflight.integrity must be 'ok'"
            )

    elif gate.code == "ACTUAL_MIGRATION_HEAD_MATCH":
        preflight = _gate_detail_group(gate, "actual_preflight")
        if preflight.get("ready") is not True:
            errors.append(
                f"{prefix}: details.actual_preflight.ready must be true"
            )
        if preflight.get("revision") != database_revision:
            errors.append(
                f"{prefix}: details.actual_preflight.revision must equal "
                "manifest database_revision"
            )
        if preflight.get("integrity") != "ok":
            errors.append(
                f"{prefix}: details.actual_preflight.integrity must be 'ok'"
            )

    elif gate.code == "SCHEMA_READY":
        for key in ("drill_preflight", "actual_preflight"):
            preflight = _gate_detail_group(gate, key)
            if preflight.get("ready") is not True:
                errors.append(f"{prefix}: details.{key}.ready must be true")
            if preflight.get("missing_tables") != []:
                errors.append(
                    f"{prefix}: details.{key}.missing_tables must be []"
                )
            if preflight.get("missing_columns") != {}:
                errors.append(
                    f"{prefix}: details.{key}.missing_columns must be {{}}"
                )

    elif gate.code == "ORPHANS_ZERO":
        for key in ("drill_report", "actual_report"):
            report = _gate_detail_group(gate, key)
            if report.get("clean") is not True:
                errors.append(f"{prefix}: details.{key}.clean must be true")
            if not _is_exact_int(report.get("total_orphans"), 0):
                errors.append(
                    f"{prefix}: details.{key}.total_orphans must be integer 0"
                )

    elif gate.code in ("FOCUSED_REGRESSION_PASS", "C0_REGRESSION_PASS"):
        report = _gate_detail_group(gate, "report")
        passed = report.get("passed")
        if type(passed) is not int or passed <= 0:
            errors.append(
                f"{prefix}: details.report.passed must be a positive integer"
            )
        if not _is_exact_int(report.get("failed"), 0):
            errors.append(
                f"{prefix}: details.report.failed must be integer 0"
            )

    return errors


def _strict_json_loads(payload: bytes | str) -> object:
    def reject_duplicate_keys(
        pairs: list[tuple[str, object]],
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_nonstandard_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant {value!r}")

    return json.loads(
        payload,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonstandard_constant,
    )


def _normalize_relative_artifact_path(value: str) -> tuple[str | None, str | None]:
    portable_value = value.strip().replace("\\", "/")
    if not portable_value:
        return None, "path is empty"
    if portable_value.startswith("/") or re.match(
        r"^[A-Za-z]:", portable_value
    ):
        return None, "absolute paths are not allowed"
    if ":" in portable_value:
        return None, "drive or alternate data stream paths are not allowed"
    normalized_parts: list[str] = []
    for part in portable_value.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None, "path traversal is not allowed"
        if part != part.rstrip(" ."):
            return None, "segments with trailing spaces or dots are not allowed"
        device_basename = part.split(".", 1)[0]
        if _WINDOWS_RESERVED_DEVICE_PATTERN.fullmatch(device_basename):
            return None, "reserved Windows device names are not allowed"
        normalized_parts.append(part)
    if not normalized_parts:
        return None, "path is empty"
    return "/".join(normalized_parts), None


def _parse_c1b_timestamp(
    value: str | None,
    identifier: str,
    errors: list[str],
) -> datetime | None:
    if value is None or not value.strip():
        errors.append(f"{identifier} is required")
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{identifier} must be an ISO-8601 timestamp")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        errors.append(f"{identifier} must include a timezone")
        return None
    parsed_utc = parsed.astimezone(UTC)
    if parsed_utc > datetime.now(UTC):
        errors.append(f"{identifier} must not be in the future")
    return parsed_utc


def _offline_sensitive_detail_paths(
    value: object,
    *,
    prefix: str = "details",
) -> list[str]:
    sensitive_paths: list[str] = []
    if isinstance(value, dict):
        for key, nested_value in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            current_path = f"{prefix}.{key_text}"
            if (
                "release" in key_lower
                or (
                    "real" in key_lower
                    and any(
                        token in key_lower
                        for token in ("gate", "provider", "billing")
                    )
                )
                or ("production" in key_lower and "billing" in key_lower)
            ):
                sensitive_paths.append(current_path)
            sensitive_paths.extend(
                _offline_sensitive_detail_paths(
                    nested_value,
                    prefix=current_path,
                )
            )
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            sensitive_paths.extend(
                _offline_sensitive_detail_paths(
                    nested_value,
                    prefix=f"{prefix}[{index}]",
                )
            )
    return sensitive_paths


def _offline_sensitive_text_claims(value: str) -> list[str]:
    claims: list[str] = []
    for match in re.finditer(
        r"(?i)\b([a-z_][a-z0-9_.-]*)\s*[:=]\s*[^\s<]+",
        value,
    ):
        key = match.group(1)
        if _is_offline_sensitive_assertion_name(key):
            claims.append(key)
    return claims


def _is_offline_sensitive_assertion_name(value: str) -> bool:
    normalized = value.lower().replace("-", "_").replace(".", "_")
    if "release" in normalized and any(
        token in normalized
        for token in ("gate", "status", "approv", "decision", "result")
    ):
        return True
    if "real" in normalized and any(
        token in normalized for token in ("gate", "provider", "billing")
    ):
        return True
    return "production" in normalized and "billing" in normalized


def _offline_sensitive_name_value_paths(
    value: object,
    *,
    prefix: str,
) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        folded_items = [
            (str(key), str(key).casefold(), nested_value)
            for key, nested_value in value.items()
        ]
        if any(folded_key == "value" for _, folded_key, _ in folded_items):
            for original_key, folded_key, assertion_name in folded_items:
                if isinstance(assertion_name, str) and (
                    folded_key in {"name", "key", "property"}
                    and _is_offline_sensitive_assertion_name(assertion_name)
                ):
                    paths.append(
                        f"{prefix}.{original_key}<{assertion_name}>"
                    )
        for key, nested_value in value.items():
            paths.extend(
                _offline_sensitive_name_value_paths(
                    nested_value,
                    prefix=f"{prefix}.{key}",
                )
            )
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            paths.extend(
                _offline_sensitive_name_value_paths(
                    nested_value,
                    prefix=f"{prefix}[{index}]",
                )
            )
    return paths


def _decode_c1b_text_snapshot(snapshot: bytes) -> str:
    if snapshot.startswith((b"\xff\xfe", b"\xfe\xff")):
        return snapshot.decode("utf-16")
    if b"\x00" in snapshot[:256]:
        return snapshot.decode("utf-16-le")
    return snapshot.decode("utf-8-sig")


def _validate_c1b_artifact_claims(
    snapshots: dict[str, bytes],
    allowed_paths: set[str],
) -> list[str]:
    errors: list[str] = []
    for identifier, snapshot in snapshots.items():
        if identifier not in allowed_paths or identifier.endswith(".db"):
            continue
        if identifier.endswith(".json"):
            try:
                payload = _strict_json_loads(snapshot)
            except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"artifact {identifier!r}: invalid JSON: {exc}")
            else:
                for path in _offline_sensitive_detail_paths(
                    payload,
                    prefix=f"artifact[{identifier!r}]",
                ):
                    errors.append(f"offline evidence cannot assert {path}")
                for path in _offline_sensitive_name_value_paths(
                    payload,
                    prefix=f"artifact[{identifier!r}]",
                ):
                    errors.append(f"offline evidence cannot assert {path}")
        if identifier.endswith(".xml"):
            try:
                xml_root = ET.fromstring(snapshot)
            except ET.ParseError:
                pass
            else:
                for element_index, element in enumerate(xml_root.iter()):
                    for path in _offline_sensitive_name_value_paths(
                        dict(element.attrib),
                        prefix=(
                            f"artifact[{identifier!r}].xml[{element_index}]"
                        ),
                    ):
                        errors.append(f"offline evidence cannot assert {path}")
        try:
            text = _decode_c1b_text_snapshot(snapshot)
        except UnicodeDecodeError as exc:
            errors.append(
                f"artifact {identifier!r}: unsupported text encoding: {exc}"
            )
            continue
        for claim in _offline_sensitive_text_claims(text):
            errors.append(
                f"offline evidence cannot assert artifact[{identifier!r}]"
                f".{claim}"
            )
    return errors


def _read_json_artifact(
    snapshot: bytes | None,
    identifier: str,
    errors: list[str],
) -> dict[str, object] | None:
    if snapshot is None:
        errors.append(
            f"artifact {identifier!r}: validated byte snapshot is unavailable"
        )
        return None
    try:
        payload = _strict_json_loads(snapshot)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"artifact {identifier!r}: invalid JSON: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"artifact {identifier!r}: JSON root must be an object")
        return None
    return payload


def _nested_int(mapping: object, key: str) -> int | None:
    if not isinstance(mapping, dict):
        return None
    value = mapping.get(key)
    return value if type(value) is int else None


def _require_exact_keys(
    payload: dict[str, object],
    expected_keys: set[str],
    identifier: str,
    errors: list[str],
) -> None:
    if set(payload) != expected_keys:
        errors.append(
            f"artifact {identifier!r}: keys must be exactly "
            + ", ".join(sorted(expected_keys))
        )


def _validate_preflight_artifact(
    payload: dict[str, object] | None,
    identifier: str,
    errors: list[str],
) -> None:
    if payload is None:
        return
    _require_exact_keys(
        payload,
        {
            "path",
            "ready",
            "integrity",
            "revision",
            "expected_revision",
            "expected_revision_canonical",
            "foreign_keys",
            "missing_tables",
            "missing_columns",
            "schema_errors",
            "llm_call_attempt_orphan_count",
        },
        identifier,
        errors,
    )
    expected_values = {
        "ready": True,
        "integrity": "ok",
        "revision": C1B_DATABASE_REVISION,
        "expected_revision": C1B_DATABASE_REVISION,
        "expected_revision_canonical": C1B_DATABASE_REVISION,
        "foreign_keys": 0,
        "missing_tables": [],
        "missing_columns": {},
        "schema_errors": [],
        "llm_call_attempt_orphan_count": 0,
    }
    for key, expected in expected_values.items():
        actual = payload.get(key)
        if type(actual) is not type(expected) or actual != expected:
            errors.append(
                f"artifact {identifier!r}: {key} must equal {expected!r}"
            )


def _validate_accounting_audit_artifact(
    payload: dict[str, object] | None,
    identifier: str,
    errors: list[str],
) -> dict[str, object] | None:
    if payload is None:
        return None
    _require_exact_keys(
        payload,
        {
            "schema",
            "database",
            "tables",
            "row_counts",
            "integrity",
            "status_counts",
            "usage_provenance",
            "legacy_unreconstructable",
        },
        identifier,
        errors,
    )
    if payload.get("schema") != "llm-accounting-audit-v1":
        errors.append(
            f"artifact {identifier!r}: schema must be "
            "'llm-accounting-audit-v1'"
        )
    database = payload.get("database")
    if not isinstance(database, dict):
        errors.append(f"artifact {identifier!r}: database must be an object")
    else:
        if set(database) != {"path", "read_only", "revision"}:
            errors.append(
                f"artifact {identifier!r}: database keys are invalid"
            )
        if database.get("read_only") is not True:
            errors.append(f"artifact {identifier!r}: database.read_only must be true")
        if database.get("revision") != C1B_DATABASE_REVISION:
            errors.append(
                f"artifact {identifier!r}: database.revision must be "
                f"{C1B_DATABASE_REVISION!r}"
            )

    tables = payload.get("tables")
    expected_tables = {"llm_calls", "llm_call_attempts", "scene_run_states"}
    if not isinstance(tables, dict) or set(tables) != expected_tables:
        errors.append(
            f"artifact {identifier!r}: tables must contain exactly the "
            "accounting tables"
        )
    else:
        for table_name, table_report in tables.items():
            columns = (
                table_report.get("columns")
                if isinstance(table_report, dict)
                else None
            )
            if (
                not isinstance(table_report, dict)
                or set(table_report)
                != {"present", "columns", "missing_required_columns"}
                or table_report.get("present") is not True
                or not isinstance(columns, list)
                or any(
                    not isinstance(column, str) or not column
                    for column in (columns if isinstance(columns, list) else ())
                )
                or len(columns if isinstance(columns, list) else ())
                != len(set(columns if isinstance(columns, list) else ()))
                or not set(ACCOUNTING_AUDIT_REQUIRED_COLUMNS[table_name]).issubset(
                    columns if isinstance(columns, list) else ()
                )
                or table_report.get("missing_required_columns") != []
            ):
                errors.append(
                    f"artifact {identifier!r}: tables.{table_name} is invalid"
                )

    integrity = payload.get("integrity")
    if not isinstance(integrity, dict):
        errors.append(f"artifact {identifier!r}: integrity must be an object")
    else:
        if set(integrity) != {
            "scope_missing_or_blank",
            "negative_token_rows",
            "stuck_reserved",
            "attempt_orphans",
        }:
            errors.append(
                f"artifact {identifier!r}: integrity keys are invalid"
            )
        if not _is_exact_int(integrity.get("scope_missing_or_blank"), 0):
            errors.append(
                f"artifact {identifier!r}: integrity.scope_missing_or_blank "
                "must be 0"
            )
        if not _is_exact_int(integrity.get("attempt_orphans"), 0):
            errors.append(
                f"artifact {identifier!r}: integrity.attempt_orphans must be 0"
            )
        for group_name in ("negative_token_rows", "stuck_reserved"):
            group = integrity.get(group_name)
            if (
                not isinstance(group, dict)
                or set(group) != {"llm_calls", "llm_call_attempts"}
                or any(
                not _is_exact_int(value, 0) for value in group.values()
                )
            ):
                errors.append(
                    f"artifact {identifier!r}: integrity.{group_name} values "
                    "must all be integer 0"
                )

    row_counts = payload.get("row_counts")
    required_row_tables = ("llm_calls", "llm_call_attempts", "scene_run_states")
    if not isinstance(row_counts, dict):
        errors.append(f"artifact {identifier!r}: row_counts must be an object")
        normalized_row_counts: dict[str, int] = {}
    else:
        if set(row_counts) != set(required_row_tables):
            errors.append(
                f"artifact {identifier!r}: row_counts keys are invalid"
            )
        normalized_row_counts = {}
        for table_name in required_row_tables:
            value = row_counts.get(table_name)
            if type(value) is not int or value < 0:
                errors.append(
                    f"artifact {identifier!r}: row_counts.{table_name} must "
                    "be a non-negative integer"
                )
            else:
                normalized_row_counts[table_name] = value

    status_counts = payload.get("status_counts")
    normalized_status_counts: dict[str, dict[str, int]] = {}
    if not isinstance(status_counts, dict):
        errors.append(f"artifact {identifier!r}: status_counts must be an object")
    else:
        if set(status_counts) != {"llm_calls", "llm_call_attempts"}:
            errors.append(
                f"artifact {identifier!r}: status_counts keys are invalid"
            )
        allowed_statuses = {
            "reserved",
            "settled",
            "failed",
            "released",
            "rejected",
            "usage_exceeds_reservation",
            "<null>",
        }
        for table_name in ("llm_calls", "llm_call_attempts"):
            table_statuses = status_counts.get(table_name)
            if not isinstance(table_statuses, dict) or any(
                not isinstance(key, str)
                or type(value) is not int
                or value < 0
                for key, value in (
                    table_statuses.items()
                    if isinstance(table_statuses, dict)
                    else ()
                )
            ) or (
                isinstance(table_statuses, dict)
                and not set(table_statuses).issubset(allowed_statuses)
            ):
                errors.append(
                    f"artifact {identifier!r}: status_counts.{table_name} "
                    "must contain non-negative integer counts"
                )
                continue
            normalized = dict(sorted(table_statuses.items()))
            normalized_status_counts[table_name] = normalized
            expected_rows = normalized_row_counts.get(table_name)
            if expected_rows is not None and sum(normalized.values()) != expected_rows:
                errors.append(
                    f"artifact {identifier!r}: status_counts.{table_name} "
                    "must sum to row_counts"
                )

    usage_provenance = payload.get("usage_provenance")
    normalized_usage: dict[str, dict[str, int]] = {}
    if not isinstance(usage_provenance, dict):
        errors.append(
            f"artifact {identifier!r}: usage_provenance must be an object"
        )
    else:
        if set(usage_provenance) != {"llm_calls", "llm_call_attempts"}:
            errors.append(
                f"artifact {identifier!r}: usage_provenance keys are invalid"
            )
        for table_name in ("llm_calls", "llm_call_attempts"):
            table_usage = usage_provenance.get(table_name)
            if not isinstance(table_usage, dict):
                errors.append(
                    f"artifact {identifier!r}: usage_provenance.{table_name} "
                    "must be an object"
                )
                continue
            if set(table_usage) != {"actual", "estimated", "unknown"}:
                errors.append(
                    f"artifact {identifier!r}: usage_provenance.{table_name} "
                    "keys are invalid"
                )
            for key in ("actual", "estimated", "unknown"):
                value = table_usage.get(key)
                if type(value) is not int or value < 0:
                    errors.append(
                        f"artifact {identifier!r}: usage_provenance."
                        f"{table_name}.{key} must be a non-negative integer"
                    )
            if all(type(table_usage.get(key)) is int for key in (
                "actual",
                "estimated",
                "unknown",
            )):
                normalized_usage[table_name] = {
                    key: table_usage[key]
                    for key in ("actual", "estimated", "unknown")
                }
                expected_rows = normalized_row_counts.get(table_name)
                if (
                    expected_rows is not None
                    and sum(normalized_usage[table_name].values())
                    != expected_rows
                ):
                    errors.append(
                        f"artifact {identifier!r}: usage_provenance."
                        f"{table_name} must sum to row_counts"
                    )
            if (
                table_name == "llm_call_attempts"
                and not _is_exact_int(table_usage.get("unknown"), 0)
            ):
                errors.append(
                    f"artifact {identifier!r}: usage_provenance."
                    f"{table_name}.unknown must be 0"
                )

    legacy = payload.get("legacy_unreconstructable")
    required_legacy_keys = (
        "calls_missing_accounting_status",
        "calls_missing_usage_provenance",
        "calls_without_attempt_ledger",
        "total_unique_calls",
    )
    if not isinstance(legacy, dict):
        errors.append(
            f"artifact {identifier!r}: legacy_unreconstructable must be an object"
        )
        return None
    if set(legacy) != set(required_legacy_keys):
        errors.append(
            f"artifact {identifier!r}: legacy_unreconstructable keys are invalid"
        )
    for key in required_legacy_keys:
        value = legacy.get(key)
        if type(value) is not int or value < 0:
            errors.append(
                f"artifact {identifier!r}: legacy_unreconstructable.{key} "
                "must be a non-negative integer"
            )
    total = legacy.get("total_unique_calls")
    if type(total) is not int or total < 0:
        return None
    calls_missing_status = legacy.get("calls_missing_accounting_status")
    calls_missing_usage = legacy.get("calls_missing_usage_provenance")
    calls_without_attempts = legacy.get("calls_without_attempt_ledger")
    call_rows = normalized_row_counts.get("llm_calls")
    if (
        type(calls_missing_status) is int
        and normalized_status_counts.get("llm_calls", {}).get("<null>", 0)
        != calls_missing_status
    ):
        errors.append(
            f"artifact {identifier!r}: legacy missing status count must match "
            "status_counts.llm_calls['<null>']"
        )
    if (
        type(calls_missing_usage) is int
        and normalized_usage.get("llm_calls", {}).get("unknown")
        != calls_missing_usage
    ):
        errors.append(
            f"artifact {identifier!r}: legacy missing usage count must match "
            "usage_provenance.llm_calls.unknown"
        )
    legacy_components = (
        calls_missing_status,
        calls_missing_usage,
        calls_without_attempts,
    )
    if (
        call_rows is not None
        and (
            any(
                type(value) is not int or value < 0 or value > call_rows
                for value in legacy_components
            )
            or total > call_rows
            or total < max(
                value for value in legacy_components if type(value) is int
            )
        )
    ):
        errors.append(
            f"artifact {identifier!r}: legacy_unreconstructable counts violate "
            "row-count bounds"
        )
    return {
        "legacy_unreconstructable_count": total,
        "row_counts": normalized_row_counts,
        "status_counts": normalized_status_counts,
        "usage_provenance": normalized_usage,
        "legacy_unreconstructable": {
            key: legacy.get(key) for key in required_legacy_keys
        },
    }


def _local_xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_junit_artifact(
    snapshot: bytes | None,
    identifier: str,
    errors: list[str],
    *,
    allowed_skips: dict[str, tuple[str, str, str]],
    max_skipped: int,
    minimum_tests: int,
) -> list[str]:
    if snapshot is None:
        errors.append(
            f"artifact {identifier!r}: validated byte snapshot is unavailable"
        )
        return []
    try:
        root = ET.fromstring(snapshot)
    except (ET.ParseError, RuntimeError, ValueError) as exc:
        errors.append(f"artifact {identifier!r}: invalid JUnit XML: {exc}")
        return []
    root_name = _local_xml_name(root.tag)
    if root_name not in {"testsuite", "testsuites"}:
        errors.append(
            f"artifact {identifier!r}: JUnit root must be testsuite or testsuites"
        )
        return []
    testcases = [
        element
        for element in root.iter()
        if _local_xml_name(element.tag) == "testcase"
    ]
    if not testcases:
        errors.append(f"artifact {identifier!r}: JUnit has no testcases")
        return []
    testcase_names: list[str] = []
    testcase_identities: set[tuple[str, str, str]] = set()
    failures = 0
    error_count = 0
    skipped = 0
    skipped_cases: list[tuple[str, str, str, str]] = []
    for testcase in testcases:
        name = testcase.attrib.get("name", "").strip()
        if not name:
            errors.append(f"artifact {identifier!r}: testcase name is empty")
            continue
        identity = (
            testcase.attrib.get("classname", ""),
            testcase.attrib.get("file", ""),
            name,
        )
        if identity in testcase_identities:
            errors.append(
                f"artifact {identifier!r}: duplicate testcase identity "
                f"{identity!r}"
            )
        testcase_identities.add(identity)
        testcase_names.append(name)
        child_names = {_local_xml_name(child.tag) for child in testcase}
        if "failure" in child_names:
            failures += 1
        if "error" in child_names:
            error_count += 1
        skipped_elements = [
            child for child in testcase if _local_xml_name(child.tag) == "skipped"
        ]
        if skipped_elements:
            skipped += 1
            if len(skipped_elements) != 1:
                errors.append(
                    f"artifact {identifier!r}: skipped testcase {name!r} "
                    "must contain exactly one skipped element"
                )
            skipped_element = skipped_elements[0]
            skipped_cases.append(
                (
                    name,
                    identity[0],
                    skipped_element.attrib.get("type", "").strip(),
                    skipped_element.attrib.get("message", "").strip(),
                )
            )
    for suite in (
        element
        for element in root.iter()
        if _local_xml_name(element.tag) in {"testsuite", "testsuites"}
    ):
        suite_testcases = [
            element
            for element in suite.iter()
            if _local_xml_name(element.tag) == "testcase"
        ]
        suite_counts = {
            "tests": len(suite_testcases),
            "failures": sum(
                1
                for testcase in suite_testcases
                if any(
                    _local_xml_name(child.tag) == "failure"
                    for child in testcase
                )
            ),
            "errors": sum(
                1
                for testcase in suite_testcases
                if any(
                    _local_xml_name(child.tag) == "error"
                    for child in testcase
                )
            ),
            "skipped": sum(
                1
                for testcase in suite_testcases
                if any(
                    _local_xml_name(child.tag) == "skipped"
                    for child in testcase
                )
            ),
        }
        for attribute, actual in suite_counts.items():
            configured = suite.attrib.get(attribute)
            if configured is None:
                continue
            try:
                configured_count = int(configured)
            except ValueError:
                configured_count = -1
            if configured_count != actual:
                errors.append(
                    f"artifact {identifier!r}: JUnit {attribute} attribute "
                    f"{configured!r} does not match recomputed {actual}"
                )
    if failures or error_count:
        errors.append(
            f"artifact {identifier!r}: JUnit contains failed/error tests "
            f"(failures={failures}, errors={error_count})"
        )
    if len(testcases) < minimum_tests:
        errors.append(
            f"artifact {identifier!r}: JUnit has {len(testcases)} tests; "
            f"minimum is {minimum_tests}"
        )
    passed = len(testcases) - failures - error_count - skipped
    if passed <= 0:
        errors.append(f"artifact {identifier!r}: JUnit has no passed tests")
    if skipped > max_skipped:
        errors.append(
            f"artifact {identifier!r}: JUnit contains {skipped} skipped tests; "
            f"maximum is {max_skipped}"
        )
    observed_allowed_skips: set[str] = set()
    for name, classname, skip_type, skip_message in skipped_cases:
        skip_policy = allowed_skips.get(name)
        if skip_policy is None:
            errors.append(
                f"artifact {identifier!r}: JUnit contains unapproved skipped "
                f"test {name!r}"
            )
            continue
        if name in observed_allowed_skips:
            errors.append(
                f"artifact {identifier!r}: approved skipped test {name!r} "
                "appears more than once"
            )
        observed_allowed_skips.add(name)
        expected_classname, expected_reason, reason_match = skip_policy
        if classname != expected_classname:
            errors.append(
                f"artifact {identifier!r}: approved skipped test {name!r} "
                f"has unexpected classname {classname!r}"
            )
        if skip_type != "pytest.skip":
            errors.append(
                f"artifact {identifier!r}: approved skipped test {name!r} "
                "must use pytest.skip"
            )
        reason_matches = (
            skip_message == expected_reason
            if reason_match == "exact"
            else skip_message.startswith(f"{expected_reason}:")
        )
        if not reason_matches:
            errors.append(
                f"artifact {identifier!r}: approved skipped test {name!r} "
                "does not contain its audited skip reason"
            )
    return testcase_names


def _validate_c1b_artifact_contents(
    manifest: OutcomeEvidenceManifest,
    snapshots: dict[str, bytes],
) -> tuple[list[str], dict[str, object]]:
    errors: list[str] = []
    context: dict[str, object] = {}
    parsed_command_starts: list[datetime] = []
    for command in manifest.commands:
        if command.started_at is None:
            continue
        try:
            parsed_command_starts.append(
                datetime.fromisoformat(
                    command.started_at.replace("Z", "+00:00")
                ).astimezone(UTC)
            )
        except ValueError:
            continue
    try:
        manifest_created_at = datetime.fromisoformat(
            manifest.created_at.replace("Z", "+00:00")
        ).astimezone(UTC)
    except ValueError:
        manifest_created_at = None
    run_started_at = min(parsed_command_starts) if parsed_command_starts else None
    process_scan = _read_json_artifact(
        snapshots.get("process-scan.json"), "process-scan.json", errors
    )
    if process_scan is not None:
        _require_exact_keys(
            process_scan,
            {
                "captured_at_utc",
                "actual_database",
                "wal_size_bytes",
                "writer_matches",
                "listening_connections",
            },
            "process-scan.json",
            errors,
        )
        actual_database = process_scan.get("actual_database")
        if (
            not isinstance(actual_database, str)
            or actual_database.replace("/", "\\").casefold()
            != _C1B_CANONICAL_ACTUAL_DATABASE.casefold()
        ):
            errors.append(
                "artifact 'process-scan.json': actual_database must name the "
                "canonical actual database"
            )
        if process_scan.get("writer_matches") != []:
            errors.append(
                "artifact 'process-scan.json': writer_matches must be []"
            )
        wal_size = process_scan.get("wal_size_bytes")
        if type(wal_size) is not int or wal_size < 0:
            errors.append(
                "artifact 'process-scan.json': wal_size_bytes must be a "
                "non-negative integer"
            )
        listening_connections = process_scan.get("listening_connections")
        if not isinstance(listening_connections, list) or any(
            not isinstance(connection, dict)
            or set(connection) != {"process_id", "local_address", "local_port"}
            or type(connection.get("process_id")) is not int
            or not isinstance(connection.get("local_address"), str)
            or type(connection.get("local_port")) is not int
            for connection in (
                listening_connections
                if isinstance(listening_connections, list)
                else ()
            )
        ):
            errors.append(
                "artifact 'process-scan.json': listening_connections must be "
                "a typed listener snapshot"
            )
        captured_at = _parse_c1b_timestamp(
            process_scan.get("captured_at_utc")
            if isinstance(process_scan.get("captured_at_utc"), str)
            else None,
            "artifact 'process-scan.json': captured_at_utc",
            errors,
        )
        if (
            captured_at is not None
            and run_started_at is not None
            and manifest_created_at is not None
            and not (
                captured_at <= run_started_at <= manifest_created_at
                and (run_started_at - captured_at).total_seconds() <= 300
            )
        ):
            errors.append(
                "artifact 'process-scan.json': captured_at_utc must be no more "
                "than 5 minutes before the first evidence command"
            )

    backup_snapshot = snapshots.get("database-before-0065.db")
    backup_meta = _read_json_artifact(
        snapshots.get("database-before-0065.db.meta.json"),
        "database-before-0065.db.meta.json",
        errors,
    )
    backup_page_count: int | None = None
    if backup_snapshot is None:
        errors.append(
            "artifact 'database-before-0065.db': validated byte snapshot is "
            "unavailable"
        )
    else:
        if len(backup_snapshot) <= 1024 * 1024:
            errors.append(
                "artifact 'database-before-0065.db': backup must be larger "
                "than 1 MiB"
            )
        connection: sqlite3.Connection | None = None
        try:
            # A database whose header records WAL mode cannot be queried after
            # ``Connection.deserialize`` on Windows: SQLite tries to resolve a
            # journal beside the in-memory database and reports "unable to open
            # database file".  Materialize only the already-hashed snapshot in
            # an isolated writable directory, then inspect that exact snapshot
            # through a read-only URI.  This keeps the TOCTOU boundary while
            # giving SQLite a real location for any transient WAL bookkeeping.
            with tempfile.TemporaryDirectory(
                prefix="outcome-evidence-sqlite-"
            ) as temp_dir:
                snapshot_path = Path(temp_dir) / "database-before-0065.db"
                snapshot_path.write_bytes(backup_snapshot)
                connection = sqlite3.connect(
                    f"{snapshot_path.resolve().as_uri()}?mode=ro",
                    uri=True,
                )
                connection.execute("PRAGMA query_only=ON")
                integrity_row = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                integrity = str(integrity_row[0]) if integrity_row else "unknown"
                revision_rows = connection.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchall()
                backup_page_count = int(
                    connection.execute("PRAGMA page_count").fetchone()[0]
                )
                backup_tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                required_legacy_tables = {
                    "evaluation_experiments",
                    "evaluation_pairs",
                    "evaluation_votes",
                    "scene_run_states",
                }
                if not required_legacy_tables.issubset(backup_tables):
                    errors.append(
                        "artifact 'database-before-0065.db': required 0064 tables "
                        "are missing"
                    )
                scene_columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(scene_run_states)"
                    )
                }
                required_scene_columns = {
                    "latest_valid_draft_row_id",
                    "run_policy",
                    "scene_token_budget",
                    "scene_tokens_used",
                }
                if not required_scene_columns.issubset(scene_columns):
                    errors.append(
                        "artifact 'database-before-0065.db': required 0064 "
                        "scene_run_states columns are missing"
                    )
                if integrity != "ok":
                    errors.append(
                        "artifact 'database-before-0065.db': integrity is not ok"
                    )
                if revision_rows != [("20260712_0064",)]:
                    errors.append(
                        "artifact 'database-before-0065.db': revision must be "
                        "'20260712_0064'"
                    )
                connection.close()
                connection = None
        except (AttributeError, sqlite3.Error) as exc:
            errors.append(
                f"artifact 'database-before-0065.db': invalid SQLite: {exc}"
            )
        finally:
            if connection is not None:
                connection.close()
    if backup_meta is not None:
        _require_exact_keys(
            backup_meta,
            {"source", "checksum", "page_count", "integrity", "created_at", "tool"},
            "database-before-0065.db.meta.json",
            errors,
        )
        backup_artifact = next(
            (
                artifact
                for artifact in manifest.artifacts
                if _normalize_relative_artifact_path(artifact.path)[0]
                == "database-before-0065.db"
            ),
            None,
        )
        expected_meta = {
            "checksum": (
                backup_artifact.sha256 if backup_artifact is not None else None
            ),
            "integrity": "ok",
            "tool": "db_backup.v1",
            "page_count": backup_page_count,
        }
        for key, expected in expected_meta.items():
            if backup_meta.get(key) != expected:
                errors.append(
                    "artifact 'database-before-0065.db.meta.json': "
                    f"{key} must equal {expected!r}"
                )
        source = backup_meta.get("source")
        if (
            not isinstance(source, str)
            or source.replace("/", "\\").casefold()
            != _C1B_CANONICAL_ACTUAL_DATABASE.casefold()
        ):
            errors.append(
                "artifact 'database-before-0065.db.meta.json': source must name "
                "the canonical actual database"
            )
        backup_created_at = _parse_c1b_timestamp(
            backup_meta.get("created_at")
            if isinstance(backup_meta.get("created_at"), str)
            else None,
            "artifact 'database-before-0065.db.meta.json': created_at",
            errors,
        )
        if (
            backup_created_at is not None
            and run_started_at is not None
            and manifest_created_at is not None
            and not (
                run_started_at.replace(microsecond=0)
                <= backup_created_at
                <= manifest_created_at
            )
        ):
            errors.append(
                "artifact 'database-before-0065.db.meta.json': created_at must "
                "be within the evidence run window"
            )

    drill_preflight = _read_json_artifact(
        snapshots.get("drill-preflight.json"), "drill-preflight.json", errors
    )
    actual_preflight = _read_json_artifact(
        snapshots.get("actual-preflight-after.json"),
        "actual-preflight-after.json",
        errors,
    )
    _validate_preflight_artifact(
        drill_preflight, "drill-preflight.json", errors
    )
    _validate_preflight_artifact(
        actual_preflight, "actual-preflight-after.json", errors
    )

    def normalized_report_path(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.replace("/", "\\").casefold()

    actual_path_key = _C1B_CANONICAL_ACTUAL_DATABASE.casefold()
    actual_preflight_path = (
        normalized_report_path(actual_preflight.get("path"))
        if actual_preflight is not None
        else None
    )
    if actual_preflight_path != actual_path_key:
        errors.append(
            "artifact 'actual-preflight-after.json': path must name the "
            "canonical actual database"
        )
    drill_preflight_path = (
        normalized_report_path(drill_preflight.get("path"))
        if drill_preflight is not None
        else None
    )
    if (
        drill_preflight_path is None
        or not drill_preflight_path.endswith("\\migration-drill.db")
    ):
        errors.append(
            "artifact 'drill-preflight.json': path must name migration-drill.db"
        )

    drill_audit = _read_json_artifact(
        snapshots.get("migration-drill-accounting.json"),
        "migration-drill-accounting.json",
        errors,
    )
    actual_audit = _read_json_artifact(
        snapshots.get("actual-accounting.json"),
        "actual-accounting.json",
        errors,
    )
    drill_audit_path = (
        normalized_report_path(drill_audit.get("database", {}).get("path"))
        if drill_audit is not None
        and isinstance(drill_audit.get("database"), dict)
        else None
    )
    actual_audit_path = (
        normalized_report_path(actual_audit.get("database", {}).get("path"))
        if actual_audit is not None
        and isinstance(actual_audit.get("database"), dict)
        else None
    )
    if drill_audit_path != drill_preflight_path:
        errors.append(
            "drill preflight and accounting audit database paths must match"
        )
    if actual_audit_path != actual_path_key:
        errors.append(
            "artifact 'actual-accounting.json': database.path must name the "
            "canonical actual database"
        )
    drill_audit_signature = _validate_accounting_audit_artifact(
        drill_audit, "migration-drill-accounting.json", errors
    )
    actual_audit_signature = _validate_accounting_audit_artifact(
        actual_audit, "actual-accounting.json", errors
    )
    if (
        drill_audit_signature is not None
        and actual_audit_signature is not None
    ):
        if drill_audit_signature != actual_audit_signature:
            errors.append(
                "drill and actual accounting audit recomputed counts must match"
            )
        else:
            context["legacy_unreconstructable_count"] = (
                actual_audit_signature["legacy_unreconstructable_count"]
            )

    inventory = _read_json_artifact(
        snapshots.get("llm-outlet-inventory.json"),
        "llm-outlet-inventory.json",
        errors,
    )
    if inventory is not None:
        _require_exact_keys(
            inventory,
            {"schema", "source_root", "summary", "outlets"},
            "llm-outlet-inventory.json",
            errors,
        )
        summary = inventory.get("summary")
        outlets = inventory.get("outlets")
        if inventory.get("schema") != "llm-outlet-inventory-v1":
            errors.append(
                "artifact 'llm-outlet-inventory.json': schema must be "
                "'llm-outlet-inventory-v1'"
            )
        source_root = inventory.get("source_root")
        normalized_source_root = (
            source_root.replace("/", "\\").rstrip("\\").casefold()
            if isinstance(source_root, str)
            else ""
        )
        if not normalized_source_root.endswith(
            "\\backend\\src\\novel_system"
        ):
            errors.append(
                "artifact 'llm-outlet-inventory.json': source_root must name "
                "backend/src/novel_system"
            )
        if not isinstance(summary, dict) or not isinstance(outlets, list):
            errors.append(
                "artifact 'llm-outlet-inventory.json': summary/outlets invalid"
            )
        else:
            if set(summary) != {
                "application_outlets",
                "unified",
                "unaccounted",
            }:
                errors.append(
                    "artifact 'llm-outlet-inventory.json': summary keys are invalid"
                )
            application_outlets = _nested_int(summary, "application_outlets")
            unified = _nested_int(summary, "unified")
            unaccounted = _nested_int(summary, "unaccounted")
            expected_outlet_keys = {
                "identity",
                "path",
                "qualname",
                "line",
                "kind",
                "expression",
                "unified",
            }
            identities = [
                outlet.get("identity")
                for outlet in outlets
                if isinstance(outlet, dict)
            ]
            outlets_are_valid = all(
                isinstance(outlet, dict)
                and set(outlet) == expected_outlet_keys
                and isinstance(outlet.get("identity"), str)
                and bool(str(outlet.get("identity")).strip())
                and isinstance(outlet.get("path"), str)
                and bool(str(outlet.get("path")).strip())
                and str(outlet.get("path")).replace("\\", "/").endswith(".py")
                and ".." not in str(outlet.get("path")).replace("\\", "/").split("/")
                and isinstance(outlet.get("qualname"), str)
                and bool(str(outlet.get("qualname")).strip())
                and type(outlet.get("line")) is int
                and outlet.get("line", 0) > 0
                and isinstance(outlet.get("kind"), str)
                and bool(str(outlet.get("kind")).strip())
                and isinstance(outlet.get("expression"), str)
                and bool(str(outlet.get("expression")).strip())
                and outlet.get("unified") is True
                for outlet in outlets
            )
            if (
                application_outlets is None
                or application_outlets <= 0
                or unified != application_outlets
                or unaccounted != 0
                or len(outlets) != application_outlets
                or not outlets_are_valid
                or len(identities) != len(set(identities))
            ):
                errors.append(
                    "artifact 'llm-outlet-inventory.json': outlet counts must "
                    "recompute to positive/all unified/zero unaccounted"
                )
            else:
                context["inventory_counts"] = {
                    "production_outlets": application_outlets,
                    "accounted_outlets": unified,
                    "unaccounted_outlets": unaccounted,
                }

    junit_policies = {
        "migration-focused.junit.xml": (0, {}),
        "c1b-gates.junit.xml": (0, {}),
        "backend-full.junit.xml": (
            len(_C1B_BACKEND_ALLOWED_SKIPS),
            _C1B_BACKEND_ALLOWED_SKIPS,
        ),
        "frontend.junit.xml": (0, {}),
    }
    for junit_path, (max_skipped, allowed_skips) in junit_policies.items():
        testcase_names = _parse_junit_artifact(
            snapshots.get(junit_path),
            junit_path,
            errors,
            allowed_skips=allowed_skips,
            max_skipped=max_skipped,
            minimum_tests=_C1B_JUNIT_MIN_TESTS[junit_path],
        )
        if junit_path == "c1b-gates.junit.xml":
            context["c1b_testcase_names"] = testcase_names
    build_snapshot = snapshots.get("frontend-build.log")
    if build_snapshot is None:
        errors.append(
            "artifact 'frontend-build.log': validated byte snapshot is unavailable"
        )
    else:
        try:
            if build_snapshot.startswith((b"\xff\xfe", b"\xfe\xff")):
                build_log = build_snapshot.decode("utf-16")
            elif b"\x00" in build_snapshot[:256]:
                build_log = build_snapshot.decode("utf-16-le")
            else:
                build_log = build_snapshot.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            errors.append(
                f"artifact 'frontend-build.log': unsupported text encoding: {exc}"
            )
        else:
            normalized_log = build_log.casefold()
            if (
                "building for production" not in normalized_log
                or re.search(r"\bbuilt in\s+\d", normalized_log) is None
            ):
                errors.append(
                    "artifact 'frontend-build.log': missing Vite production "
                    "build completion markers"
                )
    return errors, context


def _validate_c1b_gate_details(
    gate: EvidenceGate,
    artifact_paths: set[str],
    evidence_context: dict[str, object],
) -> list[str]:
    errors: list[str] = []
    prefix = f"gate {gate.code!r}"
    expected_detail_keys = {"counts", "artifact_refs"}
    if gate.code == "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED":
        expected_detail_keys.add("enforced_for_new_calls")
    if set(gate.details) != expected_detail_keys:
        errors.append(
            f"{prefix}: details must contain exactly "
            + ", ".join(sorted(expected_detail_keys))
        )
    if (
        gate.code == "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED"
        and gate.details.get("enforced_for_new_calls") is not True
    ):
        errors.append(f"{prefix}: details.enforced_for_new_calls must be true")

    counts = gate.details.get("counts")
    refs = gate.details.get("artifact_refs")
    if not isinstance(counts, dict):
        errors.append(f"{prefix}: details.counts must be an object")
        counts = {}
    if not isinstance(refs, list) or not refs:
        errors.append(
            f"{prefix}: details.artifact_refs must be a non-empty list"
        )
        refs = []

    rule = _C1B_GATE_COUNT_RULES[gate.code]
    expected_count_keys = set(rule["keys"])
    if set(counts) != expected_count_keys:
        errors.append(
            f"{prefix}: details.counts must contain exactly "
            + ", ".join(sorted(expected_count_keys))
        )

    for key in expected_count_keys:
        value = counts.get(key)
        if type(value) is not int or value < 0:
            errors.append(
                f"{prefix}: details.counts.{key} must be a non-negative integer"
            )
    for key in rule["positive"]:
        value = counts.get(key)
        if type(value) is not int or value <= 0:
            errors.append(
                f"{prefix}: details.counts.{key} must be a positive integer"
            )
    for key in rule["zero"]:
        if not _is_exact_int(counts.get(key), 0):
            errors.append(f"{prefix}: details.counts.{key} must be integer 0")
    for left_key, right_key in rule["equal"]:
        if counts.get(left_key) != counts.get(right_key):
            errors.append(
                f"{prefix}: details.counts.{left_key} must equal "
                f"details.counts.{right_key}"
            )

    normalized_refs: list[str] = []
    for index, ref in enumerate(refs):
        if not isinstance(ref, str):
            errors.append(
                f"{prefix}: details.artifact_refs[{index}] must be a string"
            )
            continue
        normalized_ref, path_error = _normalize_relative_artifact_path(ref)
        if path_error is not None or normalized_ref is None:
            errors.append(
                f"{prefix}: details.artifact_refs[{index}] {path_error}"
            )
            continue
        normalized_refs.append(normalized_ref)
        if normalized_ref not in artifact_paths:
            errors.append(
                f"{prefix}: artifact reference {normalized_ref!r} is not in "
                "the manifest"
            )
    if len(normalized_refs) != len(set(normalized_refs)):
        errors.append(f"{prefix}: duplicate artifact reference")
    required_ref = str(rule["artifact"])
    if required_ref not in normalized_refs:
        errors.append(
            f"{prefix}: required artifact reference {required_ref!r} is missing"
        )

    if gate.code == "ALL_PRODUCTION_LLM_OUTLETS_ACCOUNTED":
        inventory_counts = evidence_context.get("inventory_counts")
        if counts != inventory_counts:
            errors.append(
                f"{prefix}: details.counts must exactly match the recomputed "
                "llm-outlet-inventory.json summary"
            )
    else:
        testcase_names = evidence_context.get("c1b_testcase_names")
        selectors = _C1B_GATE_TEST_SELECTORS[gate.code]
        matched_selectors = (
            [
                selector
                for selector in selectors
                if any(
                    testcase_name == selector
                    or testcase_name.startswith(f"{selector}[")
                    for testcase_name in testcase_names
                )
            ]
            if isinstance(testcase_names, list)
            else []
        )
        missing_selectors = [
            selector for selector in selectors if selector not in matched_selectors
        ]
        if missing_selectors:
            errors.append(
                f"{prefix}: c1b-gates.junit.xml is missing required test "
                "coverage: "
                + ", ".join(missing_selectors)
            )
        if counts.get("evidence_cases") != len(matched_selectors):
            errors.append(
                f"{prefix}: details.counts.evidence_cases must equal "
                f"recomputed JUnit coverage count {len(matched_selectors)}"
            )
        recomputed_cases = len(matched_selectors)
        direct_case_keys: tuple[str, ...] = ()
        if gate.code == "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED":
            direct_case_keys = ("physical_attempts", "accounted_attempts")
        elif gate.code == "MISSING_USAGE_ESTIMATED":
            direct_case_keys = (
                "missing_usage_attempts",
                "estimated_usage_attempts",
            )
        elif gate.code == "FAILED_CALLS_CHARGED":
            direct_case_keys = ("failed_attempts", "charged_failed_attempts")
        elif gate.code in _C1B_PRIMARY_CASE_COUNT_KEYS:
            direct_case_keys = (_C1B_PRIMARY_CASE_COUNT_KEYS[gate.code],)
        for key in direct_case_keys:
            if counts.get(key) != recomputed_cases:
                errors.append(
                    f"{prefix}: details.counts.{key} must equal recomputed "
                    f"JUnit coverage count {recomputed_cases}"
                )
        if (
            gate.code == "RETRY_AND_DEGRADE_BUDGETED"
            and (
                counts.get("retry_attempts", 0)
                + counts.get("degrade_attempts", 0)
                != recomputed_cases
            )
        ):
            errors.append(
                f"{prefix}: retry_attempts + degrade_attempts must equal "
                f"recomputed JUnit coverage count {recomputed_cases}"
            )
    if gate.code == "ALL_PHYSICAL_PROVIDER_ATTEMPTS_ACCOUNTED":
        legacy_count = evidence_context.get("legacy_unreconstructable_count")
        if counts.get("legacy_unreconstructable_count") != legacy_count:
            errors.append(
                f"{prefix}: details.counts.legacy_unreconstructable_count must "
                "match drill/actual accounting audits"
            )
    return errors


def validate_manifest_evidence(
    manifest: OutcomeEvidenceManifest,
    artifact_root: str | Path,
    *,
    profile: Literal["c1b"] | None = None,
    snapshot_sink: dict[str, bytes] | None = None,
) -> list[str]:
    errors: list[str] = []

    if not manifest.commands:
        errors.append("commands: at least one command is required")
    for index, command in enumerate(manifest.commands):
        identifier = f"command[{index}] {command.command!r}"
        if not command.command.strip():
            errors.append(f"{identifier}: command string is empty")
        if not command.started_at:
            errors.append(f"{identifier}: started_at is required")
        if not command.ended_at:
            errors.append(f"{identifier}: ended_at is required")
        if not command.expected_exit_codes:
            errors.append(f"{identifier}: expected_exit_codes is empty")
        elif command.exit_code not in command.expected_exit_codes:
            errors.append(
                f"{identifier}: exit_code {command.exit_code} is not in "
                f"expected_exit_codes {command.expected_exit_codes}"
            )

    if not manifest.gates:
        errors.append("gates: at least one gate is required")
    for gate in manifest.gates:
        if not gate.passed:
            errors.append(f"gate {gate.code!r}: failed")
        errors.extend(
            _validate_known_gate_details(gate, manifest.database_revision)
        )

    if not manifest.artifacts:
        errors.append("manifest has no artifacts")
    root = Path(artifact_root)
    resolved_root: Path | None = None
    if profile == "c1b":
        if not root.exists():
            errors.append(f"artifact root {str(root)!r}: directory does not exist")
        elif not root.is_dir():
            errors.append(f"artifact root {str(root)!r}: path is not a directory")
        else:
            try:
                resolved_root = root.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                errors.append(
                    f"artifact root {str(root)!r}: could not resolve: {exc}"
                )
    seen_artifact_paths: set[str] = set()
    seen_resolved_artifact_paths: set[str] = set()
    seen_file_identities: set[tuple[int, int]] = set()
    for artifact in manifest.artifacts:
        identifier = f"artifact {artifact.path!r}"
        normalized_path: str | None = None
        if profile == "c1b":
            normalized_path, path_error = _normalize_relative_artifact_path(
                artifact.path
            )
            if path_error is not None or normalized_path is None:
                errors.append(
                    f"{identifier}: unsafe for artifact root: {path_error}"
                )
                continue
            if normalized_path in seen_artifact_paths:
                errors.append(f"duplicate artifact path {normalized_path!r}")
                continue
            seen_artifact_paths.add(normalized_path)
            if resolved_root is None:
                continue
            configured_path = Path(*normalized_path.split("/"))
            artifact_path = resolved_root / configured_path
            try:
                resolved_artifact_path = artifact_path.resolve(strict=False)
            except (OSError, RuntimeError) as exc:
                errors.append(f"{identifier}: could not resolve path: {exc}")
                continue
            if not resolved_artifact_path.is_relative_to(resolved_root):
                errors.append(
                    f"{identifier}: resolved path escapes artifact root"
                )
                continue
            resolved_path_key = os.path.normcase(str(resolved_artifact_path))
            if resolved_path_key in seen_resolved_artifact_paths:
                errors.append(
                    f"duplicate artifact path resolving to "
                    f"{str(resolved_artifact_path)!r}"
                )
                continue
            seen_resolved_artifact_paths.add(resolved_path_key)
            artifact_path = resolved_artifact_path
        else:
            configured_path = Path(artifact.path)
            artifact_path = (
                configured_path
                if configured_path.is_absolute()
                else root / configured_path
            )
        try:
            artifact_stat = artifact_path.stat()
        except OSError as exc:
            errors.append(f"{identifier}: file does not exist or cannot be read: {exc}")
            continue
        if not stat.S_ISREG(artifact_stat.st_mode):
            errors.append(f"{identifier}: path is not a regular disk file")
            continue
        try:
            capture_limit: int | None = None
            if profile == "c1b":
                capture_limit = (
                    _C1B_MAX_SQLITE_ARTIFACT_BYTES
                    if normalized_path is not None
                    and normalized_path.endswith(".db")
                    else _C1B_MAX_STRUCTURED_ARTIFACT_BYTES
                )
            (
                actual_sha256,
                actual_size,
                hashed_stat,
                captured_bytes,
            ) = _hash_regular_file(
                artifact_path,
                capture_limit=capture_limit,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{identifier}: could not read file: {exc}")
            continue
        if profile == "c1b":
            opened_identity = (hashed_stat.st_dev, hashed_stat.st_ino)
            observed_identity = (artifact_stat.st_dev, artifact_stat.st_ino)
            if opened_identity != observed_identity:
                errors.append(f"{identifier}: file identity changed before hashing")
                continue
            if hashed_stat.st_nlink != 1:
                errors.append(
                    f"{identifier}: hard-linked artifacts are not allowed"
                )
                continue
            if hashed_stat.st_ino and opened_identity in seen_file_identities:
                errors.append(f"duplicate artifact file identity for {identifier}")
                continue
            if hashed_stat.st_ino:
                seen_file_identities.add(opened_identity)
            try:
                post_hash_path = artifact_path.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                errors.append(
                    f"{identifier}: could not re-resolve path after hashing: {exc}"
                )
                continue
            if (
                resolved_root is None
                or not post_hash_path.is_relative_to(resolved_root)
                or post_hash_path != artifact_path
            ):
                errors.append(
                    f"{identifier}: path changed or escaped artifact root "
                    "while hashing"
                )
                continue
        sha256_matches = actual_sha256 == artifact.sha256
        if not sha256_matches:
            errors.append(
                f"{identifier}: sha256 mismatch "
                f"(expected {artifact.sha256}, got {actual_sha256})"
            )
        size_matches = True
        if profile == "c1b":
            if artifact.size_bytes is None:
                size_matches = False
                errors.append(f"{identifier}: size_bytes is required")
            elif artifact.size_bytes <= 0:
                size_matches = False
                errors.append(f"{identifier}: size_bytes must be positive")
            elif actual_size != artifact.size_bytes:
                size_matches = False
                errors.append(
                    f"{identifier}: size_bytes mismatch "
                    f"(expected {artifact.size_bytes}, got {actual_size})"
                )
            if capture_limit is not None and captured_bytes is None:
                size_matches = False
                errors.append(
                    f"{identifier}: exceeds safe semantic parse limit "
                    f"{capture_limit} bytes"
                )
            if (
                snapshot_sink is not None
                and normalized_path is not None
                and capture_limit is not None
                and captured_bytes is not None
                and sha256_matches
                and size_matches
            ):
                snapshot_sink[normalized_path] = captured_bytes
        elif (
            artifact.size_bytes is not None
            and actual_size != artifact.size_bytes
        ):
            errors.append(
                f"{identifier}: size_bytes mismatch "
                f"(expected {artifact.size_bytes}, got {actual_size})"
            )

    return errors


def validate_c0_gate_profile(
    manifest: OutcomeEvidenceManifest,
) -> list[str]:
    present_gate_codes = {gate.code for gate in manifest.gates}
    missing_gate_codes = [
        code for code in C0_REQUIRED_GATE_CODES if code not in present_gate_codes
    ]
    if not missing_gate_codes:
        return []
    return [
        "profile 'c0': missing required gates: "
        + ", ".join(missing_gate_codes)
    ]


def validate_c1b_gate_profile(
    manifest: OutcomeEvidenceManifest,
    artifact_snapshots: dict[str, bytes],
) -> list[str]:
    errors: list[str] = []
    prefix = "profile 'c1b'"
    if manifest.schema_version != "outcome-evidence-v1":
        errors.append(f"{prefix}: schema must be 'outcome-evidence-v1'")
    if "schema_version" not in manifest.model_fields_set:
        errors.append(f"{prefix}: schema is required")
    if not manifest.run_id.strip():
        errors.append(f"{prefix}: run_id is required")
    if manifest.database_revision != C1B_DATABASE_REVISION:
        errors.append(
            f"{prefix}: database_revision must be {C1B_DATABASE_REVISION!r}"
        )
    if re.fullmatch(r"[0-9a-f]{40}", manifest.git_commit) is None:
        errors.append(
            f"{prefix}: git_commit must be 40 lowercase hexadecimal characters"
        )
    if manifest.provenance != "offline":
        errors.append(f"{prefix}: provenance must be 'offline'")
    expected_config_hashes = {"models.yaml", "prompts.yaml", "pricing.yaml"}
    if set(manifest.config_hashes) != expected_config_hashes:
        errors.append(
            f"{prefix}: config_hashes must contain exactly "
            + ", ".join(sorted(expected_config_hashes))
        )
    for config_name, config_hash in manifest.config_hashes.items():
        if re.fullmatch(r"[0-9a-f]{64}", config_hash) is None:
            errors.append(
                f"{prefix}: config_hashes[{config_name!r}] must be a "
                "lowercase sha256"
            )
    if manifest.model_routes != {}:
        errors.append(
            f"{prefix}: model_routes must be empty for offline C1B evidence"
        )

    sensitive_paths = _offline_sensitive_detail_paths(
        manifest.model_dump(mode="json", by_alias=True),
        prefix="manifest",
    )
    for path in sensitive_paths:
        errors.append(f"{prefix}: offline evidence cannot assert {path}")

    if "created_at" not in manifest.model_fields_set:
        errors.append(f"{prefix}: created_at is required")
    created_at = _parse_c1b_timestamp(
        manifest.created_at,
        f"{prefix}: created_at",
        errors,
    )
    for index, command in enumerate(manifest.commands):
        command_prefix = f"{prefix}: command[{index}]"
        started_at = _parse_c1b_timestamp(
            command.started_at,
            f"{command_prefix}.started_at",
            errors,
        )
        ended_at = _parse_c1b_timestamp(
            command.ended_at,
            f"{command_prefix}.ended_at",
            errors,
        )
        if (
            started_at is not None
            and ended_at is not None
            and ended_at < started_at
        ):
            errors.append(
                f"{command_prefix}.ended_at must not precede started_at"
            )
        if (
            created_at is not None
            and ended_at is not None
            and ended_at > created_at
        ):
            errors.append(
                f"{command_prefix}.ended_at must not be later than created_at"
            )
    normalized_commands = [
        command.command.replace("\\", "/").casefold()
        for command in manifest.commands
        if command.exit_code == 0 and 0 in command.expected_exit_codes
    ]
    for artifact_path, required_tokens in _C1B_COMMAND_ARTIFACT_TOKENS.items():
        normalized_artifact_path = artifact_path.casefold()
        if not any(
            normalized_artifact_path in command
            and all(token.casefold() in command for token in required_tokens)
            for command in normalized_commands
        ):
            errors.append(
                f"{prefix}: no successful command is bound to artifact "
                f"{artifact_path!r} with tokens {required_tokens!r}"
            )
    for migration_log in ("drill-alembic.log", "actual-alembic.log"):
        if not any(
            migration_log in command
            and "alembic" in command
            and "upgrade" in command
            and "head" in command
            for command in normalized_commands
        ):
            errors.append(
                f"{prefix}: missing successful 0064-to-0065 migration command "
                f"bound to {migration_log!r}"
            )

    normalized_artifact_paths: set[str] = set()
    for artifact in manifest.artifacts:
        normalized_path, path_error = _normalize_relative_artifact_path(
            artifact.path
        )
        if path_error is None and normalized_path is not None:
            normalized_artifact_paths.add(normalized_path)
    missing_artifact_paths = [
        path
        for path in C1B_REQUIRED_ARTIFACT_PATHS
        if path not in normalized_artifact_paths
    ]
    if missing_artifact_paths:
        errors.append(
            f"{prefix}: missing required artifacts: "
            + ", ".join(missing_artifact_paths)
        )
    allowed_artifact_paths = set(C1B_REQUIRED_ARTIFACT_PATHS).union(
        C1B_ALLOWED_OPTIONAL_ARTIFACT_PATHS
    )
    unplanned_artifact_paths = sorted(
        normalized_artifact_paths.difference(allowed_artifact_paths)
    )
    if unplanned_artifact_paths:
        errors.append(
            f"{prefix}: unplanned artifacts are not allowed: "
            + ", ".join(unplanned_artifact_paths)
        )
    errors.extend(
        _validate_c1b_artifact_claims(
            artifact_snapshots,
            allowed_artifact_paths,
        )
    )
    content_errors, evidence_context = _validate_c1b_artifact_contents(
        manifest,
        artifact_snapshots,
    )
    errors.extend(content_errors)

    present_gate_codes = {gate.code for gate in manifest.gates}
    missing_gate_codes = [
        code
        for code in C1B_REQUIRED_GATE_CODES
        if code not in present_gate_codes
    ]
    extra_gate_codes = sorted(
        present_gate_codes.difference(C1B_REQUIRED_GATE_CODES)
    )
    if missing_gate_codes:
        errors.append(
            f"{prefix}: missing required gates: "
            + ", ".join(missing_gate_codes)
        )
    if extra_gate_codes:
        errors.append(
            f"{prefix}: unplanned gates are not allowed: "
            + ", ".join(extra_gate_codes)
        )
    for gate in manifest.gates:
        if gate.code not in _C1B_GATE_COUNT_RULES:
            continue
        if not gate.passed:
            errors.append(f"{prefix}: gate {gate.code!r} must be passed")
        errors.extend(
            _validate_c1b_gate_details(
                gate,
                normalized_artifact_paths,
                evidence_context,
            )
        )
    return errors


def write_manifest(manifest: OutcomeEvidenceManifest, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(manifest.model_dump_json(indent=2, by_alias=True))
            temporary_file.write("\n")
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_manifest(
    path: str | Path,
    *,
    c1b_strict: bool = False,
) -> OutcomeEvidenceManifest:
    source = Path(path)
    if c1b_strict:
        with source.open("rb") as handle:
            source_stat = os.fstat(handle.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise ValueError("C1B manifest is not a regular disk file")
            payload = handle.read(_C1B_MAX_MANIFEST_BYTES + 1)
        if len(payload) > _C1B_MAX_MANIFEST_BYTES:
            raise ValueError(
                f"C1B manifest exceeds {_C1B_MAX_MANIFEST_BYTES} bytes"
            )
        decoded = _strict_json_loads(payload)
        return OutcomeEvidenceManifest.model_validate(
            decoded,
            strict=True,
            extra="forbid",
        )
    payload = source.read_bytes()
    return OutcomeEvidenceManifest.model_validate_json(
        payload,
    )
