from __future__ import annotations

import json
import os
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
    write_manifest,
)


def _manifest(
    *,
    artifact: EvidenceArtifact | None = None,
    gates: list[EvidenceGate] | None = None,
    model_routes: dict[str, object] | None = None,
) -> OutcomeEvidenceManifest:
    return OutcomeEvidenceManifest(
        run_id="c0-test",
        git_commit="deadbeef",
        database_revision="20260712_0064",
        model_routes=model_routes or {},
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

    write_manifest(manifest, manifest_path)
    restored = read_manifest(manifest_path)
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert restored == manifest
    assert restored.artifacts[0].path == "report.json"
    assert len(restored.artifacts[0].sha256) == 64
    assert raw_manifest["schema"] == "outcome-evidence-v1"
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
