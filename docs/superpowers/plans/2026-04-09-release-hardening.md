# Release Hardening Implementation Plan

**Status:** implemented

> Closeout note: the repository still ships the verification scripts, CI workflow, checklist, and README guidance from this slice. Historical git publication steps were later absorbed by follow-on closeout work and are recorded as superseded notes below.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stable local verification entry points, baseline GitHub CI, release-facing docs, and a review-ready Draft PR workflow for the current Novel System baseline.

**Architecture:** Keep all existing backend and frontend commands as the source of truth, then wrap them with thin repository-level scripts so Windows and WSL verification are reproducible. Add a minimal GitHub Actions workflow for the stable cross-platform checks, and capture the stricter WSL Chroma lane in release docs plus PR checklist content rather than forcing it into fragile CI.

**Tech Stack:** PowerShell, Bash, GitHub Actions, Python 3.12, pytest, Node 22, Vue/Vite, Markdown

---

## File Structure

- `scripts/verify_windows.ps1`
  Owns the Windows-native verification lane for backend non-Chroma tests plus frontend test/build checks.
- `scripts/verify_wsl_strict.sh`
  Owns the WSL Ubuntu 24.04 strict Chroma verification lane.
- `scripts/verify_release.ps1`
  Owns the release-facing orchestration message for the two verification lanes from Windows.
- `.github/workflows/ci.yml`
  Owns the minimum PR automation for backend non-Chroma tests and frontend test/build checks.
- `.github/pull_request_template.md`
  Owns the PR structure for summary, validation evidence, strict WSL signoff, and residual risk.
- `README.md`
  Owns the primary developer-facing quickstart and verification guidance.
- `docs/release-checklist.md`
  Owns the release-facing checklist that distinguishes automatic CI from manual strict verification.

---

### Task 1: Add unified repository verification scripts

**Files:**
- Create: `scripts/verify_windows.ps1`
- Create: `scripts/verify_wsl_strict.sh`
- Create: `scripts/verify_release.ps1`

- [x] **Step 1: Run the missing-script checks to confirm the entry points do not exist yet**

Run:

```powershell
Test-Path scripts/verify_windows.ps1
Test-Path scripts/verify_wsl_strict.sh
Test-Path scripts/verify_release.ps1
```

Expected: all three commands print `False`

- [x] **Step 2: Add the Windows verification wrapper**

```powershell
param(
    [switch]$BackendOnly,
    [switch]$FrontendOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Action
    )

    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Action
}

$repoRoot = Split-Path -Parent $PSScriptRoot

if (-not $FrontendOnly) {
    Invoke-Step "Backend pytest (not chroma_integration)" {
        Push-Location (Join-Path $repoRoot "backend")
        try {
            python -m pytest -q -m "not chroma_integration"
        } finally {
            Pop-Location
        }
    }
}

if (-not $BackendOnly) {
    Invoke-Step "Frontend tests" {
        Push-Location (Join-Path $repoRoot "frontend")
        try {
            npm test
        } finally {
            Pop-Location
        }
    }

    Invoke-Step "Frontend build" {
        Push-Location (Join-Path $repoRoot "frontend")
        try {
            npm run build
        } finally {
            Pop-Location
        }
    }
}
```

- [x] **Step 3: Add the strict WSL verification wrapper and a release orchestrator**

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

cd "$BACKEND_DIR"
"$PYTHON_BIN" -m novel_system.tools.chroma_smoke
"$PYTHON_BIN" -m pytest tests/test_chroma_smoke.py tests/test_chroma_vector_store.py tests/test_review_release.py tests/test_vector_verify_gate.py tests/test_acceptance_flow.py -q
"$PYTHON_BIN" -m pytest -q
```

```powershell
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "==> Windows verification lane" -ForegroundColor Cyan
powershell -ExecutionPolicy Bypass -File (Join-Path $repoRoot "scripts\\verify_windows.ps1")

