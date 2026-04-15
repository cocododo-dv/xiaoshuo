# Frontend Scroll and Expand Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build shared progressive and virtualized list primitives, then integrate them into `Review Inbox`, `Index Console`, and `Author Workspace` to reduce scroll and expand jank without breaking focus behavior.

**Architecture:** Extract range calculation and batching logic into testable `frontend/src/lib` modules, wrap them in `ProgressiveList.vue` and `VirtualList.vue`, and integrate those wrappers into the read-heavy list surfaces first. Keep edit forms as normal DOM, use pinned keys for focused items, and bias virtualization toward stability with conservative overscan and small-list fallback.

**Tech Stack:** Vue 3 SFCs, Pinia, Vitest, jsdom, Playwright, Vite.

---

## File Map

**Create**

- `frontend/src/lib/virtualList.js`
- `frontend/src/lib/progressiveList.js`
- `frontend/src/components/VirtualList.vue`
- `frontend/src/components/ProgressiveList.vue`
- `frontend/tests/virtualList.spec.js`
- `frontend/tests/progressiveList.spec.js`
- `frontend/tests/scrollPerformance.spec.js`

**Modify**

- `frontend/src/views/ReviewInboxView.vue`
- `frontend/src/components/HumanReviewDrawer.vue`
- `frontend/src/views/IndexConsoleView.vue`
- `frontend/src/components/TargetActivityGroupCard.vue`
- `frontend/src/views/AuthorWorkspaceView.vue`
- `frontend/src/styles/app.css`
- `frontend/tests/smoothness.spec.js`
- `frontend/tests/lightKeepAlive.spec.js`
- `frontend/tests/authorWorkspace.spec.js`
- `frontend/tests/e2e/smoothness-navigation.spec.js`

**Why these files**

- `frontend/src/lib/virtualList.js` owns range calculation, pinned-key retention, height bookkeeping, and direct-render fallback.
- `frontend/src/lib/progressiveList.js` owns first-batch rendering and `requestAnimationFrame` batch growth rules.
- `frontend/src/components/VirtualList.vue` turns the virtual range state into a reusable SFC slot API.
- `frontend/src/components/ProgressiveList.vue` turns progressive batch state into a reusable SFC slot API.
- `frontend/src/views/ReviewInboxView.vue` is the first flat-card virtualization target.
- `frontend/src/components/HumanReviewDrawer.vue` is the first expand-heavy progressive-render target.
- `frontend/src/views/IndexConsoleView.vue` is the heaviest long-list read surface and needs shared list primitives across jobs, timelines, and target group summaries.
- `frontend/src/components/TargetActivityGroupCard.vue` is where nested target-group activity items should use progressive inner rendering without adding deep nested virtualization immediately.
- `frontend/src/views/AuthorWorkspaceView.vue` needs outer-list virtualization while keeping edit forms stable.
- `frontend/src/styles/app.css` needs shared container, spacer, and containment styles for the new list primitives.
- frontend tests must capture pure helper behavior, source integration, and E2E interaction survival.

---

### Task 1: Build the Virtual Window Helper

**Files:**
- Create: `frontend/src/lib/virtualList.js`
- Test: `frontend/tests/virtualList.spec.js`

- [ ] **Step 1: Write the failing test**

