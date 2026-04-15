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

  it("keeps pinned rows mounted while preserving total scroll height", () => {
    const items = Array.from({ length: 40 }, (_, index) => ({ id: `row-${index}` }));
    const estimatedItemHeight = 18;
    const viewportHeight = 180;
    const scrollTop = 18 * 12;
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
      pinnedKeys: ["row-2", "row-35"],
    });

    expect(state.virtualized).toBe(true);
    expect(state.visibleKeys).toContain("row-2");
    expect(state.visibleKeys).toContain("row-35");
    expect(
      state.topSpacerHeight +
        sumHeights(visibleRange.startIndex, visibleRange.endIndex, estimatedItemHeight) +
        state.bottomSpacerHeight,
    ).toBe(items.length * estimatedItemHeight);
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
    expect(state.topSpacerHeight).toBe(0);
    expect(state.bottomSpacerHeight).toBe(items.length * estimatedItemHeight);
  });
});
