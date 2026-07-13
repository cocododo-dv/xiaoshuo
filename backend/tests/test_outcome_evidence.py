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
from novel_system.tools.outcome_evidence import _main


def _manifest(
    *,
    artifact: EvidenceArtifact | None = None,
    commands: list[EvidenceCommand] | None = None,
    gates: list[EvidenceGate] | None = None,
    model_routes: dict[str, object] | None = None,
) -> OutcomeEvidenceManifest:
    return OutcomeEvidenceManifest(
        run_id="c0-test",
        git_commit="deadbeef",
        database_revision="20260712_0064",
        model_routes=model_routes or {},
        provenance="offline",
        commands=(
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
        artifacts=[
            artifact
            or EvidenceArtifact(path="report.json", sha256="0" * 64)
        ],
        gates=(
            gates
            if gates is not None
            else [EvidenceGate(code="DATABASE_HEAD_MATCH", passed=True)]
        ),
    )


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