```js
import { describe, expect, it } from "vitest";

import {
  buildVirtualWindow,
  resolvePinnedIndexes,
  resolveVisibleIndexes,
} from "../src/lib/virtualList";

describe("resolvePinnedIndexes", () => {
  it("maps pinned keys to stable sorted indexes", () => {
    const items = [
      { id: "row-0" },
      { id: "row-1" },
      { id: "row-2" },
      { id: "row-3" },
    ];

    expect(resolvePinnedIndexes(items, "id", ["row-3", "row-1", "missing"])).toEqual([1, 3]);
  });
});

describe("resolveVisibleIndexes", () => {
  it("expands the visible window with overscan", () => {
    const items = Array.from({ length: 20 }, (_, index) => ({ id: `row-${index}` }));

    expect(
      resolveVisibleIndexes({
        items,
        viewportHeight: 150,
        scrollTop: 150,
        estimatedItemHeight: 50,
        overscan: 1,
        measuredHeights: {},
      }),
    ).toEqual({ startIndex: 2, endIndex: 7 });
  });
});

describe("buildVirtualWindow", () => {
  it("falls back to direct rendering under the configured threshold", () => {
    const items = Array.from({ length: 6 }, (_, index) => ({ id: `row-${index}` }));

    const state = buildVirtualWindow({
      items,
      itemKey: "id",
      viewportHeight: 240,
      scrollTop: 0,
      estimatedItemHeight: 48,
      overscan: 2,
      threshold: 12,
      measuredHeights: {},
      pinnedKeys: [],
    });

    expect(state.virtualized).toBe(false);
    expect(state.visibleItems.map((item) => item.id)).toEqual(items.map((item) => item.id));
    expect(state.topSpacerHeight).toBe(0);
    expect(state.bottomSpacerHeight).toBe(0);
  });

  it("keeps pinned rows mounted even when they fall outside the current viewport", () => {
    const items = Array.from({ length: 40 }, (_, index) => ({ id: `row-${index}` }));

    const state = buildVirtualWindow({
      items,
      itemKey: "id",
      viewportHeight: 180,
      scrollTop: 18 * 12,
      estimatedItemHeight: 18,
      overscan: 1,
      threshold: 10,
      measuredHeights: {},
      pinnedKeys: ["row-2", "row-15"],
    });

    expect(state.virtualized).toBe(true);
    expect(state.visibleKeys).toContain("row-2");
    expect(state.visibleKeys).toContain("row-15");
    expect(state.topSpacerHeight).toBeGreaterThanOrEqual(0);
    expect(state.bottomSpacerHeight).toBeGreaterThanOrEqual(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm exec vitest run tests/virtualList.spec.js`

Expected: FAIL with `Cannot find module '../src/lib/virtualList'` or missing export errors.

- [ ] **Step 3: Write minimal implementation**

```js
function resolveItemKey(item, itemKey) {
  if (typeof itemKey === "function") {
    return itemKey(item);
  }
  return item?.[itemKey];
}

function resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight) {
  const item = items[index];
  const key = resolveItemKey(item, itemKey);
  return measuredHeights[key] || estimatedItemHeight;
}

export function resolvePinnedIndexes(items, itemKey, pinnedKeys = []) {
  const pinned = new Set(pinnedKeys.filter(Boolean));
  return items
    .map((item, index) => ({ index, key: resolveItemKey(item, itemKey) }))
    .filter((entry) => pinned.has(entry.key))
    .map((entry) => entry.index)
    .sort((left, right) => left - right);
}

export function resolveVisibleIndexes({
  items,
  viewportHeight,
  scrollTop,
  estimatedItemHeight,
  overscan,
  measuredHeights,
}) {
  if (!items.length) {
    return { startIndex: 0, endIndex: 0 };
  }

  const rawStart = Math.max(Math.floor(scrollTop / estimatedItemHeight) - overscan, 0);
  const rawCount = Math.ceil(viewportHeight / estimatedItemHeight) + overscan * 2;
  const rawEnd = Math.min(rawStart + rawCount, items.length);

  return {
    startIndex: rawStart,
    endIndex: rawEnd,
  };
}

export function buildVirtualWindow({
  items,
  itemKey,
  viewportHeight,
  scrollTop,
  estimatedItemHeight,
  overscan = 2,
  threshold = 20,
  measuredHeights = {},
  pinnedKeys = [],
}) {
  if (items.length <= threshold) {
    return {
      virtualized: false,
      visibleItems: items,
      visibleKeys: items.map((item) => resolveItemKey(item, itemKey)),
      topSpacerHeight: 0,
      bottomSpacerHeight: 0,
    };
  }

  const { startIndex, endIndex } = resolveVisibleIndexes({
    items,
    viewportHeight,
    scrollTop,
    estimatedItemHeight,
    overscan,
    measuredHeights,
  });
  const pinnedIndexes = resolvePinnedIndexes(items, itemKey, pinnedKeys);
  const indexes = new Set([
    ...Array.from({ length: endIndex - startIndex }, (_, offset) => startIndex + offset),
    ...pinnedIndexes,
  ]);
  const orderedIndexes = [...indexes].sort((left, right) => left - right);
  const visibleItems = orderedIndexes.map((index) => items[index]);
  const firstRenderedIndex = orderedIndexes[0] || 0;
  const lastRenderedIndex = orderedIndexes[orderedIndexes.length - 1] || 0;

  let topSpacerHeight = 0;
  for (let index = 0; index < firstRenderedIndex; index += 1) {
    topSpacerHeight += resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight);
  }

  let bottomSpacerHeight = 0;
  for (let index = lastRenderedIndex + 1; index < items.length; index += 1) {
    bottomSpacerHeight += resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight);
  }

  return {
    virtualized: true,
    visibleItems,
    visibleKeys: visibleItems.map((item) => resolveItemKey(item, itemKey)),
    topSpacerHeight,
    bottomSpacerHeight,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm exec vitest run tests/virtualList.spec.js`

