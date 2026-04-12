# Tech Stack Alignment Implementation Plan

**Status:** implemented

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the temporary vector adapter with real Chroma integration, add an idempotent first-chapter demo seed, and rebuild the frontend as Vue 3 + Pinia without changing the current API contract or verify-gate semantics.

**Architecture:** Keep SQLite `vector_alias_registry` as the only logical alias source, but swap the backing vector engine to a pluggable store with a production `ChromaVectorStore` and a test-only file/fake store. After the backend contract is stable, add a seed CLI that writes demo data through the same schema, then rebuild the editorial console in Vue 3 + Pinia on top of the existing GET/list/action endpoints.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, ChromaDB, pytest, Vue 3, Pinia, Vite, Vitest.

## Current Status Note

- Task 1 is complete: real Chroma integration has been verified in WSL Ubuntu-24.04, including `python -m novel_system.tools.chroma_smoke`, the focused Chroma/release/verify suite, and the full backend pytest run.
- Task 2 is complete: the demo seed CLI exists, is idempotent, and is covered by backend tests.
- Task 3 is complete: the frontend has been rebuilt as Vue 3 + Pinia and passes `npm test` plus `npm run build`.
- Native Windows remains a non-Chroma verification lane. Treat WSL/Linux as the required verification lane for real Chroma write-path checks on this machine.

---

## File Structure

- `backend/src/novel_system/services/vector_store.py`
  Owns the vector store abstraction plus concrete Chroma and test adapters.
- `backend/src/novel_system/services/version_manager.py`
  Owns reindex/verify/release behavior and must depend on the vector abstraction rather than a hard-coded file store.
- `backend/src/novel_system/tools/seed_demo.py`
  Owns the idempotent first-chapter seed path.
- `frontend/src/lib/api.js`
  Owns the shared API envelope parsing, idempotency header generation for POST actions, and endpoint helpers.
- `frontend/src/stores/*.js`
  Own the page-level fetch/action state for Workbench, Review Inbox, and Index Console.
- `frontend/src/views/*.vue`
  Own the top-level page layout and orchestration.
- `frontend/src/components/*.vue`
  Own reusable timeline/review/alias cards and drawers.

---

