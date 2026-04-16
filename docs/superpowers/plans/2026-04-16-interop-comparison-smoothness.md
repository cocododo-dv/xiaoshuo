# Interop Comparison Smoothness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Virtualize the Interop Center source comparison list so large preview/export/replay results do not mount every diff card at once.

**Architecture:** Keep `useInteropCenterStore` data shape unchanged and make `InteropCenterView.vue` responsible only for rendering through the shared `VirtualList`. Preserve comparison card body, target navigation, and existing test ids while adding virtual-list anchors and row spacing.

**Tech Stack:** Vue 3 SFCs, Pinia, shared `VirtualList`, Vitest with jsdom, Playwright, Vite.

---

## File Map

**Modify**

- `frontend/src/views/InteropCenterView.vue`
- `frontend/src/styles/app.css`
- `frontend/tests/scrollPerformance.spec.js`
- `frontend/tests/smoothness.spec.js`
- `frontend/tests/e2e/interop-center.spec.js`

**Why these files**

- `InteropCenterView.vue` owns the source comparison list and target jump button.
- `app.css` owns shared virtual row spacing for card lists.
- `scrollPerformance.spec.js` is the runtime proof point for large-list virtualization.
- `smoothness.spec.js` owns source guardrails for heavy surfaces.
- `interop-center.spec.js` covers the real preview/import/export/replay lifecycle.

---

## Task 1: Add Failing Interop Comparison Smoothness Regressions

**Files:**
- Modify: `frontend/tests/scrollPerformance.spec.js`
- Modify: `frontend/tests/smoothness.spec.js`
- Modify: `frontend/tests/e2e/interop-center.spec.js`

- [ ] **Step 1: Add Interop imports to the runtime test**

In `frontend/tests/scrollPerformance.spec.js`, extend imports near the top:

```js
import InteropCenterView from "../src/views/InteropCenterView.vue";
import { useInteropCenterStore } from "../src/stores/interopCenter";
```

- [ ] **Step 2: Add Interop runtime fixtures**

Add these helpers after `createKnowledgeDetail` in `frontend/tests/scrollPerformance.spec.js`:

```js
function createInteropComparison(index) {
  const objectType = index % 2 === 0 ? "style_rule" : "scene_card";
  const lineageKey = `INTEROP_${String(index).padStart(3, "0")}`;

  return {
    object_type: objectType,
    lineage_key: lineageKey,
    source_ref_key: `source_ref_${index}`,
    version_status: index % 3 === 0 ? "version_mismatch" : "same_version",
    text_status: index % 4 === 0 ? "text_mismatch" : "same_text",
    source_row_id: `source-row-${index}`,
    source_version: index,
    active_row_id: `active-row-${index}`,
    active_version: index + 1,
    source_text: `Source comparison text ${index}`,
    active_text: `Active comparison text ${index}`,
    target: {
      target_type: "knowledge_entry",
      target_id: lineageKey,
      target_ref: `knowledge_entry:${objectType}:${lineageKey}`,
      view_id: "knowledge",
    },
  };
}

async function mountInteropCenterView({ comparisonCount = 24 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = useShellRouter();
  router.reset();
  router.navigate("interop");

  const store = useInteropCenterStore();
  store.activeMode = "preview";
  store.activeEnvelope = {
    bundle_id: "bundle_interop_smoothness",
    scene_id: "CH001_SC01",
    chapter_id: "CH001",
    execution_mode: "P1_scripted",
  };
  store.activeArtifactReceipt = null;
  store.activeSourceComparisons = Array.from({ length: comparisonCount }, (_, index) =>
    createInteropComparison(index + 1),
  );
  store.error = "";
  store.actionId = "";

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [
        h(InteropCenterView, {
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
    router,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}
```

- [ ] **Step 3: Add the failing runtime test**

Append this block to `frontend/tests/scrollPerformance.spec.js` before the Author Trash describe block:

```js
describe("interop center scroll performance integration", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => callback(0)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
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

  it("virtualizes source comparisons while keeping target jump actions usable", async () => {
    const mounted = await mountInteropCenterView({ comparisonCount: 24 });

    try {
      const comparisonVirtualList = mounted.container.querySelector('[data-testid="interop-comparison-virtual-list"]');

      expect(comparisonVirtualList).not.toBeNull();
      expect(comparisonVirtualList.classList.contains("virtual-list")).toBe(true);
      expect(comparisonVirtualList.style.maxHeight).toBe("640px");
      expect(comparisonVirtualList.querySelector(".virtual-list-row")).not.toBeNull();

      const comparisonCards = mounted.container.querySelectorAll('[data-testid^="interop-source-comparison-"]');
      expect(comparisonCards.length).toBeGreaterThan(0);
      expect(comparisonCards.length).toBeLessThan(mounted.store.activeSourceComparisons.length);
      expect(mounted.container.querySelector('[data-testid="interop-source-comparison-scene_card-INTEROP_001"]')).not.toBeNull();

      mounted.container.querySelector('[data-testid="interop-source-comparison-scene_card-INTEROP_001"] button').click();
      await flushUi();

      expect(mounted.router.activeView.value).toBe("knowledge");
      expect(mounted.router.focusTarget.value.target_ref).toBe("knowledge_entry:scene_card:INTEROP_001");
    } finally {
      mounted.unmount();
    }
  });
});
```

Expected failure before implementation: `comparisonVirtualList` is `null` because `InteropCenterView.vue` still renders `activeSourceComparisons` with full-list `v-for`.

- [ ] **Step 4: Add failing smoothness source guardrails**

In `frontend/tests/smoothness.spec.js`, add a new test after the Author Trash virtual-list guard:

```js
  it("routes interop source comparisons through the shared virtual list driver", () => {
    const interopSource = readFileSync(new URL("../src/views/InteropCenterView.vue", import.meta.url), "utf8");
    const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");

    expect(interopSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(interopSource).toContain("function comparisonKey(item)");
    expect(interopSource).toContain('test-id="interop-comparison-virtual-list"');
    expect(interopSource).toContain(':item-key="comparisonKey"');
    expect(interopSource).not.toContain('v-for="item in activeSourceComparisons"');
    expect(styles).toContain(".comparison-list .virtual-list-row");
  });
```

- [ ] **Step 5: Add E2E virtual-list anchors to Interop lifecycle**

In `frontend/tests/e2e/interop-center.spec.js`, after:

```js
  await expect(page.getByTestId("interop-preview-summary")).toContainText("BSHASH_v1");
```

add:

```js
  await expect(page.getByTestId("interop-comparison-virtual-list")).toBeVisible();
```

After:

```js
  await expect(page.getByTestId("interop-envelope-panel")).toContainText("P1_scripted");
```

add:

```js
  await expect(page.getByTestId("interop-comparison-virtual-list")).toBeVisible();
```

- [ ] **Step 6: Run targeted Vitest and verify red failure**

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/bundleProvenance.spec.js
```

Expected: FAIL because `InteropCenterView.vue` does not yet import `VirtualList`, does not expose `interop-comparison-virtual-list`, and still renders comparisons with full-list `v-for`.

- [ ] **Step 7: Commit the failing tests**

Run:

```bash
git add frontend/tests/scrollPerformance.spec.js frontend/tests/smoothness.spec.js frontend/tests/e2e/interop-center.spec.js
git commit -m "test(interop): cover virtual comparison list"
```

---

## Task 2: Virtualize Interop Source Comparisons

**Files:**
- Modify: `frontend/src/views/InteropCenterView.vue`
- Modify: `frontend/src/styles/app.css`

- [ ] **Step 1: Import `VirtualList`**

In `frontend/src/views/InteropCenterView.vue`, change imports from:

```js
import LazySection from "../components/LazySection.vue";
import PanelShell from "../components/PanelShell.vue";
```

to:

```js
import LazySection from "../components/LazySection.vue";
import PanelShell from "../components/PanelShell.vue";
import VirtualList from "../components/VirtualList.vue";
```

- [ ] **Step 2: Add a stable comparison key helper**

After `formatJsonPayload` in `frontend/src/views/InteropCenterView.vue`, add:

```js
function comparisonKey(item) {
  return `${item?.object_type || "unknown"}:${item?.lineage_key || "unknown"}:${item?.source_ref_key || "unknown"}`;
}
```

- [ ] **Step 3: Replace the comparison list wrapper**

Replace:

```vue
          <div v-if="activeSourceComparisons.length" class="comparison-list">
            <article
              v-for="item in activeSourceComparisons"
              :key="`${item.object_type}:${item.lineage_key}:${item.source_ref_key}`"
              class="paper mini comparison-card"
              :data-testid="`interop-source-comparison-${item.object_type}-${item.lineage_key}`"
            >
