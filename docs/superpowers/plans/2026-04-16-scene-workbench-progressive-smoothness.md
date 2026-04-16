# Scene Workbench Progressive Smoothness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Progressively render Scene Workbench preflight and staged backfill lists so large scene payloads do not mount every item on first paint.

**Architecture:** Keep the workbench store and backend payloads unchanged. `SceneWorkbenchView.vue` imports the shared `ProgressiveList` and swaps four direct `v-for` list drivers for scoped progressive slots while preserving each row body and all action controls.

**Tech Stack:** Vue 3 SFCs, Pinia, shared `ProgressiveList`, Vitest with jsdom, Playwright, Vite.

---

## File Map

**Modify**

- `frontend/src/views/SceneWorkbenchView.vue`
- `frontend/tests/scrollPerformance.spec.js`
- `frontend/tests/smoothness.spec.js`
- `frontend/tests/e2e/scene-preflight.spec.js`
- `frontend/tests/e2e/chapter-ops.spec.js`

**Why these files**

- `SceneWorkbenchView.vue` owns the preflight groups and staged backfill controls.
- `scrollPerformance.spec.js` is the runtime proof point for heavy in-page list rendering.
- `smoothness.spec.js` owns architecture guardrails for heavy view surfaces.
- `scene-preflight.spec.js` and `chapter-ops.spec.js` are the real user lifecycle checks for preflight text and backfill actions.

---

## Task 1: Add Failing Scene Workbench Progressive Rendering Regressions

**Files:**
- Modify: `frontend/tests/scrollPerformance.spec.js`
- Modify: `frontend/tests/smoothness.spec.js`
- Modify: `frontend/tests/e2e/scene-preflight.spec.js`
- Modify: `frontend/tests/e2e/chapter-ops.spec.js`

- [ ] **Step 1: Add Scene Workbench imports to the runtime test**

In `frontend/tests/scrollPerformance.spec.js`, extend imports near the top:

```js
import SceneWorkbenchView from "../src/views/SceneWorkbenchView.vue";
import { useWorkbenchStore } from "../src/stores/workbench";
```

- [ ] **Step 2: Add Scene Workbench runtime fixtures**

Add these helpers after `createTrashScene` in `frontend/tests/scrollPerformance.spec.js`:

