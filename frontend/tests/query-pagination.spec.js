import { existsSync, readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";
import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useReviewInboxStore } from "../src/stores/reviewInbox";
import { useWorkbenchStore } from "../src/stores/workbench";

describe("list pagination api helpers", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, data: { items: [], pagination: null } }),
    });
  });

  it("serializes dual-stack page and cursor params for paged endpoints", async () => {
    expect(typeof api.fetchSceneAttempts).toBe("function");

    await api.fetchReviewItems({
      status: "pending",
      cursor: "review-cursor-1",
      limit: 10,
    });
    await api.fetchHumanReviewEvents({
      status: "needs_followup",
      page: 2,
      pageSize: 5,
    });
    await api.fetchJobs({
      jobType: "verify",
      workerId: "worker-alpha",
      stuckOnly: true,
      cursor: "job-cursor-1",
      limit: 15,
    });
    await api.fetchSceneAttempts("CH001_SC01", {
      page: 3,
      pageSize: 4,
    });

    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      1,
      "http://127.0.0.1:8000/api/v1/review-items?status=pending&cursor=review-cursor-1&limit=10",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      2,
      "http://127.0.0.1:8000/api/v1/human-review-events?status=needs_followup&page=2&page_size=5",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      3,
      "http://127.0.0.1:8000/api/v1/jobs?job_type=verify&worker_id=worker-alpha&stuck_only=true&cursor=job-cursor-1&limit=15",
    );
    expect(globalThis.fetch).toHaveBeenNthCalledWith(
      4,
      "http://127.0.0.1:8000/api/v1/scenes/CH001_SC01/attempts?page=3&page_size=4",
    );
  });
});

