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

WSL strict Chroma verification:

```powershell
wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"
```

Release preflight from Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify_release.ps1
```

`scripts/verify_release.ps1` now runs three local lanes in order:

- Windows-safe backend/frontend verification via `scripts/verify_windows.ps1`
- Seeded runtime-ops browser E2E via `cd frontend && npm run test:e2e`
- WSL strict Chroma verification via `scripts/verify_wsl_strict.sh`

GitHub Actions still covers the backend non-Chroma lane plus the frontend test/build lane only. The seeded runtime-ops E2E lane and the WSL strict Chroma lane remain required local release checks on this machine. Use [docs/release-checklist.md](docs/release-checklist.md) before marking a Draft PR ready.

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
cd /mnt/e/codex/xiaoshuo/codex/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cd ..
bash scripts/verify_wsl_strict.sh
```

The `python -m novel_system.tools.chroma_smoke` command is the minimum preflight check. It must succeed before running the strict Chroma backend suite.

Most recent successful verification on 2026-04-10:

- `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- `cd frontend && npm run test:e2e`
- `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`
- Windows lane result: backend `34 passed, 13 deselected`; frontend `33 passed`; production build succeeded.
- Seeded runtime-ops E2E result: Playwright `1 passed`, covering scene run, review approve / verify / release, due promotion, recovery sweep, human-review follow-up, and cross-view target focus.
- WSL strict lane result: Chroma smoke succeeded; focused Chroma suite `13 passed`; full backend suite `46 passed, 1 skipped`.

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

The Playwright lane seeds the `runtime_ops_e2e` fixture, forces the memory vector backend, and validates the following browser path with `Operator Ref = ops.runtime.e2e`:

- `Scene Workbench` loads `CH001_SC01` and runs the full scene pipeline
- `Review Inbox` approves, verifies, and releases `review_demo_style_observation`
- `Index Console` retries verify jobs, runs due promotions, and runs recovery sweep
- Recovery-generated human review follow-up actions progress through `retry_request`, `retry_verify`, and `release_review`
- Receipts, runtime ledger views, target activity, and cross-view target focus all keep the expected actor / linked-target identity

If you want to inspect the seed manually instead, use the local dev servers above and inspect:

- `Scene Workbench` with `CH001_SC01`
- `Review Inbox` with `review_demo_style_observation`
- `Index Console` after approve / verify / release actions create alias and job activity

## Runtime Ops Closeout Demo

Use this walkthrough only when you need an extra manual spot-check beyond the automated `npm run test:e2e` lane:

1. Start from the seeded flow above, including `alembic upgrade head`, and set `Operator Ref` in the shell rail before taking any mutating action.
2. In `Scene Workbench`, load `CH001_SC01`, run the full scene pipeline, and confirm the run receipt updates in place.
3. In `Review Inbox`, approve and release `review_demo_style_observation`, then inspect any surfaced human review events and trigger the available retry action.
4. In `Index Console`, exercise verify retry, `run due promotions`, and `recovery sweep`.
5. Confirm the latest receipts, runtime ledger, and target activity groups all retain the correct actor and linked targets.

The runtime-ops slice is considered closed out only when the seeded demo path, the runtime ledger, and the cross-view target jumps all agree on actor and target identity.

If you need strict real-Chroma verification, use the WSL lane above instead of native Windows.

## Frontend

The frontend now runs as a Vue 3 + Pinia Vite app on top of the existing backend contract.

```powershell
cd frontend
npm install
npm run dev
```