### Task 1: Replace the temporary vector adapter with real Chroma

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/novel_system/settings.py`
- Modify: `backend/src/novel_system/services/vector_store.py`
- Modify: `backend/src/novel_system/services/version_manager.py`
- Modify: `backend/src/novel_system/services/__init__.py`
- Test: `backend/tests/test_chroma_vector_store.py`
- Test: `backend/tests/test_review_release.py`
- Test: `backend/tests/test_vector_verify_gate.py`

- [x] **Step 1: Write the failing Chroma-backed vector tests**

```python
def test_chroma_store_round_trip(tmp_path: Path) -> None:
    store = ChromaVectorStore(tmp_path)
    store.write_collection(
        "style_obs_candidate_v1",
        [
            {"id": "obs_1", "text": "闁衡偓閼稿灚灏嗛柡鍐╂构缁绘岸鎮惧▎搴ｇ▏婵?, "scope": "global", "lineage_key": "STY_001"},
            {"id": "obs_2", "text": "閻庨潧婀卞▍褏绱掗幘宕囧暡閻熸洑鐒﹀﹢渚€宕戝鍫涒偓?, "scope": "global", "lineage_key": "STY_002"},
        ],
    )

    assert store.collection_exists("style_obs_candidate_v1") is True
    results = store.query("style_obs_candidate_v1", "濞达絾鐟︾亸?, top_k=2)
    assert [item["id"] for item in results] == ["obs_1"]


def test_verify_failure_keeps_old_active_alias_when_candidate_query_is_empty(client) -> None:
    seed_good_active_alias(client)
    seed_bad_candidate_alias(client)

    response = client.post(
        "/api/v1/index/verify/verify_review_style_bad/retry",
        headers={"X-Idempotency-Key": "verify-bad"},
    )

    assert response.status_code == 409
    alias = client.get("/api/v1/index/alias-scopes/style_observation:global:global")
    assert alias.json()["data"]["active_alias"] == "style_observation_global_global_candidate_v1"
```

- [x] **Step 2: Run the focused backend tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_chroma_vector_store.py tests/test_review_release.py tests/test_vector_verify_gate.py -q`

Expected:
- `ModuleNotFoundError` or `AttributeError` for `ChromaVectorStore`
- Existing release/verify tests fail because `VersionManager` still depends on the file-only implementation

- [x] **Step 3: Add Chroma as a backend dependency and expose backend settings**

```toml
[project]
dependencies = [
  "alembic>=1.14,<2",
  "chromadb>=1.1.0,<2",
  "fastapi>=0.135,<1",
  "httpx>=0.26,<1",
  "pydantic>=2.5,<3",
  "pyyaml>=6.0,<7",
  "sqlalchemy>=2.0.30,<3"
]
```

```python
@dataclass(slots=True)
class Settings:
    database_url: str
    vector_store_dir: Path
    vector_backend: str
    chroma_collection_prefix: str = "novel_system"
```

- [x] **Step 4: Implement a vector abstraction with both Chroma and test adapters**

```python
class VectorStore(Protocol):
    def write_collection(self, collection_name: str, documents: list[dict]) -> None: ...
    def collection_exists(self, collection_name: str) -> bool: ...
    def load_collection(self, collection_name: str) -> list[dict]: ...
    def query(self, collection_name: str, query_text: str, top_k: int = 3) -> list[dict]: ...
    def delete_collection(self, collection_name: str) -> None: ...


class ChromaVectorStore:
    def __init__(self, root: Path) -> None:
        self.client = PersistentClient(path=str(root))

    def write_collection(self, collection_name: str, documents: list[dict]) -> None:
        collection = self.client.get_or_create_collection(collection_name)
        collection.delete(where={})
        collection.add(
            ids=[item["id"] for item in documents],
            documents=[item["text"] for item in documents],
            metadatas=[
                {"scope": item["scope"], "lineage_key": item["lineage_key"]}
                for item in documents
            ],
        )
```

- [x] **Step 5: Inject the vector store into `VersionManager` and keep alias semantics unchanged**

```python
class VersionManager:
    def __init__(self, session: Session, vector_store: VectorStore | None = None) -> None:
        self.session = session
        self.vector_store = vector_store or build_vector_store(get_settings())
```

```python
results = self.vector_store.query(alias.candidate_alias, probe_text, top_k=3)
if not results:
    alias.verify_status = "failed"
    registry.verify_status = "failed"
    self.session.add(
        ReconcileFault(
            fault_scope="alias_mismatch",
            severity="blocking",
            object_ref=alias.alias_scope,
            details_json={"candidate_alias": alias.candidate_alias},
        )
    )
    raise DomainError("VECTOR_VERIFY_FAILED", "candidate alias verify failed", status_code=409)
```

- [x] **Step 6: Re-run the focused tests**

Run: `cd backend && python -m pytest tests/test_chroma_vector_store.py tests/test_review_release.py tests/test_vector_verify_gate.py -q`

Expected: PASS

- [x] **Step 7: Re-run the full backend suite to catch regressions**

Run: `cd backend && python -m pytest -q`

Expected: PASS with the existing 12 tests plus the new Chroma tests all green.

---

### Task 2: Add an idempotent first-chapter demo seed

**Files:**
- Create: `backend/src/novel_system/tools/__init__.py`
- Create: `backend/src/novel_system/tools/seed_demo.py`
- Modify: `backend/src/novel_system/db/session.py`
- Modify: `backend/src/novel_system/api/routes/review.py`
- Test: `backend/tests/test_seed_demo.py`
- Modify: `README.md`

- [x] **Step 1: Write the failing demo-seed tests**

```python
def test_seed_demo_creates_first_chapter_and_review_item(tmp_path: Path) -> None:
    summary = seed_demo()

    assert summary["chapter_id"] == "CH001"
    assert summary["scene_ids"] == ["CH001_SC01", "CH001_SC02", "CH001_SC03"]
    assert summary["review_ids"] == ["review_demo_style_observation"]


def test_seed_demo_is_idempotent(tmp_path: Path) -> None:
    first = seed_demo()
    second = seed_demo()

    assert first["scene_ids"] == second["scene_ids"]
    assert count_rows("scene_cards") == 3
    assert count_rows("review_items") == 1
```

- [x] **Step 2: Run the seed tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_seed_demo.py -q`

Expected: FAIL because the `novel_system.tools.seed_demo` module does not exist yet.

- [x] **Step 3: Implement the seed CLI and the idempotent upsert path**

```python
def seed_demo() -> dict:
    with SessionLocal() as session:
        upsert_chapter(
            session,
            {
                "chapter_id": "CH001",
                "planned_scene_count": 3,
                "chapter_goal": "闂佹彃绉归埀顒夋線缁楀瞼鎷犻弴鐔疯荡闁瑰瓨鍔楅悵?,
                "main_plot_push": "闁哄唲鍌欑箚閻庨潧瀚▎銏＄閾忕懓娈犵紒渚垮灱椤箑顫㈤敐鍛闁瑰灚鎸哥槐?,
                "emotional_target": "闁汇垼绮剧换婊堟偪閹达絾绁☉鎾荤細椤掔喓鎲?,
                "ending_effect": "濞寸姰鍎扮紞鎴濃枖閵忊剝鏆柡?,
            },
        )
        for payload in DEMO_SCENES:
            upsert_scene(session, payload)
        upsert_review_item(session, DEMO_STYLE_OBSERVATION_REVIEW)
        session.commit()
    return {
        "chapter_id": "CH001",
        "scene_ids": [item["scene_id"] for item in DEMO_SCENES],
        "review_ids": [DEMO_STYLE_OBSERVATION_REVIEW["review_id"]],
    }
```

```python
if __name__ == "__main__":
    summary = seed_demo()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
```

- [x] **Step 4: Re-run the seed tests**

Run: `cd backend && python -m pytest tests/test_seed_demo.py -q`

Expected: PASS

- [x] **Step 5: Document the demo flow in the README**

```md
## Demo seed

1. `cd backend`
2. `python -m novel_system.tools.seed_demo`
3. `python -m uvicorn novel_system.api.app:create_app --factory --reload`
4. `cd ../frontend && npm run dev`
```

- [x] **Step 6: Verify the seed still preserves the backend contract**

Run: `cd backend && python -m pytest -q`

Expected: PASS

---

### Task 3: Rebuild the frontend as Vue 3 + Pinia while preserving the editorial-console look

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/index.html`
- Create: `frontend/vite.config.js`
- Create: `frontend/src/main.js`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/router.js`
- Create: `frontend/src/lib/api.js`
- Create: `frontend/src/stores/workbench.js`
- Create: `frontend/src/stores/reviewInbox.js`
- Create: `frontend/src/stores/indexConsole.js`
- Create: `frontend/src/components/PanelShell.vue`
- Create: `frontend/src/components/ReviewCard.vue`
- Create: `frontend/src/components/AliasScopeCard.vue`
- Create: `frontend/src/components/AttemptTimeline.vue`
- Create: `frontend/src/components/HumanReviewDrawer.vue`
- Create: `frontend/src/views/SceneWorkbenchView.vue`
- Create: `frontend/src/views/ReviewInboxView.vue`
- Create: `frontend/src/views/IndexConsoleView.vue`
- Create: `frontend/src/styles/app.css`
- Test: `frontend/tests/app.spec.js`
- Modify: `frontend/tests/smoke.mjs`

- [x] **Step 1: Write the failing frontend component/store tests**

```js
import { describe, expect, it } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useWorkbenchStore } from "../src/stores/workbench";

describe("workbench store", () => {
  it("loads a scene workbench payload from the API envelope", async () => {
    setActivePinia(createPinia());
    const store = useWorkbenchStore();
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, data: { scene_card: { scene_id: "CH001_SC01" } } }),
    });

    await store.load("CH001_SC01");

    expect(store.sceneId).toBe("CH001_SC01");
    expect(store.data.scene_card.scene_id).toBe("CH001_SC01");
  });
});
```

```js
it("renders the three required views from the Vue shell", async () => {
  const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
  expect(source).toContain("Scene Workbench");
  expect(source).toContain("Review Inbox");
  expect(source).toContain("Index Console");
});
```

- [x] **Step 2: Install the missing frontend dependencies and run tests to verify they fail**

Run: `cd frontend && npm install vue pinia @vitejs/plugin-vue vitest`

Run: `cd frontend && npm test`

Expected:
- the new Vue/Pinia store tests fail because `src/` does not exist yet
- the current smoke test fails once `index.html` points to a non-existent Vue entry

- [x] **Step 3: Set up Vite + Vue and the API client**

```js
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
});
```

```js
export async function apiGet(path) {
  const response = await fetch(`${getApiBase()}${path}`);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error?.message || `Request failed: ${response.status}`);
  }
  return payload.data;
}

