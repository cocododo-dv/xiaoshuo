# Human Review Runtime Ops Closeout Implementation Plan

**Status:** docs-only closeout

> Closeout note: this plan captured documentation and release-handoff work for an already-implemented runtime shell. The shipped docs remain, while git publication moved into the subsequent runtime-shell documentation sync.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the current L3 runtime-ops slice by syncing repository docs, release handoff material, and publish-ready validation evidence with the already-implemented operator, recovery, promotion, and human review flows.

**Architecture:** Treat the existing dirty worktree as the intended implementation baseline. Limit this closeout to documentation, release templates, verification evidence, and publish prep unless the seeded validation run exposes a real mismatch in the current runtime-ops behavior.

**Tech Stack:** Markdown, PowerShell, Bash, Git, GitHub PR template

---

## File Structure

- `docs/superpowers/specs/2026-04-10-human-review-runtime-ops-closeout-design.md`
  Records the closed-out runtime-ops contract and seeded acceptance flow.
- `docs/superpowers/plans/2026-04-10-human-review-runtime-ops-closeout.md`
  Records the closeout implementation steps and publish checklist.
- `README.md`
  Captures the runtime-ops demo path and current verification evidence.
- `docs/release-checklist.md`
  Captures required manual acceptance evidence for release readiness.
- `.github/pull_request_template.md`
  Forces PR authors to record operator and runtime-ops evidence.
- `.gitignore`
  Keeps `.codex-run/` out of the change set.

---

### Task 1: Sync the runtime-ops contract into repository docs

**Files:**
- Create: `docs/superpowers/specs/2026-04-10-human-review-runtime-ops-closeout-design.md`
- Create: `docs/superpowers/plans/2026-04-10-human-review-runtime-ops-closeout.md`
- Modify: `README.md`

- [x] **Step 1: Record the closeout design**

Write the design doc so it captures:

- the operator identity contract
- the stable runtime-ops endpoints
- the documented response fields
- the seeded acceptance path
- the release handoff expectations

- [x] **Step 2: Record the closeout implementation plan**

Write the plan doc so it captures:

- which docs and templates are in scope
- the exact verification commands
- the seeded acceptance steps
- the publish-prep expectations for commit, push, and draft PR creation

- [x] **Step 3: Update the README demo path**

Document:

- the latest successful verification date and results
- how `Operator Ref` maps to `X-Operator-Ref`
- the runtime-ops closeout walkthrough for Workbench, Review Inbox, and Index Console

---

### Task 2: Sync release handoff material

**Files:**
- Modify: `docs/release-checklist.md`
- Modify: `.github/pull_request_template.md`
- Modify: `.gitignore`

- [x] **Step 1: Update the release checklist**

Add requirements to record:

- seeded acceptance execution
- operator ref used during the session
- recovery / promotion / human-review follow-up outcomes
- actor and target confirmation in receipts and runtime ledger views

- [x] **Step 2: Update the PR template**

Add explicit PR fields for:

- seeded demo evidence
- operator ref notes
- runtime-ops validation coverage

- [x] **Step 3: Ignore local runtime artifacts**

Add `.codex-run/` to `.gitignore` so local agent-run artifacts stay out of the PR scope.

---

### Task 3: Re-run verification and prepare publication

**Files:**
- Modify: none unless seeded acceptance exposes a real mismatch

- [x] **Step 1: Re-run the seed command**

Run: `cd backend && alembic upgrade head && python -m novel_system.tools.seed_demo`
Expected: succeeds without creating duplicate seeded content.

- [x] **Step 2: Re-run the Windows verification lane**

Run: `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
Expected: backend tests pass, frontend tests pass, frontend build succeeds.

- [x] **Step 3: Re-run the WSL strict lane**

Run: `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`
Expected: Chroma smoke succeeds, focused Chroma suite passes, full backend suite passes.

- Supersede note: publication of this docs-only closeout was absorbed by the later 2026-04-12 runtime-shell doc sync and is not backfilled here as a completed historical checklist item.
