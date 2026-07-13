from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class EvidenceGate(BaseModel):
    code: str
    passed: bool
    details: dict[str, object] = Field(default_factory=dict)


def _utc_iso_z() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    artifact_path = (
        source_path.relative_to(Path(root)).as_posix()
        if root is not None
        else source_path.as_posix()
    )
    return EvidenceArtifact(path=artifact_path, sha256=digest)


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


def validate_manifest_evidence(
    manifest: OutcomeEvidenceManifest,
    artifact_root: str | Path,
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
    for artifact in manifest.artifacts:
        configured_path = Path(artifact.path)
        artifact_path = (
            configured_path
            if configured_path.is_absolute()
            else root / configured_path
        )
        identifier = f"artifact {artifact.path!r}"
        if not artifact_path.exists():
            errors.append(f"{identifier}: file does not exist")
            continue
        if not artifact_path.is_file():
            errors.append(f"{identifier}: path is not a file")
            continue
        try:
            actual_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"{identifier}: could not read file: {exc}")
            continue
        if actual_sha256 != artifact.sha256:
            errors.append(
                f"{identifier}: sha256 mismatch "
                f"(expected {artifact.sha256}, got {actual_sha256})"
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


def read_manifest(path: str | Path) -> OutcomeEvidenceManifest:
    return OutcomeEvidenceManifest.model_validate_json(Path(path).read_bytes())
