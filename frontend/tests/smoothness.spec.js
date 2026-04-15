import { readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useShellRouter } from "../src/router";
import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useReviewInboxStore } from "../src/stores/reviewInbox";

function ok(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

describe("shell smoothness architecture", () => {
  it("tracks visited views for lazy cached navigation", () => {
    const router = useShellRouter();

    router.reset();
    expect(router.visitedViews.value).toEqual(["workbench"]);

    router.navigate("review");
    expect(router.activeView.value).toBe("review");
    expect(router.visitedViews.value).toEqual(["workbench", "review"]);

    router.openTarget({
      target_type: "knowledge_entry",
      target_id: "STYLE_TEST",
      target_ref: "knowledge_entry:style_rule:STYLE_TEST",
    });
    expect(router.activeView.value).toBe("knowledge");
    expect(router.visitedViews.value).toEqual(["workbench", "review", "knowledge"]);
  });

  it("ships async cached shell mounting instead of eager v-show views", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(source).toContain("defineAsyncComponent");
    expect(source).toContain("KeepAlive");
    expect(source).toContain("activeViewComponent");
    expect(source).toContain("stage-chrome");
    expect(source).toContain("view-fade");
    expect(routerSource).toContain('cacheMode: "light"');
    expect(source).not.toContain("v-show=\"activeView === 'author'\"");
    expect(source).not.toContain("v-show=\"activeView === 'workbench'\"");
  });

  it("keeps shell refresh reloaders lazy instead of eagerly importing every heavy store", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

    expect(source).not.toContain('from "./stores/authorTrash"');
    expect(source).not.toContain('from "./stores/authorWorkspace"');
    expect(source).not.toContain('from "./stores/indexConsole"');
    expect(source).not.toContain('from "./stores/knowledgeConsole"');
    expect(source).not.toContain('from "./stores/reviewInbox"');
    expect(source).not.toContain('from "./stores/workbench"');
    expect(source).not.toContain("const authorTrash =");
    expect(source).not.toContain("const authorWorkspace =");
    expect(source).not.toContain("const indexConsole =");
    expect(source).toContain('import("./stores/authorWorkspace")');
    expect(source).toContain('import("./stores/indexConsole")');
  });

  it("collapses heavy detail blocks behind explicit toggles", () => {
    const reviewCardSource = readFileSync(new URL("../src/components/ReviewCard.vue", import.meta.url), "utf8");
    const aliasScopeCardSource = readFileSync(new URL("../src/components/AliasScopeCard.vue", import.meta.url), "utf8");
    const humanReviewSource = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");

    expect(reviewCardSource).toContain("review-toggle-payload");
    expect(aliasScopeCardSource).toContain("alias-scope-toggle-fault");
    expect(humanReviewSource).toContain("human-review-toggle-details");
  });

  it("routes index console long lists through the shared virtual and progressive list drivers", () => {
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const targetGroupCardSource = readFileSync(new URL("../src/components/TargetActivityGroupCard.vue", import.meta.url), "utf8");

    expect(indexSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(indexSource).toContain('test-id="index-jobs-virtual-list"');
    expect(indexSource).toContain('test-id="index-recovery-virtual-list"');
    expect(indexSource).toContain('test-id="index-target-groups-virtual-list"');
    expect(indexSource).toContain("const pinnedJobKeys = computed(() =>");
    expect(indexSource).toContain("const pinnedTargetGroupKeys = computed(() =>");
    expect(targetGroupCardSource).toContain('import ProgressiveList from "./ProgressiveList.vue"');
    expect(targetGroupCardSource).toContain('test-id="target-group-progressive-list"');
    expect(targetGroupCardSource).toContain(":initial-count=\"8\"");
    expect(targetGroupCardSource).toContain(":batch-size=\"6\"");
    expect(targetGroupCardSource).toContain(":threshold=\"8\"");
  });

  it("ships shared virtual and progressive list primitives for heavy in-page surfaces", () => {
    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const authorSource = readFileSync(new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url), "utf8");
    const virtualListSource = readFileSync(new URL("../src/components/VirtualList.vue", import.meta.url), "utf8");
    const progressiveListSource = readFileSync(new URL("../src/components/ProgressiveList.vue", import.meta.url), "utf8");
    const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");

    expect(reviewSource).toContain('test-id="review-inbox-virtual-list"');
    expect(indexSource).toContain('test-id="index-jobs-virtual-list"');
    expect(authorSource).toContain('test-id="author-scene-virtual-list"');
    expect(virtualListSource).toContain('class="virtual-list"');
    expect(virtualListSource).toContain('class="virtual-list-spacer"');
    expect(virtualListSource).toContain('class="virtual-list-row"');
    expect(progressiveListSource).toContain('class="progressive-list"');
    expect(styles).toContain(".virtual-list");
    expect(styles).toContain(".virtual-list-spacer");
    expect(styles).toContain(".virtual-list-row");
    expect(styles).toContain(".progressive-list");
    expect(styles).toContain("contain: layout paint");
    expect(styles).toContain("content-visibility: auto");
  });

  it("avoids deep watchers in the heaviest cached views", () => {
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");
    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");
    const authorSource = readFileSync(new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url), "utf8");
    const trashSource = readFileSync(new URL("../src/views/AuthorTrashView.vue", import.meta.url), "utf8");

    expect(indexSource).not.toContain("deep: true");
    expect(reviewSource).not.toContain("deep: true");
    expect(indexSource).toContain("onDeactivated");
    expect(reviewSource).toContain("onDeactivated");
    expect(indexSource).not.toContain('map((group) => group?.target?.target_ref || "").join("|")');
    expect(indexSource).not.toContain('map((item) => item.job_id || "").join("|")');
    expect(reviewSource).not.toContain('map((item) => item.review_id || "").join("|")');
    expect(reviewSource).not.toContain('map((item) => item.event_id || "").join("|")');
    expect(authorSource).not.toContain('scenes.value.map((scene) => scene.scene_id).join("|")');
    expect(trashSource).not.toContain('chapters.value.map((chapter) => `${chapter.chapter_id}:${chapter.restore_allowed}:${chapter.purge_allowed}`).join("|")');
  });

  it("moves knowledge and interop heavy detail work behind lazy explicit toggles", () => {
    const knowledgeSource = readFileSync(new URL("../src/views/KnowledgeConsoleView.vue", import.meta.url), "utf8");
    const interopSource = readFileSync(new URL("../src/views/InteropCenterView.vue", import.meta.url), "utf8");

    expect(knowledgeSource).toContain("knowledge-toggle-runtime-refs");
    expect(knowledgeSource).not.toContain("workflowReviewItems.filter(");
    expect(knowledgeSource).not.toContain("workflowJobs.filter(");
    expect(knowledgeSource).not.toContain("JSON.stringify(knowledgeConsole.detail.runtime_refs || {}, null, 2)");
    expect(interopSource).toContain("interop-toggle-envelope");
    expect(interopSource).not.toContain("prettyEnvelope");
  });

  it("adds viewport-aware containment styles for long scrolling surfaces", () => {
    const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");

    expect(styles).toContain("content-visibility: auto");
    expect(styles).toContain("contain-intrinsic-size");
  });
});

