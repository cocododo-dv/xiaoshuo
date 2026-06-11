# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Commands

### Full Stack Lifecycle (Windows)
- Start full stack: `.\start-dev.cmd` (runs backend + frontend, opens browser)
- Stop full stack: `.\stop-dev.cmd`
- Restart full stack: `.\restart-dev.cmd`

Default addresses: frontend `http://127.0.0.1:5173`, backend `http://127.0.0.1:8000`. If the backend port is in use, the script picks the next available one and writes it to `.codex-run/backend.url`.

### Backend (Python 3.12 / FastAPI)
Located in `backend/`. Two venvs exist: `.venv` (Windows native) and `.venv-wsl` (Linux/WSL). Activate the appropriate one first: `.\.venv\Scripts\Activate.ps1` (Windows) or `source .venv-wsl/bin/activate` (WSL).

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

### Frontend (React, primary) — `frontend-react/`
The production frontend (FE 主线对齐 D1): the 「潮汐工作台」 high-fidelity prototype
(`codex-patches/FE-主线对齐/design/`) engineered as Vite + React 18. `start-dev.cmd`
serves it on `http://127.0.0.1:5174` and opens it by default; the Vue frontend (5173)
is legacy/backup.

```powershell
cd frontend-react
npm install        # first time
npm run dev        # http://127.0.0.1:5174
npm run build
```

Architecture rules (see `codex-patches/FE-主线对齐/契约附录-store缝合面.md`):
- **Store layer only**: views keep the prototype's store contracts (WsWorks / WsCatalog /
  WsTrashStore / review store / Lf7Bridge); stores are API-backed with sync in-memory
  caches (optimistic write + rollback / refetch-on-failure).
- `src/lib/client.js` mirrors the Vue client contract (envelope / X-Idempotency-Key /
  X-Operator-Ref / `novel-system-api-base` localStorage override).
- localStorage holds only UI preferences and read caches of backend truth
  (`wr-doc:*` is a write-through cache of author-drafts); business writes all go
  through `/api/v1` + `/api/v2` endpoints.
- Demo data comes from the backend seed (`novel_system.tools.seed_fe_demo_works`,
  project ids `tide`/`salt` — keep these literal ids).
