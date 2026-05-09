# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Full Stack Lifecycle (Windows)
- Start full stack: `.\start-dev.cmd` (runs backend + frontend, opens browser)
- Stop full stack: `.\stop-dev.cmd`
- Restart full stack: `.\restart-dev.cmd`

Default addresses: frontend `http://127.0.0.1:5173`, backend `http://127.0.0.1:8000`. If the backend port is in use, the script picks the next available one and writes it to `.codex-run/backend.url`.

### Backend (Python 3.12 / FastAPI)
Located in `backend/`. Activate the venv first: `.\.venv\Scripts\Activate.ps1` (Windows) or `source .venv/bin/activate` (Linux/WSL).

```powershell
cd backend
python -m pytest                                        # all Windows-safe tests
python -m pytest backend/tests/test_snowflake_workspace_v2.py  # single file
python -m pytest -k "test_materialize"                 # by name pattern
python -m pytest -m "not chroma_integration"           # exclude Linux-only tests
```

Tests marked `@pytest.mark.chroma_integration` require real ChromaDB and are skipped on Windows automatically. Run them via WSL:
```
wsl -d Ubuntu-24.04 bash -lc "cd <wsl-path> && bash scripts/verify_wsl_strict.sh"
```

Full Windows CI lane: `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`

### Frontend (Vue 3 + Vite + Pinia)
Located in `frontend/`.

```powershell
cd frontend
npm install          # first time
npm run dev          # dev server
npm run test         # vitest unit tests + smoke.mjs
npm run test:e2e     # Playwright E2E
npm run build        # production build

# run a single spec
npx vitest run tests/snowflakeWorkbench.spec.js
```

### Database Migrations
```powershell
cd backend
python -m alembic current
python -m alembic heads
python -m alembic upgrade head
```

A `database operation failed` response usually means the schema is stale — run `upgrade head` first.

### Author-State Reset
Wipes all project/snowflake/chapter data while preserving reference profiles and system config:
```powershell
cd backend
python -m novel_system.tools.reset_author_state           # dry-run
python -m novel_system.tools.reset_author_state --execute --yes
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `NOVEL_SYSTEM_DATABASE_URL` | `sqlite:///./novel_system.db` | SQLAlchemy DB URL |
| `NOVEL_SYSTEM_VECTOR_BACKEND` | `chroma` | `chroma` or `memory` (memory = deterministic, no ChromaDB) |
| `NOVEL_SYSTEM_CHROMA_DIR` | `./.vector_store` | ChromaDB persistence path |
| `NOVEL_SYSTEM_LLM_ENABLED` | `false` | Enable real LLM calls |
| `NOVEL_SYSTEM_LLM_PROVIDER` | `openai_compatible` | Provider: `openai`, `anthropic`, `deepseek`, `zhipu_glm`, `gemini` |
| `NOVEL_SYSTEM_LLM_BASE_URL` | `https://api.openai.com/v1` | Provider base URL |
| `NOVEL_SYSTEM_LLM_API_KEY` | — | API key for the provider |
| `NOVEL_SYSTEM_LLM_TIMEOUT_SECONDS` | `30.0` | Per-call LLM timeout |
| `NOVEL_SYSTEM_ADMIN_TOKEN` | — | Admin endpoint auth token |
| `NOVEL_SYSTEM_CONFIG_SECRET` | — | Secret for encrypted config snapshots |

## High-Level Architecture

### Backend (`backend/src/novel_system/`)

FastAPI application (`api/app.py`) with one router per domain area (`api/routes/`). Each route file maps to a service in `services/`. The `db/models.py` file contains all SQLAlchemy ORM models; `db/session.py` manages the engine.

**Domain layers:**
- `services/projects.py` + `services/snowflake_workspace.py` — Snowflake Method planning pipeline
- `services/snowflake_planner.py` + `services/snowflake_steps.py` — step catalog, completeness gates, materialization rules
- `services/snowflake_workspace_llm.py` + `services/llm_task_runner.py` — LLM call orchestration
- `services/llm_client.py` — multi-provider LLM client (OpenAI-compatible, Anthropic, DeepSeek, Zhipu GLM, Gemini)
- `services/scene_generation.py` + `services/qc_engine.py` + `services/scene_quality.py` — scene pipeline and quality gates
- `services/reference_learning.py` + `services/style_profile.py` — reference book import and abstract style-profile extraction
- `services/vector_store.py` — ChromaDB abstraction; swapped for in-memory store when `NOVEL_SYSTEM_VECTOR_BACKEND=memory`
- `services/versioning/` — promotion, review materialization, runtime recovery, vector lifecycle
- `services/idempotency.py` + `services/hash_engine.py` — idempotency contracts for LLM calls and content hashing