Expected: PASS with `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/virtualList.js frontend/tests/virtualList.spec.js
git commit -m "feat(frontend): add virtual window helper"
```

### Task 2: Build the Progressive Batch Helper

**Files:**
- Create: `frontend/src/lib/progressiveList.js`
- Test: `frontend/tests/progressiveList.spec.js`

- [ ] **Step 1: Write the failing test**

```js
import { describe, expect, it } from "vitest";

import {
  buildProgressivePlan,
  nextProgressiveCount,
  shouldProgressivelyRender,
} from "../src/lib/progressiveList";

describe("shouldProgressivelyRender", () => {
  it("skips batching when disabled", () => {
    expect(shouldProgressivelyRender({ enabled: false, itemCount: 40, threshold: 8 })).toBe(false);
  });

  it("skips batching under the threshold", () => {
    expect(shouldProgressivelyRender({ enabled: true, itemCount: 6, threshold: 8 })).toBe(false);
  });
});

describe("nextProgressiveCount", () => {
  it("grows the rendered item count in fixed batches", () => {
    expect(nextProgressiveCount({ renderedCount: 6, itemCount: 20, batchSize: 5 })).toBe(11);
    expect(nextProgressiveCount({ renderedCount: 18, itemCount: 20, batchSize: 5 })).toBe(20);
  });
});

describe("buildProgressivePlan", () => {
  it("renders the first batch immediately and tracks remaining work", () => {
    const state = buildProgressivePlan({
      items: Array.from({ length: 18 }, (_, index) => ({ id: `row-${index}` })),
      enabled: true,
      initialCount: 5,
      batchSize: 4,
      threshold: 8,
    });

    expect(state.renderedItems).toHaveLength(5);
    expect(state.renderedCount).toBe(5);
    expect(state.pending).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm exec vitest run tests/progressiveList.spec.js`

Expected: FAIL with `Cannot find module '../src/lib/progressiveList'` or missing export errors.

- [ ] **Step 3: Write minimal implementation**

```js
export function shouldProgressivelyRender({ enabled, itemCount, threshold = 12 }) {
  return Boolean(enabled) && itemCount > threshold;
}

export function nextProgressiveCount({ renderedCount, itemCount, batchSize }) {
  return Math.min(renderedCount + batchSize, itemCount);
}

export function buildProgressivePlan({
  items,
  enabled,
  initialCount = 8,
  batchSize = 8,
  threshold = 12,
}) {
  if (!shouldProgressivelyRender({ enabled, itemCount: items.length, threshold })) {
    return {
      renderedItems: items,
      renderedCount: items.length,
      pending: false,
      batchSize,
      threshold,
    };
  }

  const renderedCount = Math.min(initialCount, items.length);

  return {
    renderedItems: items.slice(0, renderedCount),
    renderedCount,
    pending: renderedCount < items.length,
    batchSize,
    threshold,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm exec vitest run tests/progressiveList.spec.js`

Expected: PASS with `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/progressiveList.js frontend/tests/progressiveList.spec.js
git commit -m "feat(frontend): add progressive list helper"
```

### Task 3: Add Shared List Components and Wire Review Inbox

**Files:**
- Create: `frontend/src/components/VirtualList.vue`
- Create: `frontend/src/components/ProgressiveList.vue`
- Modify: `frontend/src/views/ReviewInboxView.vue`
- Modify: `frontend/src/components/HumanReviewDrawer.vue`
- Modify: `frontend/tests/scrollPerformance.spec.js`

- [ ] **Step 1: Write the failing regression test**

```js
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("review list performance integration", () => {
  it("virtualizes review cards and progressively mounts human review details", () => {
    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const drawerSource = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");

    expect(reviewSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(reviewSource).toContain("<VirtualList");
    expect(drawerSource).toContain('import ProgressiveList from "./ProgressiveList.vue"');
    expect(drawerSource).toContain("<ProgressiveList");
    expect(drawerSource).toContain("data-testid=\"human-review-progressive-list\"");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm exec vitest run tests/scrollPerformance.spec.js`

