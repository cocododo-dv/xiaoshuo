# Novel System P2 L3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable FastAPI + SQLite + Chroma-backed novel workflow that reaches the L3 milestone defined in `2026-04-07-novel-system-p2-design_v1_3_5.md`, including scene orchestration, review materialization, vector verify gates, replay/interop APIs, and the three required frontend consoles.

**Architecture:** Use a small monorepo with `backend/` and `frontend/`. The backend owns the schema, deterministic services, idempotency/recovery, and REST APIs. The frontend is a Vue 3 SPA driven only by the documented GET/list/read endpoints and the required POST actions.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic, ChromaDB, pytest, Node 22, Vue 3, Vite, Pinia, Vitest.

---

### Task 1: Scaffold the monorepo and red tests for schema contracts

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/novel_system/__init__.py`
- Create: `backend/src/novel_system/settings.py`
- Create: `backend/src/novel_system/db/base.py`
- Create: `backend/src/novel_system/db/models.py`
- Create: `backend/src/novel_system/db/session.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/20260408_0001_init_schema.py`
- Create: `backend/tests/test_schema_contracts.py`
- Create: `config/allowlists.yaml`
- Create: `config/models.yaml`
- Create: `config/hash_contract.yaml`

- [ ] **Step 1: Write the failing schema tests**

```python
def test_migration_creates_required_tables(sqlite_engine):
    inspector = inspect(sqlite_engine)
    assert "chapter_goals" in inspector.get_table_names()
    assert "vector_alias_registry" in inspector.get_table_names()
    assert "idempotency_keys" in inspector.get_table_names()


def test_review_items_exposes_derived_target_collection(sqlite_session):
    row = ReviewItem(item_type="style_observation", ...)
    sqlite_session.add(row)
    sqlite_session.flush()
    refreshed = sqlite_session.get(ReviewItem, row.review_id)
    assert refreshed.target_collection == "style_observations"
```

- [ ] **Step 2: Run the backend tests to verify they fail**

Run: `cd backend; python -m pytest tests/test_schema_contracts.py -q`
Expected: FAIL because the package, models, and migration do not exist yet.

- [ ] **Step 3: Implement settings, SQLAlchemy metadata, and the initial Alembic migration**

```python
class ReviewItem(Base):
    __tablename__ = "review_items"

    review_id = mapped_column(String, primary_key=True)
    item_type = mapped_column(String, nullable=False)
    target_collection = mapped_column(
        String,
        Computed(
            "CASE "
            "WHEN item_type = 'style_observation' THEN 'style_observations' "
            "WHEN item_type = 'calibration_line' THEN 'calibration_lines' "
            "WHEN item_type = 'scene_memory' THEN 'scene_memories' "
            "ELSE 'review_items' END",
            persisted=True,
        ),
    )
```

- [ ] **Step 4: Re-run schema tests**

Run: `cd backend; python -m pytest tests/test_schema_contracts.py -q`
Expected: PASS

- [ ] **Step 5: Validate migration end-to-end**

Run: `cd backend; python -m alembic upgrade head`
Expected: exit code 0 with the initial schema applied to the local SQLite database.

---

### Task 2: Build deterministic core services and their red tests

**Files:**
- Create: `backend/src/novel_system/contracts/bundle.py`
- Create: `backend/src/novel_system/contracts/qc.py`
- Create: `backend/src/novel_system/services/hash_engine.py`
- Create: `backend/src/novel_system/services/resolver.py`
- Create: `backend/src/novel_system/services/qc_validator.py`
- Create: `backend/src/novel_system/services/bundle_builder.py`
- Create: `backend/tests/test_hash_engine.py`
- Create: `backend/tests/test_qc_validator.py`
- Create: `backend/tests/test_bundle_builder.py`

- [ ] **Step 1: Write the failing deterministic service tests**

```python
def test_bundle_hash_matches_golden_vector():
    projection = load_fixture("bundle_hash_projection.json")
    assert compute_bundle_hash_projection(projection) == (
        "311c57097d809b81a6ece39943041c3b412e3ab67ab3efd2d5619498d4ef96a4"
    )


