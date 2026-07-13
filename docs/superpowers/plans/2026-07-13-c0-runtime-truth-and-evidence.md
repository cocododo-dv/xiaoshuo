# C0 Runtime Truth and Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make database revision, schema readiness, evidence provenance, artifact hashes, and governance status independently verifiable before any later closure stage runs.

**Architecture:** Add a small Pydantic evidence domain service and a read-only SQLite preflight tool. Reuse the existing online backup tool for migration drills, then record the real commands and artifacts in an atomic `outcome-evidence-v1` manifest. Update the progress ledger so engineering, real-model, and release evidence cannot collapse into one “completed” label.

**Tech Stack:** Python 3.12, Pydantic 2, SQLite, Alembic, pytest, Markdown.

---

### Task 1: Evidence manifest domain model

**Files:**
- Create: `backend/src/novel_system/services/outcome_evidence.py`
- Create: `backend/tests/test_outcome_evidence.py`

- [ ] **Step 1: Write the failing manifest tests**

```python
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


def _manifest(artifact: EvidenceArtifact) -> OutcomeEvidenceManifest:
    return OutcomeEvidenceManifest(
        run_id="c0-test",
        git_commit="deadbeef",
        database_revision="20260712_0064",
        provenance="offline",
        commands=[EvidenceCommand(command="pytest", exit_code=0)],
        artifacts=[artifact],
        gates=[EvidenceGate(code="DATABASE_HEAD_MATCH", passed=True)],
    )


def test_manifest_round_trip_hashes_artifact(tmp_path: Path) -> None:
    artifact_path = tmp_path / "report.json"
    artifact_path.write_text('{"ok":true}', encoding="utf-8")
    manifest = _manifest(artifact_from_path(artifact_path, root=tmp_path))
    output = tmp_path / "manifest.json"
    write_manifest(manifest, output)
    loaded = read_manifest(output)
    assert loaded == manifest
    assert loaded.artifacts[0].path == "report.json"
    assert len(loaded.artifacts[0].sha256) == 64


def test_manifest_rejects_duplicate_gate_codes(tmp_path: Path) -> None:
    artifact_path = tmp_path / "a.txt"
    artifact_path.write_text("a", encoding="utf-8")
    artifact = artifact_from_path(artifact_path)
    with pytest.raises(ValueError, match="duplicate gate code"):
        OutcomeEvidenceManifest(
            run_id="duplicate",
            git_commit="deadbeef",
            database_revision="head",
            provenance="offline",
            artifacts=[artifact],
            gates=[
                EvidenceGate(code="SAME", passed=True),
                EvidenceGate(code="SAME", passed=False),
            ],
        )


def test_offline_manifest_cannot_satisfy_human_gate(tmp_path: Path) -> None:
    artifact_path = tmp_path / "a.txt"
    artifact_path.write_text("a", encoding="utf-8")
    with pytest.raises(EvidenceProvenanceError):
        require_provenance(_manifest(artifact_from_path(artifact_path)), {"human"})
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_outcome_evidence.py -q`

Expected: collection fails with `ModuleNotFoundError: novel_system.services.outcome_evidence`.

- [ ] **Step 3: Implement the manifest model and atomic writer**

```python
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

EvidenceProvenance = Literal["synthetic", "offline", "real_model", "human"]


class EvidenceProvenanceError(ValueError):
    pass


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
    details: dict[str, Any] = Field(default_factory=dict)


class OutcomeEvidenceManifest(BaseModel):
    schema: Literal["outcome-evidence-v1"] = "outcome-evidence-v1"
    run_id: str
    git_commit: str
    database_revision: str
    config_hashes: dict[str, str] = Field(default_factory=dict)
    model_routes: dict[str, Any] = Field(default_factory=dict)
    provenance: EvidenceProvenance
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    commands: list[EvidenceCommand] = Field(default_factory=list)
    artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    gates: list[EvidenceGate] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_gate_codes(self) -> "OutcomeEvidenceManifest":
        codes = [gate.code for gate in self.gates]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate gate code")
        return self


def artifact_from_path(path: str | Path, *, root: str | Path | None = None) -> EvidenceArtifact:
    file_path = Path(path)
    digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
    display = file_path.relative_to(Path(root)) if root is not None else file_path
    return EvidenceArtifact(path=display.as_posix(), sha256=digest)


def require_provenance(
    manifest: OutcomeEvidenceManifest, allowed: set[EvidenceProvenance]
) -> None:
    if manifest.provenance not in allowed:
        raise EvidenceProvenanceError(
            f"provenance {manifest.provenance!r} does not satisfy {sorted(allowed)!r}"
        )


def write_manifest(manifest: OutcomeEvidenceManifest, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=output.name, suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(manifest.model_dump_json(indent=2))
            stream.write("\n")
        os.replace(tmp_name, output)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def read_manifest(path: str | Path) -> OutcomeEvidenceManifest:
    return OutcomeEvidenceManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: Run the manifest tests and verify GREEN**

Run: `cd backend && python -m pytest tests/test_outcome_evidence.py -q`

Expected: `3 passed`.

- [ ] **Step 5: Commit the manifest service**

```bash
git add backend/src/novel_system/services/outcome_evidence.py backend/tests/test_outcome_evidence.py
git commit -m "feat(governance): add evidence manifest model"
```

### Task 2: Read-only database preflight

**Files:**
- Create: `backend/src/novel_system/tools/database_preflight.py`
- Create: `backend/tests/test_database_preflight.py`

- [ ] **Step 1: Write failing schema inspection tests**

```python
import sqlite3
from pathlib import Path

