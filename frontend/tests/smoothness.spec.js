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
    expect(source).not.toContain("stage-chrome");
    expect(source).toContain("view-fade");
    expect(routerSource).toContain('cacheMode: "light"');
    expect(source).not.toContain("v-show=\"activeView === 'author'\"");
    expect(source).not.toContain("v-show=\"activeView === 'workbench'\"");
  });

  it("keeps shell navigation free of global refresh reloaders", () => {
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
    expect(source).not.toContain('import("./stores/authorWorkspace")');
    expect(source).not.toContain('import("./stores/indexConsole")');
    expect(source).not.toContain("reloadAll");
    expect(source).not.toContain("刷新已访问视图");
  });

  it("collapses heavy detail blocks behind explicit toggles", () => {
    const reviewCardSource = readFileSync(new URL("../src/components/ReviewCard.vue", import.meta.url), "utf8");
    const aliasScopeCardSource = readFileSync(new URL("../src/components/AliasScopeCard.vue", import.meta.url), "utf8");
    const humanReviewSource = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");

    expect(reviewCardSource).toContain("review-toggle-payload");
    expect(aliasScopeCardSource).toContain("alias-scope-toggle-fault");
    expect(humanReviewSource).toContain("human-review-toggle-details");
  });

  it("precomputes human review row summaries inside the progressive render window", () => {
    const progressiveListSource = readFileSync(new URL("../src/components/ProgressiveList.vue", import.meta.url), "utf8");
    const humanReviewSource = readFileSync(new URL("../src/components/HumanReviewDrawer.vue", import.meta.url), "utf8");

    expect(progressiveListSource).toContain("mapItem");
    expect(humanReviewSource).toContain(":map-item=\"humanReviewRow\"");
    expect(humanReviewSource).toContain("function humanReviewRow(item)");
    expect(humanReviewSource).toContain("historyRows(item, eventId)");
    expect(humanReviewSource).not.toContain("(item.allowed_actions_json || []).map(actionLabel).join");
    expect(humanReviewSource).not.toContain("linkedTarget(item) || followupTarget(item) || replayTarget(item)");
    expect(humanReviewSource).not.toContain("v-if=\"historyReplayTarget(entry)\"");
    expect(humanReviewSource).not.toContain("sourceFocusedTarget(historyReplayTarget(entry), row.eventId)");
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
    expect(targetGroupCardSource).toContain(":map-item=\"targetActivityRow\"");
    expect(targetGroupCardSource).toContain("function targetActivityRow(item)");
    expect(targetGroupCardSource).not.toContain("activitySummary(item)");
    expect(targetGroupCardSource).not.toContain("isHighlighted(item)");
  });

  it("precomputes index virtual list rows inside the virtual render window", () => {
    const virtualListSource = readFileSync(new URL("../src/components/VirtualList.vue", import.meta.url), "utf8");
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");

    expect(virtualListSource).toContain("mapItem");
    expect(indexSource).toContain(':map-item="indexRecoveryRow"');
    expect(indexSource).toContain(':map-item="indexSystemRuntimeRow"');
    expect(indexSource).toContain(':map-item="indexOperatorActionRow"');
    expect(indexSource).toContain(':map-item="indexTargetGroupRow"');
    expect(indexSource).toContain(':map-item="indexJobRow"');
    expect(indexSource).toContain("function indexRecoveryRow(item)");
    expect(indexSource).toContain("function indexActivityRow(sectionId, sourceType, fallbackTitle, item)");
    expect(indexSource).toContain("function indexTargetGroupRow(group)");
    expect(indexSource).toContain("function indexJobRow(item)");
    expect(indexSource).not.toContain('activityTargets(item).length');
    expect(indexSource).not.toContain('v-for="target in activityTargets(item)"');
    expect(indexSource).not.toContain("targetSummary(item)");
    expect(indexSource).not.toContain("recoveryFollowup(item) !== '-'");
    expect(indexSource).not.toContain("activeTargetGroupRef === group.target.target_ref");
    expect(indexSource).not.toContain("groupLoading(group.target.target_ref)");
    expect(indexSource).not.toContain("groupItems(group.target.target_ref)");
  });

  it("routes the remaining index timelines through VirtualList with semantic section anchors", () => {
    const indexSource = readFileSync(new URL("../src/views/IndexConsoleView.vue", import.meta.url), "utf8");

    expect(indexSource).toContain('test-id="index-system-runtime-section"');
    expect(indexSource).toContain('test-id="index-system-runtime-virtual-list"');
    expect(indexSource).toContain('test-id="index-operator-action-section"');
    expect(indexSource).toContain('test-id="index-operator-action-virtual-list"');
    expect(indexSource).toContain("const pinnedSystemRuntimeKeys = computed(() =>");
    expect(indexSource).toContain("const pinnedOperatorActionKeys = computed(() =>");
  });

  it("routes knowledge console catalog and detail histories through shared list drivers", () => {
    const knowledgeSource = readFileSync(new URL("../src/views/KnowledgeConsoleView.vue", import.meta.url), "utf8");

    expect(knowledgeSource).toContain('import ProgressiveList from "../components/ProgressiveList.vue"');
    expect(knowledgeSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(knowledgeSource).toContain("const pinnedCatalogKeys = computed(() =>");
    expect(knowledgeSource).toContain('test-id="knowledge-catalog-virtual-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-versions-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-reviews-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-jobs-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-human-review-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-activity-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-review-refs-progressive-list"');
    expect(knowledgeSource).toContain('test-id="knowledge-bundle-refs-progressive-list"');
    expect(knowledgeSource).not.toContain('v-for="item in catalogItems"');
    expect(knowledgeSource).not.toContain('v-for="version in knowledgeConsole.detail.versions || []"');
    expect(knowledgeSource).not.toContain('v-for="review in workflowReviewItems"');
    expect(knowledgeSource).not.toContain('v-for="job in workflowJobs"');
  });

  it("precomputes knowledge detail rows inside progressive render windows", () => {
    const knowledgeSource = readFileSync(new URL("../src/views/KnowledgeConsoleView.vue", import.meta.url), "utf8");

    expect(knowledgeSource).toContain(':map-item="knowledgeCatalogRow"');
    expect(knowledgeSource).toContain(':map-item="knowledgeVersionRow"');
    expect(knowledgeSource).toContain(':map-item="knowledgeWorkflowReviewRow"');
    expect(knowledgeSource).toContain(':map-item="knowledgeWorkflowJobRow"');
    expect(knowledgeSource).toContain(':map-item="knowledgeHumanReviewRow"');
    expect(knowledgeSource).toContain(':map-item="knowledgeActivityRow"');
    expect(knowledgeSource).toContain(':map-item="knowledgeReviewRefRow"');
    expect(knowledgeSource).toContain(':map-item="knowledgeBundleRefRow"');
    expect(knowledgeSource).toContain("function knowledgeCatalogRow(item)");
    expect(knowledgeSource).toContain("function knowledgeHumanReviewRow(event)");
    expect(knowledgeSource).not.toContain("selectedEntryKey === knowledgeItemKey(item)");
    expect(knowledgeSource).not.toContain("formatItemType(item.object_type)");
    expect(knowledgeSource).not.toContain("formatStatus(item.status || \"tracked\")");
    expect(knowledgeSource).not.toContain("previewSummaryText(item.active_version)");
    expect(knowledgeSource).not.toContain('<span>{{ formatStatus(review.status) }}</span>');
    expect(knowledgeSource).not.toContain('<p class="muted">{{ formatJobType(job.job_type) }}');
    expect(knowledgeSource).not.toContain('v-for="action in event.allowed_actions_json || []"');
    expect(knowledgeSource).not.toContain('<p class="muted">{{ (group.sources || []).join(", ") ||');
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

  it("precomputes author workspace virtual rows inside the virtual render window", () => {
    const authorSource = readFileSync(new URL("../src/views/AuthorWorkspaceView.vue", import.meta.url), "utf8");

    expect(authorSource).toContain(':map-item="authorChapterRow"');
    expect(authorSource).toContain(':map-item="authorSceneRow"');
    expect(authorSource).toContain(':map-version="sceneRowMapVersion"');
    expect(authorSource).toContain("function authorChapterRow(item)");
    expect(authorSource).toContain("function authorSceneRow(item)");
    expect(authorSource).toContain("const completedSceneIdSet = computed(() =>");
    expect(authorSource).not.toContain("sceneBatchLabel(scene.scene_id)");
    expect(authorSource).not.toContain("isChapterTrashAllowed(chapter)");
  });

  it("precomputes review inbox virtual rows inside the virtual render window", () => {
    const reviewSource = readFileSync(new URL("../src/views/ReviewInboxView.vue", import.meta.url), "utf8");

    expect(reviewSource).toContain(':map-item="reviewInboxRow"');
    expect(reviewSource).toContain(':map-version="reviewRowMapVersion"');
    expect(reviewSource).toContain("function reviewInboxRow(item)");
    expect(reviewSource).toContain('const reviewId = item?.review_id || ""');
    expect(reviewSource).not.toContain("focusedReviewId(item.review_id)");
    expect(reviewSource).not.toContain("reviewSourceActionLabel(item.review_id)");
    expect(reviewSource).not.toContain("reviewInbox.actionId === item.review_id");
  });

  it("routes author trash lists through shared VirtualList anchors and keeps trash list spacing shells intact", () => {
    const authorTrashSource = readFileSync(new URL("../src/views/AuthorTrashView.vue", import.meta.url), "utf8");
    const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");

    expect(authorTrashSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(authorTrashSource).toContain("const pinnedChapterKeys = computed(() =>");
    expect(authorTrashSource).toContain("const pinnedSceneKeys = computed(() =>");
    expect(authorTrashSource).toContain(':map-item="authorTrashChapterRow"');
    expect(authorTrashSource).toContain(':map-item="authorTrashSceneRow"');
    expect(authorTrashSource).toContain("function authorTrashChapterRow(item)");
    expect(authorTrashSource).toContain("function authorTrashSceneRow(item)");
    expect(authorTrashSource).toContain('test-id="author-trash-chapter-virtual-list"');
    expect(authorTrashSource).toContain('test-id="author-trash-scene-virtual-list"');
    expect(authorTrashSource).toContain(':pinned-keys="pinnedChapterKeys"');
    expect(authorTrashSource).toContain(':pinned-keys="pinnedSceneKeys"');
    expect(authorTrashSource).toContain('class="trash-list"');
    expect(authorTrashSource).not.toContain('v-for="chapter in chapters"');
    expect(authorTrashSource).not.toContain('v-for="scene in scenes"');
    expect(authorTrashSource).not.toContain("formatTimestamp(chapter.trashed_at)");
    expect(authorTrashSource).not.toContain("formatTimestamp(scene.trashed_at)");
    expect(styles).toContain(".trash-list .virtual-list-row");
  });

  it("routes interop source comparisons through the shared virtual list driver", () => {
    const interopSource = readFileSync(new URL("../src/views/InteropCenterView.vue", import.meta.url), "utf8");
    const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");

    expect(interopSource).toContain('import VirtualList from "../components/VirtualList.vue"');
    expect(interopSource).toContain("function comparisonKey(item)");
    expect(interopSource).toContain('test-id="interop-comparison-virtual-list"');
    expect(interopSource).toContain(':item-key="comparisonKey"');
    expect(interopSource).not.toContain('v-for="item in activeSourceComparisons"');
    expect(styles).toContain(".comparison-list .virtual-list-row");
  });

  it("routes scene workbench preflight and backfill lists through progressive list drivers", () => {
    const workbenchSource = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(workbenchSource).toContain('import ProgressiveList from "../components/ProgressiveList.vue"');
    expect(workbenchSource).toContain('test-id="scene-run-preflight-blocking-progressive-list"');
    expect(workbenchSource).toContain('test-id="scene-run-preflight-warning-progressive-list"');
    expect(workbenchSource).toContain('test-id="scene-run-preflight-context-progressive-list"');
    expect(workbenchSource).toContain('test-id="chapter-backfill-progressive-list"');
    expect(workbenchSource).not.toContain('v-for="item in runPreflight.blocking_items"');
    expect(workbenchSource).not.toContain('v-for="item in runPreflight.warning_items"');
    expect(workbenchSource).not.toContain('v-for="item in runPreflight.context_items"');
    expect(workbenchSource).not.toContain('v-for="item in pendingStagedBackfillItems"');
    expect(workbenchSource).toContain("DEFAULT_BACKFILL_STRATEGY");
    expect(workbenchSource).toContain("function syncSelectedStrategies(items)");
    expect(workbenchSource).not.toContain(':value="selectedStrategyFor(item.stage_id)"');
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
    expect(authorSource).not.toContain('selectedSceneIdsForTrash.value.filter((sceneId) => scenes.value.some');
    expect(trashSource).not.toContain('chapters.value.map((chapter) => `${chapter.chapter_id}:${chapter.restore_allowed}:${chapter.purge_allowed}`).join("|")');
  });

  it("moves knowledge and interop heavy detail work behind lazy explicit toggles", () => {
    const knowledgeSource = readFileSync(new URL("../src/views/KnowledgeConsoleView.vue", import.meta.url), "utf8");
    const interopSource = readFileSync(new URL("../src/views/InteropCenterView.vue", import.meta.url), "utf8");

    expect(knowledgeSource).toContain("knowledge-toggle-runtime-refs");
    expect(knowledgeSource).toContain("workflowActionItems");
    expect(knowledgeSource).not.toContain("pendingWorkflowReviewItems");
    expect(knowledgeSource).not.toContain("retryableWorkflowJobs");
    expect(knowledgeSource).not.toContain("releasableWorkflowReviews");
    expect(knowledgeSource).not.toContain("workflowJobs.value.some(");
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

  it("keeps motion and paint effects inside the smoothness budget", () => {
    const styles = readFileSync(new URL("../src/styles/app.css", import.meta.url), "utf8");
    const buttonHoverBlock = styles.match(/button:hover\s*\{[^}]*\}/)?.[0] || "";

    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
    expect(buttonHoverBlock).not.toContain("box-shadow");
    expect(styles).not.toContain("backdrop-filter");
    expect(styles).toContain("touch-action: manipulation");
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
