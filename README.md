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

GitHub Actions covers the backend non-Chroma lane plus the frontend test/build lane. The WSL strict Chroma lane remains a required local release check on this machine. Use [docs/release-checklist.md](docs/release-checklist.md) before marking a Draft PR ready.

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

Most recent successful verification on 2026-04-09:

- `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- `wsl -d Ubuntu-24.04 bash -lc "cd /mnt/e/codex/xiaoshuo/codex && bash scripts/verify_wsl_strict.sh"`

## Demo seed

Use the demo seed to bootstrap the first chapter, three scene cards, and one pending review item.

```powershell
cd backend
python -m novel_system.tools.seed_demo
python -m uvicorn novel_system.api.app:create_app --factory --reload
cd ../frontend
npm install
npm run dev
```

The seed is idempotent, so rerunning it keeps the same `CH001` / `CH001_SC01..03` / `review_demo_style_observation` records, avoids duplicate rows, and resets the seeded chapter, scene, and review records back to their bootstrap shape. Shared vector alias state is still owned by the normal review/reindex flow.

## End-to-end demo

Use this flow for the current local demo lane on Windows:

```powershell
cd backend
alembic upgrade head
python -m novel_system.tools.seed_demo
python -m uvicorn novel_system.api.app:create_app --factory --reload
cd ../frontend
npm install
npm run dev
```

Then inspect:

- `Scene Workbench` with `CH001_SC01`
- `Review Inbox` with `review_demo_style_observation`
- `Index Console` after approve / verify / release actions create alias and job activity

If you need strict real-Chroma verification, use the WSL lane above instead of native Windows.

## Frontend

The frontend now runs as a Vue 3 + Pinia Vite app on top of the existing backend contract.

```powershell
cd frontend
npm install
npm run dev
```