```js
function createPreflightItem(prefix, index) {
  return {
    code: `${prefix}_${String(index).padStart(2, "0")}`,
    title: `${prefix} item ${index}`,
    detail: `Detailed ${prefix} explanation ${index}`,
    technical_hint: `${prefix}.hint.${index}`,
  };
}

function createBackfillItem(index) {
  const stageId = `stage_${String(index).padStart(2, "0")}`;

  return {
    stage_id: stageId,
    chapter_id: "CH_PROGRESSIVE",
    scene_id: "CH_PROGRESSIVE_SC01",
    marker_id: `F${String(index).padStart(2, "0")}`,
    marker_text: `Backfill marker ${index}`,
    marker_token: `{{backfill id=F${String(index).padStart(2, "0")} text="Backfill marker ${index}"}}`,
    status: "pending",
    linked_tracker_row_id: null,
    last_strategy: null,
  };
}

function createSceneWorkbenchPayload({ preflightCount = 14, backfillCount = 10 } = {}) {
  return {
    chapter_goal: {
      chapter_id: "CH_PROGRESSIVE",
      chapter_goal: "Keep progressive workbench lists smooth",
      main_plot_push: "Avoid mounting every preflight and backfill row together",
      emotional_target: "Lower operator friction",
      ending_effect: "The workbench remains responsive",
    },
    scene_card: {
      scene_id: "CH_PROGRESSIVE_SC01",
      scene_goal: "Verify progressive scene workbench lists",
      must_include_text: "Progressive clue",
      location: "Render lab",
    },
    scene_run_state: {
      scene_status: "ready",
      current_bundle_id: null,
      current_bundle_hash: null,
      current_final_scene_row_id: null,
    },
    chapter_state: {
      chapter_id: "CH_PROGRESSIVE",
      chapter_backfill_pending_count: backfillCount,
      aggregate_block_reason: "blocked_waiting_backfill",
      manual_hold_reason: null,
      mid_aggregate_enabled_effective: 0,
      last_interim_memory_row_id: null,
      last_final_memory_row_id: null,
      staged_backfill_items: Array.from({ length: backfillCount }, (_, index) => createBackfillItem(index + 1)),
    },
    run_preflight: {
      can_run: false,
      overall_status: "blocked",
      blocking_items: Array.from({ length: preflightCount }, (_, index) => createPreflightItem("blocking", index + 1)),
      warning_items: Array.from({ length: preflightCount }, (_, index) => createPreflightItem("warning", index + 1)),
      context_items: Array.from({ length: preflightCount }, (_, index) => createPreflightItem("context", index + 1)),
    },
    bundle: {
      bundle_id: null,
      bundle_snapshot_hash: null,
      snapshot: null,
    },
    generation_summary: null,
    hard_qc_summary: null,
    soft_qc_summary: null,
    rewrite_counters: {
      hard_partial_rewrite_count: 0,
      hard_full_rewrite_count: 0,
      soft_patch_count: 0,
      repeat_issue_key: null,
      repeat_issue_count: 0,
    },
    human_review_summary: null,
    neutral_draft: { row_id: "draft_neutral_progressive", content: "Neutral progressive draft" },
    style_draft: { row_id: "draft_style_progressive", content: "Style progressive draft" },
    final_scene: null,
    scene_memory: null,
    attempts: [],
  };
}

async function mountSceneWorkbenchView({ preflightCount = 14, backfillCount = 10 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = useShellRouter();
  router.reset();

  const payload = createSceneWorkbenchPayload({ preflightCount, backfillCount });
  const store = useWorkbenchStore();
  store.sceneId = payload.scene_card.scene_id;
  store.data = payload;
  store.attempts = [];
  store.attemptPager = {
    items: [],
    pagination: { has_next: false, next_cursor: null, returned: 0, total: 0, limit: 25, mode: "cursor" },
  };
  store.humanReviewItems = [];
  store.loaded = true;
  store.loading = false;
  store.error = "";
  store.actionId = "";
  store.ensureLoaded = vi.fn(async () => {});
  store.runChapterBackfill = vi.fn(async (chapterId, stageId, strategy) => {
    store.lastChapterActionResult = {
      action: "run_backfill",
      chapter_id: chapterId,
      stage_id: stageId,
      strategy,
      status: "completed",
    };
    return `ran ${stageId}`;
  });

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [
        h(SceneWorkbenchView, {
          onNotice: vi.fn(),
        }),
      ]);
    },
  });
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    app,
    store,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}
```

- [ ] **Step 3: Add the failing runtime test**

Append this block to `frontend/tests/scrollPerformance.spec.js` before the Author Workspace describe block:

```js
describe("scene workbench progressive rendering integration", () => {
  let animationFrames;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("progressively renders preflight and staged backfill lists while keeping first controls usable", async () => {
    const mounted = await mountSceneWorkbenchView({ preflightCount: 14, backfillCount: 10 });

    try {
      [
        "scene-run-preflight-blocking-progressive-list",
        "scene-run-preflight-warning-progressive-list",
        "scene-run-preflight-context-progressive-list",
        "chapter-backfill-progressive-list",
      ].forEach((testId) => {
        const list = mounted.container.querySelector(`[data-testid="${testId}"]`);
        expect(list).not.toBeNull();
        expect(list.classList.contains("progressive-list")).toBe(true);
      });

      const blockingRows = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-blocking_"]');
      const warningRows = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-warning_"]');
      const contextRows = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-context_"]');
      const backfillRows = mounted.container.querySelectorAll('[data-testid^="chapter-backfill-item-stage_"]');

      expect(blockingRows).toHaveLength(6);
      expect(warningRows).toHaveLength(6);
      expect(contextRows).toHaveLength(6);
      expect(backfillRows).toHaveLength(4);
      expect(mounted.container.querySelector('[data-testid="scene-run-preflight-item-blocking_01"]')).toContainText("blocking item 1");
      expect(mounted.container.querySelector('[data-testid="chapter-backfill-item-stage_01"]')).toContainText("Backfill marker 1");

      const strategySelect = mounted.container.querySelector('[data-testid="chapter-backfill-strategy-stage_01"]');
      strategySelect.value = "run_backfill_again";
      strategySelect.dispatchEvent(new Event("change"));
      await flushUi();

      mounted.container.querySelector('[data-testid="chapter-backfill-run-stage_01"]').click();
      await flushUi();

      expect(mounted.store.runChapterBackfill).toHaveBeenCalledWith(
        "CH_PROGRESSIVE",
        "stage_01",
        "run_backfill_again",
        "CH_PROGRESSIVE_SC01",
      );
      expect(mounted.store.lastChapterActionResult.stage_id).toBe("stage_01");
    } finally {
      mounted.unmount();
    }
  });
});
```