Expected: FAIL because neither component import nor list markup exists yet.

- [ ] **Step 3: Write minimal implementation**

`frontend/src/components/ProgressiveList.vue`

```vue
<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";

import { buildProgressivePlan, nextProgressiveCount } from "../lib/progressiveList";

const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  enabled: {
    type: Boolean,
    default: true,
  },
  initialCount: {
    type: Number,
    default: 8,
  },
  batchSize: {
    type: Number,
    default: 8,
  },
  threshold: {
    type: Number,
    default: 12,
  },
  testId: {
    type: String,
    default: "",
  },
});

const renderedCount = ref(0);
let frameId = 0;

function cancelFrame() {
  if (!frameId || typeof cancelAnimationFrame !== "function") {
    frameId = 0;
    return;
  }
  cancelAnimationFrame(frameId);
  frameId = 0;
}

function scheduleMore() {
  cancelFrame();
  if (renderedCount.value >= props.items.length || typeof requestAnimationFrame !== "function") {
    return;
  }
  frameId = requestAnimationFrame(() => {
    renderedCount.value = nextProgressiveCount({
      renderedCount: renderedCount.value,
      itemCount: props.items.length,
      batchSize: props.batchSize,
    });
    if (renderedCount.value < props.items.length) {
      scheduleMore();
    }
  });
}

watch(
  () => [props.items, props.enabled, props.initialCount, props.batchSize, props.threshold],
  () => {
    const plan = buildProgressivePlan({
      items: props.items,
      enabled: props.enabled,
      initialCount: props.initialCount,
      batchSize: props.batchSize,
      threshold: props.threshold,
    });
    renderedCount.value = plan.renderedCount;
    if (plan.pending) {
      scheduleMore();
    } else {
      cancelFrame();
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  cancelFrame();
});

const renderedItems = computed(() => props.items.slice(0, renderedCount.value));
</script>

<template>
  <div class="progressive-list" :data-testid="props.testId || undefined">
    <slot :items="renderedItems" :rendered-count="renderedCount" :total-count="props.items.length" />
  </div>
</template>
```

`frontend/src/components/VirtualList.vue`

```vue
<script setup>
import { computed, ref } from "vue";

import { buildVirtualWindow } from "../lib/virtualList";

const props = defineProps({
  items: {
    type: Array,
    default: () => [],
  },
  itemKey: {
    type: [String, Function],
    required: true,
  },
  estimatedItemHeight: {
    type: Number,
    default: 72,
  },
  overscan: {
    type: Number,
    default: 3,
  },
  threshold: {
    type: Number,
    default: 20,
  },
  pinnedKeys: {
    type: Array,
    default: () => [],
  },
  testId: {
    type: String,
    default: "",
  },
  viewportHeight: {
    type: Number,
    default: 520,
  },
});

const scrollTop = ref(0);
const measuredHeights = ref({});

const windowState = computed(() =>
  buildVirtualWindow({
    items: props.items,
    itemKey: props.itemKey,
    viewportHeight: props.viewportHeight,
    scrollTop: scrollTop.value,
    estimatedItemHeight: props.estimatedItemHeight,
    overscan: props.overscan,
    threshold: props.threshold,
    measuredHeights: measuredHeights.value,
    pinnedKeys: props.pinnedKeys,
  }),
);

function resolveKey(item) {
  return typeof props.itemKey === "function" ? props.itemKey(item) : item?.[props.itemKey];
}

function updateHeight(key, event) {
  const height = event?.target?.offsetHeight;
  if (!key || !height) {
    return;
  }
  measuredHeights.value = { ...measuredHeights.value, [key]: height };
}
</script>

<template>
  <div
    class="virtual-list"
    :data-testid="props.testId || undefined"
    @scroll="scrollTop = $event.target.scrollTop"
  >
    <div class="virtual-list-spacer" :style="{ height: `${windowState.topSpacerHeight}px` }" />
    <div
      v-for="item in windowState.visibleItems"
      :key="resolveKey(item)"
      class="virtual-list-row"
      @vue:mounted="updateHeight(resolveKey(item), $event)"
    >
      <slot :item="item" :virtualized="windowState.virtualized" />
    </div>
    <div class="virtual-list-spacer" :style="{ height: `${windowState.bottomSpacerHeight}px` }" />
  </div>
</template>
```

