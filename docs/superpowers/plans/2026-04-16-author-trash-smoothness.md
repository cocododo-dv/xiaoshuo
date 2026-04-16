# Author Trash Smoothness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Virtualize the Author Trash chapter and scene recycle-bin lists while preserving restore/purge selection behavior.

**Architecture:** Keep `AuthorTrashView` state and store interactions unchanged. Use the shared `VirtualList` component for both trash lists, pin selected row keys, and extend the existing virtual-row spacing CSS.

**Tech Stack:** Vue 3 SFCs, Pinia, Vitest with jsdom, Playwright, Vite.

---

## File Map

**Modify**

- `frontend/src/views/AuthorTrashView.vue`
- `frontend/src/styles/app.css`
- `frontend/tests/scrollPerformance.spec.js`
- `frontend/tests/smoothness.spec.js`
- `frontend/tests/e2e/author-trash.spec.js`

**Why these files**

- `AuthorTrashView.vue` owns the chapter and scene trash lists plus checkbox selection state.
- `app.css` owns the shared virtual row spacing selector used by other virtualized card lists.
- `scrollPerformance.spec.js` already mounts heavy views under jsdom and is the runtime proof point for virtual lists.
- `smoothness.spec.js` already contains architecture guardrails for heavy cached views.
- `author-trash.spec.js` is the existing real user flow for author trash restore/purge behavior.

---

## Task 1: Add Failing Author Trash Smoothness Regressions

**Files:**
- Modify: `frontend/tests/scrollPerformance.spec.js`
- Modify: `frontend/tests/smoothness.spec.js`
- Modify: `frontend/tests/e2e/author-trash.spec.js`

- [ ] **Step 1: Add Author Trash imports to the runtime test**

In `frontend/tests/scrollPerformance.spec.js`, extend the imports near the top:

```js
import AuthorTrashView from "../src/views/AuthorTrashView.vue";
import { useAuthorTrashStore } from "../src/stores/authorTrash";
```

- [ ] **Step 2: Add Author Trash runtime fixtures**

Add these helpers after `createAuthorScene` in `frontend/tests/scrollPerformance.spec.js`:

```js
function createTrashChapter(index) {
  const chapterId = `TRASH_CH${String(index).padStart(3, "0")}`;

  return {
    chapter_id: chapterId,
    chapter_goal: `Trashed chapter goal ${index}`,
    scene_count: (index % 4) + 1,
    trashed_at: `2026-04-16T08:${String(index).padStart(2, "0")}:00+00:00`,
    trashed_by: "ops.smoothness",
    restore_allowed: index % 6 === 0 ? 0 : 1,
    purge_allowed: index % 7 === 0 ? 0 : 1,
    restore_block_reason: index % 6 === 0 ? "restore blocked by downstream runtime" : null,
    purge_block_reason: index % 7 === 0 ? "purge blocked by downstream runtime" : null,
  };
}

function createTrashScene(index) {
  const sceneId = `TRASH_SC${String(index).padStart(3, "0")}`;

  return {
    scene_id: sceneId,
    chapter_id: `TRASH_CH${String(Math.max(index - 1, 1)).padStart(3, "0")}`,
    scene_seq: index,
    scene_goal: `Trashed scene goal ${index}`,
    trashed_at: `2026-04-16T09:${String(index).padStart(2, "0")}:00+00:00`,
    trashed_by: "ops.smoothness",
    chapter_trashed: Number(index % 5 === 0),
    restore_allowed: index % 5 === 0 ? 0 : 1,
    purge_allowed: index % 8 === 0 ? 0 : 1,
    restore_block_reason: index % 5 === 0 ? "restore the chapter first" : null,
    purge_block_reason: index % 8 === 0 ? "purge blocked by downstream runtime" : null,
  };
}

async function mountAuthorTrashView({ chapterCount = 18, sceneCount = 24 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const store = useAuthorTrashStore();
  store.chapters = Array.from({ length: chapterCount }, (_, index) => createTrashChapter(index + 1));
  store.scenes = Array.from({ length: sceneCount }, (_, index) => createTrashScene(index + 1));
  store.chapterListVersion = 1;
  store.sceneListVersion = 1;
  store.loaded = true;
  store.stale = false;
  store.loading = false;
  store.actionId = "";
  store.error = "";
  store.ensureLoaded = vi.fn(async () => {});

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [
        h(AuthorTrashView, {
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

- [ ] **Step 3: Add the failing Author Trash runtime test**

Append this block to `frontend/tests/scrollPerformance.spec.js` after the author workspace scroll performance describe:

```js
describe("author trash scroll performance integration", () => {
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

  it("virtualizes trash chapters and scenes while pinning checked rows after scroll", async () => {
    const mounted = await mountAuthorTrashView({ chapterCount: 18, sceneCount: 24 });

    try {
      const chapterVirtualList = mounted.container.querySelector('[data-testid="author-trash-chapter-virtual-list"]');
      const sceneVirtualList = mounted.container.querySelector('[data-testid="author-trash-scene-virtual-list"]');

      expect(chapterVirtualList).not.toBeNull();
      expect(sceneVirtualList).not.toBeNull();
      expect(chapterVirtualList.style.maxHeight).toBe("560px");
      expect(sceneVirtualList.style.maxHeight).toBe("560px");

      let chapterRows = mounted.container.querySelectorAll('[data-testid^="author-trash-chapter-row-"]');
      let sceneRows = mounted.container.querySelectorAll('[data-testid^="author-trash-scene-row-"]');
      expect(chapterRows.length).toBeGreaterThan(0);
      expect(chapterRows.length).toBeLessThan(mounted.store.chapters.length);
      expect(sceneRows.length).toBeGreaterThan(0);
      expect(sceneRows.length).toBeLessThan(mounted.store.scenes.length);

      mounted.container.querySelector('[data-testid="author-trash-chapter-select-TRASH_CH001"]').click();
      mounted.container.querySelector('[data-testid="author-trash-scene-select-TRASH_SC001"]').click();
      await flushUi();

      expect(mounted.container.querySelector('[data-testid="author-trash-restore-chapters-button"]').disabled).toBe(false);
      expect(mounted.container.querySelector('[data-testid="author-trash-purge-chapters-button"]').disabled).toBe(false);
      expect(mounted.container.querySelector('[data-testid="author-trash-restore-scenes-button"]').disabled).toBe(false);
      expect(mounted.container.querySelector('[data-testid="author-trash-purge-scenes-button"]').disabled).toBe(false);

      chapterVirtualList.scrollTop = 10000;
      chapterVirtualList.dispatchEvent(new Event("scroll"));
      sceneVirtualList.scrollTop = 10000;
      sceneVirtualList.dispatchEvent(new Event("scroll"));
      await flushUi();

      chapterRows = mounted.container.querySelectorAll('[data-testid^="author-trash-chapter-row-"]');
      sceneRows = mounted.container.querySelectorAll('[data-testid^="author-trash-scene-row-"]');
      expect(chapterRows.length).toBeGreaterThan(0);
      expect(chapterRows.length).toBeLessThan(mounted.store.chapters.length);
      expect(sceneRows.length).toBeGreaterThan(0);
      expect(sceneRows.length).toBeLessThan(mounted.store.scenes.length);

      const checkedChapter = mounted.container.querySelector('[data-testid="author-trash-chapter-select-TRASH_CH001"]');
      const checkedScene = mounted.container.querySelector('[data-testid="author-trash-scene-select-TRASH_SC001"]');
      expect(checkedChapter).not.toBeNull();
      expect(checkedScene).not.toBeNull();
      expect(checkedChapter.checked).toBe(true);
      expect(checkedScene.checked).toBe(true);
    } finally {
      mounted.unmount();
    }
  });
});
```

- [ ] **Step 4: Add failing source guardrails**

In `frontend/tests/smoothness.spec.js`, add this test inside `describe("shell smoothness architecture", () => { ... })` after the shared virtual/progressive list primitive test:

```js
  it("routes author trash chapter and scene lists through shared virtual list drivers", () => {
    const trashSource = readFileSync(new URL("../src/views/AuthorTrashView.vue", import.meta.url), "utf8");
    const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");

    expect(trashSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(trashSource).toContain('test-id="author-trash-chapter-virtual-list"');
    expect(trashSource).toContain('test-id="author-trash-scene-virtual-list"');
    expect(trashSource).toContain(":pinned-keys=\"pinnedChapterKeys\"");
    expect(trashSource).toContain(":pinned-keys=\"pinnedSceneKeys\"");
    expect(trashSource).not.toContain('v-for="chapter in chapters"');
    expect(trashSource).not.toContain('v-for="scene in scenes"');
    expect(styles).toContain(".trash-list .virtual-list-row");
  });
```

- [ ] **Step 5: Add E2E virtual-list anchors to the existing Author Trash path**

In `frontend/tests/e2e/author-trash.spec.js`, after:

```js
  await expect(authorTrashView).toContainText("作者回收站");
```

add:

```js
  await expect(page.getByTestId("author-trash-scene-virtual-list")).toBeVisible();
```

After the later second `await page.getByTestId("nav-trash").click();`, before the first row assertion, add:

```js
  await expect(page.getByTestId("author-trash-chapter-virtual-list")).toBeVisible();
  await expect(page.getByTestId("author-trash-scene-virtual-list")).toBeVisible();
```

- [ ] **Step 6: Run targeted tests and verify the expected red failure**

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/authorWorkspace.spec.js
```

Expected: FAIL because `AuthorTrashView.vue` does not yet import `VirtualList`, does not expose `author-trash-chapter-virtual-list` / `author-trash-scene-virtual-list`, and still renders chapter/scene rows with full-list `v-for` loops.

- [ ] **Step 7: Commit the failing tests**

```bash
git add frontend/tests/scrollPerformance.spec.js frontend/tests/smoothness.spec.js frontend/tests/e2e/author-trash.spec.js
git commit -m "test(author-trash): cover virtual trash lists"
```

---

## Task 2: Virtualize Author Trash Lists

**Files:**
- Modify: `frontend/src/views/AuthorTrashView.vue`
- Modify: `frontend/src/styles/app.css`

- [ ] **Step 1: Import `VirtualList`**

In `frontend/src/views/AuthorTrashView.vue`, change the top imports from:

```vue
import PanelShell from "../components/PanelShell.vue";
import { useAuthorTrashStore } from "../stores/authorTrash";
```

to:

```vue
import PanelShell from "../components/PanelShell.vue";
import VirtualList from "../components/VirtualList.vue";
import { useAuthorTrashStore } from "../stores/authorTrash";
```

- [ ] **Step 2: Add pinned key computed values**

After the existing `scenes` computed in `frontend/src/views/AuthorTrashView.vue`, add:

```js
const pinnedChapterKeys = computed(() => [...selectedChapterIds.value]);
const pinnedSceneKeys = computed(() => [...selectedSceneIds.value]);
```

- [ ] **Step 3: Replace the chapter trash list wrapper**

Replace the chapter list opening:

```vue
          <div v-else class="trash-list">
            <article
              v-for="chapter in chapters"
              :key="chapter.chapter_id"
              class="trash-row"
              :class="{ disabled: !chapterSelectable(chapter) }"
              :data-testid="`author-trash-chapter-row-${chapter.chapter_id}`"
            >
```

with:

```vue
          <VirtualList
            v-else
            class="trash-list"
            :items="chapters"
            item-key="chapter_id"
            :estimated-item-height="180"
            :threshold="8"
            :viewport-height="560"
            :pinned-keys="pinnedChapterKeys"
            test-id="author-trash-chapter-virtual-list"
          >
            <template #default="{ item: chapter }">
              <article
                class="trash-row"
                :class="{ disabled: !chapterSelectable(chapter) }"
                :data-testid="`author-trash-chapter-row-${chapter.chapter_id}`"
              >
```

Keep the chapter row body exactly as it is. The body starts with:

```vue
              <label class="author-select-cell" :for="`trash-chapter-${chapter.chapter_id}`">
```

and ends after:

```vue
                </div>
              </div>
```

After the chapter row `</article>`, replace the original chapter list closing:

```vue
          </div>
```

with:

```vue
            </template>
          </VirtualList>
```

- [ ] **Step 4: Replace the scene trash list wrapper**

Replace the scene list opening:

```vue
          <div v-else class="trash-list">
            <article
              v-for="scene in scenes"
              :key="scene.scene_id"
              class="trash-row"
              :class="{ disabled: !sceneSelectable(scene) }"
              :data-testid="`author-trash-scene-row-${scene.scene_id}`"
            >
```

with:

```vue
          <VirtualList
            v-else
            class="trash-list"
            :items="scenes"
            item-key="scene_id"
            :estimated-item-height="180"
            :threshold="8"
            :viewport-height="560"
            :pinned-keys="pinnedSceneKeys"
            test-id="author-trash-scene-virtual-list"
          >
            <template #default="{ item: scene }">
              <article
                class="trash-row"
                :class="{ disabled: !sceneSelectable(scene) }"
                :data-testid="`author-trash-scene-row-${scene.scene_id}`"
              >
```

Keep the scene row body exactly as it is. The body starts with:

```vue
              <label class="author-select-cell" :for="`trash-scene-${scene.scene_id}`">
```

and ends after:

```vue
                </div>
              </div>
```

After the scene row `</article>`, replace the original scene list closing:

```vue
          </div>
```

with:

```vue
            </template>
          </VirtualList>
```

- [ ] **Step 5: Preserve virtual trash row spacing**

In `frontend/src/styles/app.css`, extend the existing virtual-row spacing selector from:

```css
.review-list .virtual-list-row,
.knowledge-list .virtual-list-row,
.author-list .virtual-list-row,
.author-scene-list .virtual-list-row,
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
.receipt-list .virtual-list-row,
.job-table .virtual-list-row {
  padding-bottom: 1rem;
}
```

- [ ] **Step 6: Run targeted Vitest regressions**

Run:

```bash
npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/authorWorkspace.spec.js
```

Expected: PASS. The Author Trash runtime test should show both virtual lists, row counts below full source arrays, and checked rows still mounted after scroll.

- [ ] **Step 7: Commit the implementation**

```bash
git add frontend/src/views/AuthorTrashView.vue frontend/src/styles/app.css
git commit -m "perf(author-trash): virtualize trash lists"
```

---

## Task 3: Verify Author Trash E2E And Full Frontend Health

**Files:**
- Test: `frontend/tests/e2e/author-trash.spec.js`
- Test: full frontend suite

- [ ] **Step 1: Run the Author Trash E2E regression**

Run:

```bash
npx playwright test tests/e2e/author-trash.spec.js
```

Expected: PASS. The existing trash lifecycle should still move scenes and chapters into trash, restore scenes, purge chapters, and observe the new virtual-list anchors while rows exist.

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

Expected: only the Author Trash spec, plan, view, style, and test files are included in the branch history.

---

## Spec Coverage Check

- Chapter list virtualization is covered by Task 1 runtime/source tests and Task 2 `VirtualList` implementation.
- Scene list virtualization is covered by Task 1 runtime/source tests and Task 2 `VirtualList` implementation.
- Selected row pinning is covered by the Task 1 runtime scroll test and Task 2 `pinnedChapterKeys` / `pinnedSceneKeys`.
- Row spacing is covered by the Task 1 source guard and Task 2 CSS selector update.
- Existing restore/purge behavior is covered by Task 3 Author Trash E2E and full frontend tests.

## Placeholder Check

- The plan contains no deferred implementation tasks.
- Every code-changing step has exact target files and concrete code or exact move boundaries.
- Every verification step includes a command and expected outcome.

## Type And Naming Check

- `pinnedChapterKeys`, `pinnedSceneKeys`, `author-trash-chapter-virtual-list`, and `author-trash-scene-virtual-list` are named consistently across tests and implementation.
- Runtime fixture fields match `AuthorTrashView.vue`: `chapter_id`, `scene_id`, `restore_allowed`, `purge_allowed`, `restore_block_reason`, `purge_block_reason`, `trashed_at`, and `trashed_by`.