Expected failure before implementation: all four progressive-list anchors are missing because `SceneWorkbenchView.vue` still uses direct `v-for`.

- [ ] **Step 4: Add failing source guardrails**

In `frontend/tests/smoothness.spec.js`, add this test after the Interop source comparison guard:

```js
  it("routes scene workbench preflight and backfill lists through progressive list drivers", () => {
    const workbenchSource = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(workbenchSource).toContain('import ProgressiveList from "../components/ProgressiveList.vue"');
    expect(workbenchSource).toContain('test-id="scene-run-preflight-blocking-progressive-list"');
    expect(workbenchSource).toContain('test-id="scene-run-preflight-warning-progressive-list"');
    expect(workbenchSource).toContain('test-id="scene-run-preflight-context-progressive-list"');
    expect(workbenchSource).toContain('test-id="chapter-backfill-progressive-list"');
    expect(workbenchSource).not.toContain('v-for="item in runPreflight.blocking_items"');
    expect(workbenchSource).not.toContain('v-for="item in runPreflight.warning_items"');
    expect(workbenchSource).not.toContain('v-for="item in runPreflight.context_items"');
    expect(workbenchSource).not.toContain('v-for="item in pendingStagedBackfillItems"');
  });
```

- [ ] **Step 5: Add E2E progressive anchors to existing lifecycle tests**

In `frontend/tests/e2e/scene-preflight.spec.js`, after:

```js
  const preflightCard = page.getByTestId("scene-run-preflight-card");
```

add:

```js
  await expect(page.getByTestId("scene-run-preflight-blocking-progressive-list")).toBeVisible();
```

After loading `CH211_SC01` and before checking warning text, add:

```js
  await expect(page.getByTestId("scene-run-preflight-warning-progressive-list")).toBeVisible();
```

In `frontend/tests/e2e/chapter-ops.spec.js`, after:

```js
  await expect(page.getByTestId("scene-workbench-view")).toContainText("聚合门控：等待补写");
```

add:

```js
  await expect(page.getByTestId("chapter-backfill-progressive-list")).toBeVisible();
```

- [ ] **Step 6: Run targeted Vitest and verify red failure**

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/sceneWorkbenchPreflight.spec.js tests/workbenchChapterRuntime.spec.js
```

Expected: FAIL because `SceneWorkbenchView.vue` does not yet import `ProgressiveList` or expose the four progressive-list anchors.

- [ ] **Step 7: Commit the failing tests**

Run:

```bash
git add frontend/tests/scrollPerformance.spec.js frontend/tests/smoothness.spec.js frontend/tests/e2e/scene-preflight.spec.js frontend/tests/e2e/chapter-ops.spec.js
git commit -m "test(workbench): cover progressive preflight lists"
```

---

## Task 2: Progressively Render Scene Workbench Preflight And Backfill Lists

**Files:**
- Modify: `frontend/src/views/SceneWorkbenchView.vue`

- [ ] **Step 1: Import `ProgressiveList`**

In `frontend/src/views/SceneWorkbenchView.vue`, change imports from:

```js
import PanelShell from "../components/PanelShell.vue";
import QcReportCard from "../components/QcReportCard.vue";
```

to:

```js
import PanelShell from "../components/PanelShell.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import QcReportCard from "../components/QcReportCard.vue";
```

- [ ] **Step 2: Replace the blocking preflight item loop**

Replace the direct blocking `article v-for` block inside `data-testid="scene-run-preflight-blocking"` with:

```vue
            <ProgressiveList
              :items="runPreflight.blocking_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-blocking-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item preflight-item-blocking"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