describe("load-on-demand stores", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("avoids reloading review data until the store becomes stale", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/review-items")) {
        return ok({
          items: [{ review_id: "review_demo", status: "pending" }],
          pagination: { has_next: false, next_cursor: null, returned: 1, total: 1, limit: 25, mode: "cursor" },
        });
      }
      if (url.includes("/human-review-events")) {
        return ok({
          items: [{ event_id: "event_demo", event_source: "idempotency_recovery", status: "pending" }],
          pagination: { has_next: false, next_cursor: null, returned: 1, total: 1, limit: 25, mode: "cursor" },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useReviewInboxStore();

    await store.ensureLoaded();
    await store.ensureLoaded();
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);

    store.markStale();
    await store.ensureLoaded();
    expect(globalThis.fetch).toHaveBeenCalledTimes(4);
  });

  it("loads index summary first and defers heavy activity streams", async () => {
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
          items: [{ target: { target_ref: "review_item:review_demo" }, activity_items: [], activity_count: 0 }],
        });
      }
      if (url.includes("/activity-events")) {
        return ok({ items: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useIndexConsoleStore();

    await store.ensureLoaded();
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/vector-alias-scopes"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/jobs"));
    expect(globalThis.fetch).not.toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events"));
    expect(store.activityLoaded).toBe(false);

    await store.ensureActivityLoaded();
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/target-activity-groups"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=recovery_timeline"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=system_runtime"));
    expect(globalThis.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/v1/activity-events?stream=operator_action"));
    expect(store.activityLoaded).toBe(true);
  });
});
