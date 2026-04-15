# True AI Novel Writing Engine Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the current P2 workflow shell from a deterministic demo pipeline into a real LLM-backed novel writing system that can generate scenes, run structured QC, escalate to human review when needed, and then scale into chapter-level and long-form automation.

**Architecture:** Keep the existing `bundle -> review -> knowledge -> index -> interop` shell intact. Insert a new generation core between `BundleBuilder` and `Archiver`: prompt compilation, provider-agnostic LLM calling, structured QC, rewrite loops, and audit persistence. Deliver the work in four milestones: single-scene true generation, scene-level QC + rewrite loop, chapter batch execution, and long-form continuity.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, Vue 3, Pinia, Playwright, OpenAI-compatible HTTP provider interface, pytest, Vitest

---

## Scope and Default Decisions

- Preserve the current frontend shell, data model families, review workflow, index workflow, and interop surfaces.
- Do **not** rebuild the project around a new framework or queue system in milestone 1.
- Use an **OpenAI-compatible provider interface first** so OpenAI, DeepSeek, Qwen-compatible gateways, and Ollama-compatible bridges can all share one client contract.
- Keep **single-scene generation synchronous** in milestone 1 so the existing `POST /api/v1/scenes/{scene_id}/run/full` surface can stay alive while the true generation chain is added.
- Add **database-backed async chapter jobs** only after single-scene true generation is stable.
- Keep the current SQLite-first local workflow. Do not introduce Redis, Celery, Kafka, or external orchestration unless a later scale requirement forces it.
- Reuse the current review and human-review surfaces for all generation failures, QC dead-ends, and continuity blockers.

---

## Current Gap Summary

The current repo already has the operational shell:

- `bundle_builder.build(...)` resolves chapter, scene, and knowledge context into a stable bundle snapshot and hash.
- `review`, `knowledge`, `index`, and `interop` views are implemented and already validated by unit and E2E tests.
- `run_scene()` writes `SceneDraft`, `FinalScene`, `SceneMemory`, and chapter aggregates into the database.

The missing pieces are the ones that make the project a real AI writing system:

- no provider configuration or API key handling
- no actual LLM client
- no prompt compiler that turns bundle data into model input
- no real neutral draft generation
- no real hard/soft QC
- no rewrite / patch loop
- no prompt/model/token audit persistence
- no chapter batch runner
- no long-form continuity budget and compression policy

---

## Public API and Data Contract Changes

### New Backend Models

- `LlmCall`
  Stores provider, model, request/response metadata, token usage, prompt hash, latency, error state, and scene/chapter linkage.
- `QcReport`
  Stores structured QC output for `hard_qc` and `soft_qc`, including issue list, next action, blocking reason, and rewrite brief.
- `ChapterRunJob`
  Stores async chapter batch execution status after milestone 3.

### Existing Model Extensions

- `SceneDraft`
  Add `llm_call_id`, `prompt_hash`, and `generation_pass`.
- `FinalScene`
  Add `llm_call_id`, `source_style_draft_row_id`, and `finalization_strategy`.
- `SceneRunState`
  Keep the existing counters, but start updating `current_qc_report_id`, `hard_partial_rewrite_count`, `hard_full_rewrite_count`, `soft_patch_count`, `repeat_issue_key`, and `repeat_issue_count` for real.
- `AttemptTracker.details_json`
  Standardize on structured generation/QC payloads so the workbench can render model/QC evidence without guessing.

### Existing Endpoint Extensions

- `GET /api/v1/scenes/{scene_id}/workbench`
  Extend with latest generation summary, latest hard/soft QC summaries, latest human-review reason, and draft provenance.
- `GET /api/v1/scenes/{scene_id}/attempts`
  Keep the current cursor contract but include step-level provider/model/QC summary fields in `details_json`.

### New Endpoints

- `GET /api/v1/scenes/{scene_id}/generation-history`
  Return the scene's LLM call and QC history in reverse chronological order.
- `POST /api/v1/chapters/{chapter_id}/run/full`
  Enqueue a chapter batch run in milestone 3.
- `GET /api/v1/chapters/{chapter_id}/run-status`
  Read the status of the latest chapter run job in milestone 3.

---

## File Structure

- `backend/src/novel_system/settings.py`
  Add provider settings, API base URL, timeout, and generation feature flags.
- `config/models.yaml`
  Replace abstract routing tiers with concrete per-step provider/model settings while preserving the current task-routing shape.
- `config/prompts.yaml`
  New prompt template registry for neutral draft, hard QC, style draft, soft QC, chapter summary, and continuity compression prompts.
