import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

describe("review inbox scroll architecture", () => {
  it("routes review inbox cards through VirtualList", () => {
    const source = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");

    expect(source).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(source).toContain("<VirtualList");
    expect(source).toContain('item-key="review_id"');
    expect(source).toContain(":items=\"prioritizedReviewItems\"");
    expect(source).toContain(":pinned-keys=\"pinnedReviewKeys\"");
    expect(source).toContain("<ReviewCard");
  });

  it("routes human review details through ProgressiveList", () => {
    const source = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");

    expect(source).toContain('import ProgressiveList from "./ProgressiveList.vue"');
    expect(source).toContain("<ProgressiveList");
    expect(source).toContain('test-id="human-review-progressive-list"');
    expect(source).toContain("<article");
  });

  it("keeps the new list components wired to the Task 1 and Task 2 helpers", () => {
    const virtualListSource = readFileSync(new URL("../src/components/VirtualList.vue", import.meta.url), "utf8");
    const progressiveListSource = readFileSync(new URL("../src/components/ProgressiveList.vue", import.meta.url), "utf8");

    expect(virtualListSource).toContain('from "../lib/virtualList"');
    expect(virtualListSource).toContain("buildVirtualWindow");
    expect(progressiveListSource).toContain('from "../lib/progressiveList"');
    expect(progressiveListSource).toContain("buildProgressivePlan");
    expect(progressiveListSource).toContain("nextProgressiveCount");
  });
});