`frontend/src/views/ReviewInboxView.vue`

```vue
<script setup>
import VirtualList from "../components/VirtualList.vue";

const pinnedReviewKeys = computed(() => (focusTargetType.value === "review_item" ? [focusTargetId.value] : []));
</script>

<template>
  <div v-if="!reviewInbox.items.length" class="empty">当前没有待处理审核项。</div>
  <VirtualList
    v-else
    class="review-list"
    test-id="review-virtual-list"
    :items="prioritizedReviewItems"
    item-key="review_id"
    :estimated-item-height="248"
    :pinned-keys="pinnedReviewKeys"
    :threshold="10"
    :viewport-height="640"
  >
    <template #default="{ item }">
      <ReviewCard
        :key="item.review_id"
        :item="item"
        :highlighted="focusedReviewId(item.review_id)"
        :source-action-label="reviewSourceActionLabel(item.review_id)"
        :loading="reviewInbox.actionId === item.review_id"
        @approve="approve"
        @release="release"
        @open-target="handleReviewOpenTarget"
      />
    </template>
  </VirtualList>
</template>
```

`frontend/src/components/HumanReviewDrawer.vue`

```vue
<script setup>
import ProgressiveList from "./ProgressiveList.vue";
</script>

<template>
  <ProgressiveList
    test-id="human-review-progressive-list"
    :items="props.items"
    :enabled="props.items.length > 6"
    :initial-count="6"
    :batch-size="4"
    :threshold="6"
  >
    <template #default="{ items }">
      <article
        v-for="item in items"
        :key="item.event_id || item.status"
        class="paper mini"
        :data-testid="`human-review-event-${item.event_id}`"
        :class="{ 'focused-card': props.focusEventId && item.event_id === props.focusEventId }"
      >
      </article>
    </template>
  </ProgressiveList>
</template>
```

Keep the current `<article>` body from `frontend/src/components/HumanReviewDrawer.vue` verbatim; the only change in this task is that the outer list now iterates over the slot-provided `items`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js`

Expected: PASS with the new review integration assertions and existing smoothness assertions still green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ProgressiveList.vue frontend/src/components/VirtualList.vue frontend/src/views/ReviewInboxView.vue frontend/src/components/HumanReviewDrawer.vue frontend/tests/scrollPerformance.spec.js
git commit -m "feat(frontend): virtualize review lists"
```

### Task 4: Wire Index Console to the Shared List Primitives

**Files:**
- Modify: `frontend/src/views/IndexConsoleView.vue`
- Modify: `frontend/src/components/TargetActivityGroupCard.vue`
- Modify: `frontend/tests/smoothness.spec.js`
- Modify: `frontend/tests/scrollPerformance.spec.js`

- [ ] **Step 1: Write the failing regression test**

```js
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("index console performance integration", () => {
  it("routes jobs, timelines, and target groups through shared list primitives", () => {
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const groupSource = readFileSync(new URL("../src/components/TargetActivityGroupCard.vue", import.meta.url), "utf8");

    expect(indexSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(indexSource).toContain('test-id="index-jobs-virtual-list"');
    expect(indexSource).toContain('test-id="index-recovery-virtual-list"');
    expect(indexSource).toContain('test-id="index-target-groups-virtual-list"');
    expect(groupSource).toContain('import ProgressiveList from "./ProgressiveList.vue"');
    expect(groupSource).toContain('data-testid="target-group-progressive-list"');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm exec vitest run tests/scrollPerformance.spec.js`

Expected: FAIL on the new index integration assertions.

- [ ] **Step 3: Write minimal implementation**

`frontend/src/views/IndexConsoleView.vue`

