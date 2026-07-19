# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Product Scope

Single-machine, single-author long-form novel writing system (Chinese-language product). The root `README.md` (Chinese) is the product-truth entry point and `docs/README.md` indexes all documentation — the operator manual documents only the React workbench; dated plans/evidence describe their original run, not the current contract. Product mainline: create work → 10-step snowflake ideation → materialize chapters/scenes → per-scene AI drafting or manual writing → author review promotes authoritative text → final approval in 成稿中心. Explicitly *not* a multi-user SaaS, HA service, or automatic publication arbiter. **Demo data / fake generation are retired**: there is no product demo work, no seeded 「潮汐档案」/「盐镇来信」, and no offline/deterministic stub generation. Every generation node is fail-closed — with no live LLM configured it returns a 409/502 with an `author_action` (never canned prose). The old demo seed lives on only as neutral **test fixtures** under `backend/tests/fixture_works.py` (works `work-a`/`work-b`) + `backend/tests/fixture_runtime.py` (`seed_runtime_fixture`), consumed by tests and the contract-E2E lane; the production runtime never seeds them.

## Common Development Commands

### Full Stack Lifecycle (Windows)
- Start full stack: `.\start-dev.cmd` (runs backend + frontend, opens browser)
- Stop full stack: `.\stop-dev.cmd`
- Restart full stack: `.\restart-dev.cmd`
- Reset runtime DB/artifacts but keep LLM config: `.\reset-runtime-keep-llm.cmd` (→ `scripts/reset_runtime_keep_llm.ps1 -StopServices`; distinct from the Python `reset_author_state` tool below)

On Linux use the shell equivalents: `scripts/start-all-linux.sh` / `scripts/stop-all-linux.sh` (one-shot backend + React frontend, health-probed, logs + pidfiles under `.codex-run/`), or the per-leg `scripts/start-backend-linux.sh` / `scripts/start-frontend-linux.sh` (all safe to re-run — each leg stops its own previous instance first; shared helpers in `scripts/lib/dev-lifecycle.sh`). The backend leg runs `alembic upgrade head` with **`backend/.venv/bin/python`** (not system python) and forces `NOVEL_SYSTEM_VECTOR_BACKEND=memory`; the frontend leg does `nvm use 16` and preloads `frontend-react/crypto-polyfill.cjs` via `NODE_OPTIONS --require` (the newest Node this CentOS 7 / glibc 2.17 host can run is 16, which lacks the global WebCrypto Vite 6 needs). CI (`.github/workflows/ci.yml`, Ubuntu + Node 22) runs the raw commands instead (`cd backend && python -m alembic upgrade head` then `python -m uvicorn novel_system.api.app:create_app --factory --reload --app-dir src`; `cd frontend-react && npm install && npm run dev`).

Default addresses: the **React frontend** `http://127.0.0.1:5174` (what `start-dev.cmd` auto-opens), the backend `http://127.0.0.1:8000`, and the **legacy Vue frontend** `http://127.0.0.1:5173` (**no longer started by default** — pass `-IncludeLegacyVue` to `start-dev.cmd`/`dev.ps1` to also start it). `start-dev.cmd` (→ `scripts/dev.ps1`) brings up the backend + React frontend (plus the legacy Vue frontend only when `-IncludeLegacyVue` is passed) in one shot: it runs `alembic upgrade head` (**no demo seed** — the production launcher never injects demo works), forces `NOVEL_SYSTEM_VECTOR_BACKEND=memory`, auto-generates a `NOVEL_SYSTEM_CONFIG_SECRET`, and writes pid/url files under `.codex-run/` (`backend.url`, `frontend.url`, `frontend-react.url`). If port 8000 is busy it scans upward and records the chosen URL in `.codex-run/backend.url`. Backend readiness is probed at `GET /api/v1/chapters` (a 90s timeout — if migrations are stale this probe 500s and the browser never opens). The backend also exposes `GET /live` (process liveness only) and `GET /ready` (adds DB connectivity + migration revision + required-structure checks) — deployment probes should use their distinct semantics.

