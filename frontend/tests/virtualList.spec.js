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