- Contract-level E2E: `cd frontend; node ../frontend-react/scripts/run-smokes.mjs`
  (runs smoke-phase2..7 against a seeded backend; uses frontend/'s Playwright install).
- Progress ledger & deferred items: `codex-patches/FE-主线对齐/PROGRESS.md`.

### Frontend (Vue 3 + Vite + Pinia, legacy)
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
- `services/style_reference/` — reference-book style subsystem (ingest → segment → extract → synthesize → inject → validate → materialize); replaced the legacy `reference_learning.py`. See "Style Reference subsystem" below
- `services/style_profile.py` — older abstract style-feature contract extractor (7 features: rhythm/syntax/imagery/narrative_distance/…), separate from `style_reference/`
- `services/source_safety.py` + `services/reference_safety.py` — copy guardrails (protected source terms + n-gram copy detection over reference material)
- `services/vector_store.py` — ChromaDB abstraction; swapped for in-memory store when `NOVEL_SYSTEM_VECTOR_BACKEND=memory`
- `services/versioning/` — promotion, review materialization, runtime recovery, vector lifecycle
- `services/idempotency.py` + `services/hash_engine.py` — idempotency contracts for LLM calls and content hashing

**Key data models** (all in `db/models.py`):
- `StoryProject` / `OutlinePlan` — top-level novel project and its outline
- `SnowflakeArtifact` / `SnowflakeStepRun` — per-step artifacts and run state for the 10-step snowflake
- `SnowflakeScenePlan` / `SnowflakeSceneTriageItem` — scene-level plans and quality triage
- `SnowflakeCharacterPlan` — per-character snowflake data
- `ChapterGoal` / `SceneCard` — materialized chapter/scene production units (created by structure materialization)
- `StyleReferenceBook` / `…Paragraph` / `…Run` / `…Extraction` / `…Finding` / `…Evidence` / `…Quote` / `…Profile` / `…InjectionBinding` / `…ValidationReport` / `…BannedTerm` / `…MetricEvent` — the Style Reference subsystem's table family

**Configuration** lives in the project-root `config/` directory (not inside `backend/`):
- `config/models.yaml` — model profiles (`local_fast`, `quality_strong`, `dual_track`) and task routing (task name → provider/model/temperature/response_format)
- `config/prompts.yaml` — prompt templates with `system_prompt`, `task_prompt`, `structured_schema`, and `input_token_budget`
- `config/allowlists.yaml` / `config/hash_contract.yaml` / `config/writer_rubrics.yaml` — domain policy files
- `config/style_reference/` — Style Reference policy files (`banned_adjectives.yaml`, `extraction.yaml`, `injection_budget.yaml`, `input_thresholds.yaml`, `sensory_lexicon.yaml`, `tolerance_floors.yaml`, `anti_plagiarism_template.txt`, `prompts/`)
- `config/evals/` — evaluation datasets for literary quality scoring

Runtime LLM config can also be stored in the DB (via `SystemConfigSnapshot`) and applied on top of env vars by `settings.py:get_settings()`.

**LLM node registry** (`services/llm_node_registry.py`) defines the catalog of all LLM-calling nodes as `LLMNodeSpec` dataclasses (node_id, model, temperature, reasoning_level, api_mode). The system config UI routes each node to a specific provider at runtime. `config/models.yaml` provides task-level defaults; DB-stored routes override them.

**Response envelope**: all API responses use `{ok: bool, data: ..., error: {code, message, details}, request_id}` (see `api/response.py`). Frontend `client.js` parses this envelope and throws `ApiRequestError` with structured fields on failure.

**Request middleware**: every request gets `request.state.request_id` (a hex prefix) and `request.state.operator_ref` (from `X-Operator-Ref` header or `"operator"`). Mutating frontend calls pass `X-Idempotency-Key` and `X-Operator-Ref` headers for idempotency and audit trails.

**Author-action pattern** (`services/author_actions.py`): when the backend detects a missing prerequisite (e.g., LLM not configured, step incomplete), it returns an `author_action` dict that tells the frontend which view to navigate to and what button to show. This avoids hard-blocking the user while still guiding them.

**Style Reference subsystem** (`services/style_reference/`, route prefix `/api/v2/style-reference`): the reference-book style engine that replaced the legacy `reference_learning.py`. Pipeline: `ingest` (import + checksum + `assess_input_size` layer gating) → `segmentation/` (paragraph typing via heuristic + LLM classifier with anchor-set calibration) → `extractors/` (four layers — `language` / `narrative` / `scene` / `theme` — over 16 sub-dimensions; each finding requires ≥2 evidence spans and rejects banned vague adjectives, enforced by Pydantic + two-level retry) → `profile_synthesizer` (16 sub-profiles → `StyleProfile` + metrics baseline) → `injection/` (A=System-prompt / B=Few-shot / C=RAG strategies with a `style_intensity` slider and per-`TaskType` defaults) → `validation/` (three concurrent checks — `quantitative` adaptive-tolerance + `semantic` critic-LLM + `plagiarism` n-gram; sync fast-path for QC gates, async polling otherwise) → `materialization` (profile → `ReviewItem` → style rules). `metrics.py` computes hard quantitative anchors (sentence length, sensory-word frequency, dialogue ratio) as pure functions reused across extract/validate/preview. Findings are `observation` or `forbidden_pattern` (anti-samples), distinguished by `finding_kind`. Anti-plagiarism is two-layer: prevention (fixed System-prompt red-line segment) + detection (8-gram / 12-char). Authoritative design: `docs/style_reference_module_design_v1.1.md`; progress log: `docs/style-reference-progress.md`.

### Frontend (`frontend/src/`)

Vue 3 SPA. Navigation is managed by `router.js` (a custom SPA router, not Vue Router) which defines `workflowGroups` (journey stages: shape/draft/polish/inform/decide/toolbox) and a flat view list with metadata like `writerPrimary`, `writerOrder`, `nextViews`, and `cacheMode`. View state lives in individual Pinia stores under `stores/` (one store per major view). The API layer lives in `lib/api/` (domain modules re-exported via `lib/api/index.js`). `lib/api/client.js` handles the response envelope, idempotency keys, operator-ref headers, and `ApiRequestError` normalization. Each module reads the backend base URL from `localStorage` (key `novel-system-api-base`) and falls back to `VITE_NOVEL_SYSTEM_API_BASE` or `http://127.0.0.1:8000`.

**Primary writer views** (in `views/`):
- `SnowflakeWorkbenchView.vue` — main entry; 10-step snowflake generation, scene triage, structure materialization and confirmation
- `WriterRoomView.vue` — inline text editing for current chapter/scene
- `ReferenceLearningView.vue` (`参考书学习`) — front end for the Style Reference subsystem: import books, run extraction, synthesize a profile, and bind a `ready` profile to a project (refactored in place; route slot and `stores/referenceLearning.js` retained)
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
- **Style Reference (style imitation)**: Profiles are *abstract* (layered rhythm/syntax/imagery/narrative dimensions + anti-clone `forbidden_pattern`s) — the system must never copy source text, characters, settings, or signature imagery. See the "Style Reference subsystem" above for the ingest→extract→inject→validate pipeline; `services/source_safety.py` + `services/reference_safety.py` enforce the copy guardrails.
- **Dual-stack Pagination**: API responses support both `page`/`page_size` (offset) and `cursor`/`limit` (cursor-based) patterns via `services/pagination.py`.
- **Test Isolation**: `conftest.py` auto-creates an isolated SQLite DB per test in `tmp_path`, resets the engine, and auto-skips `chroma_integration`-marked tests on Windows. No shared test state between tests.
- **Snowflake Assistant Turns**: `SnowflakeWorkspaceAssistantService` stores conversational coaching turns per step, enabling LLM-guided iterative refinement of snowflake drafts without losing context.
