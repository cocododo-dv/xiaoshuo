from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


EvidenceProvenance = Literal["synthetic", "offline", "real_model", "human"]


class EvidenceProvenanceError(ValueError):
    """Raised when a manifest's provenance is not allowed."""


class EvidenceCommand(BaseModel):
    command: str
    exit_code: int
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
    schema: Literal["outcome-evidence-v1"] = "outcome-evidence-v1"
    run_id: str
    git_commit: str
    database_revision: str
    config_hashes: dict[str, str] = Field(default_factory=dict)
    model_routes: dict[str, str] = Field(default_factory=dict)
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


def write_manifest(path: str | Path, manifest: OutcomeEvidenceManifest) -> None:
    destination = Path(path)
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
            temporary_file.write(manifest.model_dump_json(indent=2))
            temporary_file.write("\n")
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_manifest(path: str | Path) -> OutcomeEvidenceManifest:
    return OutcomeEvidenceManifest.model_validate_json(Path(path).read_bytes())
