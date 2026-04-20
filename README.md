# Novel System P2

This repository currently uses a split verification strategy for the vector layer:

- Windows native Python is supported for non-Chroma unit and contract tests.
- Real Chroma write-path verification is treated as Linux-only and should run in WSL Ubuntu 24.04.

This prevents the Windows native `chromadb` crash path from taking down unrelated backend tests.
The strict Chroma lane has already been verified successfully in WSL Ubuntu 24.04 for this repo; keep using that lane for future real-Chroma regression checks.

## Verification Scripts

Use the repository-level verification scripts first. They wrap the current supported test/build flows and keep the commands aligned with CI and release docs.

Windows-safe verification:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1
```

The backend half of `scripts/verify_windows.ps1` is the current CI-safe verification lane for true generation work:

- `backend/tests/test_scene_generation.py` exercises provider-backed generation with fake-provider fixtures.
- `backend/tests/test_qc_engine.py` exercises hard/soft QC with fake-provider fixtures.
- `backend/tests/test_chapter_runner.py` and `backend/tests/test_chapter_runtime.py` cover the current chapter runner/runtime path inside the same backend pytest lane.
- Until secrets handling is formalized, real-provider smoke checks remain local-only evidence and must be reported separately from this required fake-provider/deterministic lane.

WSL strict Chroma verification:

```powershell
wsl -d Ubuntu-24.04 bash -lc "cd <current-checkout-in-wsl> && bash scripts/verify_wsl_strict.sh"
```

Replace `<current-checkout-in-wsl>` with the checkout/worktree root you are validating, not a different clone.

Release preflight from Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_release.ps1
```

`scripts/verify_release.ps1` now runs three local lanes in order:

- Windows-safe backend/frontend verification via `scripts/verify_windows.ps1`
- Seeded chapter-runtime + runtime-ops + knowledge-console + interop-center browser E2E via `cd frontend && npm run test:e2e`
- WSL strict Chroma verification via `scripts/verify_wsl_strict.sh`

GitHub Actions still covers the backend non-Chroma lane plus the frontend test/build lane only. That means CI must stay green on the fake-provider/deterministic backend lane, while any real-provider smoke evidence is local-only until secrets handling is formalized. The seeded browser E2E lane and the WSL strict Chroma lane remain required local release checks on this machine. Use [docs/release-checklist.md](docs/release-checklist.md) before marking a Draft PR ready.

## Backend on Windows

Use the Windows lane for regular backend work that does not require real Chroma writes.

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1 -BackendOnly
```

Notes:

- Non-integration backend tests default to `NOVEL_SYSTEM_VECTOR_BACKEND=memory`.
- If `NOVEL_SYSTEM_VECTOR_BACKEND=chroma` is selected on native Windows, the app fails fast with a clear `CHROMA_RUNTIME_UNSUPPORTED` error instead of crashing the process.

## Strict Chroma in WSL

The strict Chroma lane is intended for WSL Ubuntu 24.04 and is the verified path for real Chroma on this machine.

Recommended setup:

```powershell
wsl --install -d Ubuntu-24.04
```

Once the distro is available:

```bash
cd <current-checkout-in-wsl>/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cd ..
bash scripts/verify_wsl_strict.sh
```

The `python -m novel_system.tools.chroma_smoke` command is the minimum preflight check. It must succeed before running the strict Chroma backend suite.

Most recent successful verification:

- `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- `cd frontend && npm run test:e2e`
- `wsl -d Ubuntu-24.04 bash -lc "cd <current-checkout-in-wsl> && bash scripts/verify_wsl_strict.sh"`
- 2026-04-15 Windows lane result: backend `164 passed, 12 deselected`; frontend `92 passed`; frontend smoke passed; production build succeeded.
- 2026-04-15 seeded browser E2E result: Playwright `8 passed`, including chapter runtime ops, the focused scene LLM pipeline, runtime-ops closeout, `Knowledge Console` workflow/provenance, and `Interop Center` worksheet preview/import/export/replay.
- 2026-04-12 WSL strict lane result: Chroma smoke succeeded; focused Chroma suite `12 passed`; full backend suite `91 passed, 1 skipped`.

## Demo seed

Use the demo seed to bootstrap the first chapter, three scene cards, and one pending review item.

```powershell
cd backend
alembic upgrade head
python -m novel_system.tools.seed_demo
python -m uvicorn novel_system.api.app:create_app --factory --reload
cd ../frontend
npm install
npm run dev
```