### Backend (Python 3.12 / FastAPI)
Located in `backend/`. **On Windows, do not activate a venv** — run backend `pytest` / `alembic` directly with the Anaconda Python on `PATH`, from inside `backend/`. The `.venv` / `.venv-wsl` dirs, when present, are Linux/WSL venvs (no `Scripts\Activate.ps1`) and are only consumed by the WSL/release lanes (e.g. `scripts/verify_wsl_strict.sh`). `pyproject.toml` sets `pythonpath=["src"]` and `testpaths=["tests"]`, so pytest/alembic must run **from `backend/`** with paths relative to it — and the PowerShell working dir resets to repo root between calls, so always `cd backend` in the same command.

```powershell
cd backend
python -m pytest                                        # all Windows-safe tests
python -m pytest tests/test_snowflake_workspace_v2.py          # single file (path is relative to backend/)
python -m pytest -k "test_materialize"                 # by name pattern
python -m pytest -m "not chroma_integration"           # exclude Linux-only tests
```

Tests marked `@pytest.mark.chroma_integration` require real ChromaDB and are auto-skipped on Windows by `backend/tests/conftest.py`. Run them via WSL:
```
wsl -d Ubuntu-24.04 bash -lc "cd <wsl-path> && bash scripts/verify_wsl_strict.sh"
```
The other declared marker, `consistency_validation` (blueprint §17 Action B recall/precision), is **not** auto-skipped and runs in the default Windows suite.

Full Windows CI lane: `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1` (pytest `-m "not chroma_integration"` + `node --test scripts/tests/*.cjs` governance-QA script contract tests from the repo root + the **React mainline** `frontend-react` `npm test` (vitest) + build; the legacy Vue `npm test`/build run only with `-IncludeLegacyVue`). Full release lane (Windows CI → **React mainline contract E2E** (`scripts/verify_react_e2e.ps1`, see below) → WSL strict Chroma; the seeded Vue Playwright E2E runs only with `-IncludeLegacyVue`): `scripts/verify_release.ps1`.

