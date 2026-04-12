# Runtime Shell Docs Sync Implementation Plan

**Status:** docs-only closeout

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sync the repository's runtime shell documentation and release handoff material to the verified 2026-04-12 implementation state without changing product behavior.

**Architecture:** Treat the current branch as documentation-only work. Add one new current-state spec, add one new current-state implementation plan, then update release-facing docs so they describe the chapter runtime surface, domain read API decomposition, cursor pagination, and four-spec seeded browser evidence now present in the codebase.

**Tech Stack:** Markdown, PowerShell, Bash, GitHub PR template

---

## File Structure

- `docs/superpowers/specs/2026-04-12-runtime-shell-docs-sync-design.md`
  Captures the current runtime shell contract snapshot and supersedes the earlier closeout/query-closure docs for present-tense reference.
- `docs/superpowers/plans/2026-04-12-runtime-shell-docs-sync.md`
  Records this execution plan and the exact release-proof steps.
- `README.md`
  Captures the current verification counts, the four Playwright specs, the four operator refs, and the present runtime shell read-path guidance.
- `docs/release-checklist.md`
  Captures the release-ready evidence checklist for chapter runtime, runtime ops, knowledge, interop, domain API decomposition, and cursor pagination.
- `.github/pull_request_template.md`
  Forces PR authors to record the expanded browser coverage, operator refs, and domain/pagination validation source.

---

### Task 1: Add the 2026-04-12 runtime shell documentation snapshot

**Files:**
- Create: `docs/superpowers/specs/2026-04-12-runtime-shell-docs-sync-design.md`
- Create: `docs/superpowers/plans/2026-04-12-runtime-shell-docs-sync.md`

- [x] **Step 1: Write the current-state design doc**

Create the design doc with these sections:

- `Background`
- `Goals`
- `Non-Goals`
- `Current Runtime Shell Contract`
- `Supersede Note`

The contract section must explicitly name:

- the chapter runtime endpoints
- the shell's primary read paths
- the legacy `index/*` compatibility surface
- the dual-stack pagination endpoints and parameter pairs
- the four Playwright specs and four operator refs

- [x] **Step 2: Write the implementation plan**

Create this plan file so it lists:

- the new design doc as the canonical current-state reference
- the repo files that must be updated for release handoff
- the exact verification commands
- the release evidence that must be copied into README, checklist, and PR template

---

### Task 2: Update the release-facing docs

**Files:**
- Modify: `README.md`
- Modify: `docs/release-checklist.md`
- Modify: `.github/pull_request_template.md`

- [x] **Step 1: Refresh README verification evidence**

Update `README.md` so it records the 2026-04-12 results from:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1
cd frontend && npm run test:e2e
wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"
```

The README update must also:

- change the seeded browser lane from 3 specs to 4 specs
- list `ops.chapter.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`
- document the chapter runtime lane and the current domain read API split
- document the dual pagination contract for review items, human review events, jobs, and scene attempts

- [x] **Step 2: Refresh the release checklist**

Update `docs/release-checklist.md` so it requires PR authors to record:

- chapter runtime E2E coverage
- runtime-ops, knowledge, and interop E2E coverage
- all four operator refs
- the 2026-04-12 Windows and WSL results
- where domain API decomposition and pagination were revalidated

- [x] **Step 3: Refresh the PR template**

Update `.github/pull_request_template.md` so it requires:

- a summary of the documentation/runtime-shell contract change
- the standard verification checklist
- the four-spec seeded browser checklist
- explicit operator-ref notes
- a short note on domain API decomposition and pagination validation sources

---

### Task 3: Re-run verification and proofread the doc sync

**Files:**
- Modify: none unless the re-run exposes a doc mismatch

- [x] **Step 1: Re-run Windows verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1
```

Expected:

- backend `80 passed, 12 deselected`
- frontend `79 passed`
- frontend build succeeds

- [x] **Step 2: Re-run seeded browser E2E**

Run:

```powershell
cd frontend
npm run test:e2e
```

Expected:

- Playwright `4 passed`
- evidence maps to `ops.chapter.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`

- [x] **Step 3: Re-run WSL strict Chroma verification**

Run:

```powershell
wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"
```

Expected:

- Chroma smoke succeeds
- focused Chroma suite `12 passed`
- full backend suite `91 passed, 1 skipped`

- [x] **Step 4: Proofread the final text**

Confirm the updated docs explicitly mention:

- `GET /api/v1/chapters/{chapter_id}/status`
- `POST /api/v1/chapters/{chapter_id}/runtime/backfill/{stage_id}`
- `POST /api/v1/chapters/{chapter_id}/runtime/aggregate/final`
- `POST /api/v1/chapters/{chapter_id}/runtime/manual-hold`
- `POST /api/v1/chapters/{chapter_id}/runtime/manual-hold/clear`
- `/api/v1/knowledge-entries`
- `/api/v1/vector-alias-scopes`
- `/api/v1/jobs`
- `/api/v1/activity-events`
- `/api/v1/target-activity-groups`
- `page/page_size`
- `cursor/limit`

- [x] **Step 5: Review the final diff**

Check that the diff is documentation-only and that the historical 2026-04-10 and 2026-04-11 spec files were not rewritten in place.