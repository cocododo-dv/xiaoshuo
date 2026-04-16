// @vitest-environment jsdom

import { KeepAlive, createApp, h, nextTick, ref } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import VirtualList from "../src/components/VirtualList.vue";
import {
  buildVirtualWindow,
  buildHeightProfile,
  resolvePinnedIndexes,
  resolveVisibleIndexes,
} from "../src/lib/virtualList";

async function flushUi() {
  await nextTick();
  await Promise.resolve();
}

function createAnimationFrameController() {
  let nextId = 1;
  let queue = [];
  let executedCount = 0;

  return {
    get executedCount() {
      return executedCount;
    },
    get queuedCount() {
      return queue.length;
    },
    request(callback) {
      const id = nextId;
      nextId += 1;
      queue.push({ id, callback });
      return id;
    },
    cancel(id) {
      queue = queue.filter((entry) => entry.id !== id);
    },
    async flushAll() {
      while (queue.length) {
        const currentQueue = queue;
        queue = [];
        currentQueue.forEach((entry) => {
          executedCount += 1;
          entry.callback(0);
        });
        await flushUi();
      }
    },
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

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

  it("keeps falsy keys like 0 pinnable", () => {
    const items = [{ id: 0 }, { id: 1 }, { id: 2 }];

    expect(resolvePinnedIndexes(items, "id", [0])).toEqual([0]);
  });
});

describe("VirtualList KeepAlive lifecycle", () => {
  it("coalesces rapid scroll events into one animation-frame render", async () => {
    const animationFrames = createAnimationFrameController();
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", {
      configurable: true,
      value: 20,
    });

    const items = Array.from({ length: 80 }, (_, index) => ({
      id: `virtual-row-${index + 1}`,
      label: `Virtual row ${index + 1}`,
    }));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const app = createApp({
      render() {
        return h(
          VirtualList,
          {
            items,
            itemKey: "id",
            estimatedItemHeight: 20,
            overscan: 1,
            threshold: 0,
            viewportHeight: 80,
            testId: "virtual-list-under-test",
          },
          {
            default: ({ item }) =>
              h("div", { "data-testid": item.id }, item.label),
          },
        );
      },
    });

    app.mount(container);
    await flushUi();
    await animationFrames.flushAll();

    try {
      const list = container.querySelector('[data-testid="virtual-list-under-test"]');
      expect(list).not.toBeNull();
      expect(container.querySelector('[data-testid="virtual-row-1"]')).not.toBeNull();

      list.scrollTop = 280;
      list.dispatchEvent(new Event("scroll"));
      list.scrollTop = 520;
      list.dispatchEvent(new Event("scroll"));
      await flushUi();

      expect(animationFrames.queuedCount).toBe(1);
      expect(container.querySelector('[data-testid="virtual-row-26"]')).toBeNull();

      await animationFrames.flushAll();

      expect(container.querySelector('[data-testid="virtual-row-26"]')).not.toBeNull();
    } finally {
      app.unmount();
      container.remove();
    }
  });

  it("pauses queued measurements while deactivated and resumes after activation", async () => {
    const animationFrames = createAnimationFrameController();
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });

    const visible = ref(true);
    const items = Array.from({ length: 30 }, (_, index) => ({
      id: `virtual-row-${index + 1}`,
      label: `Virtual row ${index + 1}`,
    }));
    const Placeholder = {
      name: "VirtualListPlaceholder",
      render() {
        return h("section", { "data-testid": "virtual-placeholder" }, "hidden");
      },
    };
    const container = document.createElement("div");
    document.body.appendChild(container);
    const app = createApp({
      render() {
        return h(KeepAlive, null, () =>
          visible.value
            ? h(
              VirtualList,
              {
                items,
                itemKey: "id",
                estimatedItemHeight: 20,
                overscan: 1,
                threshold: 0,
                viewportHeight: 80,
                testId: "virtual-list-under-test",
              },
              {
                default: ({ item }) =>
                  h("div", { "data-testid": item.id }, item.label),
              },
            )
            : h(Placeholder),
        );
      },
    });

    app.mount(container);
    await flushUi();

    try {
      expect(container.querySelector('[data-testid="virtual-list-under-test"]')).not.toBeNull();
      expect(animationFrames.queuedCount).toBeGreaterThan(0);

      visible.value = false;
      await flushUi();
      expect(container.querySelector('[data-testid="virtual-placeholder"]')).not.toBeNull();

      await animationFrames.flushAll();

      expect(animationFrames.executedCount).toBe(0);

      visible.value = true;
      await flushUi();
      expect(container.querySelector('[data-testid="virtual-list-under-test"]')).not.toBeNull();

      await animationFrames.flushAll();

      expect(animationFrames.executedCount).toBeGreaterThan(0);
      expect(container.querySelector('[data-testid="virtual-row-1"]')).not.toBeNull();
    } finally {
      app.unmount();
      container.remove();
    }
  });
});