describe("paged review inbox store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes("/review-items/") && url.includes("/approve")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_id: "review_page_002",
              actor_ref: "ops.duwei",
            },
          }),
        };
      }

      if (url.includes("/review-items")) {
        const isSecondPage = url.includes("cursor=review-next-1");
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: isSecondPage
                ? [{ review_id: "review_page_001", status: "pending" }]
                : [{ review_id: "review_page_002", status: "pending" }],
              pagination: {
                mode: "cursor",
                limit: 25,
                page: null,
                page_size: null,
                returned: 1,
                total: 2,
                has_next: !isSecondPage,
                next_cursor: isSecondPage ? null : "review-next-1",
              },
            },
          }),
        };
      }

      if (url.includes("/human-review-events")) {
        const isSecondPage = url.includes("cursor=human-next-1");
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: isSecondPage
                ? [{ event_id: "human_page_001", event_source: "idempotency_recovery", status: "open" }]
                : [{ event_id: "human_page_002", event_source: "idempotency_recovery", status: "open" }],
              pagination: {
                mode: "cursor",
                limit: 25,
                page: null,
                page_size: null,
                returned: 1,
                total: 2,
                has_next: !isSecondPage,
                next_cursor: isSecondPage ? null : "human-next-1",
              },
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url} ${options.method || "GET"}`);
    });
  });

  it("tracks independent cursor stacks for review items and human review events", async () => {
    const store = useReviewInboxStore();

    await store.load();
    expect(store.items).toEqual([{ review_id: "review_page_002", status: "pending" }]);
    expect(store.reviewPagination).toEqual(
      expect.objectContaining({
        next_cursor: "review-next-1",
        total: 2,
      }),
    );
    expect(store.humanReviewPagination).toEqual(
      expect.objectContaining({
        next_cursor: "human-next-1",
        total: 2,
      }),
    );

    await store.nextReviewPage();
    expect(store.items).toEqual([{ review_id: "review_page_001", status: "pending" }]);
    expect(store.reviewCursorStack).toEqual([""]);

    await store.previousReviewPage();
    expect(store.items).toEqual([{ review_id: "review_page_002", status: "pending" }]);
    expect(store.reviewCursorStack).toEqual([]);

    await store.nextHumanReviewPage();
    expect(store.humanReviewItems).toEqual([
      { event_id: "human_page_001", event_source: "idempotency_recovery", status: "open" },
    ]);
    expect(store.humanReviewCursorStack).toEqual([""]);
  });

  it("resets the affected list cursor to the first page after approve", async () => {
    const store = useReviewInboxStore();

    await store.load();
    await store.nextReviewPage();
    expect(store.items[0].review_id).toBe("review_page_001");

    const message = await store.approve("review_page_002");

    expect(message).toContain("review_page_002");
    expect(store.reviewCursor).toBe("");
    expect(store.reviewCursorStack).toEqual([]);
    expect(store.items[0].review_id).toBe("review_page_002");
  });
});

describe("paged index console store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/vector-alias-scopes")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { items: [{ alias_scope: "style_observation:global:global" }] } }),
        };
      }

      if (url.includes("/jobs")) {
        const isSecondPage = url.includes("cursor=job-next-1");
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: isSecondPage
                ? [{ job_id: "verify_job_001", job_type: "verify", status: "running" }]
                : [{ job_id: "reindex_job_001", job_type: "reindex", status: "running" }],
              pagination: {
                mode: "cursor",
                limit: 25,
                page: null,
                page_size: null,
                returned: 1,
                total: 2,
                has_next: !isSecondPage,
                next_cursor: isSecondPage ? null : "job-next-1",
              },
            },
          }),
        };
      }

      if (url.includes("/target-activity-groups")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { items: [] } }),
        };
      }

      if (url.includes("/activity-events")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { items: [] } }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  it("applies job cursor pagination without affecting alias or ledger reads", async () => {
    const store = useIndexConsoleStore();
    store.jobFilters.workerId = "worker-alpha";
    store.jobFilters.stuckOnly = true;

    await store.load();
    expect(store.jobs).toEqual([{ job_id: "reindex_job_001", job_type: "reindex", status: "running" }]);
    expect(store.jobPagination).toEqual(
      expect.objectContaining({
        next_cursor: "job-next-1",
        total: 2,
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/jobs?worker_id=worker-alpha&stuck_only=true&limit=25"),
    );

    await store.nextJobPage();
    expect(store.jobs).toEqual([{ job_id: "verify_job_001", job_type: "verify", status: "running" }]);
    expect(store.jobCursorStack).toEqual([""]);
  });
});

describe("paged workbench attempts", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_card: { scene_id: "CH001_SC01" },
              scene_run_state: { scene_status: "ready" },
              bundle: { bundle_id: "bundle_CH001_SC01" },
              attempts: [{ attempt_id: 999, step: "legacy" }],
            },
          }),
        };
      }

      if (url.includes("/scenes/CH001_SC01/attempts")) {
        const isSecondPage = url.includes("cursor=attempt-next-1");
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: isSecondPage
                ? [{ attempt_id: 1, step: "bundle_built", status: "ok" }]
                : [{ attempt_id: 2, step: "archived", status: "ok" }],
              pagination: {
                mode: "cursor",
                limit: 25,
                page: null,
                page_size: null,
                returned: 1,
                total: 2,
                has_next: !isSecondPage,
                next_cursor: isSecondPage ? null : "attempt-next-1",
              },
            },
          }),
        };
      }

      if (url.includes("/human-review-events?scene_id=CH001_SC01")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { items: [] } }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  it("loads attempts from the dedicated paged endpoint and keeps the workbench payload compatible", async () => {
    const store = useWorkbenchStore();

    await store.refreshAll("CH001_SC01");
    expect(store.data.attempts).toEqual([{ attempt_id: 999, step: "legacy" }]);
    expect(store.attempts).toEqual([{ attempt_id: 2, step: "archived", status: "ok" }]);
    expect(store.attemptPagination).toEqual(
      expect.objectContaining({
        next_cursor: "attempt-next-1",
        total: 2,
      }),
    );

    await store.nextAttemptsPage();
    expect(store.attempts).toEqual([{ attempt_id: 1, step: "bundle_built", status: "ok" }]);
    expect(store.attemptCursorStack).toEqual([""]);
  });
});

describe("pager source wiring", () => {
  it("ships a shared cursor pager component and wires it into review, index, and workbench views", () => {
    expect(existsSync(new URL("../src/components/CursorPager.vue", import.meta.url))).toBe(true);

    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const workbenchSource = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(reviewSource).toContain("CursorPager");
    expect(reviewSource).toContain("review-items-pager");
    expect(reviewSource).toContain("human-review-pager");
    expect(indexSource).toContain("CursorPager");
    expect(indexSource).toContain("jobs-pager");
    expect(workbenchSource).toContain("CursorPager");
    expect(workbenchSource).toContain("attempts-pager");
  });
});
