# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Full Stack Lifecycle (Windows)
- Start full stack: `.\start-dev.cmd` (Runs backend/frontend and opens browser)
- Stop full stack: `.\stop-dev.cmd` 
- Restart full stack: `.\restart-dev.cmd`

### Backend (Python/FastAPI)
The backend is located in the `backend/` directory and uses Python 3.12.
- Activate environment: `cd backend` then `.\.venv\Scripts\Activate.ps1` (or `source .venv/bin/activate` on Linux/WSL)
- Run tests (Windows-safe): `cd backend` then `python -m pytest` or `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1 -BackendOnly`
- Verify WSL strict (real Chroma, WSL Ubuntu 24.04): `wsl -d Ubuntu-24.04 bash -lc "cd <current-checkout-in-wsl> && bash scripts/verify_wsl_strict.sh"`
- Reset demo data: `cd backend && alembic upgrade head && python -m novel_system.tools.seed_demo`

### Frontend (Vue 3 + Vite)
The frontend is located in the `frontend/` directory and uses Vue 3 and Pinia.
- Install dependencies: `cd frontend && npm install`
- Start dev server: `cd frontend && npm run dev`
- Run unit/smoke tests: `cd frontend && npm run test`
- Run E2E tests (Playwright): `cd frontend && npm run test:e2e`
- Build production: `cd frontend && npm run build`

### CI/Release Verification
- Verify Windows (safe for local development without WSL): `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- Release preflight (runs all local lanes): `powershell -ExecutionPolicy Bypass -File scripts/verify_release.ps1`

## High-Level Architecture

This is a Novel System application featuring a decoupled backend/frontend architecture with a split verification strategy.

### Backend (`backend/`)
- Built with FastAPI and SQLAlchemy
- Split verification strategy for the vector layer (ChromaDB):
  - Windows lane uses memory backend (`NOVEL_SYSTEM_VECTOR_BACKEND=memory`) for fake-provider/deterministic testing
  - Linux/WSL lane uses real Chroma write-path verification
- Contains modular routes in `backend/src/novel_system/api/`
- Includes background job processing (`novel_system.tools.*`) for seeding and smoke tests
- Database schema changes are managed via Alembic

### Frontend (`frontend/`)
- Vue 3 + Pinia + Vite application
- Includes specialized workflow views:
  - `Author Workspace`: Source-of-truth editing and runtime handoff
  - `Scene Workbench`: Chapter runtime path and scene LLM pipeline
  - `Review Inbox`: Review workflows (approve/verify/release)
  - `Knowledge Console`: Detail/workflow management for reference data
  - `Index Console`: Runtime vector operations, alias scopes, jobs and activity
  - `Interop Center`: YAML worksheet operations (preview/import/export/replay)

### Key Architectural Concepts
- **Runtime Ops Shell**: Frontend views are built around "operations" and operators; mutating requests include `X-Operator-Ref` for auditing/receipts.
- **Vector Backend Abstraction**: Real vector operations are separated from deterministic business logic, allowing safe CI/CD on standard machines.
- **Reference Learning**: Supports importing TXT/MD books to build style/narrative profiles.
- **Pagination**: Dual-stack pagination supporting both `page`/`page_size` and `cursor`/`limit` in API responses.