The seed expects the local SQLite schema to be at the current Alembic head. Run `alembic upgrade head` first if you are starting from a fresh or older local database.

The seed is idempotent, so rerunning it keeps the same `CH001` / `CH001_SC01..03` / `review_demo_style_observation` records, avoids duplicate rows, and resets the seeded chapter, scene, and review records back to their bootstrap shape. Shared vector alias state is still owned by the normal review/reindex flow.

For the memory backend used by the Windows-safe lane and the local demo path, the in-process vector store is reused per resolved vector-store directory. That keeps seeded candidate/active alias state visible across multiple API requests in the same session, so the demo can now complete `approve -> verify -> release` without switching backends.

Runtime-ops closeout note:

- The shell persists the operator identity in local storage under `novel-system-operator-ref`.
- Every mutating frontend POST request sends `X-Operator-Ref`, so receipts, runtime ledger entries, and human review follow-up actions can be traced back to the active operator.

## One-click Windows Dev Lifecycle

Use the root launchers when you want the local demo stack to bootstrap and run without manually opening separate backend/frontend terminals.

Start both services:

```powershell
.\start-dev.cmd
```

Stop the tracked backend/frontend process trees:

```powershell
.\stop-dev.cmd
```

Restart the full stack:

```powershell
.\restart-dev.cmd
```

What the lifecycle wrapper does:

- runs `alembic upgrade head` in `backend`
- reruns the idempotent demo seed
- starts FastAPI on `http://127.0.0.1:8000`
- starts Vite on `http://127.0.0.1:5173`
- records logs under `.codex-run/`

If you want to re-verify the wrapper itself, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_dev_lifecycle.ps1
```

## Reference Book Learning Quick Start

Use this flow when you want to drop in one TXT/MD reference book, let the system sample it, and only make review decisions.

1. Start the local stack with `.\start-dev.cmd` or `.\restart-dev.cmd`, then open `http://127.0.0.1:5173`.
2. Open `Reference Learning` in the shell.
3. Import a `.txt`, `.md`, or `.markdown` file by upload or local path.
4. Choose the cloud policy before importing:
   - `local_only`: never calls the LLM path; uses deterministic local heuristics.
   - `segments_only`: sends only selected segments to the configured LLM route.
   - `allow_full_cloud`: allows full-book processing through segment-by-segment map/reduce; it does not send the whole book as one prompt.
5. Start a learning run and click advance. Each round produces review cards for style rules, style observations, narrative patterns, banned replication rules, and calibration candidates.
6. Approve or reject the cards. The run pauses whenever review is pending; once enough approved coverage exists, it synthesizes a per-book reference profile.
7. Apply the profile to `global`, `chapter`, or `scene`. Applying only creates review items; it does not activate the profile automatically.
8. In `Review Inbox`, approve and release the generated apply reviews. After release, the scene bundle can include the style profile and narrative patterns.

The reference profile is intentionally abstract. Runtime data should contain transferable craft guidance, narrative structure, calibration notes, and forbidden replication rules; it should not preserve long source sentences, named characters, settings, proper nouns, or recognizable scene bridges from the reference book.

Current v1 limits:

- TXT/MD only; EPUB/PDF/DOCX are not supported yet.
- UTF-8 is tried first, then GB18030 fallback.
- Reference profiles are stored as independent assets per book and only enter generation after manual apply/review/release.

## End-to-end Demo

```powershell
cd backend
alembic upgrade head
python -m novel_system.tools.seed_demo
python -m uvicorn novel_system.api.app:create_app --factory --reload
cd ../frontend
npm install
npm run dev
```

Manual inspection is still useful during development. When you want the release-grade seeded runtime-ops coverage on Windows, run the automated lane instead:

```powershell
cd frontend
npm run test:e2e
```

The Playwright lane seeds the browser fixtures, forces the memory vector backend, keeps `NOVEL_SYSTEM_LLM_ENABLED=false`, and validates five browser paths with `Operator Ref = ops.chapter.e2e`, `ops.scene-llm.e2e`, `ops.runtime.e2e`, `ops.knowledge.e2e`, and `ops.interop.e2e`. This browser lane proves the deterministic offline/fake-provider path, not a real-provider secret-backed integration:

