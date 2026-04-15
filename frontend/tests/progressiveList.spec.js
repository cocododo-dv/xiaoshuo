import { describe, expect, it } from "vitest";

import {
  buildProgressivePlan,
  nextProgressiveCount,
  shouldProgressivelyRender,
} from "../src/lib/progressiveList";

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