- `backend/src/novel_system/services/llm_client.py`
  New provider-agnostic OpenAI-compatible client with retry, timeout, and structured JSON support.
- `backend/src/novel_system/services/prompt_builder.py`
  New bundle-to-prompt compiler plus prompt hash calculation.
- `backend/src/novel_system/services/qc_engine.py`
  New hard/soft QC execution and validation layer.
- `backend/src/novel_system/services/scene_generation.py`
  New scene-level generation orchestration extracted from `Orchestrator`.
- `backend/src/novel_system/services/orchestrator.py`
  Stop using placeholder strings and delegate real generation/QC/archive behavior to the new services.
- `backend/src/novel_system/services/chapter_runner.py`
  New chapter batch execution flow for milestone 3.
- `backend/src/novel_system/services/context_budget.py`
  New prompt-budgeting and continuity compression helpers for milestone 4.
- `backend/src/novel_system/db/models.py`
  Add `LlmCall`, `QcReport`, and `ChapterRunJob`; extend draft/final scene metadata.
- `backend/alembic/versions/<timestamp>_add_llm_qc_and_chapter_jobs.py`
  New migration for all schema additions.
- `backend/src/novel_system/api/routes/scenes.py`
  Extend workbench payload and add generation history endpoint.
- `backend/src/novel_system/api/routes/chapters.py`
  Add chapter batch run endpoints in milestone 3.
- `frontend/src/lib/api.js`
  Add generation-history and chapter-run helpers.
- `frontend/src/stores/workbench.js`
  Load generation summaries and chapter-run state.
- `frontend/src/views/SceneWorkbenchView.vue`
  Surface provider/model/QC/rewrite evidence inside the existing workbench.
- `frontend/src/views/AuthorWorkspaceView.vue`
  Add chapter-run entry points and chapter execution status in milestone 3.
- `frontend/src/components/GenerationSummaryCard.vue`
  New scene generation evidence card.
- `frontend/src/components/QcReportCard.vue`
  New hard/soft QC result card.
- `backend/tests/test_llm_client.py`
  New provider client contract coverage.
- `backend/tests/test_prompt_builder.py`
  New prompt compilation coverage.
- `backend/tests/test_scene_generation.py`
  New single-scene true generation coverage.
- `backend/tests/test_qc_engine.py`
  New structured QC and rewrite loop coverage.
- `backend/tests/test_chapter_runner.py`
  New chapter batch coverage.
- `frontend/tests/workbenchGeneration.spec.js`
  New workbench rendering coverage for generation and QC evidence.
- `frontend/tests/e2e/scene-llm-pipeline.spec.js`
  New scene-level true generation browser path.
- `frontend/tests/e2e/chapter-batch.spec.js`
  New chapter batch browser path.

---

## Milestone Plan

### Milestone 1: Single-Scene True Generation

**Target outcome:** `POST /api/v1/scenes/{scene_id}/run/full` performs real neutral draft generation, real style draft generation, and real final scene creation using a configured model provider, while the current workbench UI remains usable.

**Exit criteria:**

- a configured provider can generate `neutral_draft` and `style_draft`
- workbench shows the generated text instead of template placeholder text
- each draft is traceable to `LlmCall`
- the seeded single-scene demo still passes end-to-end

### Milestone 2: Structured QC, Rewrite, and Human Review

**Target outcome:** hard/soft QC become real decision steps; repeated failures or blocked outputs create `human_review_event` records and stop unsafe automation.

**Exit criteria:**

- hard QC can fail and force rewrite or human review
- soft QC can patch, waive, or block
- `SceneRunState` counters and repeat issue keys are updated
- review inbox shows generation-related human review events

### Milestone 3: Chapter Batch Execution

**Target outcome:** a chapter can be run scene-by-scene in order using a database-backed chapter job, stopping on blockers and preserving intermediate state.

**Exit criteria:**

- chapter batch jobs can be started and inspected
- scenes run in chapter order
- batch execution halts on unresolved human review or aggregate blockers
- author workspace can launch and inspect chapter runs

### Milestone 4: Long-Form Continuity and Context Budgeting

**Target outcome:** multi-scene and multi-chapter execution remain coherent under prompt limits, with continuity summaries and compression rules that preserve story intent.

**Exit criteria:**

- prompts are compressed by explicit policy rather than accidental truncation
- continuity failures can be diagnosed in QC output
- chapter summary and carry-forward memory are used consistently

---

