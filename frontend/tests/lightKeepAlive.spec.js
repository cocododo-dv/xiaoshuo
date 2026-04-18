import { readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { isReactive } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useReviewInboxStore } from "../src/stores/reviewInbox";

function ok(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

describe("light keep-alive shell architecture", () => {
  it("keeps light keep-alive metadata without duplicating per-view stage chrome", () => {
    const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(appSource).not.toContain("stage-chrome");
    expect(appSource).toContain("view-fade");
    expect(appSource).not.toContain("stage-settings");
    expect(appSource).not.toContain("api-base-input");
    expect(appSource).not.toContain("operator-ref-input");
    expect(routerSource).toContain('cacheMode: "light"');
    expect(routerSource).not.toContain("chromeTitle");
    expect(routerSource).not.toContain("chromeDescription");
  });

  it("replaces join-signature watchers with version markers in cached heavy views", () => {
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const authorSource = readFileSync(new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url), "utf8");
    const trashSource = readFileSync(new URL("../src/views/AuthorTrashView.vue", import.meta.url), "utf8");

    expect(indexSource).not.toContain('map((group) => group?.target?.target_ref || "").join("|")');
    expect(indexSource).not.toContain('map((item) => item.job_id || "").join("|")');
    expect(reviewSource).not.toContain('map((item) => item.review_id || "").join("|")');
    expect(reviewSource).not.toContain('map((item) => item.event_id || "").join("|")');
    expect(authorSource).not.toContain('scenes.value.map((scene) => scene.scene_id).join("|")');
    expect(authorSource).not.toContain('chapters.value.map((chapter) => `${chapter.chapter_id}:${chapter.trash_allowed}`).join("|")');
    expect(trashSource).not.toContain('chapters.value.map((chapter) => `${chapter.chapter_id}:${chapter.restore_allowed}:${chapter.purge_allowed}`).join("|")');
    expect(trashSource).not.toContain('scenes.value.map((scene) => `${scene.scene_id}:${scene.restore_allowed}:${scene.purge_allowed}`).join("|")');
  });

  it("adds deactivated guards so cached pages pause hidden focus work", () => {
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const knowledgeSource = readFileSync(new URL("../src/views/KnowledgeConsoleView.vue", import.meta.url), "utf8");
    const workbenchSource = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(indexSource).toContain("onDeactivated");
    expect(indexSource).toContain("isViewActive");
    expect(reviewSource).toContain("onDeactivated");
    expect(reviewSource).toContain("isViewActive");
    expect(knowledgeSource).toContain("onDeactivated");
    expect(knowledgeSource).toContain("isViewActive");
    expect(workbenchSource).toContain("onDeactivated");
    expect(workbenchSource).toContain("isViewActive");
  });

  it("keeps cached heavy surfaces routed through shared list primitives", () => {
    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const authorSource = readFileSync(new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url), "utf8");
    const virtualListSource = readFileSync(new URL("../src/components/VirtualList.vue", import.meta.url), "utf8");
    const progressiveListSource = readFileSync(new URL("../src/components/ProgressiveList.vue", import.meta.url), "utf8");

    expect(reviewSource).toContain('test-id="review-inbox-virtual-list"');
    expect(indexSource).toContain('test-id="index-target-groups-virtual-list"');
    expect(authorSource).toContain('test-id="author-chapter-virtual-list"');
    expect(reviewSource).toContain("onDeactivated");
    expect(indexSource).toContain("onDeactivated");
    expect(virtualListSource).toContain('class="virtual-list"');
    expect(virtualListSource).toContain('class="virtual-list-row"');
    expect(progressiveListSource).toContain('class="progressive-list"');
  });
});