**Key data models** (all in `db/models.py`):
- `StoryProject` / `OutlinePlan` — top-level novel project and its outline
- `SnowflakeArtifact` / `SnowflakeStepRun` — per-step artifacts and run state for the 10-step snowflake
- `SnowflakeScenePlan` / `SnowflakeSceneTriageItem` — scene-level plans and quality triage
- `SnowflakeCharacterPlan` — per-character snowflake data
- `ChapterGoal` / `SceneCard` — materialized chapter/scene production units (created by structure materialization)

**LLM task routing** is declared in `config/models.yaml` (task name → provider/model/temperature). Prompt templates live in `config/prompts.yaml`. Runtime LLM config can also be stored in the DB (via `SystemConfigSnapshot`) and applied on top of env vars by `settings.py:get_settings()`.

**Request middleware**: every request gets `request.state.request_id` (a hex prefix) and `request.state.operator_ref` (from `X-Operator-Ref` header or `"operator"`). Mutating frontend calls pass this header for audit trails.

### Frontend (`frontend/src/`)

Vue 3 SPA. Navigation is managed by `router.js` (a custom SPA router, not Vue Router), with view state in individual Pinia stores under `stores/`. The API layer lives in `lib/api/` (domain modules re-exported via `lib/api/index.js`). Each module reads the backend base URL from `localStorage` (key `novel-system-api-base`) and falls back to `VITE_NOVEL_SYSTEM_API_BASE` or `http://127.0.0.1:8000`.

**Primary writer views** (in `views/`):
- `SnowflakeWorkbenchView.vue` — main entry; 10-step snowflake generation, scene triage, structure materialization and confirmation
- `WriterRoomView.vue` — inline text editing for current chapter/scene
- `ReferenceLearningView.vue` — import TXT/MD books and bind style profiles to a project
- `ReviewInboxView.vue` — human-review queue (QC blocks, safety flags, triage exceptions)

**Advanced/production views** (hidden from writer mode):
- `AuthorWorkspaceView.vue`, `SceneWorkbenchView.vue`, `ChapterManuscriptView.vue`, `LongformControlView.vue`
- `KnowledgeConsoleView.vue`, `IndexConsoleView.vue`, `InteropCenterView.vue`, `SystemConfigView.vue`

The `UiModeSwitch` component switches between `作家` (writer) and `高级` (advanced) modes, which controls which views are accessible.

### Key Architectural Concepts

- **Snowflake Method pipeline**: The primary authoring flow. Author progresses through 10 ordered steps (reader positioning → one-line summary → one-paragraph summary → character summaries → one-page synopsis → character backstories → long outline → character bibles → scene list → scene planning). Each step produces a `SnowflakeStepRun` with draft JSON. Steps 1, 2, 3, 9, 10 are hard gates for structure materialization; others produce warnings.
- **Structure Materialization**: `POST /api/v2/projects/{id}/snowflake-workspace/materialize` converts approved `SnowflakeScenePlan` rows into `ChapterGoal` and `SceneCard` records. Proactive scenes get `Goal/Conflict/Setback` written to `SceneCard.writer_brief_json`; reactive scenes get `Reaction/Dilemma/Decision`.
- **Scene Triage**: Before materialization, each scene plan is scored and assigned a triage status (`qualified`, `needs_fix`, `rewrite`). The `suggest` endpoint uses LLM to recommend triage decisions.
- **Vector Backend Split**: Windows tests always use `memory` backend; real ChromaDB only runs in Linux/WSL and is gated by the `chroma_integration` pytest marker. `conftest.py` applies this automatically.
- **Reference Learning**: Imports books as `ReferenceBook` → segments → style findings → `ReferenceProfile`. Profiles are abstract (rhythm, syntax, structure); the system must never copy source text, characters, or plot.
- **Dual-stack Pagination**: API responses support both `page`/`page_size` (offset) and `cursor`/`limit` (cursor-based) patterns via `services/pagination.py`.