## Task 1: Build the Provider and Configuration Foundation

**Files:**

- Create: `backend/src/novel_system/services/llm_client.py`
- Create: `backend/tests/test_llm_client.py`
- Modify: `backend/src/novel_system/settings.py`
- Modify: `config/models.yaml`
- Modify: `backend/pyproject.toml`

**Implementation checklist:**

- [ ] Add environment settings for `NOVEL_SYSTEM_LLM_PROVIDER`, `NOVEL_SYSTEM_LLM_BASE_URL`, `NOVEL_SYSTEM_LLM_API_KEY`, `NOVEL_SYSTEM_LLM_TIMEOUT_SECONDS`, and `NOVEL_SYSTEM_LLM_ENABLED`.
- [ ] Expand `config/models.yaml` so each pipeline step has `provider`, `model`, `temperature`, `max_output_tokens`, and `response_format`.
- [ ] Implement a provider-agnostic client that accepts one normalized request payload and returns one normalized response payload.
- [ ] Support OpenAI-compatible chat/responses JSON mode first; do not add provider-specific branching in orchestrator code.
- [ ] Normalize request timeout, retryable HTTP failures, rate-limit errors, and malformed JSON responses into one exception family.
- [ ] Add unit tests that mock a successful JSON generation, an HTTP 429 retry path, and a malformed JSON failure path.

**Tests:**

- `cd backend && python -m pytest tests/test_llm_client.py -q`

**Acceptance criteria:**

- one test provider config can be loaded entirely from env + `config/models.yaml`
- the client returns normalized `text`, `structured_output`, `usage`, `finish_reason`, and `request_id`
- no generation logic elsewhere knows whether the request went to OpenAI, DeepSeek, or another compatible endpoint

---

## Task 2: Add Prompt Templates and Bundle-to-Prompt Compilation

**Files:**

- Create: `config/prompts.yaml`
- Create: `backend/src/novel_system/services/prompt_builder.py`
- Create: `backend/tests/test_prompt_builder.py`
- Modify: `backend/src/novel_system/services/bundle_builder.py`

**Implementation checklist:**

- [ ] Create one prompt template entry per step: `neutral_draft`, `hard_qc`, `style_draft`, `soft_qc`, `chapter_summary`, and `continuity_compression`.
- [ ] Compile a stable prompt payload from bundle snapshot data: system prompt, user prompt, structured schema, prompt hash, and token-budget metadata.
- [ ] Keep prompt assembly deterministic for the same bundle snapshot and template version.
- [ ] Add prompt-budget metadata that reports which bundle sections were included, compressed, or omitted.
- [ ] Add a compact continuity policy based on the design doc rule ordering: drop similar-scene context first, then compress style observations, then calibration lines, then relation/world/memory digests, and finally stop with a split-scene recommendation.
- [ ] Add tests that verify required bundle sections appear in the prompt and that the prompt hash changes only when relevant inputs change.

**Tests:**

- `cd backend && python -m pytest tests/test_prompt_builder.py -q`

**Acceptance criteria:**

- the same bundle hash + prompt template version always yields the same prompt hash
- prompt payloads explicitly state what context was compacted
- hard/soft QC prompts consume draft content plus bundle policy, not raw scene data alone

---

## Task 3: Add Audit and QC Persistence

**Files:**

- Modify: `backend/src/novel_system/db/models.py`
- Create: `backend/alembic/versions/<timestamp>_add_llm_qc_and_chapter_jobs.py`
- Create: `backend/tests/test_generation_persistence.py`

**Implementation checklist:**

- [ ] Add `LlmCall` with identifiers for provider, model, prompt hash, step, scene/chapter linkage, request payload summary, response payload summary, prompt tokens, completion tokens, total tokens, latency, finish reason, and error code.
- [ ] Add `QcReport` with `qc_report_id`, `scene_id`, `chapter_id`, `qc_type`, `source_draft_row_id`, `source_bundle_id`, `resolution_code`, `pass_flag`, `next_action`, `issues_json`, and `rewrite_brief_json`.
- [ ] Add `ChapterRunJob` for milestone 3 now so schema only migrates once.
- [ ] Extend `SceneDraft` and `FinalScene` with foreign keys or reference IDs back to the generation record.
- [ ] Keep all new fields nullable for historical rows so the current demo database can migrate cleanly.
- [ ] Add migration tests that confirm historical seeded rows remain readable after upgrade.

**Tests:**

- `cd backend && python -m pytest tests/test_generation_persistence.py -q`

**Acceptance criteria:**

