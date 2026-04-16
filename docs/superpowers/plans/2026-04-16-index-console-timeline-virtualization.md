# Index Console Timeline Virtualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Virtualize the remaining `system_runtime` and `operator_action` flat timelines in `Index Console` so long event streams scroll more smoothly without breaking focus, buttons, or pagination.

**Architecture:** Reuse the existing `VirtualList.vue` primitive that already powers jobs, recovery timeline, target-group summaries, and authoring lists. Add section-specific pinned keys and semantic section anchors in `IndexConsoleView.vue`, then extend runtime, source, and E2E regressions to prove the new virtualized surfaces survive scroll and navigation.

**Tech Stack:** Vue 3 SFCs, Pinia, Vitest with jsdom, Playwright, Vite.

**Execution Note (2026-04-16):** `ActivitySectionCard.vue` already accepts `testId`, so this slice should wire new section anchors from `IndexConsoleView.vue` instead of reopening the section-shell component. Runtime tests are the primary proof of virtualization; E2E should use section-scoped selectors and may accept section-scoped empty-state fallback if the Playwright backend returns an empty stream.

---

## File Map

**Modify**

- `frontend/src/views/IndexConsoleView.vue`
- `frontend/tests/scrollPerformance.spec.js`
- `frontend/tests/smoothness.spec.js`
- `frontend/tests/e2e/smoothness-navigation.spec.js`

**Why these files**

- `frontend/src/views/IndexConsoleView.vue` is the only production file that still renders `system_runtime` and `operator_action` as full `ul/li` timelines.
- `frontend/tests/scrollPerformance.spec.js` already mounts `IndexConsoleView` under jsdom and is the right place to prove row windowing, pinned rows, and button survival at runtime.
- `frontend/tests/smoothness.spec.js` already carries lightweight source assertions for the existing virtualization rollout and should pin the new section anchors and `VirtualList` routing.
- `frontend/tests/e2e/smoothness-navigation.spec.js` already exercises the heavy review/index/author navigation path and should extend that path to the two remaining index timelines.

---

### Task 1: Add the Failing Timeline Virtualization Regressions

**Files:**
- Modify: `frontend/tests/scrollPerformance.spec.js`
- Modify: `frontend/tests/smoothness.spec.js`
- Modify: `frontend/tests/e2e/smoothness-navigation.spec.js`

- [ ] **Step 1: Write the failing runtime, source, and E2E assertions**

`frontend/tests/scrollPerformance.spec.js`

