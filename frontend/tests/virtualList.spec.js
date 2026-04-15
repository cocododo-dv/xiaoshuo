import { describe, expect, it } from "vitest";

import {
  buildVirtualWindow,
  buildHeightProfile,
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
    ).toEqual({ startIndex: 0, endIndex: 2 });
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
    ).toEqual({ startIndex: 2, endIndex: 4 });
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