- every new LLM-backed draft can be traced to one `LlmCall`
- every hard/soft QC decision can be traced to one `QcReport`
- the migration is additive and does not require wiping the local database

---

## Task 4: Replace Placeholder Neutral Draft Generation

**Files:**

- Create: `backend/src/novel_system/services/scene_generation.py`
- Create: `backend/tests/test_scene_generation.py`
- Modify: `backend/src/novel_system/services/orchestrator.py`

**Implementation checklist:**

- [ ] Extract scene generation steps from `Orchestrator` into `SceneGenerationService`.
- [ ] Replace the hard-coded neutral draft string with a real model call that uses the compiled neutral-draft prompt.
- [ ] Persist the `LlmCall`, then persist `SceneDraft(stage='neutral_draft')`, then append `AttemptTracker(step='neutral_draft')`.
- [ ] Update `SceneRunState.current_neutral_draft_row_id`, `current_bundle_id`, `current_bundle_hash`, and `total_attempt_count` consistently.
- [ ] Preserve the current source bundle linkage for every downstream step.
- [ ] Add tests using a fake client that returns deterministic text and usage data.

**Tests:**

- `cd backend && python -m pytest tests/test_scene_generation.py -q`

**Acceptance criteria:**

- a real provider response is written into `SceneDraft.content`
- the neutral draft content is no longer derived from `scene.location` string concatenation
- the workbench still loads successfully for seeded demo scenes

---

## Task 5: Implement Hard QC and Rewrite / Block / Continue

**Files:**

- Create: `backend/src/novel_system/services/qc_engine.py`
- Create: `backend/tests/test_qc_engine.py`
- Modify: `backend/src/novel_system/services/scene_generation.py`
- Modify: `backend/src/novel_system/services/orchestrator.py`
- Modify: `backend/src/novel_system/services/human_review_manager.py`

**Implementation checklist:**

- [ ] Run a real `hard_qc` step immediately after neutral draft generation.
- [ ] Validate the returned QC payload shape before accepting it.
- [ ] Persist `QcReport(qc_type='hard_qc')` and write its ID into `SceneRunState.current_qc_report_id`.
- [ ] Implement the allowed hard-QC branches: `continue`, `rewrite_partial`, `rewrite_full`, and `human_review_required`.
- [ ] Update `hard_partial_rewrite_count`, `hard_full_rewrite_count`, `repeat_issue_key`, and `repeat_issue_count` from report content.
- [ ] Enforce the circuit breaker from the design doc: too many rewrites, repeated issue keys, or total attempt budget triggers human review.
- [ ] When blocked, create a `HumanReviewEvent` with explicit failure reason, linked target, recommended action, and replay context.

**Tests:**

- `cd backend && python -m pytest tests/test_qc_engine.py -q`

**Acceptance criteria:**

- hard QC can stop a bad scene before style generation
- repeated QC failures no longer silently pass through to archive
- the review inbox can display generation-originated blockers without a frontend rewrite

---

## Task 6: Implement Style Draft Generation and Soft QC

**Files:**

- Modify: `backend/src/novel_system/services/scene_generation.py`
- Modify: `backend/src/novel_system/services/orchestrator.py`
- Modify: `backend/tests/test_scene_generation.py`
- Modify: `backend/tests/test_qc_engine.py`

**Implementation checklist:**

- [ ] Generate `style_draft` from the approved neutral draft plus the style prompt template.
- [ ] Persist the style draft and its `LlmCall`.
- [ ] Run real `soft_qc` against the style draft.
- [ ] Implement soft-QC branches: `continue`, `patch`, `waive`, and `human_review_required`.
- [ ] For `patch`, perform one controlled patch-generation pass rather than a full scene rewrite.
- [ ] Create the final scene only when soft QC resolves to pass/continue/waive.
- [ ] Append attempt-tracker rows for `style_draft`, `soft_qc`, `soft_patch`, and `finalize`.

**Tests:**

- `cd backend && python -m pytest tests/test_scene_generation.py tests/test_qc_engine.py -q`

**Acceptance criteria:**

- style output is model-produced and distinguishable from neutral draft
- soft QC failure does not archive unsafe text
- final scene is traceable to style draft provenance

---

## Task 7: Surface Generation Evidence in the Workbench

**Files:**

- Create: `frontend/src/components/GenerationSummaryCard.vue`
- Create: `frontend/src/components/QcReportCard.vue`
- Create: `frontend/tests/workbenchGeneration.spec.js`
- Modify: `backend/src/novel_system/api/routes/scenes.py`
- Modify: `frontend/src/lib/api.js`
- Modify: `frontend/src/stores/workbench.js`
- Modify: `frontend/src/views/SceneWorkbenchView.vue`

