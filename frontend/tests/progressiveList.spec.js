// @vitest-environment jsdom

import { KeepAlive, createApp, h, nextTick, ref } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProgressiveList from "../src/components/ProgressiveList.vue";
import {
  buildProgressivePlan,
  nextProgressiveCount,
  shouldProgressivelyRender,
} from "../src/lib/progressiveList";

async function flushUi() {
  await nextTick();
  await Promise.resolve();
}

function createAnimationFrameController() {
  let nextId = 1;
  let queue = [];

  return {
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
        currentQueue.forEach((entry) => entry.callback(0));
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

describe("shouldProgressivelyRender", () => {
  it("returns false when progressive rendering is disabled", () => {
    expect(
      shouldProgressivelyRender({
        enabled: false,
        itemCount: 25,
        threshold: 10,
      }),
    ).toBe(false);
  });

  it("returns false when the item count is at or below the threshold", () => {
    expect(
      shouldProgressivelyRender({
        enabled: true,
        itemCount: 10,
        threshold: 10,
      }),
    ).toBe(false);
  });

  it("returns true when progressive rendering is enabled and the item count exceeds the threshold", () => {
    expect(
      shouldProgressivelyRender({
        enabled: true,
        itemCount: 11,
        threshold: 10,
      }),
    ).toBe(true);
  });

  it("uses the default threshold when one is omitted", () => {
    expect(
      shouldProgressivelyRender({
        enabled: true,
        itemCount: 12,
      }),
    ).toBe(false);

    expect(
      shouldProgressivelyRender({
        enabled: true,
        itemCount: 13,
      }),
    ).toBe(true);
  });
});

describe("nextProgressiveCount", () => {
  it("grows the rendered count by a fixed batch size", () => {
    expect(
      nextProgressiveCount({
        renderedCount: 5,
        itemCount: 20,
        batchSize: 4,
      }),
    ).toBe(9);
  });

  it("clamps the rendered count to the item count", () => {
    expect(
      nextProgressiveCount({
        renderedCount: 18,
        itemCount: 20,
        batchSize: 8,
      }),
    ).toBe(20);
  });
});

describe("buildProgressivePlan", () => {
  it("returns all items immediately when progressive rendering is disabled", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];

    expect(
      buildProgressivePlan({
        items,
        enabled: false,
        initialCount: 1,
        batchSize: 2,
        threshold: 10,
      }),
    ).toEqual({
      items,
      renderedItems: items,
      renderedCount: 3,
      pending: false,
      batchSize: 2,
      threshold: 10,
    });
  });

  it("uses the default batch size and threshold when omitted", () => {
    const items = Array.from({ length: 13 }, (_, index) => ({ id: `row-${index}` }));

    expect(
      buildProgressivePlan({
        items,
        enabled: true,
      }),
    ).toEqual({
      items,
      renderedItems: items.slice(0, 8),
      renderedCount: 8,
      pending: true,
      batchSize: 8,
      threshold: 12,
    });
  });

  it("keeps stable metadata defaults on the non-progressive path", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }];

    expect(
      buildProgressivePlan({
        items,
        enabled: false,
      }),
    ).toEqual({
      items,
      renderedItems: items,
      renderedCount: 3,
      pending: false,
      batchSize: 8,
      threshold: 12,
    });
  });

  it("returns the first batch immediately when progressive rendering is enabled", () => {
    const items = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }, { id: "e" }];

    expect(
      buildProgressivePlan({
        items,
        enabled: true,
        initialCount: 2,
        batchSize: 2,
        threshold: 3,
      }),
    ).toEqual({
      items,
      renderedItems: [{ id: "a" }, { id: "b" }],
      renderedCount: 2,
      pending: true,
      batchSize: 2,
      threshold: 3,
    });
  });

  it("treats an initial count above the item count as fully rendered", () => {
    const items = [{ id: "a" }, { id: "b" }];

    expect(
      buildProgressivePlan({
        items,
        enabled: true,
        initialCount: 5,
        batchSize: 2,
        threshold: 1,
      }),
    ).toEqual({
      items,
      renderedItems: items,
      renderedCount: 2,
      pending: false,
      batchSize: 2,
      threshold: 1,
    });
  });
});