from novel_system.tools.database_preflight import inspect_database


def _database(path: Path, *, revision: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        conn.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        conn.execute(
            "CREATE TABLE scene_run_states ("
            "scene_id TEXT PRIMARY KEY, latest_valid_draft_row_id TEXT, run_policy TEXT, "
            "scene_token_budget INTEGER, scene_tokens_used INTEGER)"
        )
        for table in ("evaluation_experiments", "evaluation_pairs", "evaluation_votes"):
            conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()


def test_preflight_passes_head_schema(tmp_path: Path) -> None:
    path = tmp_path / "head.db"
    _database(path, revision="20260712_0064")
    report = inspect_database(path, expected_revision="20260712_0064")
    assert report["ready"] is True
    assert report["integrity"] == "ok"
    assert report["missing_tables"] == []
    assert report["missing_columns"] == {}


def test_preflight_reports_stale_revision_and_missing_schema(tmp_path: Path) -> None:
    path = tmp_path / "stale.db"
    sqlite3.connect(path).close()
    report = inspect_database(path, expected_revision="20260712_0064")
    assert report["ready"] is False
    assert report["revision"] is None
    assert "evaluation_experiments" in report["missing_tables"]
    assert "scene_run_states" in report["missing_tables"]
```

- [ ] **Step 2: Run tests and verify RED**

Run: `cd backend && python -m pytest tests/test_database_preflight.py -q`

Expected: collection fails because `database_preflight` does not exist.

- [ ] **Step 3: Implement inspection and JSON CLI**

```python
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

REQUIRED_TABLES = {
    "scene_run_states",
    "evaluation_experiments",
    "evaluation_pairs",
    "evaluation_votes",
}
REQUIRED_COLUMNS = {
    "scene_run_states": {
        "latest_valid_draft_row_id",
        "run_policy",
        "scene_token_budget",
        "scene_tokens_used",
    }
}


def inspect_database(path: str | Path, *, expected_revision: str) -> dict[str, Any]:
    db_path = Path(path)
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        revision = None
        if "alembic_version" in tables:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = str(row[0]) if row else None
        missing_tables = sorted(REQUIRED_TABLES - tables)
        missing_columns: dict[str, list[str]] = {}
        for table, required in REQUIRED_COLUMNS.items():
            if table not in tables:
                continue
            actual = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
            missing = sorted(required - actual)
            if missing:
                missing_columns[table] = missing
        ready = (
            integrity == "ok"
            and revision == expected_revision
            and not missing_tables
            and not missing_columns
        )
        return {
            "path": str(db_path.resolve()),
            "ready": ready,
            "integrity": integrity,
            "revision": revision,
            "expected_revision": expected_revision,
            "foreign_keys": int(conn.execute("PRAGMA foreign_keys").fetchone()[0]),
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
        }
    finally:
        conn.close()


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only governance database preflight")
    parser.add_argument("path")
    parser.add_argument("--expected-revision", required=True)
    args = parser.parse_args(argv)
    report = inspect_database(args.path, expected_revision=args.expected_revision)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `cd backend && python -m pytest tests/test_database_preflight.py -q`

Expected: `2 passed`.

- [ ] **Step 5: Commit database preflight**

```bash
git add backend/src/novel_system/tools/database_preflight.py backend/tests/test_database_preflight.py
git commit -m "feat(governance): add database readiness preflight"
```

### Task 3: Provenance-aware manifest CLI

**Files:**
- Create: `backend/src/novel_system/tools/outcome_evidence.py`
- Modify: `backend/tests/test_outcome_evidence.py`

- [ ] **Step 1: Add a failing CLI validation test**

```python
from novel_system.tools.outcome_evidence import _main


def test_cli_rejects_offline_manifest_for_human_requirement(tmp_path: Path) -> None:
    artifact_path = tmp_path / "a.txt"
    artifact_path.write_text("a", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(_manifest(artifact_from_path(artifact_path)), manifest_path)
    assert _main([
        "validate",
        str(manifest_path),
        "--require-provenance",
        "human",
    ]) == 1
```

- [ ] **Step 2: Run the CLI test and verify RED**

Run: `cd backend && python -m pytest tests/test_outcome_evidence.py::test_cli_rejects_offline_manifest_for_human_requirement -q`

Expected: collection fails because the CLI module does not exist.

- [ ] **Step 3: Implement the validation CLI**

```python
from __future__ import annotations

import argparse
import json
import sys

from novel_system.services.outcome_evidence import (
    EvidenceProvenanceError,
    read_manifest,
    require_provenance,
)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Outcome evidence manifest tools")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("manifest")
    validate.add_argument(
        "--require-provenance",
        action="append",
        choices=("synthetic", "offline", "real_model", "human"),
        default=[],
    )
    args = parser.parse_args(argv)
    try:
        manifest = read_manifest(args.manifest)
        if args.require_provenance:
            require_provenance(manifest, set(args.require_provenance))
        print(json.dumps({"valid": True, "run_id": manifest.run_id}, ensure_ascii=False))
        return 0
    except (ValueError, EvidenceProvenanceError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 4: Run manifest tests and verify GREEN**

Run: `cd backend && python -m pytest tests/test_outcome_evidence.py -q`

Expected: `4 passed`.

- [ ] **Step 5: Commit the CLI**

```bash
git add backend/src/novel_system/tools/outcome_evidence.py backend/tests/test_outcome_evidence.py
git commit -m "feat(governance): validate evidence provenance"
```

### Task 4: Correct the progress ledger status model

**Files:**
- Modify: `docs/outcome-governance-progress.md`
- Modify: `docs/superpowers/specs/2026-07-13-ai-novel-outcome-governance-completion-assessment.md`

- [ ] **Step 1: Replace single completion labels with a status matrix**

Insert immediately after the progress-ledger discipline block:

```markdown
## 状态口径（2026-07-13 起）

| Wave | engineering_status | real_gate_status | release_gate_status |
|---|---|---|---|
| 0 | completed | pending | pending |
| 1 | completed | pending | pending |
| 2 | completed | pending | pending |
| 3 | completed | pending | pending |
| 4 | completed | pending | pending |
| 5 | completed | pending_human | pending |
| 6 | partial | pending | pending |
| 7 | partial | pending | pending |

`completed` 只表示对应层级证据已满足。合成数据和离线 mock 不得把
`real_gate_status` 或 `release_gate_status` 置为 `completed`。
```

Change Wave headings from `已完成` to `工程实现已完成，真实门待验` for Wave 0–5, and to `部分完成` for Wave 6–7.

- [ ] **Step 2: Record C0 evidence rules in the assessment**

Add `outcome-evidence-v1` and the three status columns to the C0 section, including the rule that missing or ignored artifacts keep the real gate pending.

- [ ] **Step 3: Verify document consistency**

Run:

```powershell
rg -n '—— 已完成|engineering_status|real_gate_status|release_gate_status|outcome-evidence-v1' docs/outcome-governance-progress.md docs/superpowers/specs/2026-07-13-ai-novel-outcome-governance-completion-assessment.md
```

Expected: no Wave heading uses the bare `—— 已完成` form; the status matrix and manifest schema are present.

- [ ] **Step 4: Commit the status correction**

```bash
git add docs/outcome-governance-progress.md docs/superpowers/specs/2026-07-13-ai-novel-outcome-governance-completion-assessment.md
git commit -m "docs(governance): separate engineering and release status"
```

### Task 5: Run the database migration drill and create C0 evidence

**Files:**
- Create runtime artifact: `.codex-run/governance-c0/20260713-c0/database-backup.db`
- Create runtime artifact: `.codex-run/governance-c0/20260713-c0/database-backup.db.meta.json`
- Create runtime artifact: `.codex-run/governance-c0/20260713-c0/preflight-before.json`
- Create runtime artifact: `.codex-run/governance-c0/20260713-c0/preflight-after.json`
- Create runtime artifact: `.codex-run/governance-c0/20260713-c0/manifest.json`

- [ ] **Step 1: Capture the current read-only preflight**

Run from `backend`:

```powershell
python -m novel_system.tools.database_preflight E:\codex\xiaoshuo\codex\backend\novel_system.db --expected-revision 20260712_0064
```

Expected: exit 1 with the existing stale revision and missing schema listed. Save stdout as `preflight-before.json`.

- [ ] **Step 2: Produce and verify an online backup**

Run:

```powershell
python -m novel_system.tools.db_backup --backup E:\codex\xiaoshuo\codex\backend\novel_system.db E:\codex\xiaoshuo\codex\.worktrees\outcome-governance-closure\.codex-run\governance-c0\20260713-c0\database-backup.db
python -m novel_system.tools.db_backup --verify E:\codex\xiaoshuo\codex\.worktrees\outcome-governance-closure\.codex-run\governance-c0\20260713-c0\database-backup.db
```

Expected: backup metadata has `integrity=ok`; verify returns `ok=true`.

- [ ] **Step 3: Restore the verified backup to a drill database and upgrade it**

Run:

```powershell
python -m novel_system.tools.db_backup --restore E:\codex\xiaoshuo\codex\.worktrees\outcome-governance-closure\.codex-run\governance-c0\20260713-c0\database-backup.db E:\codex\xiaoshuo\codex\.worktrees\outcome-governance-closure\.codex-run\governance-c0\20260713-c0\migration-drill.db
$env:NOVEL_SYSTEM_DATABASE_URL='sqlite:///E:/codex/xiaoshuo/codex/.worktrees/outcome-governance-closure/.codex-run/governance-c0/20260713-c0/migration-drill.db'
python -m alembic upgrade head
python -m novel_system.tools.database_preflight E:\codex\xiaoshuo\codex\.worktrees\outcome-governance-closure\.codex-run\governance-c0\20260713-c0\migration-drill.db --expected-revision 20260712_0064
```

Expected: Alembic reaches `20260712_0064`; preflight exits 0 and reports `ready=true`.

- [ ] **Step 4: Run orphan inventory and focused regression against the drill database**

Run:

```powershell
$env:NOVEL_SYSTEM_DATABASE_URL='sqlite:///E:/codex/xiaoshuo/codex/.worktrees/outcome-governance-closure/.codex-run/governance-c0/20260713-c0/migration-drill.db'
python -m novel_system.tools.orphan_inventory --json
python -m pytest tests/test_metadata_isolation.py tests/test_generation_persistence.py -q
```

Expected: orphan inventory reports zero; focused tests pass.

- [ ] **Step 5: Build and validate the offline evidence manifest**

Use `OutcomeEvidenceManifest` with provenance `offline`, exact command exit codes, the preflight/backup artifacts, and gates `BACKUP_VERIFIED`, `MIGRATION_HEAD_MATCH`, `SCHEMA_READY`, `ORPHANS_ZERO`, and `FOCUSED_REGRESSION_PASS`. Write atomically, then run:

```powershell
python -m novel_system.tools.outcome_evidence validate E:\codex\xiaoshuo\codex\.worktrees\outcome-governance-closure\.codex-run\governance-c0\20260713-c0\manifest.json --require-provenance offline
```

Expected: exit 0 with `valid=true`.

- [ ] **Step 6: Run C0 regression**

Run:

```powershell
cd backend
python -m pytest tests/test_outcome_evidence.py tests/test_database_preflight.py tests/test_db_backup.py tests/test_orphan_inventory.py tests/test_metadata_isolation.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 7: Commit C0 implementation and plan completion**

```bash
git add backend/src/novel_system/services/outcome_evidence.py backend/src/novel_system/tools/outcome_evidence.py backend/src/novel_system/tools/database_preflight.py backend/tests/test_outcome_evidence.py backend/tests/test_database_preflight.py docs/outcome-governance-progress.md docs/superpowers/specs/2026-07-13-ai-novel-outcome-governance-completion-assessment.md docs/superpowers/plans/2026-07-13-c0-runtime-truth-and-evidence.md
git commit -m "feat(governance): close runtime truth and evidence C0"
```

The ignored `.codex-run` artifacts remain outside Git; their hashes and command results are represented by the manifest. A later evidence retention change may publish a redacted manifest index, but C0 does not add real-model or human provenance.