**Implementation checklist:**

- [ ] Extend the scene workbench payload with latest generation summary, latest hard/soft QC summary, rewrite counters, and most recent human-review event summary.
- [ ] Add one generation evidence card that shows provider, model, prompt hash, token usage, latency, and finish reason.
- [ ] Add one QC card that shows pass/fail, resolution code, issue keys, next action, and rewrite brief.
- [ ] Keep the existing workbench view layout and place these cards near the current run receipt and attempt timeline.
- [ ] Make sure the empty state still renders for scenes with historical deterministic rows.
- [ ] Add a browser test that confirms the new cards appear after a mocked LLM-backed scene run.

**Tests:**

- `cd frontend && npx vitest run tests/workbenchGeneration.spec.js`

**Acceptance criteria:**

- an operator can tell why a scene passed, rewrote, or escalated without opening the database
- historical rows do not crash the workbench
- the scene workbench remains the primary execution console for scene-level generation

---

## Task 8: Add Scene Generation History API

**Files:**

- Modify: `backend/src/novel_system/api/routes/scenes.py`
- Create: `backend/tests/test_scene_generation_history_api.py`
- Modify: `frontend/src/lib/api.js`

**Implementation checklist:**

- [ ] Add `GET /api/v1/scenes/{scene_id}/generation-history`.
- [ ] Return normalized generation/QC history grouped by attempt order.
- [ ] Include `LlmCall`, `QcReport`, and `HumanReviewEvent` references in one response shape so the frontend can render a timeline later without joining client-side.
- [ ] Keep the existing `GET /api/v1/scenes/{scene_id}/attempts` endpoint unchanged for compatibility.

**Tests:**

- `cd backend && python -m pytest tests/test_scene_generation_history_api.py -q`

**Acceptance criteria:**

- generation audit can be retrieved without shelling into SQLite
- no current consumer breaks because `attempts` remains backward compatible

---

## Task 9: Add Chapter Batch Execution

**Files:**

- Create: `backend/src/novel_system/services/chapter_runner.py`
- Modify: `backend/src/novel_system/api/routes/chapters.py`
- Create: `backend/tests/test_chapter_runner.py`
- Modify: `frontend/src/lib/api.js`
- Modify: `frontend/src/stores/authorWorkspace.js`
- Modify: `frontend/src/views/AuthorWorkspaceView.vue`
- Create: `frontend/tests/e2e/chapter-batch.spec.js`

**Implementation checklist:**

- [ ] Add `POST /api/v1/chapters/{chapter_id}/run/full` that creates a `ChapterRunJob` and runs scenes in `scene_seq` order.
- [ ] Add `GET /api/v1/chapters/{chapter_id}/run-status` that returns active job state, current scene, completed scenes, blocked scene, and latest error.
- [ ] Reuse the current scene-generation service for each scene in order; do not fork a second pipeline for chapter jobs.
- [ ] Stop the chapter run on unresolved human review, pending staged backfill, or aggregate blockers.
- [ ] Update author workspace so operators can launch a chapter run and inspect chapter-run progress.
- [ ] Keep local execution database-backed and single-process first; the worker separation can remain internal to the backend process for this milestone.

**Tests:**

- `cd backend && python -m pytest tests/test_chapter_runner.py -q`
- `cd frontend && npm run test:e2e -- tests/e2e/chapter-batch.spec.js`

**Acceptance criteria:**

- an operator can launch a chapter and see where it stopped
- scene memory and final aggregate behavior still use the existing runtime services
- chapter execution can be resumed from persisted job state rather than restarting from scene 1 every time

---

## Task 10: Add Context Budgeting and Continuity Compression

**Files:**

- Create: `backend/src/novel_system/services/context_budget.py`
- Modify: `backend/src/novel_system/services/prompt_builder.py`
- Modify: `backend/src/novel_system/services/qc_engine.py`
- Create: `backend/tests/test_context_budget.py`

**Implementation checklist:**

- [ ] Implement explicit token-budget estimation before each generation/QC call.
- [ ] Apply the compaction order from the design doc when a prompt exceeds budget.
- [ ] Record what was dropped or compressed into `LlmCall.request_summary_json`.
- [ ] Return a structured continuity warning when the prompt cannot be made safe without splitting the scene.
- [ ] Surface the continuity warning into hard/soft QC so it can escalate cleanly to human review.

