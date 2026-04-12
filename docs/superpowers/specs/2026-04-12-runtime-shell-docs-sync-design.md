# Runtime Shell Docs Sync Design

> Date: 2026-04-12
> Target slice: documentation sync for the current runtime shell contract, seeded browser evidence, domain read API decomposition, and cursor pagination.

---

## 1. Background

The repository moved beyond the 2026-04-10 runtime-ops closeout and the 2026-04-11 review/index query-closure slice:

- `Scene Workbench` now includes chapter runtime actions for staged backfill, manual hold, and final aggregate.
- `Knowledge Console` and `Index Console` now read primarily through decomposed domain endpoints instead of only the legacy `index/*` aggregate reads.
- cursor pagination now exists across review items, human review events, jobs, and scene attempts.
- the seeded browser lane now covers four Playwright specs instead of three.

This working tree therefore needs a current-state documentation sync rather than another product-design pass.

Fresh verification evidence collected on 2026-04-12:

- `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
  backend `80 passed, 12 deselected`; frontend `79 passed`; production build succeeded.
- `cd frontend && npm run test:e2e`
  Playwright `4 passed`.
- `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`
  Chroma smoke succeeded; focused Chroma suite `12 passed`; full backend suite `91 passed, 1 skipped`.

---

## 2. Goals

1. Freeze the 2026-04-12 runtime shell contract in repository docs without changing backend or frontend behavior.
2. Update release handoff materials so they reflect the current four-spec seeded browser lane and the latest verification counts.
3. Make the current public read-path split explicit: legacy `index/*` endpoints remain supported, but the shell's primary read surface now uses decomposed domain endpoints.

---

## 3. Non-Goals

- No backend or frontend product changes.
- No schema migrations, endpoint renames, or response-shape changes.
- No reauthoring of the 2026-04-10 or 2026-04-11 documents in place.
- No expansion into the next milestone after the current runtime shell closure.

---

## 4. Current Runtime Shell Contract

### 4.1 Chapter runtime endpoints

The following chapter runtime endpoints are now part of the documented operator contract:

- `GET /api/v1/chapters/{chapter_id}/status`
- `POST /api/v1/chapters/{chapter_id}/runtime/backfill/{stage_id}`
- `POST /api/v1/chapters/{chapter_id}/runtime/aggregate/final`
- `POST /api/v1/chapters/{chapter_id}/runtime/manual-hold`
- `POST /api/v1/chapters/{chapter_id}/runtime/manual-hold/clear`

Documented behavior for this slice:

- `status` is the authority for chapter gate state, including `chapter_backfill_pending_count`, `aggregate_block_reason`, `mid_aggregate_enabled_effective`, and memory pointers.
- `backfill/{stage_id}` applies an explicit strategy and returns a receipt suitable for the shell receipt rail.
- `aggregate/final` is blocked until staged backfill is resolved and manual hold is cleared.
- manual hold set/clear operations are operator-traceable mutating actions and remain part of the seeded browser contract.

### 4.2 Frontend primary read paths

The shell's current primary read paths are:

- `Review Inbox`
  - `GET /api/v1/review-items`
  - `GET /api/v1/human-review-events`
- `Scene Workbench`
  - `GET /api/v1/scenes/{scene_id}/workbench`
  - `GET /api/v1/scenes/{scene_id}/attempts`
  - `GET /api/v1/human-review-events?scene_id=...`
- `Knowledge Console`
  - `GET /api/v1/knowledge-entries`
  - `GET /api/v1/knowledge-entries/{object_type}/{lineage_key}`
  - `GET /api/v1/knowledge-entries/{object_type}/{lineage_key}/workflow`
- `Index Console`
  - `GET /api/v1/vector-alias-scopes`
  - `GET /api/v1/jobs`
  - `GET /api/v1/activity-events`
  - `GET /api/v1/target-activity-groups`

Mutating runtime/index actions still rely on the existing stable POST surfaces, including:

- `POST /api/v1/index/verify/{job_id}/retry`
- `POST /api/v1/runtime/recovery/sweep`
- `POST /api/v1/runtime/promotions/run-due`

Legacy compatibility note:

- `GET /api/v1/index/alias-scopes`
- `GET /api/v1/index/jobs`
- `GET /api/v1/index/runtime-ledger`

remain valid compatibility endpoints and continue to be covered by backend/frontend tests, but they are no longer the shell's primary read path for the index and knowledge surfaces.

### 4.3 Dual-stack pagination contract

The current dual-stack pagination contract is:

- `GET /api/v1/review-items`
- `GET /api/v1/human-review-events`
- `GET /api/v1/jobs`
- `GET /api/v1/scenes/{scene_id}/attempts`

All four endpoints accept both:

- page mode via `page` and `page_size`
- cursor mode via `cursor` and `limit`

Additional compatibility note:

- `Scene Workbench` still returns the full attempt history inside `/api/v1/scenes/{scene_id}/workbench` for compatibility, while `/api/v1/scenes/{scene_id}/attempts` is the dedicated paged read path used by the shell pager.

### 4.4 Seeded browser acceptance contract

The seeded browser lane now consists of four Playwright specs and four fixture operator refs:

- `chapter-ops.spec.js` with `ops.chapter.e2e`
  covers staged backfill, manual hold, and final aggregate in `Scene Workbench`.
- `runtime-ops.spec.js` with `ops.runtime.e2e`
  covers full scene run, review approve/retry/release, due promotions, recovery sweep, follow-up actions, receipts, target activity, and cross-view focus.
- `knowledge-console.spec.js` with `ops.knowledge.e2e`
  covers knowledge candidate creation, approve/verify/release workflow, filters, detail reset, review refs, bundle refs, and provenance jumps.
- `interop-center.spec.js` with `ops.interop.e2e`
  covers worksheet preview, import, export, final-scene replay, source comparisons, and shell jump targets.

### 4.5 Release evidence expectations

Release-facing docs must now record:

- the 2026-04-12 Windows lane counts
- the 2026-04-12 seeded browser lane result of `4 passed`
- the four fixture operator refs
- the 2026-04-12 WSL strict Chroma counts
- whether domain read decomposition and dual pagination evidence came from automated route/helper tests, browser E2E, or both

---

## 5. Supersede Note

This document supersedes the 2026-04-10 runtime-ops closeout design and the 2026-04-11 review/index query-closure design as the current runtime shell documentation snapshot.

Those earlier documents remain historical slices:

- `docs/superpowers/specs/2026-04-10-human-review-runtime-ops-closeout-design.md`
- `docs/superpowers/specs/2026-04-11-review-index-query-closure-design.md`

They should remain unchanged; this 2026-04-12 document is the place where the current contract snapshot is reconciled.