```vue
<script setup>
import VirtualList from "../components/VirtualList.vue";

const pinnedJobKeys = computed(() =>
  ["verify_job", "reindex_job"].includes(focusTargetType.value) ? [focusTargetId.value] : [],
);
const pinnedTargetGroupKeys = computed(() => (focusTargetRef.value ? [focusTargetRef.value] : []));
const recoveryItems = computed(() => indexConsole.recoveryTimelineItems);
const systemItems = computed(() => indexConsole.systemRuntimeTimelineItems);
const operatorItems = computed(() => indexConsole.operatorActionTimelineItems);
</script>

<template>
  <VirtualList
    v-if="indexConsole.jobs.length"
    test-id="index-jobs-virtual-list"
    :items="prioritizedJobs"
    item-key="job_id"
    :estimated-item-height="188"
    :threshold="8"
    :pinned-keys="pinnedJobKeys"
    :viewport-height="560"
  >
    <template #default="{ item }">
      <div
        class="job-row"
        :data-testid="`verify-job-${item.job_id}`"
        :class="{ 'focused-card': ['verify_job', 'reindex_job'].includes(focusTargetType) && focusTargetId === item.job_id }"
      >
      </div>
    </template>
  </VirtualList>

  <ActivitySectionCard title="恢复时间线" :expanded="expandedSections.recovery_timeline" @toggle="toggleSection('recovery_timeline')">
    <VirtualList
      test-id="index-recovery-virtual-list"
      :items="recoveryItems"
      :item-key="(item) => item.event_id || activityItemKey('recovery_timeline', item)"
      :estimated-item-height="168"
      :threshold="8"
      :pinned-keys="[focusedSourceId]"
      :viewport-height="520"
    >
      <template #default="{ item }">
        <li
          :data-activity-key="activityItemKey('recovery_timeline', item)"
          :class="{ 'focused-card': isFocusedSource('recovery_timeline', item.event_id) || isFocusedSource('recovery_receipt', item.event_id) }"
        >
        </li>
      </template>
    </VirtualList>
  </ActivitySectionCard>

  <ActivitySectionCard title="目标活动组" :expanded="expandedSections.target_groups" @toggle="toggleSection('target_groups')">
    <VirtualList
      test-id="index-target-groups-virtual-list"
      :items="prioritizedTargetGroups"
      :item-key="(group) => group.target.target_ref"
      :estimated-item-height="172"
      :threshold="6"
      :pinned-keys="pinnedTargetGroupKeys"
      :viewport-height="520"
    >
      <template #default="{ item: group }">
        <TargetActivityGroupCard
          :group="group"
          :expanded="activeTargetGroupRef === group.target.target_ref"
          :loading="groupLoading(group.target.target_ref)"
          :items="groupItems(group.target.target_ref)"
          :pagination="indexConsole.targetGroupPagination(group.target.target_ref)"
          :can-previous="groupCanPrevious(group.target.target_ref)"
          :can-next="groupCanNext(group.target.target_ref)"
          :focused="focusTargetRef === group.target.target_ref"
          :focused-activity-key="focusedActivityKey"
          :source-linked-activity-key="sourceLinkedActivityKey"
          @toggle="toggleTargetGroup"
          @open-target="jumpToTarget"
          @previous="previousGroupPage"
          @next="nextGroupPage"
        />
      </template>
    </VirtualList>
  </ActivitySectionCard>
</template>
```

`frontend/src/components/TargetActivityGroupCard.vue`

```vue
<script setup>
import ProgressiveList from "./ProgressiveList.vue";
</script>

<template>
  <div v-if="props.expanded" class="receipt-detail">
    <div v-if="props.loading" class="empty">正在加载活动详情...</div>
    <ProgressiveList
      v-else-if="props.items.length"
      test-id="target-group-progressive-list"
      :items="props.items"
      :enabled="props.items.length > 8"
      :initial-count="8"
      :batch-size="6"
      :threshold="8"
    >
      <template #default="{ items }">
        <ul class="receipt-list">
          <li
            v-for="item in items"
            :key="item.activity_key"
            :data-activity-key="item.activity_key"
            :data-testid="`target-activity-item-${item.activity_key}`"
            :class="{
              'focused-card': isHighlighted(item),
              'focused-activity-item': item.activity_key === props.focusedActivityKey,
            }"
          >
          </li>
        </ul>
      </template>
    </ProgressiveList>
    <p v-else class="muted target-group-empty">这个目标下还没有活动记录。</p>
  </div>
</template>
```

Keep the current job diagnostics, recovery-row content, and target-group activity markup exactly as it exists today; this task only changes the list driver so those rows render through `VirtualList` or `ProgressiveList`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js tests/lightKeepAlive.spec.js`

Expected: PASS with index console source assertions and existing shell guards unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/IndexConsoleView.vue frontend/src/components/TargetActivityGroupCard.vue frontend/tests/scrollPerformance.spec.js frontend/tests/smoothness.spec.js frontend/tests/lightKeepAlive.spec.js
git commit -m "feat(frontend): virtualize index console lists"
```

