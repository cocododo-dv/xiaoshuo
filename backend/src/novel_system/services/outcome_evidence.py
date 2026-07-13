from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


EvidenceProvenance = Literal["synthetic", "offline", "real_model", "human"]


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