def test_soft_qc_waive_requires_carry_note():
    with pytest.raises(QCValidationError):
        validate_qc_report("soft_qc", {
            "resolution_code": "soft_waive",
            "pass_flag": True,
            "next_action": "pass_with_notes",
            "issues": [],
        })
```

- [ ] **Step 2: Run the service tests to verify they fail**

Run: `cd backend; python -m pytest tests/test_hash_engine.py tests/test_qc_validator.py tests/test_bundle_builder.py -q`
Expected: FAIL because the contracts and services are not implemented yet.

- [ ] **Step 3: Implement canonical bundle projection hashing, QC schemas, resolver cache, and bundle building**

```python
def compute_bundle_hash_projection(payload: BundleSnapshotHashProjection) -> str:
    canonical = canonical_json(payload.model_dump())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

```python
def validate_qc_report(qc_type: str, payload: dict) -> ValidatedQCReport:
    model = HardQCOutput if qc_type == "hard_qc" else SoftQCOutput
    parsed = model.model_validate(payload)
    ensure_resolution_combo(parsed)
    return parsed
```

- [ ] **Step 4: Re-run the deterministic service tests**

Run: `cd backend; python -m pytest tests/test_hash_engine.py tests/test_qc_validator.py tests/test_bundle_builder.py -q`
Expected: PASS

---

### Task 3: Implement orchestration, archiving, version management, vector verify, and API red tests

**Files:**
- Create: `backend/src/novel_system/services/idempotency.py`
- Create: `backend/src/novel_system/services/archiver.py`
- Create: `backend/src/novel_system/services/aggregator.py`
- Create: `backend/src/novel_system/services/vector_store.py`
- Create: `backend/src/novel_system/services/version_manager.py`
- Create: `backend/src/novel_system/services/orchestrator.py`
- Create: `backend/src/novel_system/api/deps.py`
- Create: `backend/src/novel_system/api/app.py`
- Create: `backend/src/novel_system/api/routes/chapters.py`
- Create: `backend/src/novel_system/api/routes/scenes.py`
- Create: `backend/src/novel_system/api/routes/review.py`
- Create: `backend/src/novel_system/api/routes/indexing.py`
- Create: `backend/src/novel_system/api/routes/interop.py`
- Create: `backend/tests/test_orchestrator_flow.py`
- Create: `backend/tests/test_idempotency_contract.py`
- Create: `backend/tests/test_vector_verify_gate.py`
- Create: `backend/tests/test_review_release.py`

- [ ] **Step 1: Write the failing API and workflow tests**

```python
def test_run_full_scene_archives_memory_and_updates_status(client):
    seed_story(client)
    response = client.post(
        "/api/v1/scenes/CH001_SC01/run/full",
        headers={"X-Idempotency-Key": "scene-run-1"},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["scene_status"] == "archived"
    assert data["current_final_scene_row_id"]
```

```python
def test_verify_failure_keeps_old_alias_serving(client):
    seed_vector_candidate_with_bad_queries(client)
    response = client.post(
        "/api/v1/index/verify/job_verify_1/retry",
        headers={"X-Idempotency-Key": "verify-retry-1"},
    )
    assert response.status_code == 409
    alias = client.get("/api/v1/index/alias-scopes/style_observation:global:global")
    assert alias.json()["data"]["active_alias"] == "style_obs_active_v1"
```

- [ ] **Step 2: Run the workflow tests to verify they fail**

Run: `cd backend; python -m pytest tests/test_orchestrator_flow.py tests/test_idempotency_contract.py tests/test_vector_verify_gate.py tests/test_review_release.py -q`
Expected: FAIL because the services and API routes do not exist yet.

- [ ] **Step 3: Implement the workflow, release/promotion, recovery sweep, replay/interop, and REST API**

```python
@router.post("/api/v1/scenes/{scene_id}/run/full")
def run_scene(scene_id: str, request: Request, session: SessionDep):
    result = with_http_idempotency(
        session,
        request,
        lambda: orchestrator.run_scene(scene_id, from_step="bundle", resume=False),
    )
    return ok(result)
```

