import { describe, expect, it } from "vitest";

import {
  buildVirtualWindow,
  resolvePinnedIndexes,
  resolveVisibleIndexes,
} from "../src/lib/virtualList";

function sumHeights(startIndex, endIndex, estimatedItemHeight) {
  let total = 0;

  for (let index = startIndex; index < endIndex; index += 1) {
    total += estimatedItemHeight;
  }

  return total;
}

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
    expect(state.totalHeight).toBe(6 * 48);
    expect(state.renderedEntries.map((entry) => entry.index)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("keeps pinned rows mounted while preserving total scroll geometry", () => {
    const items = Array.from({ length: 40 }, (_, index) => ({ id: `row-${index}` }));
    const estimatedItemHeight = 18;
    const viewportHeight = 54;
    const scrollTop = 54;
    const visibleRange = resolveVisibleIndexes({
      items,
      viewportHeight,
      scrollTop,
      estimatedItemHeight,
      overscan: 1,
      measuredHeights: {},
    });

    const state = buildVirtualWindow({
      items,
      itemKey: "id",
      viewportHeight,
      scrollTop,
      estimatedItemHeight,
      overscan: 1,
      threshold: 10,
      measuredHeights: {},
      pinnedKeys: ["row-1", "row-35"],
    });

    expect(state.virtualized).toBe(true);
    expect(state.visibleKeys).toEqual(["row-1", "row-2", "row-3", "row-4", "row-5", "row-6", "row-35"]);
    expect(state.visibleKeys).toContain("row-35");
    expect(state.totalHeight).toBe(items.length * estimatedItemHeight);
    expect(state.renderedEntries.map((entry) => entry.index)).toEqual([1, 2, 3, 4, 5, 6, 35]);
    expect(state.renderedEntries.map((entry) => entry.offsetTop)).toEqual([18, 36, 54, 72, 90, 108, 630]);
    expect(state.renderedEntries.find((entry) => entry.index === 35)).toMatchObject({
      pinned: true,
      inViewport: false,
      offsetTop: 630,
      height: estimatedItemHeight,
    });
    expect(
      state.topSpacerHeight +
        sumHeights(visibleRange.startIndex, visibleRange.endIndex, estimatedItemHeight) +
        state.bottomSpacerHeight,
    ).toBe(state.totalHeight);
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
