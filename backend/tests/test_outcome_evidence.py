from __future__ import annotations

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
    write_manifest,
)


def _manifest(
    *,
    artifact: EvidenceArtifact | None = None,
    gates: list[EvidenceGate] | None = None,
) -> OutcomeEvidenceManifest:
    return OutcomeEvidenceManifest(
        run_id="c0-test",
        git_commit="deadbeef",
        database_revision="20260712_0064",
        provenance="offline",
        commands=[EvidenceCommand(command="pytest", exit_code=0)],
        artifacts=[
            artifact
            or EvidenceArtifact(path="report.json", sha256="0" * 64)
        ],
        gates=gates
        or [EvidenceGate(code="DATABASE_HEAD_MATCH", passed=True)],
    )


def test_manifest_round_trip_hashes_artifact(tmp_path: Path) -> None:
    report_path = tmp_path / "report.json"
    report_path.write_text('{"ok":true}', encoding="utf-8")
    artifact = artifact_from_path(report_path, root=tmp_path)
    manifest = _manifest(artifact=artifact)
    manifest_path = tmp_path / "outcome-evidence.json"

    write_manifest(manifest_path, manifest)
    restored = read_manifest(manifest_path)

    assert restored == manifest
    assert restored.artifacts[0].path == "report.json"
    assert len(restored.artifacts[0].sha256) == 64


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