**Tests:**

- `cd backend && python -m pytest tests/test_context_budget.py -q`

**Acceptance criteria:**

- prompt overflow becomes a visible, explainable state
- the system recommends scene splitting rather than blindly truncating essential context

---

## Task 11: Expand Verification and Release Proof

**Files:**

- Modify: `README.md`
- Modify: `docs/release-checklist.md`
- Create: `frontend/tests/e2e/scene-llm-pipeline.spec.js`
- Modify: `.github/pull_request_template.md`

**Implementation checklist:**

- [ ] Add one backend verification lane with fake-provider tests for generation, QC, and chapter runner.
- [ ] Add one browser E2E that covers a true scene run with mocked LLM responses, QC pass, and final archive.
- [ ] Extend release docs to require recording provider config used for verification, prompt-template version, and generation/QC evidence.
- [ ] Document the fallback rule: fake-provider tests are required in CI; real-provider smoke tests are local-only until secrets handling is formalized.

**Tests:**

- `powershell -ExecutionPolicy Bypass -File scripts/verify_windows.ps1`
- `cd frontend && npm run test:e2e`

**Acceptance criteria:**

- the new true-generation path is covered by deterministic tests
- release docs distinguish fake-provider CI evidence from real-provider local smoke evidence

---

## Recommended Delivery Order

1. Task 1
2. Task 2
3. Task 3
4. Task 4
5. Task 5
6. Task 6
7. Task 7
8. Task 8
9. Task 11
10. Task 9
11. Task 10

Rationale:

- Tasks 1-6 are the minimum path to make single-scene generation real.
- Tasks 7-8 make the result operable and debuggable without inspecting the DB manually.
- Task 11 should land before chapter batching so the true-generation path is already protected by tests.
- Task 9 should only start after single-scene generation is stable.
- Task 10 belongs last because context compression rules are easier to tune after real prompts exist.

---

## Risks and Mitigations

- **Risk:** provider-specific JSON behavior is inconsistent.
  **Mitigation:** normalize behind `llm_client.py` and keep provider branching out of orchestration code.
- **Risk:** token cost grows too fast once long continuity is added.
  **Mitigation:** implement prompt-budget tracking before chapter batching, not after.
- **Risk:** generation failures create hidden state drift.
  **Mitigation:** persist `LlmCall`, `QcReport`, and `AttemptTracker` before mutating run-state pointers.
- **Risk:** frontend becomes coupled to provider-specific output.
  **Mitigation:** expose only normalized generation/QC summaries from API routes.
- **Risk:** chapter batching amplifies bugs from the scene pipeline.
  **Mitigation:** gate milestone 3 on stable milestone 1 + 2 verification.

---

## Verification Matrix

- `backend/tests/test_llm_client.py`
  Provider normalization, retry, timeout, malformed payload handling
- `backend/tests/test_prompt_builder.py`
  Prompt compilation, prompt hash stability, budget compaction metadata
- `backend/tests/test_generation_persistence.py`
  Migration safety and persistence integrity
- `backend/tests/test_scene_generation.py`
  Neutral/style generation, final scene provenance, audit linkage
- `backend/tests/test_qc_engine.py`
  Hard/soft QC branches, rewrite counters, circuit breaker, human review creation
- `backend/tests/test_scene_generation_history_api.py`
  API contract for scene generation audit
- `backend/tests/test_chapter_runner.py`
  Chapter batch ordering, blocker handling, resume behavior
- `backend/tests/test_context_budget.py`
  Context overflow policy and split-scene escalation
- `frontend/tests/workbenchGeneration.spec.js`
  Generation/QC evidence rendering
- `frontend/tests/e2e/scene-llm-pipeline.spec.js`
  Browser-level true scene run path
- `frontend/tests/e2e/chapter-batch.spec.js`
  Browser-level chapter batch path

---

## Final Acceptance Criteria

- running a scene uses a configured model provider rather than deterministic placeholder strings
- hard/soft QC can fail, rewrite, or escalate instead of always passing
- the workbench shows generation and QC evidence clearly
- human review events are created for blocked generation states
- chapter runs can execute scene-by-scene with persisted progress
- prompt-budget overflow is explicit and recoverable

---

## Assumptions

- The first production-capable provider contract will be OpenAI-compatible HTTP.
- The current review, knowledge, and interop UX should be extended, not replaced.
- CI will use fake-provider mocks until repository secret handling is formalized.
- Single-node SQLite remains the default development environment during this upgrade.