export async function apiPost(path, body = {}) {
  const response = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Idempotency-Key": `${path}-${Date.now()}`,
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error?.message || `Request failed: ${response.status}`);
  }
  return payload.data;
}
```

- [x] **Step 4: Implement the Pinia stores before the views**

```js
export const useWorkbenchStore = defineStore("workbench", {
  state: () => ({
    sceneId: "CH001_SC01",
    data: null,
    loading: false,
    error: "",
  }),
  actions: {
    async load(sceneId = this.sceneId) {
      this.loading = true;
      this.error = "";
      this.sceneId = sceneId;
      try {
        this.data = await apiGet(`/api/v1/scenes/${sceneId}/workbench`);
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
  },
});
```

- [x] **Step 5: Build the Vue views and reusable components**

```vue
<template>
  <PanelShell eyebrow="Scene Workbench" title="闁革妇鍎ゅ▍娆撴⒒椤撶姴绠氬☉鎾抽濞叉牠寮?>
    <div class="stats">
      <div class="stat">
        <span>Bundle</span>
        <strong>{{ workbench.data?.bundle?.bundle_id || "-" }}</strong>
      </div>
      <div class="stat">
        <span>Status</span>
        <strong>{{ workbench.data?.scene_run_state?.scene_status || "-" }}</strong>
      </div>
    </div>
    <AttemptTimeline :items="workbench.data?.attempts || []" />
  </PanelShell>
</template>
```

```vue
<template>
  <PanelShell eyebrow="Index Console" title="Alias闁靛棔绠揺rify 濞?Recovery">
    <div class="alias-grid">
      <AliasScopeCard
        v-for="item in indexStore.aliasScopes"
        :key="item.alias_scope"
        :item="item"
      />
    </div>
  </PanelShell>
</template>
```

- [x] **Step 6: Re-run the frontend tests**

Run: `cd frontend && npm test`

Expected: PASS

- [x] **Step 7: Build the Vue frontend**

Run: `cd frontend && npm run build`

Expected: PASS with a production bundle emitted into `frontend/dist`

---

### Task 4: Full verification and demo handoff

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-04-08-tech-stack-alignment-design.md`
- Modify: `docs/superpowers/plans/2026-04-08-tech-stack-alignment.md`

- [x] **Step 1: Re-run the full backend suite**

Run: `cd backend && python -m pytest -q`

Expected: PASS

- [x] **Step 2: Re-run Alembic migration**

Run: `cd backend && alembic upgrade head`

Expected: PASS

- [x] **Step 3: Re-run the demo seed against a clean database**

Run: `cd backend && python -m novel_system.tools.seed_demo`

Expected:

```json
{
  "chapter_id": "CH001",
  "scene_ids": ["CH001_SC01", "CH001_SC02", "CH001_SC03"],
  "review_ids": ["review_demo_style_observation"]
}
```

- [x] **Step 4: Re-run the full frontend checks**

Run: `cd frontend && npm test`

Expected: PASS

Run: `cd frontend && npm run build`

Expected: PASS

- [x] **Step 5: Update the README handoff section**

```md
## End-to-end demo

1. `cd backend && alembic upgrade head`
2. `python -m novel_system.tools.seed_demo`
3. `python -m uvicorn novel_system.api.app:create_app --factory --reload`
4. `cd ../frontend && npm install && npm run dev`
5. Open the app and inspect:
   - `Scene Workbench` for `CH001_SC01`
   - `Review Inbox` for `review_demo_style_observation`
   - `Index Console` after review actions create alias/job activity
```