describe("versioned visibility lookups", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("tracks review item versions and visible human review lookups without scanning arrays", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/review-items")) {
        return ok({
          items: [
            { review_id: "review_demo", status: "pending" },
            { review_id: "review_demo_2", status: "approved" },
          ],
          pagination: { has_next: false, next_cursor: null, returned: 2, total: 2, limit: 25, mode: "cursor" },
        });
      }
      if (url.includes("/human-review-events")) {
        return ok({
          items: [
            { event_id: "recovery_demo", event_source: "idempotency_recovery", status: "pending" },
            { event_id: "manual_demo", event_source: "manual_scene_review", status: "pending" },
          ],
          pagination: { has_next: false, next_cursor: null, returned: 2, total: 2, limit: 25, mode: "cursor" },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useReviewInboxStore();

    await store.ensureLoaded();

    expect(store.reviewItemsVersion).toBeGreaterThan(0);
    expect(store.humanReviewItemsVersion).toBeGreaterThan(0);
    expect(store.hasReviewItem("review_demo")).toBe(true);
    expect(store.hasVisibleHumanReviewEvent("recovery_demo", "")).toBe(true);
    expect(store.hasVisibleHumanReviewEvent("manual_demo", "")).toBe(false);
    expect(store.hasVisibleHumanReviewEvent("manual_demo", "manual_scene_review")).toBe(true);
  });

  it("tracks index job and target-group visibility with versioned lookups", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/vector-alias-scopes")) {
        return ok({ items: [{ alias_scope: "style_rule:global:global" }] });
      }
      if (url.includes("/jobs")) {
        return ok({
          items: [{ job_id: "verify_demo", job_type: "verify", status: "pending" }],
          pagination: { has_next: false, next_cursor: null, returned: 1, total: 1, limit: 25, mode: "cursor" },
        });
      }
      if (url.includes("/target-activity-groups")) {
        return ok({
          items: [
            {
              target: {
                target_type: "review_item",
                target_id: "review_demo",
                target_ref: "review_item:review_demo",
              },
              latest_at: "2026-04-15T00:00:00+00:00",
              activity_count: 1,
              sources: ["operator_action"],
            },
          ],
          pagination: { has_next: false, next_cursor: null, returned: 1, total: 1, limit: 25, mode: "cursor" },
        });
      }
      if (url.includes("/activity-events")) {
        return ok({
          items: [],
          pagination: { has_next: false, next_cursor: null, returned: 0, total: 0, limit: 25, mode: "cursor" },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useIndexConsoleStore();

    await store.ensureLoaded();
    await store.ensureActivitySectionLoaded("target_groups");

    expect(store.jobsVersion).toBeGreaterThan(0);
    expect(store.targetGroupsVersion).toBeGreaterThan(0);
    expect(store.hasJob("verify_demo")).toBe(true);
    expect(store.hasTargetActivityGroup("review_item:review_demo")).toBe(true);
  });

  it("keeps large store payload rows out of deep Vue reactivity", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/review-items")) {
        return ok({
          items: [{ review_id: "review_demo", status: "pending", candidate_payload_json: { nested: true } }],
          pagination: { has_next: false, next_cursor: null, returned: 1, total: 1, limit: 25, mode: "cursor" },
        });
      }
      if (url.includes("/human-review-events")) {
        return ok({
          items: [{ event_id: "event_demo", event_source: "idempotency_recovery", status: "pending" }],
          pagination: { has_next: false, next_cursor: null, returned: 1, total: 1, limit: 25, mode: "cursor" },
        });
      }
      if (url.includes("/vector-alias-scopes")) {
        return ok({ items: [{ alias_scope: "style_rule:global:global", recent_fault_summary: { details_json: {} } }] });
      }
      if (url.includes("/jobs")) {
        return ok({
          items: [{ job_id: "verify_demo", job_type: "verify", status: "pending", extra: { nested: true } }],
          pagination: { has_next: false, next_cursor: null, returned: 1, total: 1, limit: 25, mode: "cursor" },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const reviewStore = useReviewInboxStore();
    const indexStore = useIndexConsoleStore();

    await reviewStore.ensureLoaded();
    await indexStore.ensureLoaded();

    expect(isReactive(reviewStore.items[0])).toBe(false);
    expect(isReactive(reviewStore.items[0].candidate_payload_json)).toBe(false);
    expect(isReactive(reviewStore.humanReviewItems[0])).toBe(false);
    expect(isReactive(indexStore.aliasScopes[0])).toBe(false);
    expect(isReactive(indexStore.jobs[0])).toBe(false);
    expect(isReactive(indexStore.jobs[0].extra)).toBe(false);
  });
});
