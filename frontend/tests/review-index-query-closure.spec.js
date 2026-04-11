import { existsSync, readFileSync } from "node:fs";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchAliasScopes,
  fetchHumanReviewEvents,
  fetchIndexJobs,
  fetchIndexRuntimeLedger,
  fetchReviewItems,
} from "../src/lib/api";
import { isIndexFocusVisible, isReviewFocusVisible } from "../src/lib/filterFocus";
import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useReviewInboxStore } from "../src/stores/reviewInbox";

describe("query filter helpers", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, data: { items: [], target_activity_groups: [] } }),
    });
  });

  it("serializes review and index query params", async () => {
    await fetchReviewItems({
      status: "pending",
      itemType: "style_observation",
      targetCollection: "style_observations",
      sceneId: "CH001_SC01",
      chapterId: "CH001",
    });
    await fetchHumanReviewEvents({
      status: "needs_followup",
      eventSource: "idempotency_recovery",
      priority: "high",
      owner: "ops.duwei",
    });
    await fetchAliasScopes({
      objectType: "style_observation",
      scope: "global",
      scopeRefId: "global",
      verifyStatus: "succeeded",
    });
    await fetchIndexJobs({
      jobType: "verify",
      status: "failed",
      reviewId: "review_scene_pending",
    });
    await fetchIndexRuntimeLedger({
      targetRef: "review_item:review_scene_pending",
      source: "operator_action",
      actorRef: "ops.duwei",
    });

    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/v1/review-items?status=pending&item_type=style_observation&target_collection=style_observations&scene_id=CH001_SC01&chapter_id=CH001",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/v1/human-review-events?status=needs_followup&event_source=idempotency_recovery&priority=high&owner=ops.duwei",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8000/api/v1/index/alias-scopes?object_type=style_observation&scope=global&scope_ref_id=global&verify_status=succeeded",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      4,
      "http://127.0.0.1:8000/api/v1/index/jobs?job_type=verify&status=failed&review_id=review_scene_pending",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      5,
      "http://127.0.0.1:8000/api/v1/index/runtime-ledger?target_ref=review_item%3Areview_scene_pending&source=operator_action&actor_ref=ops.duwei",
    );
  });

  it("reloads both stores with persisted filters", async () => {
    const reviewStore = useReviewInboxStore();
    reviewStore.reviewFilters.status = "pending";
    reviewStore.humanReviewFilters.eventSource = "idempotency_recovery";

    const indexStore = useIndexConsoleStore();
    indexStore.jobFilters.jobType = "verify";
    indexStore.ledgerFilters.targetRef = "review_item:review_scene_pending";

    await reviewStore.load();
    await indexStore.load();

    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/review-items?status=pending"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/human-review-events?event_source=idempotency_recovery"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/index/alias-scopes"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/index/jobs?job_type=verify"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/index/runtime-ledger?target_ref=review_item%3Areview_scene_pending"));
  });
});

describe("focus visibility helpers", () => {
  it("drops review focus when the filtered payload no longer contains the focused row", () => {
    expect(
      isReviewFocusVisible(
        { target_type: "review_item", target_id: "review_scene_pending", target_ref: "review_item:review_scene_pending" },
        [{ review_id: "review_other" }],
        [],
      ),
    ).toBe(false);
  });

  it("drops index focus when the filtered payload removes the focused target", () => {
    expect(
      isIndexFocusVisible(
        { target_type: "verify_job", target_id: "verify_job_match", target_ref: "verify_job:verify_job_match" },
        [],
        [],
        [],
      ),
    ).toBe(false);
  });
});

describe("filter controls", () => {
  it("ships review and index filter controls with refresh and clear actions", () => {
    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");

    expect(reviewSource).toContain('data-testid="review-filter-status"');
    expect(reviewSource).toContain('data-testid="human-review-filter-clear"');
    expect(indexSource).toContain('data-testid="index-alias-filter-verify-status"');
    expect(indexSource).toContain('data-testid="index-job-filter-review-id"');
    expect(indexSource).toContain('data-testid="index-ledger-filter-target-ref"');
    expect(indexSource).toContain('data-testid="index-ledger-filter-clear"');
  });

  it("adds the focus helper module to the frontend source tree", () => {
    expect(existsSync(new URL("../src/lib/filterFocus.js", import.meta.url))).toBe(true);
  });
});