```js
function createSystemRuntimeItem(index) {
  return {
    operation_id: index,
    source: "system_runtime",
    event_type: `system_event_${index}`,
    label: `System event ${index}`,
    status: index % 2 === 0 ? "succeeded" : "pending",
    actor_ref: `system-${index}`,
    timestamp: `2026-04-16T05:${String(index).padStart(2, "0")}:00+00:00`,
    summary: `System summary ${index}`,
    description: `System description ${index}`,
    target_refs: [
      {
        target_type: "review_item",
        target_id: `review-${index}`,
        target_ref: `review_item:review-${index}`,
      },
    ],
  };
}

function createOperatorActionItem(index) {
  return {
    operation_id: index,
    source: "operator_action",
    action: index % 2 === 0 ? "approve_review" : "inspect",
    label: `Operator event ${index}`,
    status: index % 2 === 0 ? "approved" : "pending",
    status_before: "pending",
    status_after: index % 2 === 0 ? "approved" : "pending",
    actor_ref: `operator-${index}`,
    timestamp: `2026-04-16T06:${String(index).padStart(2, "0")}:00+00:00`,
    summary: `Operator summary ${index}`,
    description: `Operator description ${index}`,
    target_refs: [
      {
        target_type: "review_item",
        target_id: `review-${index}`,
        target_ref: `review_item:review-${index}`,
      },
    ],
  };
}

async function mountIndexConsoleView({
  jobCount = 15,
  recoveryCount = 15,
  systemRuntimeCount = 18,
  operatorActionCount = 18,
  targetGroupCount = 14,
  targetGroupItemCount = 10,
  focusTarget,
} = {}) {
  // existing setup above remains unchanged
  store.recoveryTimelineItems = Array.from({ length: recoveryCount }, (_, index) => createRecoveryItem(index));
  store.systemRuntimeTimelineItems = Array.from({ length: systemRuntimeCount }, (_, index) => createSystemRuntimeItem(index + 1));
  store.operatorActionTimelineItems = Array.from({ length: operatorActionCount }, (_, index) => createOperatorActionItem(index + 1));
  store.targetActivityGroups = Array.from({ length: targetGroupCount }, (_, index) => createTargetGroup(index));
  store.activitySections.recovery_timeline.loaded = true;
  store.activitySections.system_runtime.loaded = true;
  store.activitySections.operator_action.loaded = true;
  store.activitySections.target_groups.loaded = true;
  // existing setup below remains unchanged
}

it("mounts system runtime through VirtualList and keeps the focused system row mounted after scroll", async () => {
  const mounted = await mountIndexConsoleView({
    focusTarget: {
      target_type: "review_item",
      target_id: "review-14",
      target_ref: "review_item:review-14",
      view_id: "index",
      source_type: "system_activity",
      source_id: 14,
    },
  });

  try {
    const systemSection = mounted.container.querySelector('[data-testid="index-system-runtime-section"]');
    systemSection.querySelector('[data-testid="index-toggle-system-runtime"]').click();
    await flushUi();

    const systemList = systemSection.querySelector('[data-testid="index-system-runtime-virtual-list"]');
    expect(systemList).not.toBeNull();
    expect(systemList.style.maxHeight).toBe("560px");

    let rows = systemSection.querySelectorAll('[data-activity-key^="system_runtime:"]');
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(mounted.store.systemRuntimeTimelineItems.length);
    expect(systemSection.querySelector('[data-activity-key="system_runtime:14"]')).not.toBeNull();
    expect(systemSection.querySelector(".card-actions button")).not.toBeNull();

    systemList.scrollTop = 10000;
    systemList.dispatchEvent(new Event("scroll"));
    await flushUi();

    rows = systemSection.querySelectorAll('[data-activity-key^="system_runtime:"]');
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(mounted.store.systemRuntimeTimelineItems.length);
    expect(systemSection.querySelector('[data-activity-key="system_runtime:14"]')).not.toBeNull();
  } finally {
    mounted.unmount();
  }
});

it("mounts operator action through VirtualList and keeps the focused operator row mounted after scroll", async () => {
  const mounted = await mountIndexConsoleView({
    focusTarget: {
      target_type: "review_item",
      target_id: "review-15",
      target_ref: "review_item:review-15",
      view_id: "index",
      source_type: "operator_action",
      source_id: 15,
    },
  });

  try {
    const operatorSection = mounted.container.querySelector('[data-testid="index-operator-action-section"]');
    operatorSection.querySelector('[data-testid="index-toggle-operator-action"]').click();
    await flushUi();

    const operatorList = operatorSection.querySelector('[data-testid="index-operator-action-virtual-list"]');
    expect(operatorList).not.toBeNull();
    expect(operatorList.style.maxHeight).toBe("560px");

    let rows = operatorSection.querySelectorAll('[data-activity-key^="operator_action:"]');
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(mounted.store.operatorActionTimelineItems.length);
    expect(operatorSection.querySelector('[data-activity-key="operator_action:15"]')).not.toBeNull();
    expect(operatorSection.querySelector(".card-actions button")).not.toBeNull();

    operatorList.scrollTop = 10000;
    operatorList.dispatchEvent(new Event("scroll"));
    await flushUi();

    rows = operatorSection.querySelectorAll('[data-activity-key^="operator_action:"]');
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThan(mounted.store.operatorActionTimelineItems.length);
    expect(operatorSection.querySelector('[data-activity-key="operator_action:15"]')).not.toBeNull();
  } finally {
    mounted.unmount();
  }
});
```

`frontend/tests/smoothness.spec.js`

```js
it("routes the remaining index timelines through VirtualList with semantic section anchors", () => {
  const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");

  expect(indexSource).toContain('test-id="index-system-runtime-section"');
  expect(indexSource).toContain('test-id="index-system-runtime-virtual-list"');
  expect(indexSource).toContain('test-id="index-operator-action-section"');
  expect(indexSource).toContain('test-id="index-operator-action-virtual-list"');
  expect(indexSource).toContain("const pinnedSystemRuntimeKeys = computed(() =>");
  expect(indexSource).toContain("const pinnedOperatorActionKeys = computed(() =>");
});
```

`frontend/tests/e2e/smoothness-navigation.spec.js`