```

- [ ] **Step 3: Replace the warning preflight item loop**

Replace the direct warning `article v-for` block inside `data-testid="scene-run-preflight-warning"` with:

```vue
            <ProgressiveList
              :items="runPreflight.warning_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-warning-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
```

- [ ] **Step 4: Replace the context preflight item loop**

Replace the direct context `article v-for` block inside `data-testid="scene-run-preflight-context"` with:

```vue
            <ProgressiveList
              :items="runPreflight.context_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-context-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
```

- [ ] **Step 5: Replace the staged backfill loop**

Replace:

```vue
              <div v-if="pendingStagedBackfillItems.length" class="chapter-backfill-list">
                <article
                  v-for="item in pendingStagedBackfillItems"
                  :key="item.stage_id"
                  class="chapter-backfill-item"
                  :data-testid="`chapter-backfill-item-${item.stage_id}`"
                >
```

with:

```vue
              <ProgressiveList
                v-if="pendingStagedBackfillItems.length"
                class="chapter-backfill-list"
                :items="pendingStagedBackfillItems"
                :initial-count="4"
                :batch-size="4"
                :threshold="4"
                test-id="chapter-backfill-progressive-list"
              >
                <template #default="{ items }">
                  <article
                    v-for="item in items"
                    :key="item.stage_id"
                    class="chapter-backfill-item"
                    :data-testid="`chapter-backfill-item-${item.stage_id}`"
                  >
```

Keep the row body exactly the same, from:

```vue
                  <p><strong>{{ item.marker_text }}</strong></p>
```

through the row's execute button.

Replace the old backfill list closing:

```vue
                </article>
              </div>
```

with:

```vue
                  </article>
                </template>
              </ProgressiveList>
```

- [ ] **Step 6: Run targeted Vitest regressions**

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/sceneWorkbenchPreflight.spec.js tests/workbenchChapterRuntime.spec.js
```

Expected: PASS. The runtime test should show only six preflight rows per group and four backfill rows initially, while the first backfill select/button still calls `runChapterBackfill` with the selected strategy.

- [ ] **Step 7: Commit the implementation**

Run:

```bash
git add frontend/src/views/SceneWorkbenchView.vue
git commit -m "perf(workbench): progressively render preflight lists"
```

---

## Task 3: Verify Scene Workbench E2E And Full Frontend Health

**Files:**
- Test: `frontend/tests/e2e/scene-preflight.spec.js`
- Test: `frontend/tests/e2e/chapter-ops.spec.js`
- Test: full frontend suite

- [ ] **Step 1: Run Scene Workbench E2E regressions**

Run:

```bash
npx playwright test tests/e2e/scene-preflight.spec.js tests/e2e/chapter-ops.spec.js
```

Expected: PASS. Existing preflight text checks and chapter backfill operations should still work with the new progressive wrappers.

- [ ] **Step 2: Run the full frontend test suite**

Run:

```bash
npm test
```

Expected: PASS with all Vitest files passing and `frontend smoke ok`.

- [ ] **Step 3: Run production build**

Run:

```bash
npm run build
```

Expected: PASS with a successful Vite production build.

- [ ] **Step 4: Inspect final status and branch diff**

Run:

```bash
git status --short
git diff --stat main...HEAD
```

Expected: only the Scene Workbench progressive-rendering spec, plan, view, and test files are included in the branch.

---

## Spec Coverage Check

- Preflight blocking, warning, and context groups are covered by Task 1 runtime/source tests and Task 2 wrappers.
- Pending staged backfill controls are covered by Task 1 runtime/source tests and Task 2 wrapper.
- Existing E2E lifecycle behavior is covered by Task 3.
- No backend API or store payload changes are included.

## Placeholder Check

- The plan contains no deferred implementation tasks.
- Every code-changing task includes exact files and concrete snippets.
- Every verification step includes a command and expected result.

## Type And Naming Check

- `scene-run-preflight-blocking-progressive-list`, `scene-run-preflight-warning-progressive-list`, `scene-run-preflight-context-progressive-list`, and `chapter-backfill-progressive-list` are named consistently across tests and implementation.
- Existing row ids `scene-run-preflight-item-${item.code}` and `chapter-backfill-item-${item.stage_id}` remain unchanged.
