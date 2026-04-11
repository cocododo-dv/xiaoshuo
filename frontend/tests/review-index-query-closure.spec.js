import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchAliasScopes,
  fetchHumanReviewEvents,
  fetchIndexJobs,
  fetchIndexRuntimeLedger,
  fetchReviewItems,
} from "../src/lib/api";
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
      3,
      "http://127.0.0.1:8000/api/v1/index/alias-scopes?object_type=style_observation&scope=global&scope_ref_id=global&verify_status=succeeded",
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