```js
  await page.getByTestId("index-toggle-system-runtime").click();
  const systemSection = page.getByTestId("index-system-runtime-section");
  await expect
    .poll(async () => {
      const hasVirtualList = await systemSection.getByTestId("index-system-runtime-virtual-list").count();
      const hasEmptyState = await systemSection.locator(".empty").count();
      return hasVirtualList + hasEmptyState;
    })
    .toBeGreaterThan(0);

  if (await systemSection.getByTestId("index-system-runtime-virtual-list").count()) {
    const systemList = systemSection.getByTestId("index-system-runtime-virtual-list");
    await expect(systemList).toBeVisible();
    await systemList.evaluate((node) => {
      node.scrollTop = node.scrollHeight;
      node.dispatchEvent(new Event("scroll"));
    });
    await expect(systemSection.locator("[data-activity-key^='system_runtime:']").first()).toBeVisible();
  } else {
    await expect(systemSection.locator(".empty")).toBeVisible();
  }

  await page.getByTestId("index-toggle-operator-action").click();
  const operatorSection = page.getByTestId("index-operator-action-section");
  await expect
    .poll(async () => {
      const hasVirtualList = await operatorSection.getByTestId("index-operator-action-virtual-list").count();
      const hasEmptyState = await operatorSection.locator(".empty").count();
      return hasVirtualList + hasEmptyState;
    })
    .toBeGreaterThan(0);

  if (await operatorSection.getByTestId("index-operator-action-virtual-list").count()) {
    const operatorList = operatorSection.getByTestId("index-operator-action-virtual-list");
    await expect(operatorList).toBeVisible();
    await operatorList.evaluate((node) => {
      node.scrollTop = node.scrollHeight;
      node.dispatchEvent(new Event("scroll"));
    });
    await expect(operatorSection.locator("[data-activity-key^='operator_action:']").first()).toBeVisible();
  } else {
    await expect(operatorSection.locator(".empty")).toBeVisible();
  }
```

- [ ] **Step 2: Run the targeted tests to verify they fail**

Run: `npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js`

Expected: FAIL because `IndexConsoleView.vue` does not yet define `index-system-runtime-section`, `index-system-runtime-virtual-list`, `index-operator-action-section`, `index-operator-action-virtual-list`, `pinnedSystemRuntimeKeys`, or `pinnedOperatorActionKeys`.

---

### Task 2: Replace the Remaining Flat Timelines with VirtualList and Verify End-to-End

**Files:**
- Modify: `frontend/src/views/IndexConsoleView.vue`
- Modify: `frontend/tests/scrollPerformance.spec.js`
- Modify: `frontend/tests/smoothness.spec.js`
- Modify: `frontend/tests/e2e/smoothness-navigation.spec.js`

- [ ] **Step 1: Write the minimal implementation in `IndexConsoleView.vue`**

```vue
const pinnedSystemRuntimeKeys = computed(() => {
  if (focusedSourceType.value !== "system_activity" || focusedSourceId.value === null) {
    return [];
  }
  return [`system_runtime:${focusedSourceId.value}`];
});

const pinnedOperatorActionKeys = computed(() => {
  if (focusedSourceType.value !== "operator_action" || focusedSourceId.value === null) {
    return [];
  }
  return [`operator_action:${focusedSourceId.value}`];
});
```