Write-Host "==> WSL strict Chroma verification lane" -ForegroundColor Cyan
wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"
```

- [x] **Step 4: Run the Windows verification wrapper**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1
```

Expected: backend non-Chroma tests pass, then frontend test/build pass

- [x] **Step 5: Run the strict WSL wrapper directly**

Run:

```powershell
wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"
```

Expected: `chroma_smoke`, focused Chroma suite, and full backend `pytest -q` all pass

---

### Task 2: Add GitHub Actions CI for stable PR checks

**Files:**
- Create: `.github/workflows/ci.yml`

- [x] **Step 1: Confirm no root CI workflow exists yet**

Run:

```powershell
Test-Path .github/workflows/ci.yml
```

Expected: `False`

- [x] **Step 2: Add the GitHub Actions workflow**

```yaml
name: CI

on:
  pull_request:
  push:
    branches:
      - main
      - master
      - "codex/**"

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install backend dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e .[dev]
      - name: Run backend tests
        run: python -m pytest -q -m "not chroma_integration"

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: "npm"
          cache-dependency-path: frontend/package-lock.json
      - name: Install frontend dependencies
        run: npm ci
      - name: Run frontend tests
        run: npm test
      - name: Build frontend
        run: npm run build
```

- [x] **Step 3: Validate the workflow file shape locally**

Run:

```powershell
Get-Content .github/workflows/ci.yml
```

Expected: workflow contains both `backend` and `frontend` jobs with the commands above

---

### Task 3: Add release checklist and PR review scaffolding

**Files:**
- Create: `.github/pull_request_template.md`
- Create: `docs/release-checklist.md`
- Modify: `README.md`

- [x] **Step 1: Confirm the current docs do not mention the new repository-level verification scripts**

Run:

```powershell
Select-String -Path README.md -Pattern "verify_windows.ps1|verify_wsl_strict.sh|release-checklist"
```

Expected: no matches

- [x] **Step 2: Add the PR template**

```markdown
## Summary

- Summarize the release-hardening changes in 2-4 bullets.

## Validation

- [x] `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- [x] `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`

## WSL Strict Chroma Notes

- Record the exact WSL execution result and any environment caveats.

## Risks / Follow-ups

- Record any known residual risk or leave `None`.
```

- [x] **Step 3: Add the release checklist document**

```markdown
# Release Checklist

## Automatic checks

- GitHub Actions backend job passes
- GitHub Actions frontend job passes

## Required local checks

- Run `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- Run `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`

## Release gate

- Confirm Draft PR includes both validation results
- Confirm any remaining risk is documented before marking the PR ready
```

- [x] **Step 4: Update the README to point at the script entry points and explain the CI/manual boundary**

```markdown
## Verification

Use the repository-level scripts for the current validation flow:

- `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`

GitHub Actions covers the Windows-safe backend lane and the frontend lane. The strict Chroma lane remains a required local release check on this machine.
```

- [x] **Step 5: Re-read the updated docs to make sure the commands match the scripts exactly**

Run:

```powershell
Get-Content README.md
Get-Content docs/release-checklist.md
Get-Content .github/pull_request_template.md
```

Expected: the commands, environments, and release gates match the scripts and CI workflow

---

### Task 4: Run verification, finalize git state, and publish a draft PR

**Files:**
- Modify: `README.md`
- Modify: `docs/release-checklist.md`
- Modify: `.github/pull_request_template.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/verify_windows.ps1`
- Modify: `scripts/verify_wsl_strict.sh`
- Modify: `scripts/verify_release.ps1`

- [x] **Step 1: Run the repository-level Windows verification script**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1
```

Expected: exit code `0`

- [x] **Step 2: Run the repository-level strict WSL verification script**

Run:

```powershell
wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"
```

Expected: exit code `0`

- [x] **Step 3: Review the final diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only the intended release-hardening files are modified

- Supersede note: git commit, push, and Draft PR publication for this slice were absorbed by the later runtime closeout/doc-sync slices and are not backfilled here as completed historical checklist items.