### Task 5: Wire Author Workspace Lists Without Virtualizing the Forms

**Files:**
- Modify: `frontend/src/views/AuthorWorkspaceView.vue`
- Modify: `frontend/tests/authorWorkspace.spec.js`
- Modify: `frontend/tests/scrollPerformance.spec.js`

- [ ] **Step 1: Write the failing regression test**

```js
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("author workspace performance integration", () => {
  it("virtualizes chapter and scene lists while keeping the edit panes outside the virtual list", () => {
    const source = readFileSync(new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url), "utf8");

    expect(source).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(source).toContain('test-id="author-chapter-virtual-list"');
    expect(source).toContain('test-id="author-scene-virtual-list"');
    expect(source).toContain("data-testid=\"author-chapter-form\"");
    expect(source).toContain("data-testid=\"author-scene-form\"");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm exec vitest run tests/scrollPerformance.spec.js tests/authorWorkspace.spec.js`

Expected: FAIL because the author workspace does not yet import or render `VirtualList`.

- [ ] **Step 3: Write minimal implementation**

`frontend/src/views/AuthorWorkspaceView.vue`

```vue
<script setup>
import VirtualList from "../components/VirtualList.vue";

const pinnedChapterKeys = computed(() => (authorWorkspace.selectedChapterId ? [authorWorkspace.selectedChapterId] : []));
const pinnedSceneKeys = computed(() => (selectedSceneId.value ? [selectedSceneId.value] : []));
</script>

<template>
  <div v-else class="author-layout">
    <article class="paper author-sidebar">
      <div v-if="!chapters.length" class="empty">当前还没有活跃章节。</div>
      <VirtualList
        v-else
        test-id="author-chapter-virtual-list"
        :items="chapters"
        item-key="chapter_id"
        :estimated-item-height="128"
        :threshold="8"
        :pinned-keys="pinnedChapterKeys"
        :viewport-height="520"
      >
        <template #default="{ item: chapter }">
          <article class="author-list-row" :class="{ disabled: !isChapterTrashAllowed(chapter) }">
          </article>
        </template>
      </VirtualList>
    </article>

    <article class="paper">
      <form data-testid="author-chapter-form"></form>
    </article>

    <article class="paper">
      <div v-if="!authorWorkspace.selectedChapterId" class="empty">请先选择或新建章节，再编辑场景。</div>
      <VirtualList
        v-else
        test-id="author-scene-virtual-list"
        :items="scenes"
        item-key="scene_id"
        :estimated-item-height="188"
        :threshold="10"
        :pinned-keys="pinnedSceneKeys"
        :viewport-height="560"
      >
        <template #default="{ item: scene }">
          <article class="author-scene-row" :class="{ active: selectedSceneId === scene.scene_id }">
          </article>
        </template>
      </VirtualList>
      <form data-testid="author-scene-form"></form>
    </article>
  </div>
</template>
```

Retain the current chapter row, scene row, chapter form, and scene form markup exactly as-is. This task only wraps the two list surfaces in `VirtualList` and adds `data-testid="author-chapter-form"` / `data-testid="author-scene-form"` to the form containers.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm exec vitest run tests/scrollPerformance.spec.js tests/authorWorkspace.spec.js`

Expected: PASS with author workspace integration assertions and existing author store tests still green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/AuthorWorkspaceView.vue frontend/tests/scrollPerformance.spec.js frontend/tests/authorWorkspace.spec.js
git commit -m "feat(frontend): virtualize author workspace lists"
```

### Task 6: Add Shared Styles, Final Regressions, and End-to-End Verification

**Files:**
- Modify: `frontend/src/styles/app.css`
- Modify: `frontend/tests/smoothness.spec.js`
- Modify: `frontend/tests/lightKeepAlive.spec.js`
- Modify: `frontend/tests/e2e/smoothness-navigation.spec.js`

- [ ] **Step 1: Write the failing regression and E2E updates**

```js
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("shared list primitive styling", () => {
  it("adds virtual and progressive list containment styles", () => {
    const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");

    expect(styles).toContain(".virtual-list");
    expect(styles).toContain(".virtual-list-spacer");
    expect(styles).toContain(".virtual-list-row");
    expect(styles).toContain(".progressive-list");
    expect(styles).toContain("contain: layout paint");
    expect(styles).toContain("content-visibility: auto");
  });
});
```