describe("ProgressiveList KeepAlive lifecycle", () => {
  it("maps only the rows currently admitted into the progressive render window", async () => {
    const animationFrames = createAnimationFrameController();
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));

    const items = Array.from({ length: 6 }, (_, index) => ({
      id: `mapped-row-${index + 1}`,
      label: `Mapped row ${index + 1}`,
    }));
    const mapItem = vi.fn((item) => ({
      id: item.id,
      label: item.label.toUpperCase(),
    }));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const app = createApp({
      render() {
        return h(
          ProgressiveList,
          {
            items,
            mapItem,
            initialCount: 2,
            batchSize: 2,
            threshold: 2,
            testId: "progressive-map-list",
          },
          {
            default: ({ items: renderedItems }) =>
              renderedItems.map((item) => h("div", { "data-testid": item.id }, item.label)),
          },
        );
      },
    });

    app.mount(container);
    await flushUi();

    try {
      expect(mapItem).toHaveBeenCalledTimes(2);
      expect(container.querySelector('[data-testid="mapped-row-1"]')?.textContent).toBe("MAPPED ROW 1");
      expect(container.querySelector('[data-testid="mapped-row-3"]')).toBeNull();

      await animationFrames.flushAll();

      expect(mapItem).toHaveBeenCalledTimes(6);
      expect(container.querySelector('[data-testid="mapped-row-6"]')?.textContent).toBe("MAPPED ROW 6");
    } finally {
      app.unmount();
      container.remove();
    }
  });

  it("remaps cached rows when the mapper version changes", async () => {
    const items = [
      { id: "versioned-row-1", label: "Row 1" },
      { id: "versioned-row-2", label: "Row 2" },
    ];
    const mapVersion = ref("v1");
    const mapItem = vi.fn((item) => ({
      id: item.id,
      label: `${mapVersion.value}:${item.label}`,
    }));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const app = createApp({
      render() {
        return h(
          ProgressiveList,
          {
            items,
            mapItem,
            mapVersion: mapVersion.value,
            enabled: false,
            testId: "progressive-versioned-map-list",
          },
          {
            default: ({ items: renderedItems }) =>
              renderedItems.map((item) => h("div", { "data-testid": item.id }, item.label)),
          },
        );
      },
    });

    app.mount(container);
    await flushUi();

    try {
      expect(mapItem).toHaveBeenCalledTimes(2);
      expect(container.querySelector('[data-testid="versioned-row-1"]')?.textContent).toBe("v1:Row 1");

      mapVersion.value = "v2";
      await flushUi();

      expect(mapItem).toHaveBeenCalledTimes(4);
      expect(container.querySelector('[data-testid="versioned-row-1"]')?.textContent).toBe("v2:Row 1");
    } finally {
      app.unmount();
      container.remove();
    }
  });

  it("pauses pending batches while deactivated and resumes after activation", async () => {
    const animationFrames = createAnimationFrameController();
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));

    const visible = ref(true);
    const items = Array.from({ length: 6 }, (_, index) => ({
      id: `progressive-row-${index + 1}`,
      label: `Progressive row ${index + 1}`,
    }));
    const Placeholder = {
      name: "ProgressiveListPlaceholder",
      render() {
        return h("section", { "data-testid": "progressive-placeholder" }, "hidden");
      },
    };
    const container = document.createElement("div");
    document.body.appendChild(container);
    const app = createApp({
      render() {
        return h(KeepAlive, null, () =>
          visible.value
            ? h(
              ProgressiveList,
              {
                items,
                initialCount: 2,
                batchSize: 2,
                threshold: 2,
                testId: "progressive-list-under-test",
              },
              {
                default: ({ items: renderedItems }) =>
                  renderedItems.map((item) =>
                    h("div", { "data-testid": item.id }, item.label),
                  ),
              },
            )
            : h(Placeholder),
        );
      },
    });

    app.mount(container);
    await flushUi();

    try {
      expect(container.querySelectorAll('[data-testid^="progressive-row-"]')).toHaveLength(2);

      visible.value = false;
      await flushUi();
      expect(container.querySelector('[data-testid="progressive-placeholder"]')).not.toBeNull();

      await animationFrames.flushAll();

      visible.value = true;
      await flushUi();
      expect(container.querySelectorAll('[data-testid^="progressive-row-"]')).toHaveLength(2);

      await animationFrames.flushAll();

      expect(container.querySelectorAll('[data-testid^="progressive-row-"]')).toHaveLength(6);
      expect(container.querySelector('[data-testid="progressive-row-6"]')).not.toBeNull();
    } finally {
      app.unmount();
      container.remove();
    }
  });
});
