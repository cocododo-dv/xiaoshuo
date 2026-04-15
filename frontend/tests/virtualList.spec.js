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

  it("keeps falsy keys like 0 pinnable", () => {
    const items = [{ id: 0 }, { id: 1 }, { id: 2 }];

    expect(resolvePinnedIndexes(items, "id", [0])).toEqual([0]);
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
    ).toEqual({ startIndex: 0, endIndex: 1 });
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
    expect(state.visibleKeys).toEqual(items.map((item) => item.id));
    expect(state.topSpacerHeight).toBe(0);
    expect(state.bottomSpacerHeight).toBe(0);
    expect(state.totalHeight).toBe(6 * 48);
    expect(state.renderedEntries.map((entry) => entry.index)).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("keeps visibleItems contiguous while rendering pinned rows separately", () => {
    const items = Array.from({ length: 5 }, (_, index) => ({ id: `row-${index}` }));
    const measuredHeights = { "row-0": 60 };

    const state = buildVirtualWindow({
      items,
      itemKey: "id",
      viewportHeight: 20,
      scrollTop: 25,
      estimatedItemHeight: 10,
      overscan: 0,
      threshold: 0,
      measuredHeights,
      pinnedKeys: ["row-4"],
    });

    expect(state.visibleItems.map((item) => item.id)).toEqual(["row-0"]);
    expect(state.visibleKeys).toEqual(["row-0"]);
    expect(state.totalHeight).toBe(100);
    expect(state.renderedEntries.map((entry) => entry.index)).toEqual([0, 4]);
    expect(state.renderedEntries.map((entry) => entry.offsetTop)).toEqual([0, 90]);
    expect(state.renderedEntries.find((entry) => entry.index === 4)).toMatchObject({
      pinned: true,
      inViewport: false,
      offsetTop: 90,
      height: 10,
    });
    expect(state.topSpacerHeight).toBe(0);
    expect(state.bottomSpacerHeight).toBe(40);
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