describe("resolveVisibleIndexes", () => {
  it("uses measured heights when choosing the visible slice", () => {
    const items = Array.from({ length: 4 }, (_, index) => ({ id: `row-${index}` }));

    expect(
      resolveVisibleIndexes({
        items,
        itemKey: "id",
        viewportHeight: 20,
        scrollTop: 25,
        estimatedItemHeight: 10,
        overscan: 0,
        measuredHeights: { "row-0": 60 },
      }),
    ).toEqual({
      viewportStartIndex: 0,
      viewportEndIndex: 1,
      renderStartIndex: 0,
      renderEndIndex: 1,
    });
  });

  it("defaults overscan safely when omitted", () => {
    const items = Array.from({ length: 5 }, (_, index) => ({ id: `row-${index}` }));

    expect(
      resolveVisibleIndexes({
        items,
        itemKey: "id",
        viewportHeight: 15,
        scrollTop: 5,
        estimatedItemHeight: 10,
      }),
    ).toEqual({
      viewportStartIndex: 0,
      viewportEndIndex: 2,
      renderStartIndex: 0,
      renderEndIndex: 2,
    });
  });

  it("clamps stale scroll positions instead of returning an empty tail slice", () => {
    const items = Array.from({ length: 4 }, (_, index) => ({ id: `row-${index}` }));

    expect(
      resolveVisibleIndexes({
        items,
        itemKey: "id",
        viewportHeight: 15,
        scrollTop: 999,
        estimatedItemHeight: 10,
        overscan: 0,
      }),
    ).toEqual({
      viewportStartIndex: 2,
      viewportEndIndex: 4,
      renderStartIndex: 2,
      renderEndIndex: 4,
    });
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
    expect(state.visibleItems.map((item) => item.id)).toEqual([
      "row-0",
      "row-1",
      "row-2",
      "row-3",
      "row-4",
    ]);
    expect(state.visibleKeys).toEqual(["row-0", "row-1", "row-2", "row-3", "row-4"]);
    expect(state.topSpacerHeight).toBe(0);
    expect(state.bottomSpacerHeight).toBe(0);
    expect(state.totalHeight).toBe(6 * 48);
    expect(state.renderedEntries.map((entry) => entry.index)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("keeps visibleItems contiguous while rendering overscan and pinned rows separately", () => {
    const items = Array.from({ length: 6 }, (_, index) => ({ id: `row-${index}` }));

    const state = buildVirtualWindow({
      items,
      itemKey: "id",
      viewportHeight: 10,
      scrollTop: 10,
      estimatedItemHeight: 10,
      overscan: 1,
      threshold: 0,
      measuredHeights: {},
      pinnedKeys: ["row-5"],
    });

    expect(state.visibleItems.map((item) => item.id)).toEqual(["row-1"]);
    expect(state.visibleKeys).toEqual(["row-1"]);
    expect(state.totalHeight).toBe(60);
    expect(state.renderedEntries.map((entry) => entry.index)).toEqual([0, 1, 2, 5]);
    expect(state.renderedEntries.map((entry) => entry.offsetTop)).toEqual([0, 10, 20, 50]);
    expect(state.renderedEntries.find((entry) => entry.index === 0)).toMatchObject({
      pinned: false,
      inViewport: false,
      offsetTop: 0,
      height: 10,
    });
    expect(state.renderedEntries.find((entry) => entry.index === 2)).toMatchObject({
      pinned: false,
      inViewport: false,
      offsetTop: 20,
      height: 10,
    });
    expect(state.renderedEntries.find((entry) => entry.index === 5)).toMatchObject({
      pinned: true,
      inViewport: false,
      offsetTop: 50,
      height: 10,
    });
    expect(state.topSpacerHeight).toBe(10);
    expect(state.bottomSpacerHeight).toBe(40);
  });

  it("supports cached geometry inputs and function item keys", () => {
    const items = [
      { key: "row-0" },
      { key: "row-1" },
      { key: "row-2" },
      { key: "row-3" },
    ];
    const itemKey = (item) => item.key;
    const heightProfile = buildHeightProfile(items, itemKey, { "row-1": 20 }, 10);

    const state = buildVirtualWindow({
      items,
      itemKey,
      viewportHeight: 15,
      scrollTop: 35,
      estimatedItemHeight: 10,
      overscan: 0,
      threshold: 0,
      heightProfile,
      pinnedIndexes: [1],
    });

    expect(state.visibleItems.map((item) => item.key)).toEqual(["row-2", "row-3"]);
    expect(state.visibleKeys).toEqual(["row-2", "row-3"]);
    expect(state.totalHeight).toBe(50);
    expect(state.renderedEntries.map((entry) => entry.index)).toEqual([1, 2, 3]);
    expect(state.renderedEntries.map((entry) => entry.offsetTop)).toEqual([10, 30, 40]);
    expect(state.renderedEntries.find((entry) => entry.index === 1)).toMatchObject({
      pinned: true,
      inViewport: false,
      offsetTop: 10,
      height: 20,
    });
  });

  it("preserves total height when the visible range is empty", () => {
    const items = Array.from({ length: 8 }, (_, index) => ({ id: `row-${index}` }));
    const estimatedItemHeight = 24;

    const state = buildVirtualWindow({
      items,
      itemKey: "id",
      viewportHeight: 0,
      scrollTop: 0,
      estimatedItemHeight,
      overscan: 0,
      threshold: 0,
      measuredHeights: {},
      pinnedKeys: [],
    });

    expect(state.virtualized).toBe(true);
    expect(state.visibleItems).toEqual([]);
    expect(state.visibleKeys).toEqual([]);
    expect(state.topSpacerHeight).toBe(0);
    expect(state.bottomSpacerHeight).toBe(items.length * estimatedItemHeight);
    expect(state.totalHeight).toBe(items.length * estimatedItemHeight);
    expect(state.renderedEntries).toEqual([]);
  });
});
