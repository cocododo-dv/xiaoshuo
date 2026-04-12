# Scene Workbench Run Actions Implementation Plan

**Status:** implemented

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Scene Workbench trigger the existing `run/full` pipeline and refresh the current scene board in place.

**Architecture:** Add a thin frontend API helper, extend the workbench Pinia store with a dedicated run action and receipt state, then wire a single execution button plus a compact receipt card into the existing view. Keep the backend unchanged and reuse current notice handling.

**Tech Stack:** Vue 3, Pinia, Vite, Vitest

---

## File Structure

- `frontend/tests/app.spec.js`
  Extend store tests for the new run action.
- `frontend/tests/bundleProvenance.spec.js`
  Extend source-level coverage for view integration.
- `frontend/src/lib/api.js`
  Add a `runFullScene` helper.
- `frontend/src/stores/workbench.js`
  Add run state and run action.
- `frontend/src/views/SceneWorkbenchView.vue`
  Add the button and receipt UI wiring.
- `frontend/src/styles/app.css`
  Add receipt/action styles.

---

### Task 1: Red tests for the executable workbench

**Files:**
- Modify: `frontend/tests/app.spec.js`
- Modify: `frontend/tests/bundleProvenance.spec.js`

- [x] **Step 1: Write the failing store test**

```js
it("runs a full scene and refreshes the workbench state", async () => {
  const store = useWorkbenchStore();

  globalThis.fetch = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          scene_status: "archived",
          current_bundle_id: "bundle_CH001_SC01",
          current_bundle_hash: "hash_123",
          current_final_scene_row_id: "final_scene_CH001_SC01",
        },
      }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          scene_card: { scene_id: "CH001_SC01" },
          scene_run_state: { scene_status: "archived" },
          bundle: { bundle_id: "bundle_CH001_SC01" },
          attempts: [],
        },
      }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ok: true, data: { items: [] } }),
    });

  const message = await store.runScene("CH001_SC01");

  expect(message).toContain("CH001_SC01");
  expect(store.lastRunResult.current_final_scene_row_id).toBe("final_scene_CH001_SC01");
  expect(globalThis.fetch).toHaveBeenCalledTimes(3);
});
```

- [x] **Step 2: Write the failing view integration test**

```js
it("wires a run action and receipt section into the scene workbench", () => {
  const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

  expect(source).toContain("Run Full Scene");
  expect(source).toContain("workbench.runScene");
  expect(source).toContain("lastRunResult");
});
```

- [x] **Step 3: Run the targeted tests to verify RED**

Run: `npx vitest run tests/app.spec.js tests/bundleProvenance.spec.js`
Expected: FAIL because the store and view do not yet expose run action behavior.

---

### Task 2: Implement the run action

**Files:**
- Modify: `frontend/src/lib/api.js`
- Modify: `frontend/src/stores/workbench.js`

- [x] **Step 1: Add the API helper**

```js
export function runFullScene(sceneId) {
  return apiPost(`/api/v1/scenes/${sceneId}/run/full`);
}
```

- [x] **Step 2: Add store run state and action**

```js
state: () => ({
  sceneId: "CH001_SC01",
  data: null,
  humanReviewItems: [],
  loading: false,
  humanReviewLoading: false,
  actionId: "",
  lastRunResult: null,
  error: "",
})
```

```js
async runScene(sceneId = this.sceneId) {
  this.actionId = "run-scene";
  this.error = "";
  this.sceneId = sceneId;
  try {
    const result = await runFullScene(sceneId);
    this.lastRunResult = result;
    await this.refreshAll(sceneId);
    return `Ran ${sceneId} through full scene pipeline`;
  } catch (error) {
    this.error = error.message;
    throw error;
  } finally {
    this.actionId = "";
  }
}
```

- [x] **Step 3: Run the targeted tests to verify GREEN for store behavior**

Run: `npx vitest run tests/app.spec.js tests/bundleProvenance.spec.js`
Expected: still FAIL because the view has not been updated yet.

---

### Task 3: Wire the workbench UI

**Files:**
- Modify: `frontend/src/views/SceneWorkbenchView.vue`
- Modify: `frontend/src/styles/app.css`

- [x] **Step 1: Add the run button and handler**

```vue
async function runScene() {
  try {
    const message = await workbench.runScene(requestedSceneId.value.trim() || workbench.sceneId);
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}
```

```vue
<button :disabled="workbench.actionId === 'run-scene'" @click="runScene">
  {{ workbench.actionId === 'run-scene' ? 'Running...' : 'Run Full Scene' }}
</button>
```

- [x] **Step 2: Add the receipt panel**

```vue
<article v-if="workbench.lastRunResult" class="paper receipt-card">
  <h3>Run Receipt</h3>
  <p><strong>Status</strong><br />{{ workbench.lastRunResult.scene_status }}</p>
  <p><strong>Bundle</strong><br />{{ workbench.lastRunResult.current_bundle_id }}</p>
  <p><strong>Hash</strong><br />{{ workbench.lastRunResult.current_bundle_hash }}</p>
  <p><strong>Final Scene</strong><br />{{ workbench.lastRunResult.current_final_scene_row_id }}</p>
</article>
```

- [x] **Step 3: Add minimal styles for the action strip and receipt card**

```css
.receipt-card {
  position: relative;
  overflow: hidden;
}

.receipt-card::after {
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 6px;
  background: linear-gradient(180deg, var(--accent), #d57049);
}
```

- [x] **Step 4: Run the targeted tests to verify GREEN**

Run: `npx vitest run tests/app.spec.js tests/bundleProvenance.spec.js`
Expected: PASS

---

### Task 4: Full verification

**Files:**
- Modify: none

- [x] **Step 1: Run frontend test suite**

Run: `npm test`
Expected: PASS

- [x] **Step 2: Run production build**

Run: `npm run build`
Expected: PASS