- `Scene Workbench` chapter runtime path loads `CH200_SC01` and exercises staged backfill, manual hold, and final aggregate
- `Scene Workbench` scene LLM path loads `CH001_SC01`, runs the full scene pipeline, records `offline_deterministic` generation evidence, shows hard/soft QC pass summaries, and finishes with an archived final scene
- `Scene Workbench` runtime path loads `CH001_SC01` and runs the full scene pipeline
- `Review Inbox` approves, verifies, and releases `review_demo_style_observation`
- `Index Console` retries verify jobs, runs due promotions, and runs recovery sweep
- Recovery-generated human review follow-up actions progress through `retry_request`, `retry_verify`, and `release_review`
- Receipts, runtime ledger views, target activity, and cross-view target focus all keep the expected actor / linked-target identity
- `Knowledge Console` creates candidates, runs approve / verify / release workflow, applies object / scope / scope-ref / status filters, clears stale detail state when filters exclude the current lineage, opens linked review refs in `Review Inbox`, and opens bundle refs in `Scene Workbench`
- `Interop Center` previews strict YAML worksheets, imports validated bundles, exports bundle worksheets, replays final-scene envelopes, and surfaces version/text drift comparisons with cross-view jumps back into the shell

If you want to inspect the seed manually instead, use the local dev servers above and inspect:

- `Author Workspace` for chapter/scene source-of-truth editing and handoff into runtime
- `Author Trash` for restore / purge behavior after author-side trash actions
- `Scene Workbench` with `CH001_SC01`
- `Review Inbox` with `review_demo_style_observation`
- `Index Console` after approve / verify / release actions create alias and job activity
- `Interop Center` with a strict YAML worksheet targeting existing `CH001` / `CH001_SC01` records

## Runtime Ops Closeout Demo

Use this walkthrough only when you need an extra manual spot-check beyond the automated `npm run test:e2e` lane:

1. Start from the seeded flow above, including `alembic upgrade head`, and set `Operator Ref` in the shell rail before taking any mutating action.
2. In `Scene Workbench`, load `CH001_SC01`, run the full scene pipeline, and confirm the run receipt updates in place.
3. In `Review Inbox`, approve and release `review_demo_style_observation`, then inspect any surfaced human review events and trigger the available retry action.
4. In `Index Console`, exercise verify retry, `run due promotions`, and `recovery sweep`.
5. Confirm the latest receipts, runtime ledger, and target activity groups all retain the correct actor and linked targets.

The runtime-ops slice is considered closed out only when the seeded demo path, the runtime ledger, and the cross-view target jumps all agree on actor and target identity.

If you need strict real-Chroma verification, use the WSL lane above instead of native Windows.

## Runtime Shell Read APIs

The shell currently reads through a mix of stable compatibility endpoints and decomposed domain endpoints:

- `Review Inbox` reads `GET /api/v1/review-items` and `GET /api/v1/human-review-events`
- `Scene Workbench` reads `GET /api/v1/scenes/{scene_id}/workbench`, `GET /api/v1/scenes/{scene_id}/attempts`, and scene-scoped human review reads
- `Knowledge Console` reads `GET /api/v1/knowledge-entries` plus its detail/workflow endpoints
- `Index Console` reads `GET /api/v1/vector-alias-scopes`, `GET /api/v1/jobs`, `GET /api/v1/activity-events`, and `GET /api/v1/target-activity-groups`

The legacy `GET /api/v1/index/alias-scopes`, `GET /api/v1/index/jobs`, and `GET /api/v1/index/runtime-ledger` routes remain available as compatibility surfaces, but the current shell's primary read path for knowledge/index workflows has moved to the decomposed domain endpoints above.

## Pagination

The runtime shell now uses dual-stack pagination on the list endpoints that need operator paging:

- `GET /api/v1/review-items`
- `GET /api/v1/human-review-events`
- `GET /api/v1/jobs`
- `GET /api/v1/scenes/{scene_id}/attempts`

Each endpoint accepts both `page` / `page_size` and `cursor` / `limit`. `Scene Workbench` still includes the full attempt list inside `/api/v1/scenes/{scene_id}/workbench` for compatibility, while the dedicated `/attempts` endpoint is the paged source used by the UI pager.

## Frontend

The frontend now runs as a Vue 3 + Pinia Vite app on top of the existing backend contract.

```powershell
cd frontend
npm install
npm run dev
```

The shell currently exposes `Author Workspace`, `Author Trash`, `Scene Workbench`, `Review Inbox`, `Index Console`, `Knowledge Console`, and `Interop Center`. `Interop Center` is the worksheet workstation for strict YAML preview/import/export/replay flows and cross-view provenance inspection, while `Author Workspace` / `Author Trash` cover the author-side source-of-truth and recycle lifecycle.