GitHub Actions (`.github/workflows/ci.yml`) gates three jobs on every PR/push: **Backend Tests** (pytest `-m "not chroma_integration"`), **Frontend Tests (React mainline)** (`frontend-react`: `npm ci` → vitest → build), and **Legacy Vue Frontend Tests** (`frontend`). The React mainline job is the authoritative frontend gate; the heavy lanes that need extra infra (the React contract E2E's seeded `:8009` backend, and WSL strict Chroma) stay local in `verify_release.ps1`, mirroring how the Chroma lane has always been local-only.

**Schema-drift guard** (`backend/tests/test_metadata_isolation.py::test_migration_built_schema_matches_orm_models`) — the most important non-obvious gotcha. The test suite builds the schema via `Base.metadata.create_all`, but dev/prod build it via Alembic `upgrade head` (`auto_create_tables` defaults to `False`). This test builds it **both** ways and diffs tables/columns/named-indexes, because an ORM model that gains a column/index **without a matching migration** still passes every test yet 500s at runtime (`OperationalError: no such column`) — which silently kills `start-dev` (its health probe hits `GET /api/v1/chapters`). If it fails: write the missing migration, **or** declare the missing index in the model's `__table_args__`. Run: `cd backend; python -m pytest tests/test_metadata_isolation.py`.

### Frontend (React, primary) — `frontend-react/`
The production frontend is the maintained Vite + React 18 「潮汐工作台」 in
`frontend-react/`. `start-dev.cmd` serves it on `http://127.0.0.1:5174` and opens it
by default (landing view is `主页`, not the snowflake view); the Vue frontend on 5173
is an explicit legacy compatibility lane.

```powershell
cd frontend-react
npm install        # first time
npm run dev        # http://127.0.0.1:5174
npm run build
```

Architecture rules:
- **Store layer only**: views keep the prototype's store contracts — `WsWorks` / `WsCatalog` +
  `WsTrashStore` / `WsReview` (the review store) / `WsLibrary` / `Lf7Bridge`, plus the newer
  `WsManuStore` (成稿中心, `ws-manuscripts-store.jsx`), `WsCost` (`ws-cost.jsx`), `WsEval`
  (`ws-eval.jsx`), `WsAiProviders` (`ws-ai-providers.jsx`), and the writer-side
  `WrDocs`/`WrDocVersions`/`WrRecovery` (`wr-doc-store.jsx`). These are **runtime globals attached
  to `window`** (`Object.assign(window, {...})`) from kebab-case files — grep `window.WsWorks`,
  not an ES import. Stores are API-backed with sync in-memory caches (optimistic write +
  rollback / refetch-on-failure). Writer/advanced mode gating lives here too (`ws-app.jsx`
  `WS_NAV_GROUPS`), not only in the Vue `UiModeSwitch`.
- **Store unit tests** (vitest, `src/*.test.jsx`, ~20 suites): cover the optimistic-write +
  rollback/refetch contract per store — `ws-works`, `ws-catalog` (incl. `WsTrashStore`),
  `ws-review`, `lf7-bridge`, and the newer `ws-ai-providers` / `ws-chapter-run` / `ws-cost` /
  `ws-eval` / `ws-scene-run` / `ws-manuscripts` / `wr-doc-store` / `wr-canonical-control` /
  `wr-content-safety-review` / `wr-recovery-center` suites.
  They `vi.mock("./lib/client.js")` and route `apiGet` by URL through the shared
  `src/test-helpers.js` `installApiRouter`; each store loads in isolation via `vi.resetModules()` +
  dynamic import (the active work falls back to a `__loading__` placeholder until a seeded
  `/api/v2/projects` resolves with a real `project_id`). Run `npm test` (or the `verify_windows.ps1`
  React gate / GitHub CI). Keep tests falsifiable — verify rollback/alert paths actually trip.
- `src/lib/client.js` owns the shared client contract (envelope / X-Idempotency-Key /
  X-Operator-Ref / `novel-system-api-base` localStorage override).
- localStorage holds only UI preferences and read caches of backend truth
  (`wr-doc:*` is a write-through cache of author-drafts); business writes all go
  through `/api/v1` + `/api/v2` endpoints.
- Test/E2E fixture works come from `backend/tests/fixture_works.py` (`seed_fixture_works`,
  project ids `work-a`/`work-b` — keep these literal ids) + `backend/tests/fixture_runtime.py`
  (`seed_runtime_fixture`, also seeds the `PRJ_DEMO_CH001` runtime fixture). These are neutral
  placeholder works for tests only — the product runtime never seeds them.
- Contract-level E2E: `cd frontend; node ../frontend-react/scripts/run-smokes.mjs [BASE] [API]`
  (runs `smoke-phase2..7` + `smoke-ai-settings`, reseeding via `python tests/fixture_runtime.py` before each suite; uses
  frontend/'s Playwright install). Defaults are `BASE=http://127.0.0.1:5174/` and a **separate
  seeded backend** `API=http://127.0.0.1:8009` — not the dev `:8000`. `scripts/verify_react_e2e.ps1`
  now orchestrates this end-to-end (isolated e2e sqlite under `.codex-run/e2e/`, seeded `:8009`
  backend + React `:5174`, full process-tree teardown) and is wired into `verify_release.ps1` as a
  default gate. **Gotcha**: a fresh `alembic upgrade head` aborts on migration `20260523_0036`'s
  legacy-backup guard unless `backups/style_reference_legacy_*.json` exists; the e2e lane satisfies
  it via that migration's `STYLE_REFERENCE_REPO_ROOT` test override pointed at a placeholder backup.
- Current user and engineering documentation is indexed in `docs/README.md`; dated plans and
  evidence describe their original run and are not the current runtime contract.

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

Migration `20260716_0073` **irreversibly** rewrites historical LLM-audit payloads (prompts, drafts, model output, provider error bodies) into bounded fingerprints — back up an existing DB before upgrading past it; preview the affected rows first with `python -m novel_system.tools.llm_audit_scrub --database ./novel_system.db --dry-run`. After upgrading, a strict structural preflight is available: `python -m novel_system.tools.database_preflight ./novel_system.db --expected-revision <head>`.

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
| `NOVEL_SYSTEM_LLM_PROVIDER` | `openai_compatible` | Provider key resolved against the `services/llm_providers/` adapter registry (12 adapters: `openai_compatible`, `openai`, `anthropic`, `deepseek`, `zhipu_glm`, `gemini`, `qwen_dashscope`, `moonshot`, `minimax`, `doubao_ark`, `xai`, `ollama`) |
| `NOVEL_SYSTEM_LLM_BASE_URL` | `https://api.openai.com/v1` | Provider base URL |
| `NOVEL_SYSTEM_LLM_API_KEY` | — | API key for the provider |
| `NOVEL_SYSTEM_LLM_TIMEOUT_SECONDS` | `30.0` | Per-call LLM timeout |
| `NOVEL_SYSTEM_ADMIN_TOKEN` | — | Admin endpoint auth token |
| `NOVEL_SYSTEM_CONFIG_SECRET` | — | Secret for encrypted config snapshots |
| `NOVEL_SYSTEM_AUTO_CREATE_TABLES` | `false` | If true, bypass Alembic and `create_all` tables on startup — **dangerous**: hides schema drift (see the schema-drift guard) |
| `NOVEL_SYSTEM_LLM_AUTO_CRITIQUE_ENABLED` | `false` | §8 opt-in: layer an independent LLM editor critic on top of the rule-based pass in `orchestrator.py` (after Best-of-N, before soft QC) |
| `NOVEL_SYSTEM_LLM_EVENT_EXTRACTION_ENABLED` | `false` | §2 opt-in: extract narrative events from finished prose (`prose_event_extractor.py`) |
| `NOVEL_SYSTEM_CHROMA_COLLECTION_PREFIX` | `novel_system` | Prefix for ChromaDB collection names |
| `NOVEL_SYSTEM_CORS_ORIGINS` | `…:5173/5174/5175/8081` | Comma-separated allowed CORS origins |
| `NOVEL_SYSTEM_EXPOSE_ERROR_DETAIL` | `false` | Whether the error envelope exposes `error.details` |
| `NOVEL_SYSTEM_LITERARY_EVAL_REPORT_PATH` | `.codex-run/literary_eval_latest.json` | Where the literary-eval route writes its latest report JSON |
| `NOVEL_SYSTEM_LOCAL_ONLY` | `true` | Loopback-only: rejects non-loopback clients and forwarded headers. Setting `false` **requires** `NOVEL_SYSTEM_REMOTE_ACCESS_TOKEN` (`create_app` refuses to start otherwise) |
| `NOVEL_SYSTEM_REMOTE_ACCESS_TOKEN` | — | Shared access token when not local-only; the browser sends it as `X-Novel-Access-Token` (frontend default injectable via `VITE_NOVEL_SYSTEM_ACCESS_TOKEN`, runtime value lives in sessionStorage). Not user auth/RBAC |
| `NOVEL_SYSTEM_LLM_DAILY_TOKEN_LIMIT` / `…_MONTHLY_TOKEN_LIMIT` / `…_PROJECT_DAILY_TOKEN_LIMIT` / `…_DAILY_REQUEST_LIMIT` / `…_MAX_CONCURRENT_REQUESTS` | `1M` / `20M` / `250K` / `2000` / `4` | LLM quota family, enforced by the accounting layer *before* provider dispatch |
| `NOVEL_SYSTEM_LLM_DAILY_COST_LIMIT_USD` (+ `…_LLM_INPUT_COST_PER_MILLION_USD` / `…_LLM_OUTPUT_COST_PER_MILLION_USD`) | `0.0` (off) | Optional daily cost cap; a nonzero cap requires nonzero unit prices |
| `NOVEL_SYSTEM_LLM_RESERVATION_RECOVERY_TTL_SECONDS` | `3600` | TTL after which orphaned LLM accounting reservations are reclaimed |
| `NOVEL_SYSTEM_CONTENT_SAFETY_MODE` | `review` | `review` or `audit` — content-risk triage mode on publication actions |
| `NOVEL_SYSTEM_SQLITE_FOREIGN_KEYS_ENABLED` | `true` | Enforce FK pragma on SQLite connections |
| `NOVEL_SYSTEM_CORS_ALLOW_CREDENTIALS` | `true` | CORS credentials flag |
| `NOVEL_SYSTEM_STYLE_REFERENCE_IMPORT_ROOTS` | — | Allowed filesystem roots for style-reference path imports |

## High-Level Architecture

### Backend (`backend/src/novel_system/`)

FastAPI application (`api/app.py`) with one router per domain area (`api/routes/`). Each route file maps to a service in `services/`. The `db/models.py` file contains all SQLAlchemy ORM models; `db/session.py` manages the engine. The authoritative list of mounted routers is the `include_router` calls in `api/app.py` — **not** `api/routes/__init__.py`'s `__all__`, which omits several (`catalog`, `trash`, `library`, `longform_tower`, `project_overview`, `chapter_manuscripts`, `work_profile`, …).

**Domain layers:**
- `services/projects.py` + `services/snowflake_workspace.py` — Snowflake Method planning pipeline
- `services/snowflake_planner.py` + `services/snowflake_steps.py` — step catalog, completeness gates, materialization rules
- `services/snowflake_workspace_llm.py` + `services/llm_task_runner.py` — LLM call orchestration
- `services/llm_client.py` + `services/llm_providers/` — multi-provider LLM client built on a **pluggable adapter registry** (`llm_providers/registry.py` + `presets.py`, one adapter module per provider, 12 in total). Edit provider behavior / default base URLs in `llm_providers/`, not `llm_client.py`
- `services/scene_generation.py` + `services/qc_engine.py` + `services/scene_quality.py` — scene pipeline and quality gates
- `services/style_reference/` — reference-book style subsystem (ingest → segment → extract → synthesize → inject → validate → materialize); replaced the legacy `reference_learning.py`. See "Style Reference subsystem" below
- `services/style_profile.py` — older abstract style-feature contract extractor (7 features: rhythm/syntax/imagery/narrative_distance/…), separate from `style_reference/`
- `services/source_safety.py` + `services/reference_safety.py` — copy guardrails (protected source terms + n-gram copy detection over reference material)
- `services/vector_store.py` — ChromaDB abstraction; swapped for in-memory store when `NOVEL_SYSTEM_VECTOR_BACKEND=memory`
- `services/versioning/` — promotion, review materialization, runtime recovery, vector lifecycle
- `services/idempotency.py` + `services/hash_engine.py` — idempotency contracts for LLM calls and content hashing
- `services/orchestrator.py` (+ `bundle_builder.py`, `scene_execution.py`) — the scene-run pipeline (bundle context → generate → Best-of-N → optional auto-critique → QC). The **blueprint quality-floor v2 / anti-AI-taste** cluster hangs off it: `services/literary_quality.py` (21 weighted quality dimensions incl. `perception_filter` / `self_repetition` / `conflict_too_clean`; route `/api/v1/literary-quality`), `services/best_of_n_blind_eval.py`, `services/self_repetition.py` (cross-scene n-gram + semantic guard, reuses the style-reference plagiarism engine), `services/auto_critique.py` (Reflexion-style editor pass), `services/scene_criticality.py`
- Narrative-coherence / continuity overlay (backs the scene-run pipeline): `services/narrative_event_log.py` + `services/prose_event_extractor.py` (append-only event sourcing), `services/causal_chain_validator.py` + `services/reverse_causal_skeleton.py`, `services/foreshadow_lifecycle.py`, `services/tension_curve.py`, `services/character_continuity.py` (+ `character_arc.py` / `character_psychology.py` / `relationship_matrix.py`), `services/voice_fingerprint.py` + `services/style_drift_detector.py` — among others
- **Outcome-governance / LLM cost cluster**: `services/llm_accounting.py` (durable accounting boundary around *every* provider POST — short reservation → dispatch → settlement transactions, no DB write txn held during network I/O; quotas fail before dispatch), `services/cost_aggregation.py` + `services/pricing.py` + `config/pricing.yaml` (centralized per-provider/model price snapshots, all placeholder rates marked `is_estimate: true`), `services/llm_audit.py` (audit rows store bounded fingerprints, not payloads — see migration `0073`), route `api/routes/cost.py`; audit tools `tools/llm_accounting_audit.py` / `tools/llm_outlet_inventory.py`
- **Evaluation & evidence-gated quality strategy**: `services/evaluation_experiment.py` (persistent anonymous A/B human blind eval on top of the `best_of_n_blind_eval.py` pure core; `next_pair` deliberately never leaks mapping/strategy/tokens), `services/quality_evidence.py` (stage-2 hidden public/private benchmark boundary — rubric text never persisted), `services/quality_strategy.py` (genre × scene-function strategy resolution; Best-of-N enables only when the *exact* cell has completed hidden-run artifacts + human votes), `services/outcome_governance_policy.py` + `config/outcome-governance-policy.json` (fail-closed repo policy — only `apply_evaluation_report` behind the evaluation policy gate can flip the Best-of-N default), tools `evaluation_policy_apply.py` / `evaluation_experiment_report.py` / `outcome_evidence.py` / `quality_evidence.py`; React UI `ws-eval.jsx`. Design/progress: `docs/outcome-governance-roadmap-2026-07-15.md` + `docs/outcome-governance-progress.md`
- **Persistent jobs & crash recovery**: `services/scene_run_jobs.py` (cancellable persistent scene-run jobs) + `scene_run_checkpoint.py` + `scene_run_preflight.py`, `services/chapter_runner.py` (advanced-mode 运行本章 chapter jobs with polled progress), `services/background_recovery.py` (`run_startup_recovery` wired into the FastAPI lifespan — startup scan submits durable candidates; workers own the CAS so duplicate scans from multiple ASGI workers are harmless)
- **Canonical final-text lifecycle**: `services/canonical_manuscripts.py` + `services/final_text_gate.py` + `services/chapter_approval.py` — 成稿中心 final approval requires an explicit read-through confirmation of the *server-side* text, then a body-hash confirm, then project-level `approve-final`; reopening requires a reason and the server cascades revocation of downstream approvals. `services/archiver.py` and `services/narrative_position.py` support this layer
- `services/content_safety.py` — deterministic, auditable content-risk triage on publication: blocks only unattended publication of a few compound high-risk patterns; the author acknowledges exact finding codes on the exact publication action (dark themes stay writable, ordinary genre violence is advisory)
- `services/author_preferences.py` + `services/author_instructions.py` — scoped, prompt-safe author preference/instruction summaries shared by generation, review, and bundle construction

**Key data models** (all in `db/models.py`):
- `StoryProject` / `OutlinePlan` — top-level novel project and its outline
- `SnowflakeArtifact` / `SnowflakeStepRun` — per-step artifacts and run state for the 10-step snowflake
- `SnowflakeScenePlan` / `SnowflakeSceneTriageItem` — scene-level plans and quality triage
- `SnowflakeCharacterPlan` — per-character snowflake data
- `ChapterGoal` / `SceneCard` — materialized chapter/scene production units (created by structure materialization)
- `StyleReferenceBook` / `…Paragraph` / `…Run` / `…Extraction` / `…Finding` / `…Evidence` / `…Quote` / `…Profile` / `…InjectionBinding` / `…ValidationReport` / `…BannedTerm` / `…MetricEvent` / `…FindingFeedback` — the Style Reference subsystem's table family
- `NarrativeEvent` (append-only event-sourcing log — replay events up to a scene to reconstruct entity state), `VolumeSummary`, `ForeshadowTracker` (plant/payoff lifecycle), plus blueprint-v2 columns (`SceneCard.constraint_intensity`, `SceneRunState.criticality_level` / `candidate_dispersion_score`) — the causal/foreshadow/theme overlay on the snowflake pipeline
- `LlmCall` / `LlmCallAttempt` — durable LLM accounting rows (reservation → dispatch → settlement); payload columns hold bounded fingerprints since migration `0073`
- `ChapterRunJob` / `BackgroundRecoveryLease` — persistent chapter runs and the startup-recovery lease
- `EvaluationExperiment` / `EvaluationPair` / `EvaluationVote` + `QualityBenchmarkManifest` / `QualityBenchmarkRun` / `QualityBenchmarkResult` / `QualityStrategyPolicy` / `QualityValueObservation` — the outcome-governance evidence family
- `AuthorPreferenceProfile` — scoped author preferences injected into prompts

**Configuration** lives in the project-root `config/` directory (not inside `backend/`):
- `config/models.yaml` — model profiles (`local_fast`, `quality_strong`, `dual_track`), task routing (task name → provider/model/temperature/response_format), and top-level `retry_budget` + `job_runtime` (lease/idempotency TTLs). The blueprint-v2 quality floor is config-driven here too: new task-routing entries (`scene_blueprint`, `character_pressure_blueprint`, …) and decoding penalties on `stylize` (`frequency_penalty` / `presence_penalty`, §7 anti-mean sampling)
- `config/prompts.yaml` — prompt templates with `system_prompt`, `task_prompt`, `structured_schema`, and `input_token_budget` (incl. the Scene Literary Blueprint v2 / Character Pressure Blueprint templates)
- `config/allowlists.yaml` / `config/hash_contract.yaml` / `config/writer_rubrics.yaml` — domain policy files
- `config/style_reference/` — Style Reference policy files (`banned_adjectives.yaml`, `extraction.yaml`, `injection_budget.yaml` incl. `rag_*` keys, `input_thresholds.yaml`, `sensory_lexicon.yaml`, `tolerance_floors.yaml`, `feedback.yaml`, `anti_plagiarism_template.txt`, `prompts/`)
- `config/evals/` — evaluation datasets for literary quality scoring
- `config/pricing.yaml` — per-(provider, model) price snapshots with `effective_at`, used by cost aggregation (shipped rates are placeholder estimates, `is_estimate: true`)
- `config/outcome-governance-policy.json` — the fail-closed Best-of-N production default; changed only via the evidence-gated `apply_evaluation_report` flow, not by hand
- `config/qa/` — QA lane manifests (e.g. the public-domain source-safety five-chapter run consumed by `scripts/run-*.cjs` and `scripts/tests/`)

Runtime LLM config can also be stored in the DB (via `SystemConfigSnapshot`) and applied on top of env vars by `settings.py:get_settings()`.

**LLM node registry** (`services/llm_node_registry.py`) defines the catalog of all LLM-calling nodes as `LLMNodeSpec` dataclasses (node_id, model, temperature, reasoning_level, api_mode). The system config UI routes each node to a specific provider at runtime. `config/models.yaml` provides task-level defaults; DB-stored routes override them.

**Response envelope**: all API responses use `{ok: bool, data: ..., error: {code, message, details}, request_id}` (see `api/response.py`). Frontend `client.js` parses this envelope and throws `ApiRequestError` with structured fields on failure.

**Request middleware**: every request gets `request.state.request_id` (a hex prefix) and `request.state.operator_ref` (from `X-Operator-Ref` header or `"operator"`). Mutating frontend calls pass `X-Idempotency-Key` and `X-Operator-Ref` headers for idempotency and audit trails.

**Author-action pattern** (`services/author_actions.py`): when the backend detects a missing prerequisite (e.g., LLM not configured, step incomplete), it returns an `author_action` dict that tells the frontend which view to navigate to and what button to show. This avoids hard-blocking the user while still guiding them.

**Style Reference subsystem** (`services/style_reference/`, route prefix `/api/v2/style-reference`): the reference-book style engine that replaced the legacy `reference_learning.py`. Pipeline: `ingest` (import + checksum + `assess_input_size` layer gating) → `segmentation/` (paragraph typing via heuristic + LLM classifier with anchor-set calibration) → `extractors/` (four layers — `language` / `narrative` / `scene` / `theme` — over 16 sub-dimensions; each finding requires ≥2 evidence spans and rejects banned vague adjectives, enforced by Pydantic + two-level retry) → `profile_synthesizer` (16 sub-profiles → `StyleProfile` + metrics baseline) → `injection.py` (A=System-prompt / B=Few-shot / C=RAG strategies with a `style_intensity` slider and per-`TaskType` defaults; binding scope resolves scene > character > project > global) → `validation/` (three concurrent checks — `quantitative` adaptive-tolerance + `semantic` critic-LLM + `plagiarism` n-gram; sync fast-path for QC gates, async polling otherwise) → `materialization` (profile → `ReviewItem` → style rules). `metrics.py` computes hard quantitative anchors (sentence length, sensory-word frequency, dialogue ratio) as pure functions reused across extract/validate/preview. Findings are `observation` or `forbidden_pattern` (anti-samples), distinguished by `finding_kind`. Anti-plagiarism is two-layer: prevention (fixed System-prompt red-line segment) + detection (8-gram / 12-char). **Phase 3 additions** (the recent work): `rag.py` — Strategy C is a real three-granularity (sentence/paragraph/scene) vector recall, with chroma collections `style_ref_rag_{profile_id}_{granularity}` built at synthesize time, deterministic rerank, and no LLM on the inject hot path (acceptance `hit@5 ≥ 0.7`, WSL-only `chroma_integration` test); `finding_feedback.py` — per-operator 👍/👎 votes recalibrate a finding's confidence ±1 tier off a frozen `base_confidence` (policy in `config/style_reference/feedback.yaml`); scene/character binding scopes (`BindingScope` PROJECT/SCENE/CHARACTER); and `cleanup.py` `purge_derived_data` — the library-delete (删书) cascade that manually deletes ~10 derived tables in FK-reverse order plus `ReviewItem` rows and each profile's RAG index (SQLite has no `ON DELETE CASCADE`), deliberately keeping `…MetricEvent`. Authoritative design: `docs/style_reference_module_design_v1.1.md`; progress log: `docs/style-reference-progress.md`.

### Frontend (`frontend/src/`, legacy Vue)

Vue 3 SPA — a compatibility-regression surface only; the operator manual and product docs describe the React workbench exclusively. Navigation is managed by `router.js` (a custom SPA router, not Vue Router) which defines `workflowGroups` (journey stages: shape/draft/polish/inform/decide/toolbox) and a flat view list with metadata like `writerPrimary`, `writerOrder`, `nextViews`, and `cacheMode`. View state lives in individual Pinia stores under `stores/` (one store per major view). The API layer lives in `lib/api/` (domain modules re-exported via `lib/api/index.js`). `lib/api/client.js` handles the response envelope, idempotency keys, operator-ref headers, and `ApiRequestError` normalization. Each module reads the backend base URL from `localStorage` (key `novel-system-api-base`) and falls back to `VITE_NOVEL_SYSTEM_API_BASE` or `http://127.0.0.1:8000`.

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
- **Schema build split**: tests build the schema via `Base.metadata.create_all`, but dev/prod build it via Alembic migrations (`auto_create_tables` defaults to `False`). A model change without a matching migration therefore passes CI but 500s at runtime — the `test_metadata_isolation.py` drift guard (see Backend commands above) is the tripwire. Adding a column/index means writing a migration *and* keeping the ORM `__table_args__` in sync.
- **Scene-run orchestration & quality floor**: `services/orchestrator.py` runs a scene end-to-end — bundle context → generate → Best-of-N → optional LLM auto-critique → QC gates — scored by `literary_quality.py`'s 21 dimensions and guarded against repetition by `self_repetition.py`. This is the "blueprint quality floor v2" layer on top of raw scene generation.
- **Narrative event sourcing**: `NarrativeEvent` is an append-only log treated as the single source of truth for story state; entity state at a given scene is reconstructed by replaying events up to that point (`narrative_event_log.py`, populated from prose by `prose_event_extractor.py` when event extraction is enabled).
- **Durable LLM accounting & quotas**: every provider POST goes through `llm_accounting.py`'s reservation → dispatch → settlement transactions; daily/monthly/per-project token, request, concurrency, and optional cost quotas are checked *before* dispatch, and no DB write transaction is held while waiting on the network. Orphaned reservations are reclaimed after a TTL.
- **Evidence-gated strategy defaults (outcome governance)**: expensive quality strategies (Best-of-N) default off and can only be enabled per exact genre × scene-function cell backed by completed hidden-benchmark runs plus human blind-eval evidence; the production default in `config/outcome-governance-policy.json` changes only through the evaluation-report policy gate. Everything here is fail-closed.
- **Startup background recovery**: the FastAPI lifespan runs `run_startup_recovery` to re-submit durable scene/chapter/style/validation jobs after a crash; persistent leases + worker-owned CAS make duplicate scans harmless. Scene runs are cancellable and checkpointed.
- **Canonical final-text lifecycle**: chapter/project final approval is a deliberate multi-step gate (read-through confirm of server text → body-hash confirm → `approve-final`); the catalog cannot fake `approved`, and reopening needs an auditable reason with server-side cascade revocation of downstream approvals.
- **Local-only network boundary**: the backend defaults to `NOVEL_SYSTEM_LOCAL_ONLY=true` (loopback clients only, forwarded headers rejected); remote access requires an explicit shared token — there is no user auth, RBAC, or tenant isolation.
- **Demo vs. real data**: retired. There is no product demo work and no fake/offline generation — the 「潮汐档案」/「盐镇来信」 seeds, the 长篇控制塔 (`ct-*`/`lf*` view family), and all offline stub clients were removed. Neutral placeholder works survive only as test fixtures (`backend/tests/fixture_works.py`, ids `work-a`/`work-b`). Every generation path is fail-closed: no live LLM → 409/502 + `author_action`, never canned output.