```js
test("keeps scroll-heavy list surfaces interactive after expansion", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("api-base-input").fill(apiBase);
  await page.getByTestId("api-base-input").press("Tab");
  await page.getByTestId("operator-ref-input").fill("ops.smoothness.scroll");
  await page.getByTestId("operator-ref-input").press("Tab");

  await page.getByTestId("nav-review").click();
  await expect(page.getByTestId("review-virtual-list")).toBeVisible();
  await page.getByTestId(/review-toggle-payload-/).first().click();
  await expect(page.locator("[data-testid^='review-card-']").first().locator("pre")).toBeVisible();

  await page.getByTestId("nav-index").click();
  await page.getByTestId("index-toggle-target-groups").click();
  await expect(page.getByTestId("index-target-groups-virtual-list")).toBeVisible();

  await page.getByTestId("nav-author").click();
  await expect(page.getByTestId("author-chapter-virtual-list")).toBeVisible();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm exec vitest run tests/smoothness.spec.js tests/lightKeepAlive.spec.js tests/scrollPerformance.spec.js`

Expected: FAIL because the new shared list classes and source assertions are not all present yet.

- [ ] **Step 3: Write minimal implementation**

`frontend/src/styles/app.css`

```css
.virtual-list {
  display: block;
  overflow-y: auto;
  min-width: 0;
  max-height: 42rem;
}

.virtual-list-spacer {
  width: 100%;
  pointer-events: none;
}

.virtual-list-row {
  contain: layout paint;
  content-visibility: auto;
  contain-intrinsic-size: 180px;
}

.progressive-list {
  display: grid;
  gap: 1rem;
  min-width: 0;
}

.review-list .virtual-list-row,
.author-list .virtual-list-row,
.author-scene-list .virtual-list-row,
.receipt-list .virtual-list-row,
.job-table .virtual-list-row {
  padding-bottom: 1rem;
}
```

`frontend/tests/smoothness.spec.js`

```js
it("ships shared virtual and progressive list primitives for heavy in-page surfaces", () => {
  const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
  const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
  const authorSource = readFileSync(new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");

  expect(reviewSource).toContain("review-virtual-list");
  expect(indexSource).toContain("index-jobs-virtual-list");
  expect(authorSource).toContain("author-scene-virtual-list");
  expect(styles).toContain(".virtual-list");
  expect(styles).toContain(".progressive-list");
});
```

- [ ] **Step 4: Run the full verification suite**

Run: `npm test`

Expected: PASS with the existing frontend suite plus the new list primitive and integration regressions.

Run: `npm run build`

Expected: PASS with a successful Vite production build.

Run: `npx playwright test tests/e2e/smoothness-navigation.spec.js`

Expected: PASS with the existing smoothness navigation coverage plus the new scroll-heavy interaction check.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/styles/app.css frontend/tests/smoothness.spec.js frontend/tests/lightKeepAlive.spec.js frontend/tests/e2e/smoothness-navigation.spec.js
git commit -m "test(frontend): verify scroll and expand performance paths"
```

---

## Spec Coverage Check

- Shared `ProgressiveList` and `VirtualList` primitives: covered by Tasks 1-3.
- `Review Inbox` integration: covered by Task 3.
- `Index Console` jobs, timelines, and target group summary integration: covered by Task 4.
- `Author Workspace` list integration with stable forms: covered by Task 5.
- Focus safety, pinned items, and small-list fallback: covered by Tasks 1, 4, and 5.
- Shared styles, containment hints, and verification updates: covered by Task 6.

No spec requirement is left without a task.

## Type and Naming Check

- `buildVirtualWindow`, `resolvePinnedIndexes`, and `resolveVisibleIndexes` are used consistently between the helper tests and the component plan.
- `buildProgressivePlan`, `nextProgressiveCount`, and `shouldProgressivelyRender` are used consistently between the helper tests and the component plan.
- `pinnedKeys`, `itemKey`, `estimatedItemHeight`, `threshold`, and `viewportHeight` are used consistently across planned integrations.

## Placeholder Check

- No `TBD`, `TODO`, or deferred implementation placeholders remain in the plan.
- Every code-writing step includes concrete code blocks.
- Every verification step includes an exact command and expected outcome.
