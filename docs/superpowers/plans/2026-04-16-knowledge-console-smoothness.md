# Knowledge Console Smoothness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `KnowledgeConsoleView` catalog and detail expansion jank by routing remaining long knowledge lists through the existing virtual/progressive list primitives.

**Architecture:** Keep the current Knowledge Console page structure, store state, and backend API usage. Use `VirtualList` for the top-level catalog because it is scroll-position driven, and use `ProgressiveList` inside detail `LazySection` panels because history sections reveal independently and do not need their own scroll viewport.

**Tech Stack:** Vue 3 SFCs, Pinia, Vitest with jsdom, Playwright, Vite.

---

## File Map

**Modify**

- `frontend/src/views/KnowledgeConsoleView.vue`
- `frontend/tests/scrollPerformance.spec.js`
- `frontend/tests/smoothness.spec.js`
- `frontend/tests/e2e/knowledge-console.spec.js`

**Why these files**

- `KnowledgeConsoleView.vue` owns the catalog, selected detail drawer, workflow history lists, and cross-page action buttons.
- `scrollPerformance.spec.js` already mounts heavy views under jsdom with mocked animation frames and is the runtime proof point.
- `smoothness.spec.js` already carries source-level guardrails for virtual/progressive list wiring.
- `knowledge-console.spec.js` already exercises the real knowledge create/review/index/workbench flow.

---

## Task 1: Add Failing Knowledge Console Smoothness Regressions

**Files:**
- Modify: `frontend/tests/scrollPerformance.spec.js`
- Modify: `frontend/tests/smoothness.spec.js`
- Modify: `frontend/tests/e2e/knowledge-console.spec.js`

- [ ] **Step 1: Add Knowledge Console imports to the runtime test**

In `frontend/tests/scrollPerformance.spec.js`, extend the imports near the top:

```js
import KnowledgeConsoleView from "../src/views/KnowledgeConsoleView.vue";
import { useKnowledgeConsoleStore } from "../src/stores/knowledgeConsole";
```

- [ ] **Step 2: Add Knowledge Console runtime fixtures**

Add this code after `createHumanReviewItem` in `frontend/tests/scrollPerformance.spec.js`:

```js
function createKnowledgeCatalogItem(index) {
  const objectType = index % 2 === 0 ? "style_rule" : "calibration_line";
  const lineageKey = `KNOWLEDGE_${String(index).padStart(3, "0")}`;

  return {
    object_type: objectType,
    lineage_key: lineageKey,
    status: index % 2 === 0 ? "active" : "candidate",
    active_version: { row_id: `active-${index}`, version: index, text: `Active knowledge text ${index}` },
    candidate_version: { row_id: `candidate-${index}`, review_id: `knowledge-review-${index}`, text: `Candidate knowledge text ${index}` },
    runtime_refs: { alias_scope: `style_rule:global:${index}`, verify_status: index % 3 === 0 ? "failed" : "succeeded" },
    review_refs: [`knowledge-review-${index}`],
    bundle_refs: [{ bundle_id: `bundle-${index}`, scene_id: `CH001_SC${String(index).padStart(2, "0")}`, chapter_id: "CH001" }],
  };
}

function createKnowledgeDetail(index = 14) {
  const base = createKnowledgeCatalogItem(index);
  return {
    ...base,
    versions: Array.from({ length: 18 }, (_, itemIndex) => ({
      row_id: `version-${itemIndex}`,
      version: itemIndex + 1,
      text: `Version history ${itemIndex}`,
    })),
    review_refs: Array.from({ length: 18 }, (_, itemIndex) => `knowledge-review-${itemIndex}`),
    bundle_refs: Array.from({ length: 18 }, (_, itemIndex) => ({
      bundle_id: `bundle-${itemIndex}`,
      scene_id: `CH001_SC${String(itemIndex).padStart(2, "0")}`,
      chapter_id: "CH001",
    })),
    workflow: {
      review_items: Array.from({ length: 18 }, (_, itemIndex) => ({
        review_id: `knowledge-review-${itemIndex}`,
        status: itemIndex % 2 === 0 ? "pending" : "approved",
        materialize_status: itemIndex % 3 === 0 ? "succeeded" : "pending",
        approved_item_row_id: `version-${itemIndex}`,
      })),
      jobs: Array.from({ length: 18 }, (_, itemIndex) => ({
        job_id: `knowledge-job-${itemIndex}`,
        job_type: "verify",
        review_id: `knowledge-review-${itemIndex}`,
        status: itemIndex % 2 === 0 ? "failed" : "running",
        alias_scope: `style_rule:global:${itemIndex}`,
      })),
      human_review_events: Array.from({ length: 18 }, (_, itemIndex) => ({
        event_id: `knowledge-event-${itemIndex}`,
        status: itemIndex % 2 === 0 ? "pending" : "resolved",
        default_action: "inspect",
        allowed_actions_json: ["inspect", "retry_request"],
      })),
      target_activity_groups: Array.from({ length: 18 }, (_, itemIndex) => ({
        target: { target_type: "review_item", target_id: `knowledge-review-${itemIndex}`, target_ref: `review_item:knowledge-review-${itemIndex}` },
        activity_count: 8 + itemIndex,
        sources: ["operator_action", "system_runtime"],
      })),
      recommended_primary_action: { kind: "review", action: "approve_review", review_id: "knowledge-review-0" },
    },
  };
}

async function mountKnowledgeConsoleView({ catalogCount = 24, selectedIndex = 14 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const store = useKnowledgeConsoleStore();
  store.items = Array.from({ length: catalogCount }, (_, index) => createKnowledgeCatalogItem(index));
  store.detail = createKnowledgeDetail(selectedIndex);
  store.selectedObjectType = store.detail.object_type;
  store.selectedLineageKey = store.detail.lineage_key;
  store.supportedObjectTypes = ["style_rule", "calibration_line"];
  store.loaded = true;
  store.stale = false;
  store.loading = false;
  store.actionId = "";
  store.error = "";

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [h(KnowledgeConsoleView, { onNotice: vi.fn() })]);
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

- [ ] **Step 3: Add failing runtime tests**

Append this describe block to `frontend/tests/scrollPerformance.spec.js`:

```js
describe("knowledge console scroll performance integration", () => {
  let animationFrames;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("mounts the knowledge catalog through VirtualList and keeps the selected card pinned after scroll", async () => {
    const mounted = await mountKnowledgeConsoleView({ catalogCount: 24, selectedIndex: 14 });

    try {
      const catalogList = mounted.container.querySelector('[data-testid="knowledge-catalog-virtual-list"]');
      expect(catalogList).not.toBeNull();
      expect(catalogList.style.maxHeight).toBe("640px");

      let catalogCards = mounted.container.querySelectorAll('[data-testid^="knowledge-card-"]');
      expect(catalogCards.length).toBeGreaterThan(0);
      expect(catalogCards.length).toBeLessThan(mounted.store.items.length);
      expect(mounted.container.querySelector('[data-testid="knowledge-card-style_rule-KNOWLEDGE_014"]')).not.toBeNull();

      catalogList.scrollTop = 10000;
      catalogList.dispatchEvent(new Event("scroll"));
      await flushUi();

      catalogCards = mounted.container.querySelectorAll('[data-testid^="knowledge-card-"]');
      expect(catalogCards.length).toBeGreaterThan(0);
      expect(catalogCards.length).toBeLessThan(mounted.store.items.length);
      expect(mounted.container.querySelector('[data-testid="knowledge-card-style_rule-KNOWLEDGE_014"]')).not.toBeNull();
    } finally {
      mounted.unmount();
    }
  });

  it("progressively renders knowledge detail history lists while keeping visible actions usable", async () => {
    const mounted = await mountKnowledgeConsoleView({ catalogCount: 24, selectedIndex: 14 });

    try {
      [
        "knowledge-toggle-versions",
        "knowledge-toggle-reviews",
        "knowledge-toggle-jobs",
        "knowledge-toggle-human-review",
        "knowledge-toggle-activity",
        "knowledge-toggle-review-refs",
        "knowledge-toggle-bundle-refs",
      ].forEach((testId) => mounted.container.querySelector(`[data-testid="${testId}"]`).click());
      await flushUi();

      [
        "knowledge-versions-progressive-list",
        "knowledge-reviews-progressive-list",
        "knowledge-jobs-progressive-list",
        "knowledge-human-review-progressive-list",
        "knowledge-activity-progressive-list",
        "knowledge-review-refs-progressive-list",
        "knowledge-bundle-refs-progressive-list",
      ].forEach((testId) => {
        expect(mounted.container.querySelector(`[data-testid="${testId}"]`)).not.toBeNull();
      });

      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-version-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-review-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-job-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-human-review-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-activity-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-review-ref-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-bundle-ref-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelector('[data-testid="knowledge-open-related-review-knowledge-review-0"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="knowledge-human-review-action-knowledge-event-0-inspect"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="knowledge-open-review-ref-knowledge-review-0"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="knowledge-open-bundle-ref-bundle-0"]')).not.toBeNull();

      await animationFrames.flushAll();

      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-version-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-review-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-job-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-human-review-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-activity-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-review-ref-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-bundle-ref-row-"]')).toHaveLength(18);
    } finally {
      mounted.unmount();
    }
  });
});
```

- [ ] **Step 4: Add failing source assertions**

In `frontend/tests/smoothness.spec.js`, add this test inside `describe("shell smoothness architecture", () => { ... })` after the existing index timeline virtualization test:

```js
  it("routes knowledge console catalog and detail histories through shared list drivers", () => {
    const knowledgeSource = readFileSync(new URL("../src/views/KnowledgeConsoleView.vue", import.meta.url), "utf8");

    expect(knowledgeSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(knowledgeSource).toContain('import ProgressiveList from "../components/ProgressiveList.vue"');
    expect(knowledgeSource).toContain("const pinnedCatalogKeys = computed(() =>");
    expect(knowledgeSource).toContain('test-id="knowledge-catalog-virtual-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-versions-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-reviews-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-jobs-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-human-review-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-activity-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-review-refs-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-bundle-refs-progressive-list"');
    expect(knowledgeSource).not.toContain('v-for="item in catalogItems"');
    expect(knowledgeSource).not.toContain('v-for="version in knowledgeConsole.detail.versions || []"');
    expect(knowledgeSource).not.toContain('v-for="review in workflowReviewItems"');
    expect(knowledgeSource).not.toContain('v-for="job in workflowJobs"');
  });
```

- [ ] **Step 5: Add failing E2E anchors to the existing knowledge path**

In `frontend/tests/e2e/knowledge-console.spec.js`, after `await expect(page.getByTestId("knowledge-console-view")).toBeVisible();`, add:

```js
  await expect(page.getByTestId("knowledge-catalog-virtual-list")).toBeVisible();
```

After the first `await page.getByTestId("knowledge-view-detail-style_rule-STYLE_KNOWLEDGE_E2E").click();`, add:

```js
  await page.getByTestId("knowledge-toggle-reviews").click();
  await expect(page.getByTestId("knowledge-reviews-progressive-list")).toBeVisible();
```

After `await page.getByTestId("knowledge-toggle-review-refs").click();`, add:

```js
  await expect(page.getByTestId("knowledge-review-refs-progressive-list")).toBeVisible();
```

After `await page.getByTestId("knowledge-toggle-bundle-refs").click();`, add:

```js
  await expect(page.getByTestId("knowledge-bundle-refs-progressive-list")).toBeVisible();
```

- [ ] **Step 6: Run targeted tests and verify they fail for the right reason**

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js
```

Expected: FAIL because `KnowledgeConsoleView.vue` does not yet import `VirtualList` / `ProgressiveList`, does not define `pinnedCatalogKeys`, and does not expose the new `knowledge-*` list anchors.

- [ ] **Step 7: Commit the failing tests**

```bash
git add frontend/tests/scrollPerformance.spec.js frontend/tests/smoothness.spec.js frontend/tests/e2e/knowledge-console.spec.js
git commit -m "test(knowledge): cover smooth list rendering"
```

---

## Task 2: Route Knowledge Console Lists Through VirtualList And ProgressiveList

**Files:**
- Modify: `frontend/src/views/KnowledgeConsoleView.vue`

- [ ] **Step 1: Import shared list primitives**

At the top of `frontend/src/views/KnowledgeConsoleView.vue`, change:

```vue
import LazySection from "../components/LazySection.vue";
import PanelShell from "../components/PanelShell.vue";
```

to:

```vue
import LazySection from "../components/LazySection.vue";
import PanelShell from "../components/PanelShell.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import VirtualList from "../components/VirtualList.vue";
```

- [ ] **Step 2: Add stable catalog key helpers**

After `selectedEntryKey`, add:

```js
const pinnedCatalogKeys = computed(() => (selectedEntryKey.value ? [selectedEntryKey.value] : []));

function knowledgeItemKey(item) {
  return `${item.object_type}:${item.lineage_key}`;
}
```

- [ ] **Step 3: Replace the catalog full render with `VirtualList`**

Replace the catalog `div v-else class="knowledge-list"` block with:

```vue
          <VirtualList
            v-else
            class="knowledge-list"
            :items="catalogItems"
            :item-key="knowledgeItemKey"
            :estimated-item-height="220"
            :threshold="8"
            :viewport-height="640"
            :pinned-keys="pinnedCatalogKeys"
            test-id="knowledge-catalog-virtual-list"
          >
            <template #default="{ item }">
              <article
                class="review-card knowledge-card"
                :class="{ 'focused-card': selectedEntryKey === knowledgeItemKey(item) }"
                :data-testid="`knowledge-card-${item.object_type}-${item.lineage_key}`"
              >
                <div class="source-top">
                  <div>
                    <div class="eyebrow">{{ formatItemType(item.object_type) }}</div>
                    <h3>{{ item.lineage_key }}</h3>
                  </div>
                  <span class="badge">{{ formatStatus(item.status || "tracked") }}</span>
                </div>
                <p><strong>Active text</strong><br />{{ previewSummaryText(item.active_version) }}</p>
                <p><strong>Candidate text</strong><br />{{ previewSummaryText(item.candidate_version) }}</p>
                <p class="muted">Runtime refs: {{ item.runtime_refs?.alias_scope || item.runtime_refs?.mode || "-" }}</p>
                <div class="card-actions">
                  <button class="ghost" :data-testid="`knowledge-view-detail-${item.object_type}-${item.lineage_key}`" @click="selectEntry(item)">
                    View detail
                  </button>
                  <button class="ghost" @click="openReviewInbox(item)">Open review inbox</button>
                  <button class="ghost" @click="openIndexConsole(item)">Open index console</button>
                </div>
              </article>
            </template>
          </VirtualList>
```

- [ ] **Step 4: Convert versions history to `ProgressiveList`**

Replace the versions `LazySection` body with this structure, keeping the section in the same detail-drawer location:

```vue
            <LazySection :key="`versions-${selectedEntryKey}`" title="Version history" toggle-test-id="knowledge-toggle-versions">
              <ProgressiveList
                :items="knowledgeConsole.detail.versions || []"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                test-id="knowledge-versions-progressive-list"
              >
                <template #default="{ items }">
                  <ol class="history-list">
                    <li v-for="version in items" :key="version.row_id" class="history-entry" :data-testid="`knowledge-version-row-${version.row_id}`">
                      <p class="history-meta">
                        <strong>{{ version.row_id }}</strong>
                        <span>v{{ version.version || "candidate" }}</span>
                      </p>
                      <p>{{ version.text || "-" }}</p>
                    </li>
                  </ol>
                </template>
              </ProgressiveList>
            </LazySection>
```

- [ ] **Step 5: Convert related reviews and jobs to `ProgressiveList`**

Wrap related reviews in `ProgressiveList` with `test-id="knowledge-reviews-progressive-list"`, `:initial-count="6"`, `:batch-size="6"`, and row test ids of `knowledge-review-row-${review.review_id}`. Keep the current review row fields and keep the existing `knowledge-open-related-review-${review.review_id}` button.

Wrap related jobs in `ProgressiveList` with `test-id="knowledge-jobs-progressive-list"`, `:initial-count="6"`, `:batch-size="6"`, and row test ids of `knowledge-job-row-${job.job_id}`. Keep the current job row fields and keep the existing `openJobTarget(job)` button.

- [ ] **Step 6: Convert human review events and target activity groups**

Wrap human review events in `ProgressiveList` with `test-id="knowledge-human-review-progressive-list"`, `:initial-count="6"`, `:batch-size="6"`, and row test ids of `knowledge-human-review-row-${event.event_id}`. Keep the current event row fields, `openHumanReviewEvent(event)` button, and per-action buttons using `knowledge-human-review-action-${event.event_id}-${action}`.

Wrap target activity groups in `ProgressiveList` with `test-id="knowledge-activity-progressive-list"`, `:initial-count="6"`, `:batch-size="6"`, and row test ids of `knowledge-activity-row-${group.target.target_ref}`. Keep the current target row fields and `openActivityTarget(group)` button.

- [ ] **Step 7: Convert review refs and bundle refs**

Replace the review refs section with:

```vue
            <LazySection :key="`review-refs-${selectedEntryKey}`" title="Review refs" toggle-test-id="knowledge-toggle-review-refs">
              <ProgressiveList
                v-if="detailReviewRefs.length"
                :items="detailReviewRefs"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                test-id="knowledge-review-refs-progressive-list"
              >
                <template #default="{ items }">
                  <ol class="history-list">
                    <li v-for="reviewRef in items" :key="reviewRef" class="history-entry" :data-testid="`knowledge-review-ref-row-${reviewRef}`">
                      <p class="history-meta">
                        <strong>{{ reviewRef }}</strong>
                        <span>review_item</span>
                      </p>
                      <div class="card-actions">
                        <button class="ghost" :data-testid="`knowledge-open-review-ref-${reviewRef}`" @click="openReviewRef(reviewRef)">
                          Open review inbox
                        </button>
                      </div>
                    </li>
                  </ol>
                </template>
              </ProgressiveList>
              <p v-else class="muted">No review refs yet.</p>
            </LazySection>
```

Replace the bundle refs section with:

```vue
            <LazySection :key="`bundle-refs-${selectedEntryKey}`" title="Bundle refs" toggle-test-id="knowledge-toggle-bundle-refs">
              <ProgressiveList
                v-if="detailBundleRefs.length"
                :items="detailBundleRefs"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                test-id="knowledge-bundle-refs-progressive-list"
              >
                <template #default="{ items }">
                  <ol class="history-list">
                    <li v-for="bundleRef in items" :key="bundleRef.bundle_id" class="history-entry" :data-testid="`knowledge-bundle-ref-row-${bundleRef.bundle_id}`">
                      <p class="history-meta">
                        <strong>{{ bundleRef.bundle_id }}</strong>
                        <span>{{ bundleRef.scene_id }}</span>
                      </p>
                      <p class="muted">Chapter {{ bundleRef.chapter_id || "-" }}</p>
                      <div class="card-actions">
                        <button class="ghost" :data-testid="`knowledge-open-bundle-ref-${bundleRef.bundle_id}`" @click="openBundleWorkbench(bundleRef)">
                          Open workbench
                        </button>
                      </div>
                    </li>
                  </ol>
                </template>
              </ProgressiveList>
              <p v-else class="muted">No bundle refs yet.</p>
            </LazySection>
```

- [ ] **Step 8: Run targeted Vitest regressions**

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js
```

Expected: PASS. The catalog virtual list exposes `knowledge-catalog-virtual-list`, keeps the selected card mounted after scroll, and detail lists reveal progressively from 6 rows to all 18 rows after animation frames flush.

- [ ] **Step 9: Commit the implementation**

```bash
git add frontend/src/views/KnowledgeConsoleView.vue
git commit -m "perf(knowledge): virtualize catalog and progressive detail lists"
```

---

## Task 3: Verify E2E Behavior And Full Frontend Health

**Files:**
- Test: `frontend/tests/e2e/knowledge-console.spec.js`
- Test: full frontend suite

- [ ] **Step 1: Run the Knowledge Console E2E regression**

Run:

```bash
npx playwright test tests/e2e/knowledge-console.spec.js
```

Expected: PASS. The existing creation, approval, review navigation, and workbench navigation flow continues to work with the new catalog and detail list anchors.

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

- [ ] **Step 4: Inspect final git status and changed files**

Run:

```bash
git status --short
git diff --stat main...HEAD
```

Expected: only the planned Knowledge Console spec, plan, view, and test files are included in the branch history.

---

## Spec Coverage Check

- Knowledge catalog virtualization is covered by Task 1 runtime/source tests and Task 2 `VirtualList` implementation.
- Selected catalog card pinning is covered by Task 1 scroll test and Task 2 `pinnedCatalogKeys`.
- Detail workflow/history progressive rendering is covered by Task 1 runtime/source tests and Task 2 `ProgressiveList` conversions.
- Existing action buttons and cross-page navigation are covered by Task 1 runtime action assertions and Task 3 E2E verification.
- Backend API and store state remain unchanged because Task 2 only edits `KnowledgeConsoleView.vue`.

## Placeholder Check

- The plan contains no deferred implementation steps.
- Every code-changing step includes concrete code or exact replacement blocks.
- Every verification step includes the command and expected outcome.

## Type And Naming Check

- `pinnedCatalogKeys`, `knowledgeItemKey`, `knowledge-catalog-virtual-list`, and every `knowledge-*-progressive-list` anchor are named consistently across tasks.
- Runtime test row selectors match the planned `data-testid` values in Task 2.
- The implementation uses existing `VirtualList` and `ProgressiveList` props: `items`, `item-key`, `estimated-item-height`, `threshold`, `viewport-height`, `pinned-keys`, `initial-count`, `batch-size`, and `test-id`.