```

with:

```vue
          <VirtualList
            v-if="activeSourceComparisons.length"
            class="comparison-list"
            :items="activeSourceComparisons"
            :item-key="comparisonKey"
            :estimated-item-height="260"
            :threshold="8"
            :viewport-height="640"
            test-id="interop-comparison-virtual-list"
          >
            <template #default="{ item }">
              <article
                class="paper mini comparison-card"
                :data-testid="`interop-source-comparison-${item.object_type}-${item.lineage_key}`"
              >
```

Keep the entire comparison card body unchanged.

Replace the old closing:

```vue
            </article>
          </div>
```

with:

```vue
              </article>
            </template>
          </VirtualList>
```

- [ ] **Step 4: Preserve spacing for virtual comparison rows**

In `frontend/src/styles/app.css`, extend:

```css
.review-list .virtual-list-row,
.knowledge-list .virtual-list-row,
.author-list .virtual-list-row,
.author-scene-list .virtual-list-row,
.trash-list .virtual-list-row,
.receipt-list .virtual-list-row,
.job-table .virtual-list-row {
  padding-bottom: 1rem;
}
```

to:

```css
.review-list .virtual-list-row,
.knowledge-list .virtual-list-row,
.author-list .virtual-list-row,
.author-scene-list .virtual-list-row,
.trash-list .virtual-list-row,
.comparison-list .virtual-list-row,
.receipt-list .virtual-list-row,
.job-table .virtual-list-row {
  padding-bottom: 1rem;
}
```

- [ ] **Step 5: Run targeted Vitest regressions**

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/bundleProvenance.spec.js
```

Expected: PASS. The runtime test should show the Interop comparison list is a `VirtualList`, rendered card count is below the full source array, and target jump still routes to `knowledge`.

- [ ] **Step 6: Commit the implementation**

Run:

```bash
git add frontend/src/views/InteropCenterView.vue frontend/src/styles/app.css
git commit -m "perf(interop): virtualize comparison list"
```

---

## Task 3: Verify Interop E2E And Full Frontend Health

**Files:**
- Test: `frontend/tests/e2e/interop-center.spec.js`
- Test: full frontend suite

- [ ] **Step 1: Run the Interop E2E regression**

Run:

```bash
npx playwright test tests/e2e/interop-center.spec.js
```

Expected: PASS. The existing preview/import/export/replay lifecycle should still find comparison rows and the new virtual-list anchor.

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

Expected: only the Interop comparison spec, plan, view, style, and test files are included in this branch.

---

## Spec Coverage Check

- Large comparison list virtualization is covered by Task 1 runtime test and Task 2 `VirtualList` implementation.
- Existing comparison card content and target jump behavior are preserved by reusing the existing card body and by the runtime click assertion.
- E2E lifecycle anchors are covered by `interop-center.spec.js`.
- Source guardrails prevent regression to full-list `v-for`.
- Row spacing is covered by the source guard and CSS selector update.

## Placeholder Check

- The plan contains no deferred implementation tasks.
- Every code-changing task includes exact files and concrete snippets.
- Every verification step includes a command and expected result.

## Type And Naming Check

- `comparisonKey`, `interop-comparison-virtual-list`, `.comparison-list .virtual-list-row`, and the existing `interop-source-comparison-${object_type}-${lineage_key}` test ids are named consistently across tests and implementation.