```vue
<ActivitySectionCard
  title="系统活动"
  description="系统运行时事件按需读取，避免首屏吞掉整包 payload。"
  :summary="sectionSummary.system_runtime()"
  badge="系统"
  :expanded="expandedSections.system_runtime"
  :loading="indexConsole.activitySectionState('system_runtime').loading"
  test-id="index-system-runtime-section"
  toggle-test-id="index-toggle-system-runtime"
  @toggle="toggleSection('system_runtime')"
>
  <div v-if="!indexConsole.systemRuntimeTimelineItems.length" class="empty">当前没有系统活动。</div>
  <template v-else>
    <VirtualList
      class="receipt-list"
      :items="indexConsole.systemRuntimeTimelineItems"
      :item-key="(item) => activityItemKey('system_runtime', item)"
      :estimated-item-height="176"
      :threshold="8"
      :viewport-height="560"
      :pinned-keys="pinnedSystemRuntimeKeys"
      test-id="index-system-runtime-virtual-list"
    >
      <template #default="{ item }">
        <article
          class="receipt-list-item"
          :data-activity-key="activityItemKey('system_runtime', item)"
          :class="{ 'focused-card': isFocusedSource('system_activity', item.operation_id) }"
        >
          <strong>{{ item.label || item.event_type || "系统活动" }}</strong><br />
          {{ targetSummary(item) }}<br />
          {{ item.summary || item.description || "-" }}
          <div v-if="activityTargets(item).length" class="card-actions">
            <button
              v-for="target in activityTargets(item)"
              :key="`${activityItemKey('system_runtime', item)}:${target.target_ref}`"
              type="button"
              class="ghost"
              @click="jumpToTarget(withIndexFocusTarget(target, 'system_activity', item.operation_id))"
            >
              {{ targetActionLabel(target) }}
            </button>
          </div>
        </article>
      </template>
    </VirtualList>
    <CursorPager
      test-id-prefix="system-runtime-pager"
      :pagination="indexConsole.activitySectionPagination('system_runtime')"
      :can-previous="sectionCanPrevious('system_runtime')"
      :can-next="sectionCanNext('system_runtime')"
      :disabled="indexConsole.activitySectionState('system_runtime').loading"
      @previous="previousSectionPage('system_runtime')"
      @next="nextSectionPage('system_runtime')"
    />
  </template>
</ActivitySectionCard>

<ActivitySectionCard
  title="人工操作"
  description="操作流保持收起，避免每次进入索引页都渲染长时间线。"
  :summary="sectionSummary.operator_action()"
  badge="操作"
  :expanded="expandedSections.operator_action"
  :loading="indexConsole.activitySectionState('operator_action').loading"
  test-id="index-operator-action-section"
  toggle-test-id="index-toggle-operator-action"
  @toggle="toggleSection('operator_action')"
>
  <div v-if="!indexConsole.operatorActionTimelineItems.length" class="empty">当前没有人工操作记录。</div>
  <template v-else>
    <VirtualList
      class="receipt-list"
      :items="indexConsole.operatorActionTimelineItems"
      :item-key="(item) => activityItemKey('operator_action', item)"
      :estimated-item-height="188"
      :threshold="8"
      :viewport-height="560"
      :pinned-keys="pinnedOperatorActionKeys"
      test-id="index-operator-action-virtual-list"
    >
      <template #default="{ item }">
        <article
          class="receipt-list-item"
          :data-activity-key="activityItemKey('operator_action', item)"
          :class="{ 'focused-card': isFocusedSource('operator_action', item.operation_id) }"
        >
          <strong>{{ item.label || item.action || "人工操作" }}</strong><br />
          {{ targetSummary(item) }}<br />
          {{ item.summary || item.description || "-" }}
          <div v-if="activityTargets(item).length" class="card-actions">
            <button
              v-for="target in activityTargets(item)"
              :key="`${activityItemKey('operator_action', item)}:${target.target_ref}`"
              type="button"
              class="ghost"
              @click="jumpToTarget(withIndexFocusTarget(target, 'operator_action', item.operation_id))"
            >
              {{ targetActionLabel(target) }}
            </button>
          </div>
        </article>
      </template>
    </VirtualList>
    <CursorPager
      test-id-prefix="operator-action-pager"
      :pagination="indexConsole.activitySectionPagination('operator_action')"
      :can-previous="sectionCanPrevious('operator_action')"
      :can-next="sectionCanNext('operator_action')"
      :disabled="indexConsole.activitySectionState('operator_action').loading"
      @previous="previousSectionPage('operator_action')"
      @next="nextSectionPage('operator_action')"
    />
  </template>
</ActivitySectionCard>
```

- [ ] **Step 2: Run the targeted Vitest regressions**

Run: `npm exec vitest run tests/scrollPerformance.spec.js tests/smoothness.spec.js`

Expected: PASS with the new `system_runtime` and `operator_action` virtual-list anchors, pinned-key wiring, and runtime scroll assertions.

- [ ] **Step 3: Run the E2E navigation regression**

Run: `npx playwright test tests/e2e/smoothness-navigation.spec.js`

Expected: PASS with the existing navigation tests plus the new section-scoped checks for `system_runtime` and `operator_action`.

- [ ] **Step 4: Run the full frontend verification suite**

Run: `npm test`

Expected: PASS with the full Vitest suite plus `frontend smoke ok`.

Run: `npm run build`

Expected: PASS with a successful Vite production build.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/IndexConsoleView.vue frontend/tests/scrollPerformance.spec.js frontend/tests/smoothness.spec.js frontend/tests/e2e/smoothness-navigation.spec.js
git commit -m "perf(index): virtualize remaining timeline sections"
```

---

## Spec Coverage Check

- `system_runtime` virtualization: covered by Task 1 regressions and Task 2 implementation.
- `operator_action` virtualization: covered by Task 1 regressions and Task 2 implementation.
- section-specific pinned keys: covered by Task 1 source assertions and Task 2 computed properties.
- semantic section anchors for runtime/E2E: covered by Task 1 assertions and Task 2 `test-id` wiring.
- runtime proof of row windowing and pinned-row survival: covered by Task 1 `scrollPerformance.spec.js` additions.
- navigation-path survival across heavy surfaces: covered by Task 1 E2E additions and Task 2 Playwright verification.

No spec requirement is left without a task.

## Placeholder Check

- No `TODO`, `TBD`, or deferred implementation notes remain in the plan.
- Every code-writing step includes concrete code blocks.
- Every verification step includes exact commands and expected outcomes.

## Type and Naming Check

- `pinnedSystemRuntimeKeys`, `pinnedOperatorActionKeys`, `index-system-runtime-section`, `index-system-runtime-virtual-list`, `index-operator-action-section`, and `index-operator-action-virtual-list` are used consistently across implementation and tests.
- `activityItemKey("system_runtime", item)` and `activityItemKey("operator_action", item)` remain the canonical keys for both item rendering and pinned-key expectations.
- `system_activity` and `operator_action` source types are used consistently between focus handling, runtime tests, and E2E expectations.