```python
def run_verify(job_id: str) -> VerifyResult:
    job = claim_verify_job(job_id)
    probe = vector_store.verify_candidate(job.alias_scope, job.target_embedding_version)
    if not probe.ok:
        mark_verify_failed(job, probe)
        raise DomainError("VECTOR_VERIFY_FAILED", probe.reason)
    return verify_gate.flip_alias(job)
```

- [ ] **Step 4: Re-run the workflow tests**

Run: `cd backend; python -m pytest tests/test_orchestrator_flow.py tests/test_idempotency_contract.py tests/test_vector_verify_gate.py tests/test_review_release.py -q`
Expected: PASS

---

### Task 4: Build the Vue SPA for Workbench, Review Inbox, and Index Console

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/router.ts`
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/app.css`
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/stores/workbench.ts`
- Create: `frontend/src/stores/reviewInbox.ts`
- Create: `frontend/src/stores/indexConsole.ts`
- Create: `frontend/src/components/StatusPill.vue`
- Create: `frontend/src/components/PanelShell.vue`
- Create: `frontend/src/views/SceneWorkbenchView.vue`
- Create: `frontend/src/views/ReviewInboxView.vue`
- Create: `frontend/src/views/IndexConsoleView.vue`
- Create: `frontend/src/views/HumanReviewDrawer.vue`
- Create: `frontend/src/components/BundleReplayPanel.vue`
- Create: `frontend/src/components/QcIssueList.vue`
- Create: `frontend/src/components/TimelineList.vue`
- Create: `frontend/src/components/AliasScopeCard.vue`
- Create: `frontend/tests/app.spec.ts`

- [ ] **Step 1: Write the failing frontend smoke tests**

```ts
it("renders the three required consoles from API-backed stores", async () => {
  render(App)
  expect(await screen.findByText(/Scene Workbench/i)).toBeInTheDocument()
  expect(await screen.findByText(/Review Inbox/i)).toBeInTheDocument()
  expect(await screen.findByText(/Index Console/i)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run: `cd frontend; npm test -- --run`
Expected: FAIL because the app does not exist yet.

- [ ] **Step 3: Implement the SPA with a clear editorial-console visual direction**

```vue
<PanelShell title="Review Inbox" eyebrow="Materialize / release / reject">
  <ReviewFilters />
  <ReviewCard
    v-for="item in store.items"
    :key="item.review_id"
    :item="item"
    @approve="store.approve"
    @release="store.release"
  />
</PanelShell>
```

- [ ] **Step 4: Re-run the frontend tests**

Run: `cd frontend; npm test -- --run`
Expected: PASS

- [ ] **Step 5: Build the frontend bundle**

Run: `cd frontend; npm run build`
Expected: exit code 0 with a production build in `frontend/dist`.

---

### Task 5: Full verification and acceptance sweep

**Files:**
- Create: `backend/tests/test_acceptance_flow.py`
- Create: `README.md`

- [ ] **Step 1: Write the failing acceptance test**

```python
def test_l3_acceptance_smoke(client):
    seed_story(client)
    run_scene_full(client, "CH001_SC01")
    run_scene_full(client, "CH001_SC02")
    run_scene_full(client, "CH001_SC03")
    alias = create_and_verify_style_observation(client)
    worksheet = client.get("/api/v1/interop/export/bundle-worksheet/bundle_CH001_SC03")
    assert alias["verify_status"] == "succeeded"
    assert worksheet.status_code == 200
```

- [ ] **Step 2: Run the acceptance test to verify it fails**

Run: `cd backend; python -m pytest tests/test_acceptance_flow.py -q`
Expected: FAIL until the seeded flow and interop endpoints are fully wired together.

- [ ] **Step 3: Implement the missing glue and docs**

```md
## Local development

1. `cd backend && pip install -e .[dev]`
2. `cd frontend && npm install`
3. `uvicorn novel_system.api.app:app --reload`
4. `npm run dev`
```

- [ ] **Step 4: Run the complete verification suite**

Run: `cd backend; python -m pytest -q`
Expected: PASS

Run: `cd frontend; npm test -- --run`
Expected: PASS

Run: `cd frontend; npm run build`
Expected: PASS

