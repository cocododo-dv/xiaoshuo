import { describe, expect, it } from "vitest";

import {
  focusedActivityKeyForGroup,
  normalizeActivityItems,
  normalizeTargetActivityGroups,
  nextExpandedTargetRefs,
  orderedActivityItems,
  toggleExpandedTargetRef,
} from "../src/lib/targetActivity";

const GROUPS = [
  {
    target: {
      target_type: "review_item",
      target_id: "review_style_released",
      target_ref: "review_item:review_style_released",
    },
  },
  {
    target: {
      target_type: "review_item",
      target_id: "review_style_pending",
      target_ref: "review_item:review_style_pending",
    },
  },
];

describe("target activity helpers", () => {
  it("auto-expands only the focused target when the console jumps into a group", () => {
    expect(nextExpandedTargetRefs([], GROUPS, "review_item:review_style_pending")).toEqual([
      "review_item:review_style_pending",
    ]);
  });

  it("preserves manually expanded groups when there is no focus target", () => {
    expect(
      nextExpandedTargetRefs(
        ["review_item:review_style_released", "review_item:missing"],
        GROUPS,
        "",
      ),
    ).toEqual(["review_item:review_style_released"]);
  });

  it("toggles an individual target group without mutating the existing list", () => {
    const expanded = ["review_item:review_style_released"];

    expect(toggleExpandedTargetRef(expanded, "review_item:review_style_pending")).toEqual([
      "review_item:review_style_released",
      "review_item:review_style_pending",
    ]);
    expect(toggleExpandedTargetRef(expanded, "review_item:review_style_released")).toEqual([]);
    expect(expanded).toEqual(["review_item:review_style_released"]);
  });

  it("orders activity items from newest to oldest before focus is resolved", () => {
    expect(
      orderedActivityItems([
        { activity_key: "recovery", timestamp: "2026-04-10T01:35:00+00:00" },
        { activity_key: "system", timestamp: "2026-04-10T01:40:00+00:00" },
        { activity_key: "operator", timestamp: "2026-04-10T01:32:00+00:00" },
      ]).map((item) => item.activity_key),
    ).toEqual(["system", "recovery", "operator"]);
  });

  it("focuses the latest activity item inside the focused target group", () => {
    expect(
      focusedActivityKeyForGroup(
        {
          target: {
            target_ref: "review_item:review_style_released",
          },
          activity_items: [
            { activity_key: "recovery", timestamp: "2026-04-10T01:35:00+00:00" },
            { activity_key: "system", timestamp: "2026-04-10T01:40:00+00:00" },
          ],
        },
        "review_item:review_style_released",
      ),
    ).toBe("system");

    expect(
      focusedActivityKeyForGroup(
        {
          target: {
            target_ref: "review_item:review_style_released",
          },
          activity_items: [{ activity_key: "system", timestamp: "2026-04-10T01:40:00+00:00" }],
        },
        "review_item:review_style_pending",
      ),
    ).toBe("");
  });

  it("normalizes activity items once into newest-first order", () => {
    expect(
      normalizeActivityItems([
        { activity_key: "recovery", timestamp: "2026-04-10T01:35:00+00:00" },
        { activity_key: "system", timestamp: "2026-04-10T01:40:00+00:00" },
        { activity_key: "operator", timestamp: "2026-04-10T01:32:00+00:00" },
      ]).map((item) => item.activity_key),
    ).toEqual(["system", "recovery", "operator"]);
  });

  it("normalizes target groups with sorted activity items and a cached latest key", () => {
    expect(
      normalizeTargetActivityGroups([
        {
          target: {
            target_ref: "review_item:review_style_released",
          },
          activity_items: [
            { activity_key: "recovery", timestamp: "2026-04-10T01:35:00+00:00" },
            { activity_key: "system", timestamp: "2026-04-10T01:40:00+00:00" },
          ],
        },
      ]),
    ).toEqual([
      {
        target: {
          target_ref: "review_item:review_style_released",
        },
        activity_items: [
          { activity_key: "system", timestamp: "2026-04-10T01:40:00+00:00" },
          { activity_key: "recovery", timestamp: "2026-04-10T01:35:00+00:00" },
        ],
        latest_activity_key: "system",
      },
    ]);
  });

  it("preserves summary-only target groups without synthesizing heavy activity arrays", () => {
    expect(
      normalizeTargetActivityGroups([
        {
          target: {
            target_ref: "review_item:review_style_pending",
          },
          latest_activity_key: "operator_action:42",
          latest_at: "2026-04-10T01:40:00+00:00",
          activity_count: 3,
          sources: ["operator_action"],
        },
      ]),
    ).toEqual([
      {
        target: {
          target_ref: "review_item:review_style_pending",
        },
        latest_activity_key: "operator_action:42",
        latest_at: "2026-04-10T01:40:00+00:00",
        activity_count: 3,
        sources: ["operator_action"],
        activity_items: [],
      },
    ]);
  });
});
