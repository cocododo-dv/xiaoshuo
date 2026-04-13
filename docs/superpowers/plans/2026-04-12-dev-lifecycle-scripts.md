# Dev Lifecycle Scripts Implementation Plan

**Status:** implemented

> Closeout note: the lifecycle scripts were implemented directly in the working tree, then replayed through an explicit red/green verification pass on 2026-04-13 before this plan was marked complete.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one-click start, stop, and restart scripts for the local Windows development workflow.

**Architecture:** Keep the behavior in a single PowerShell entry point under `scripts/dev.ps1`, then expose root-level `.cmd` launchers for double-click and terminal usage. Persist runtime state under `.codex-run`, run backend migration/demo seed before boot, and stop services by walking the tracked process tree from recorded root PIDs.

**Tech Stack:** PowerShell 5.1+, `python`, `npm.cmd`, FastAPI/Uvicorn, Vite.

---

### Task 1: Lock in the lifecycle contract

**Files:**
- Create: `scripts/test_dev_lifecycle.ps1`

- [x] **Step 1: Write the failing integration-style test**
- [x] **Step 2: Run the test and confirm it fails because the lifecycle entry points do not exist yet**

### Task 2: Implement the lifecycle scripts

**Files:**
- Create: `scripts/dev.ps1`
- Create: `start-dev.cmd`
- Create: `stop-dev.cmd`
- Create: `restart-dev.cmd`

- [x] **Step 1: Add the shared PowerShell start/stop/restart logic**
- [x] **Step 2: Add root `.cmd` wrappers that delegate to `scripts/dev.ps1`**

### Task 3: Verify the workflow end-to-end

**Files:**
- Test: `scripts/test_dev_lifecycle.ps1`

- [x] **Step 1: Run the lifecycle test and confirm start/stop/restart all pass**
- [x] **Step 2: Spot-check the generated PID files, logs, and local URLs**

---

## Verification Evidence

- 2026-04-13 red check: temporarily moved `scripts/dev.ps1` plus the three root `.cmd` wrappers aside and confirmed `powershell -ExecutionPolicy Bypass -File scripts/test_dev_lifecycle.ps1` failed with `Missing lifecycle script: scripts/dev.ps1`.
- 2026-04-13 green check: restored the entry points and reran `powershell -ExecutionPolicy Bypass -File scripts/test_dev_lifecycle.ps1`; the smoke test completed successfully across `start -> restart -> stop`.
- Spot-check result: `.codex-run/backend.out.log`, `.codex-run/backend.err.log`, `.codex-run/frontend.out.log`, and `.codex-run/frontend.err.log` were generated as expected. The smoke test also asserts that backend/frontend PID files are created during runtime and removed again after stop.
