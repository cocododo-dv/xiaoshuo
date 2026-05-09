// @vitest-environment jsdom

import { KeepAlive, createApp, h, nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AuthorWorkspaceView from "../src/views/AuthorWorkspaceView.vue";
import AuthorTrashView from "../src/views/AuthorTrashView.vue";
import InteropCenterView from "../src/views/InteropCenterView.vue";
import KnowledgeConsoleView from "../src/views/KnowledgeConsoleView.vue";
import IndexConsoleView from "../src/views/IndexConsoleView.vue";
import SceneWorkbenchView from "../src/views/SceneWorkbenchView.vue";
import { useShellRouter } from "../src/router";
import { useAuthorTrashStore } from "../src/stores/authorTrash";
import { useAuthorWorkspaceStore } from "../src/stores/authorWorkspace";
import { useInteropCenterStore } from "../src/stores/interopCenter";
import { useKnowledgeConsoleStore } from "../src/stores/knowledgeConsole";
import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useReviewInboxStore } from "../src/stores/reviewInbox";
import { useWorkbenchStore } from "../src/stores/workbench";
import ReviewInboxView from "../src/views/ReviewInboxView.vue";

function createReviewItem(index) {
  return {
    review_id: `review-${index}`,
    target_collection: "style_rule",
    candidate_text: `Candidate ${index}`,
    status: "pending",
    materialize_status: index % 2 === 0 ? "succeeded" : "pending",
    candidate_payload_json: {
      lineage_key: `lineage-${index}`,
      scope: "global",
      scope_ref_id: `scope-${index}`,
      scene_id: `scene-${index}`,
      chapter_id: `chapter-${index}`,
    },
  };
}

function createHumanReviewItem(index) {
  return {
    event_id: `event-${index}`,
    event_source: "idempotency_recovery",
    status: "pending",
    object_ref: `scene_card:scene-${index}`,
    details_json: {
      request_path_template: `/recovery/${index}`,
      created_by_ref: `operator-${index}`,
      created_reason: `reason-${index}`,
      action_history: [],
    },
    allowed_actions_json: ["inspect", "retry_request"],
  };
}

function createKnowledgeCatalogItem(index) {
  const objectType = index % 2 === 0 ? "style_rule" : "calibration_line";
  const lineageKey = `KNOWLEDGE_${String(index).padStart(3, "0")}`;

  return {
    object_type: objectType,
    lineage_key: lineageKey,
    status: index % 2 === 0 ? "active" : "candidate",
    active_version: {
      row_id: `active-${index}`,
      version: index,
      text: `Active knowledge text ${index}`,
    },
    candidate_version: {
      row_id: `candidate-${index}`,
      review_id: `knowledge-review-${index}`,
      text: `Candidate knowledge text ${index}`,
    },
    runtime_refs: {
      alias_scope: `style_rule:global:${index}`,
      verify_status: index % 3 === 0 ? "failed" : "succeeded",
    },
    review_refs: [`knowledge-review-${index}`],
    bundle_refs: [
      {
        bundle_id: `bundle-${index}`,
        scene_id: `CH001_SC${String(index).padStart(2, "0")}`,
        chapter_id: "CH001",
      },
    ],
  };
}

function createKnowledgeDetail(index = 14) {
  const base = createKnowledgeCatalogItem(index);

  return {
    ...base,
    versions: Array.from({ length: 18 }, (_, itemIndex) => ({
      row_id: `version-${itemIndex}`,
      version: itemIndex + 1,
      text: `Version history ${itemIndex}`,
    })),
    review_refs: Array.from({ length: 18 }, (_, itemIndex) => `knowledge-review-${itemIndex}`),
    bundle_refs: Array.from({ length: 18 }, (_, itemIndex) => ({
      bundle_id: `bundle-${itemIndex}`,
      scene_id: `CH001_SC${String(itemIndex).padStart(2, "0")}`,
      chapter_id: "CH001",
    })),
    workflow: {
      review_items: Array.from({ length: 18 }, (_, itemIndex) => ({
        review_id: `knowledge-review-${itemIndex}`,
        status: itemIndex % 2 === 0 ? "pending" : "approved",
        materialize_status: itemIndex % 3 === 0 ? "succeeded" : "pending",
        approved_item_row_id: `version-${itemIndex}`,
      })),
      jobs: Array.from({ length: 18 }, (_, itemIndex) => ({
        job_id: `knowledge-job-${itemIndex}`,
        job_type: "verify",
        review_id: `knowledge-review-${itemIndex}`,
        status: itemIndex % 2 === 0 ? "failed" : "running",
        alias_scope: `style_rule:global:${itemIndex}`,
      })),
      human_review_events: Array.from({ length: 18 }, (_, itemIndex) => ({
        event_id: `knowledge-event-${itemIndex}`,
        status: itemIndex % 2 === 0 ? "pending" : "resolved",
        default_action: "inspect",
        allowed_actions_json: ["inspect", "retry_request"],
      })),
      target_activity_groups: Array.from({ length: 18 }, (_, itemIndex) => ({
        target: {
          target_type: "review_item",
          target_id: `knowledge-review-${itemIndex}`,
          target_ref: `review_item:knowledge-review-${itemIndex}`,
        },
        activity_count: 8 + itemIndex,
        sources: ["operator_action", "system_runtime"],
      })),
      recommended_primary_action: {
        kind: "review",
        action: "approve_review",
        review_id: "knowledge-review-0",
      },
    },
  };
}

function createInteropComparison(index) {
  const objectType = index % 2 === 0 ? "style_rule" : "scene_card";
  const lineageKey = `INTEROP_${String(index).padStart(3, "0")}`;

  return {
    object_type: objectType,
    lineage_key: lineageKey,
    source_ref_key: `source_ref_${index}`,
    version_status: index % 3 === 0 ? "version_mismatch" : "same_version",
    text_status: index % 4 === 0 ? "text_mismatch" : "same_text",
    source_row_id: `source-row-${index}`,
    source_version: index,
    active_row_id: `active-row-${index}`,
    active_version: index + 1,
    source_text: `Source comparison text ${index}`,
    active_text: `Active comparison text ${index}`,
    target: {
      target_type: "knowledge_entry",
      target_id: lineageKey,
      target_ref: `knowledge_entry:${objectType}:${lineageKey}`,
      view_id: "knowledge",
    },
  };
}

async function mountInteropCenterView({ comparisonCount = 24 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = useShellRouter();
  router.reset();
  router.navigate("interop");

  const store = useInteropCenterStore();
  store.activeMode = "preview";
  store.activeEnvelope = {
    bundle_id: "bundle_interop_smoothness",
    scene_id: "CH001_SC01",
    chapter_id: "CH001",
    execution_mode: "P1_scripted",
  };
  store.activeArtifactReceipt = null;
  store.activeSourceComparisons = Array.from({ length: comparisonCount }, (_, index) =>
    createInteropComparison(index + 1),
  );
  store.error = "";
  store.actionId = "";

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [
        h(InteropCenterView, {
          onNotice: vi.fn(),
        }),
      ]);
    },
  });
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    app,
    store,
    router,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

async function mountKnowledgeConsoleView({ catalogCount = 24, selectedIndex = 14 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const store = useKnowledgeConsoleStore();
  store.items = Array.from({ length: catalogCount }, (_, index) => createKnowledgeCatalogItem(index));
  store.detail = createKnowledgeDetail(selectedIndex);
  store.selectedObjectType = store.detail.object_type;
  store.selectedLineageKey = store.detail.lineage_key;
  store.supportedObjectTypes = ["calibration_line", "style_rule"];
  store.loaded = true;
  store.stale = false;
  store.loading = false;
  store.actionId = "";
  store.error = "";

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [h(KnowledgeConsoleView, { onNotice: vi.fn() })]);
    },
  });
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    app,
    store,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

async function flushUi() {
  for (let index = 0; index < 4; index += 1) {
    await Promise.resolve();
    await nextTick();
  }
}

function createAnimationFrameController() {
  let nextId = 1;
  let queue = [];

  return {
    request(callback) {
      const id = nextId;
      nextId += 1;
      queue.push({ id, callback });
      return id;
    },
    cancel(id) {
      queue = queue.filter((entry) => entry.id !== id);
    },
    async flushAll() {
      while (queue.length) {
        const currentQueue = queue;
        queue = [];
        currentQueue.forEach((entry) => entry.callback(0));
        await flushUi();
      }
    },
  };
}

describe("scene workbench progressive rendering integration", () => {
  let animationFrames;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("progressively renders preflight and staged backfill lists while keeping first controls usable", async () => {
    const mounted = await mountSceneWorkbenchView({ preflightCount: 14, backfillCount: 10 });

    try {
      [
        "scene-run-preflight-blocking-progressive-list",
        "scene-run-preflight-warning-progressive-list",
        "scene-run-preflight-context-progressive-list",
        "chapter-backfill-progressive-list",
      ].forEach((testId) => {
        const list = mounted.container.querySelector(`[data-testid="${testId}"]`);
        expect(list).not.toBeNull();
        expect(list.classList.contains("progressive-list")).toBe(true);
      });

      const blockingRows = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-blocking_"]');
      const warningRows = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-warning_"]');
      const contextRows = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-context_"]');
      const backfillRows = mounted.container.querySelectorAll('[data-testid^="chapter-backfill-item-stage_"]');

      expect(blockingRows).toHaveLength(6);
      expect(warningRows).toHaveLength(6);
      expect(contextRows).toHaveLength(6);
      expect(backfillRows).toHaveLength(4);
      expect(mounted.container.querySelector('[data-testid="scene-run-preflight-item-blocking_01"]').textContent).toContain("blocking item 1");
      expect(mounted.container.querySelector('[data-testid="chapter-backfill-item-stage_01"]').textContent).toContain("Backfill marker 1");

      const strategySelect = mounted.container.querySelector('[data-testid="chapter-backfill-strategy-stage_01"]');
      strategySelect.value = "run_backfill_again";
      strategySelect.dispatchEvent(new Event("change"));
      await flushUi();

      mounted.container.querySelector('[data-testid="chapter-backfill-run-stage_01"]').click();
      await flushUi();

      expect(mounted.store.runChapterBackfill).toHaveBeenCalledWith(
        "CH_PROGRESSIVE",
        "stage_01",
        "run_backfill_again",
        "CH_PROGRESSIVE_SC01",
      );
      expect(mounted.store.lastChapterActionResult.stage_id).toBe("stage_01");

      await animationFrames.flushAll();

      const blockingRowsAfterFlush = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-blocking_"]');
      const warningRowsAfterFlush = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-warning_"]');
      const contextRowsAfterFlush = mounted.container.querySelectorAll('[data-testid^="scene-run-preflight-item-context_"]');
      const backfillRowsAfterFlush = mounted.container.querySelectorAll('[data-testid^="chapter-backfill-item-stage_"]');

      expect(blockingRowsAfterFlush).toHaveLength(14);
      expect(warningRowsAfterFlush).toHaveLength(14);
      expect(contextRowsAfterFlush).toHaveLength(14);
      expect(backfillRowsAfterFlush).toHaveLength(10);
      expect(mounted.container.querySelector('[data-testid="scene-run-preflight-item-blocking_14"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="chapter-backfill-item-stage_10"]')).not.toBeNull();
    } finally {
      mounted.unmount();
    }
  });
});

async function mountReviewInboxView({ reviewCount = 15, humanReviewCount = 10 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const store = useReviewInboxStore();
  store.assignReviewItems(Array.from({ length: reviewCount }, (_, index) => createReviewItem(index)));
  store.assignHumanReviewItems(Array.from({ length: humanReviewCount }, (_, index) => createHumanReviewItem(index)));
  store.loaded = true;
  store.stale = false;
  store.loading = false;
  store.error = "";

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp(ReviewInboxView);
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    app,
    store,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

function createIndexJob(index) {
  return {
    job_id: `verify-job-${index}`,
    job_type: "verify",
    status: index % 2 === 0 ? "pending" : "running",
    alias_scope: `style_rule:global:${index}`,
    target_snapshot_version: `snapshot-${index}`,
    target_embedding_version: `embedding-${index}`,
    worker_id: `worker-${index}`,
    attempt_no: index,
    heartbeat_at: `2026-04-15T00:${String(index).padStart(2, "0")}:00+00:00`,
    lease_expires_at: `2026-04-15T01:${String(index).padStart(2, "0")}:00+00:00`,
    started_at: `2026-04-15T00:${String(index).padStart(2, "0")}:00+00:00`,
    finished_at: index % 3 === 0 ? `2026-04-15T02:${String(index).padStart(2, "0")}:00+00:00` : "",
    error_text: "",
  };
}

function createRecoveryItem(index) {
  return {
    event_id: `recovery-${index}`,
    event_source: "idempotency_recovery",
    status: index % 2 === 0 ? "pending" : "resolved",
    actor_ref: `operator-${index}`,
    linked_target_ref: `review_item:review-${index}`,
    action: "inspect",
    resolution_reason: `resolution-${index}`,
    created_at: `2026-04-15T00:${String(index).padStart(2, "0")}:00+00:00`,
    last_action_at: `2026-04-15T00:${String(index).padStart(2, "0")}:30+00:00`,
  };
}

function createSystemRuntimeItem(index) {
  return {
    operation_id: index,
    source: "system_runtime",
    event_type: `system_event_${index}`,
    label: `System event ${index}`,
    status: index % 2 === 0 ? "succeeded" : "pending",
    actor_ref: `system-${index}`,
    timestamp: `2026-04-16T05:${String(index).padStart(2, "0")}:00+00:00`,
    summary: `System summary ${index}`,
    description: `System description ${index}`,
    target_refs: [
      {
        target_type: "review_item",
        target_id: `review-${index}`,
        target_ref: `review_item:review-${index}`,
      },
    ],
  };
}

function createOperatorActionItem(index) {
  return {
    operation_id: index,
    source: "operator_action",
    action: index % 2 === 0 ? "approve_review" : "inspect",
    label: `Operator event ${index}`,
    status: index % 2 === 0 ? "approved" : "pending",
    status_before: "pending",
    status_after: index % 2 === 0 ? "approved" : "pending",
    actor_ref: `operator-${index}`,
    timestamp: `2026-04-16T06:${String(index).padStart(2, "0")}:00+00:00`,
    summary: `Operator summary ${index}`,
    description: `Operator description ${index}`,
    target_refs: [
      {
        target_type: "review_item",
        target_id: `review-${index}`,
        target_ref: `review_item:review-${index}`,
      },
    ],
  };
}

function createTargetGroup(index) {
  return {
    target: {
      target_type: "review_item",
      target_id: `review-${index}`,
      target_ref: `review_item:review-${index}`,
    },
    latest_at: `2026-04-15T03:${String(index).padStart(2, "0")}:00+00:00`,
    activity_count: 10,
    sources: ["operator_action", "recovery_timeline"],
    latest_activity_key: `operator_action:${index}:9`,
  };
}

function createTargetGroupItem(groupIndex, itemIndex) {
  return {
    activity_key: `operator_action:${groupIndex}:${itemIndex}`,
    source: itemIndex % 2 === 0 ? "operator_action" : "recovery_timeline",
    status: itemIndex % 2 === 0 ? "resolved" : "pending",
    actor_ref: `operator-${groupIndex}-${itemIndex}`,
    timestamp: `2026-04-15T04:${String(itemIndex).padStart(2, "0")}:00+00:00`,
    label: `Activity ${groupIndex}-${itemIndex}`,
    summary: `Summary ${groupIndex}-${itemIndex}`,
    target_refs: [
      {
        target_type: "review_item",
        target_id: `review-${groupIndex}`,
        target_ref: `review_item:review-${groupIndex}`,
      },
    ],
  };
}

async function mountIndexConsoleView({
  jobCount = 15,
  recoveryCount = 15,
  systemRuntimeCount = 18,
  operatorActionCount = 18,
  targetGroupCount = 14,
  targetGroupItemCount = 10,
  focusTarget,
} = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = useShellRouter();
  router.reset();
  router.navigate("index");
  if (focusTarget) {
    router.openTarget(focusTarget, {
      view_id: "index",
      source_type: focusTarget.source_type,
      source_id: focusTarget.source_id,
    });
  }

  const store = useIndexConsoleStore();
  store.aliasScopes = [{ alias_scope: "style_rule:global:global" }];
  store.jobs = Array.from({ length: jobCount }, (_, index) => createIndexJob(index));
  store.jobsVersion = 1;
  store.jobLookup = Object.fromEntries(store.jobs.map((item) => [item.job_id, true]));
  store.recoveryTimelineItems = Array.from({ length: recoveryCount }, (_, index) => createRecoveryItem(index));
  store.systemRuntimeTimelineItems = Array.from({ length: systemRuntimeCount }, (_, index) => createSystemRuntimeItem(index + 1));
  store.operatorActionTimelineItems = Array.from({ length: operatorActionCount }, (_, index) => createOperatorActionItem(index + 1));
  store.targetActivityGroups = Array.from({ length: targetGroupCount }, (_, index) => createTargetGroup(index));
  store.targetGroupsVersion = 1;
  store.targetGroupLookup = Object.fromEntries(store.targetActivityGroups.map((group) => [group.target.target_ref, true]));
  store.targetGroupItemsByRef = Object.fromEntries(
    store.targetActivityGroups.map((group, index) => [
      group.target.target_ref,
      Array.from({ length: targetGroupItemCount }, (_, itemIndex) => createTargetGroupItem(index, itemIndex)),
    ]),
  );
  store.targetGroupMetaByRef = Object.fromEntries(
    store.targetActivityGroups.map((group) => [group.target.target_ref, {
      target: group.target,
      latestAt: group.latest_at,
      activityCount: group.activity_count,
      sources: group.sources,
      latestActivityKey: group.latest_activity_key,
    }]),
  );
  store.activitySections.recovery_timeline.loaded = true;
  store.activitySections.system_runtime.loaded = true;
  store.activitySections.operator_action.loaded = true;
  store.activitySections.target_groups.loaded = true;
  store.targetActivityGroups.forEach((group) => {
    store.targetGroupStatesByRef[group.target.target_ref] = {
      pager: {
        cursor: null,
        cursorStack: [],
        pagination: {
          has_next: false,
          next_cursor: null,
          returned: targetGroupItemCount,
          total: targetGroupItemCount,
          limit: 25,
          mode: "cursor",
        },
      },
      loaded: true,
      stale: false,
      loading: false,
    };
  });
  store.loaded = true;
  store.loading = false;
  store.activityLoaded = true;
  store.activityLoading = false;
  store.error = "";

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [
        h(IndexConsoleView, {
          onNotice: vi.fn(),
        }),
      ]);
    },
  });
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    app,
    store,
    router,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

function createAuthorChapter(index, sceneCount) {
  return {
    chapter_id: `CH${String(index).padStart(3, "0")}`,
    planned_scene_count: 2,
    chapter_goal: `Chapter goal ${index}`,
    main_plot_push: `Push ${index}`,
    emotional_target: `Emotion ${index}`,
    ending_effect: `Ending ${index}`,
    must_not: `Avoid ${index}`,
    notes: `Notes ${index}`,
    current_phase: "drafting",
    chapter_passed_scene_count: 0,
    chapter_backfill_pending_count: 0,
    active_scene_count: sceneCount,
    trashed_scene_count: 0,
    trash_allowed: 1,
    trash_block_reason: null,
  };
}

function createAuthorScene(index, chapterId) {
  return {
    scene_id: `${chapterId}_SC${String(index).padStart(2, "0")}`,
    chapter_id: chapterId,
    scene_seq: index,
    pov_character_id: `CHAR_${index}`,
    onstage_chars_json: [`CHAR_${index}`],
    location: `Location ${index}`,
    scene_goal: `Scene goal ${index}`,
    beats_json: [`Beat ${index}`],
    must_include_text: `Include ${index}`,
    forbidden_text: `Avoid ${index}`,
    exit_change: `Change ${index}`,
    hook: `Hook ${index}`,
    target_length_band: "medium",
    scene_type: "reunion",
    is_chapter_last: Number(index === 16),
    scene_status: "ready",
    current_bundle_id: null,
    current_final_scene_row_id: null,
  };
}

function createTrashChapter(index, sceneCount) {
  return {
    chapter_id: `CH${String(index).padStart(3, "0")}`,
    chapter_goal: `Trash chapter goal ${index}`,
    scene_count: sceneCount,
    trashed_at: `2026-04-15T08:${String(index).padStart(2, "0")}:00+00:00`,
    trashed_by: `operator-${index}`,
    restore_allowed: index % 2 === 0 ? 1 : 0,
    purge_allowed: 1,
    restore_block_reason: index % 2 === 0 ? null : `Restore blocked ${index}`,
    purge_block_reason: null,
  };
}

function createTrashScene(index, chapterId) {
  return {
    scene_id: `${chapterId}_SC${String(index).padStart(2, "0")}`,
    chapter_id: chapterId,
    scene_seq: index,
    scene_goal: `Trash scene goal ${index}`,
    trashed_at: `2026-04-15T09:${String(index).padStart(2, "0")}:00+00:00`,
    trashed_by: `operator-${index}`,
    restore_allowed: index % 2 === 0 ? 1 : 0,
    purge_allowed: 1,
    chapter_trashed: Number(index % 3 === 0),
    restore_block_reason: index % 2 === 0 ? null : `Restore blocked ${index}`,
    purge_block_reason: null,
  };
}

function createPreflightItem(prefix, index) {
  return {
    code: `${prefix}_${String(index).padStart(2, "0")}`,
    title: `${prefix} item ${index}`,
    detail: `Detailed ${prefix} explanation ${index}`,
    technical_hint: `${prefix}.hint.${index}`,
  };
}

function createBackfillItem(index) {
  const stageId = `stage_${String(index).padStart(2, "0")}`;

  return {
    stage_id: stageId,
    chapter_id: "CH_PROGRESSIVE",
    scene_id: "CH_PROGRESSIVE_SC01",
    marker_id: `F${String(index).padStart(2, "0")}`,
    marker_text: `Backfill marker ${index}`,
    marker_token: `{{backfill id=F${String(index).padStart(2, "0")} text="Backfill marker ${index}"}}`,
    status: "pending",
    linked_tracker_row_id: null,
    last_strategy: null,
  };
}

function createSceneWorkbenchPayload({ preflightCount = 14, backfillCount = 10 } = {}) {
  return {
    chapter_goal: {
      chapter_id: "CH_PROGRESSIVE",
      chapter_goal: "Keep progressive workbench lists smooth",
      main_plot_push: "Avoid mounting every preflight and backfill row together",
      emotional_target: "Lower operator friction",
      ending_effect: "The workbench remains responsive",
    },
    scene_card: {
      scene_id: "CH_PROGRESSIVE_SC01",
      scene_goal: "Verify progressive scene workbench lists",
      must_include_text: "Progressive clue",
      location: "Render lab",
    },
    scene_run_state: {
      scene_status: "ready",
      current_bundle_id: null,
      current_bundle_hash: null,
      current_final_scene_row_id: null,
    },
    chapter_state: {
      chapter_id: "CH_PROGRESSIVE",
      chapter_backfill_pending_count: backfillCount,
      aggregate_block_reason: "blocked_waiting_backfill",
      manual_hold_reason: null,
      mid_aggregate_enabled_effective: 0,
      last_interim_memory_row_id: null,
      last_final_memory_row_id: null,
      staged_backfill_items: Array.from({ length: backfillCount }, (_, index) => createBackfillItem(index + 1)),
    },
    run_preflight: {
      can_run: false,
      overall_status: "blocked",
      blocking_items: Array.from({ length: preflightCount }, (_, index) => createPreflightItem("blocking", index + 1)),
      warning_items: Array.from({ length: preflightCount }, (_, index) => createPreflightItem("warning", index + 1)),
      context_items: Array.from({ length: preflightCount }, (_, index) => createPreflightItem("context", index + 1)),
    },
    bundle: {
      bundle_id: null,
      bundle_snapshot_hash: null,
      snapshot: null,
    },
    generation_summary: null,
    hard_qc_summary: null,
    soft_qc_summary: null,
    rewrite_counters: {
      hard_partial_rewrite_count: 0,
      hard_full_rewrite_count: 0,
      soft_patch_count: 0,
      repeat_issue_key: null,
      repeat_issue_count: 0,
    },
    human_review_summary: null,
    neutral_draft: { row_id: "draft_neutral_progressive", content: "Neutral progressive draft" },
    style_draft: { row_id: "draft_style_progressive", content: "Style progressive draft" },
    final_scene: null,
    scene_memory: null,
    attempts: [],
  };
}

async function mountSceneWorkbenchView({ preflightCount = 14, backfillCount = 10 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = useShellRouter();
  router.reset();
  router.navigate("workbench");

  const payload = createSceneWorkbenchPayload({ preflightCount, backfillCount });
  const store = useWorkbenchStore();
  store.sceneId = payload.scene_card.scene_id;
  store.data = payload;
  store.attempts = [];
  store.attemptPager = {
    items: [],
    cursor: null,
    cursorStack: [],
    pagination: { has_next: false, next_cursor: null, returned: 0, total: 0, limit: 25, mode: "cursor" },
  };
  store.humanReviewItems = [];
  store.loaded = true;
  store.loading = false;
  store.error = "";
  store.actionId = "";
  store.ensureLoaded = vi.fn(async () => {});
  store.runChapterBackfill = vi.fn(async (chapterId, stageId, strategy, sceneId) => {
    store.lastChapterActionResult = {
      action: "run_backfill",
      chapter_id: chapterId,
      stage_id: stageId,
      strategy,
      scene_id: sceneId,
      status: "completed",
    };
    return `ran ${stageId}`;
  });

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [
        h(SceneWorkbenchView, {
          onNotice: vi.fn(),
        }),
      ]);
    },
  });
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    app,
    store,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

async function mountAuthorTrashView({ chapterCount = 24, sceneCount = 30, selectedChapterIndex = 14 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = useShellRouter();
  router.reset();
  router.navigate("trash");

  const store = useAuthorTrashStore();
  const chapters = Array.from({ length: chapterCount }, (_, index) => createTrashChapter(index + 1, sceneCount));
  const selectedChapter = chapters[selectedChapterIndex - 1];
  const scenes = Array.from({ length: sceneCount }, (_, index) => createTrashScene(index + 1, selectedChapter.chapter_id));

  store.chapters = chapters;
  store.chapterListVersion = 1;
  store.scenes = scenes;
  store.sceneListVersion = 1;
  store.loaded = true;
  store.stale = false;
  store.loading = false;
  store.error = "";
  store.actionId = "";

  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true, data: { chapters, scenes } }),
    })),
  );

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [
        h(AuthorTrashView, {
          onNotice: vi.fn(),
        }),
      ]);
    },
  });
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    app,
    store,
    router,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

async function mountAuthorWorkspaceView({ chapterCount = 14, sceneCount = 30, selectedChapterIndex = 14 } = {}) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = useShellRouter();
  router.reset();
  router.navigate("author");

  const store = useAuthorWorkspaceStore();
  const chapters = Array.from({ length: chapterCount }, (_, index) => createAuthorChapter(index + 1, sceneCount));
  const selectedChapter = chapters[selectedChapterIndex - 1];
  const scenes = Array.from({ length: sceneCount }, (_, index) => createAuthorScene(index + 1, selectedChapter.chapter_id));

  store.chapters = chapters;
  store.chapterListVersion = 1;
  store.selectedChapterId = selectedChapter.chapter_id;
  store.chapter = {
    chapter_id: selectedChapter.chapter_id,
    planned_scene_count: 2,
    mid_aggregate_enabled: 0,
    chapter_goal: selectedChapter.chapter_goal,
    main_plot_push: selectedChapter.main_plot_push,
    emotional_target: selectedChapter.emotional_target,
    ending_effect: selectedChapter.ending_effect,
    must_not: selectedChapter.must_not,
    notes: selectedChapter.notes,
  };
  store.chapterState = {
    chapter_id: selectedChapter.chapter_id,
    current_phase: "drafting",
    chapter_passed_scene_count: 0,
    chapter_backfill_pending_count: 0,
  };
  store.chapterRunStatus = {
    job_id: null,
    chapter_id: selectedChapter.chapter_id,
    job_type: "chapter_run_full",
    status: "idle",
    scene_ids: scenes.map((scene) => scene.scene_id),
    current_scene_id: null,
    completed_scene_ids: [],
    blocked_scene_id: null,
    latest_error: null,
  };
  store.scenes = scenes;
  store.sceneListVersion = 1;
  store.loaded = true;
  store.stale = false;
  store.loading = false;
  store.error = "";
  store.actionId = "";

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp({
    render() {
      return h(KeepAlive, null, [
        h(AuthorWorkspaceView, {
          onNotice: vi.fn(),
        }),
      ]);
    },
  });
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    app,
    store,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

describe("review inbox scroll performance integration", () => {
  let animationFrames;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("mounts the review inbox through VirtualList and ProgressiveList at runtime", async () => {
    const mounted = await mountReviewInboxView();

    try {
      const reviewVirtualList = mounted.container.querySelector('[data-testid="review-inbox-virtual-list"]');
      const humanReviewProgressiveList = mounted.container.querySelector('[data-testid="human-review-progressive-list"]');

      expect(reviewVirtualList).not.toBeNull();
      expect(humanReviewProgressiveList).not.toBeNull();
      expect(reviewVirtualList.classList.contains("virtual-list")).toBe(true);
      expect(reviewVirtualList.querySelector(".virtual-list-row")).not.toBeNull();
      expect(humanReviewProgressiveList.classList.contains("progressive-list")).toBe(true);
      expect(reviewVirtualList.style.maxHeight).toBe("640px");

      const reviewCards = mounted.container.querySelectorAll('[data-testid^="review-card-review-"]');
      expect(reviewCards.length).toBeGreaterThan(0);
      expect(reviewCards.length).toBeLessThan(mounted.store.items.length);
      expect(mounted.container.querySelector('[data-testid="review-card-review-0"]')).not.toBeNull();

      let humanReviewCards = mounted.container.querySelectorAll('[data-testid^="human-review-event-"]');
      expect(humanReviewCards).toHaveLength(6);
      expect(mounted.container.querySelector('[data-testid="human-review-event-event-0"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="human-review-event-event-9"]')).toBeNull();

      await animationFrames.flushAll();

      humanReviewCards = mounted.container.querySelectorAll('[data-testid^="human-review-event-"]');
      expect(humanReviewCards).toHaveLength(mounted.store.systemRecoveryItems.length);
      expect(mounted.container.querySelector('[data-testid="human-review-event-event-9"]')).not.toBeNull();
    } finally {
      mounted.unmount();
    }
  });
});

describe("knowledge console scroll performance integration", () => {
  let animationFrames;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("mounts the knowledge catalog through VirtualList and keeps the selected card pinned after scroll", async () => {
    const mounted = await mountKnowledgeConsoleView({ catalogCount: 24, selectedIndex: 14 });

    try {
      const catalogList = mounted.container.querySelector('[data-testid="knowledge-catalog-virtual-list"]');
      expect(catalogList).not.toBeNull();
      expect(catalogList.style.maxHeight).toBe("640px");

      let catalogCards = mounted.container.querySelectorAll('[data-testid^="knowledge-card-"]');
      expect(catalogCards.length).toBeGreaterThan(0);
      expect(catalogCards.length).toBeLessThan(mounted.store.items.length);
      expect(catalogCards[0].dataset.testid).toBe("knowledge-card-style_rule-KNOWLEDGE_014");
      expect(mounted.container.querySelector('[data-testid="knowledge-card-style_rule-KNOWLEDGE_014"]')).not.toBeNull();

      catalogList.scrollTop = 10000;
      catalogList.dispatchEvent(new Event("scroll"));
      await flushUi();

      catalogCards = mounted.container.querySelectorAll('[data-testid^="knowledge-card-"]');
      expect(catalogCards.length).toBeGreaterThan(0);
      expect(catalogCards.length).toBeLessThan(mounted.store.items.length);
      expect(mounted.container.querySelector('[data-testid="knowledge-card-style_rule-KNOWLEDGE_014"]')).not.toBeNull();
    } finally {
      mounted.unmount();
    }
  });

  it("progressively renders knowledge detail history lists while keeping visible actions usable", async () => {
    const mounted = await mountKnowledgeConsoleView({ catalogCount: 24, selectedIndex: 14 });

    try {
      [
        "knowledge-toggle-versions",
        "knowledge-toggle-reviews",
        "knowledge-toggle-jobs",
        "knowledge-toggle-human-review",
        "knowledge-toggle-activity",
        "knowledge-toggle-review-refs",
        "knowledge-toggle-bundle-refs",
      ].forEach((testId) => {
        const toggle = mounted.container.querySelector(`[data-testid="${testId}"]`);
        expect(toggle).not.toBeNull();
        toggle.click();
      });

      await flushUi();

      [
        "knowledge-versions-progressive-list",
        "knowledge-reviews-progressive-list",
        "knowledge-jobs-progressive-list",
        "knowledge-human-review-progressive-list",
        "knowledge-activity-progressive-list",
        "knowledge-review-refs-progressive-list",
        "knowledge-bundle-refs-progressive-list",
      ].forEach((testId) => {
        expect(mounted.container.querySelector(`[data-testid="${testId}"]`)).not.toBeNull();
      });

      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-version-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-review-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-job-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-human-review-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-activity-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-review-ref-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-bundle-ref-row-"]')).toHaveLength(6);
      expect(mounted.container.querySelector('[data-testid="knowledge-open-related-review-knowledge-review-0"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="knowledge-human-review-action-knowledge-event-0-inspect"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="knowledge-open-review-ref-knowledge-review-0"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="knowledge-open-bundle-ref-bundle-0"]')).not.toBeNull();

      await animationFrames.flushAll();

      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-version-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-review-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-job-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-human-review-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-activity-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-review-ref-row-"]')).toHaveLength(18);
      expect(mounted.container.querySelectorAll('[data-testid^="knowledge-bundle-ref-row-"]')).toHaveLength(18);
    } finally {
      mounted.unmount();
    }
  });
});

describe("index console scroll performance integration", () => {
  let animationFrames;
  let scrollIntoViewSpy;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
    scrollIntoViewSpy = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoViewSpy;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("mounts index console through VirtualList and ProgressiveList while keeping focused rows available", async () => {
    const mounted = await mountIndexConsoleView({
      focusTarget: {
        target_type: "verify_job",
        target_id: "verify-job-14",
        target_ref: "verify_job:verify-job-14",
      },
    });

    try {
      const jobsVirtualList = mounted.container.querySelector('[data-testid="index-jobs-virtual-list"]');
      expect(jobsVirtualList).not.toBeNull();
      expect(jobsVirtualList.style.maxHeight).toBe("640px");

      const jobRows = mounted.container.querySelectorAll('[data-testid^="verify-job-"]');
      expect(jobRows.length).toBeGreaterThan(0);
      expect(jobRows.length).toBeLessThan(mounted.store.jobs.length);
      expect(jobRows[0].className).toContain("readable-job-row");
      expect(jobRows[0].querySelector(".job-diagnostics").className).toContain("readable-row-meta");
      expect(jobRows[0].querySelector(".readable-tech-ref")).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="verify-job-verify-job-14"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="retry-verify-job-verify-job-14"]')).not.toBeNull();

      mounted.container.querySelector('[data-testid="index-toggle-recovery-timeline"]').click();
      await flushUi();

      const recoveryVirtualList = mounted.container.querySelector('[data-testid="index-recovery-virtual-list"]');
      expect(recoveryVirtualList).not.toBeNull();
      expect(recoveryVirtualList.style.maxHeight).toBe("560px");

      const recoveryRows = recoveryVirtualList.querySelectorAll("[data-activity-key]");
      expect(recoveryRows.length).toBeGreaterThan(0);
      expect(recoveryRows.length).toBeLessThan(mounted.store.recoveryTimelineItems.length);
      expect(mounted.container.querySelector('[data-activity-key="recovery_timeline:recovery-0"]')).not.toBeNull();
    } finally {
      mounted.unmount();
    }
  });

  it("mounts system runtime through VirtualList and keeps the focused system row mounted after scroll", async () => {
    const mounted = await mountIndexConsoleView({
      focusTarget: {
        target_type: "review_item",
        target_id: "review-14",
        target_ref: "review_item:review-14",
        view_id: "index",
        source_type: "system_activity",
        source_id: 14,
      },
    });

    try {
      const systemSection = mounted.container.querySelector('[data-testid="index-system-runtime-section"]');
      expect(systemSection).not.toBeNull();
      let systemList = systemSection.querySelector('[data-testid="index-system-runtime-virtual-list"]');
      if (!systemList) {
        systemSection.querySelector('[data-testid="index-toggle-system-runtime"]').click();
        await flushUi();
        systemList = systemSection.querySelector('[data-testid="index-system-runtime-virtual-list"]');
      }

      expect(systemList).not.toBeNull();
      expect(systemList.style.maxHeight).toBe("560px");

      let rows = systemSection.querySelectorAll('[data-activity-key^="system_runtime:"]');
      expect(rows.length).toBeGreaterThan(0);
      expect(rows.length).toBeLessThan(mounted.store.systemRuntimeTimelineItems.length);
      expect(systemSection.querySelector('[data-activity-key="system_runtime:14"]')).not.toBeNull();
      expect(systemSection.querySelector(".card-actions button")).not.toBeNull();

      systemList.scrollTop = 10000;
      systemList.dispatchEvent(new Event("scroll"));
      await flushUi();

      rows = systemSection.querySelectorAll('[data-activity-key^="system_runtime:"]');
      expect(rows.length).toBeGreaterThan(0);
      expect(rows.length).toBeLessThan(mounted.store.systemRuntimeTimelineItems.length);
      expect(systemSection.querySelector('[data-activity-key="system_runtime:14"]')).not.toBeNull();
    } finally {
      mounted.unmount();
    }
  });

  it("mounts operator action through VirtualList and keeps the focused operator row mounted after scroll", async () => {
    const mounted = await mountIndexConsoleView({
      focusTarget: {
        target_type: "review_item",
        target_id: "review-15",
        target_ref: "review_item:review-15",
        view_id: "index",
        source_type: "operator_action",
        source_id: 15,
      },
    });

    try {
      const operatorSection = mounted.container.querySelector('[data-testid="index-operator-action-section"]');
      expect(operatorSection).not.toBeNull();
      let operatorList = operatorSection.querySelector('[data-testid="index-operator-action-virtual-list"]');
      if (!operatorList) {
        operatorSection.querySelector('[data-testid="index-toggle-operator-action"]').click();
        await flushUi();
        operatorList = operatorSection.querySelector('[data-testid="index-operator-action-virtual-list"]');
      }

      expect(operatorList).not.toBeNull();
      expect(operatorList.style.maxHeight).toBe("560px");

      let rows = operatorSection.querySelectorAll('[data-activity-key^="operator_action:"]');
      expect(rows.length).toBeGreaterThan(0);
      expect(rows.length).toBeLessThan(mounted.store.operatorActionTimelineItems.length);
      expect(operatorSection.querySelector('[data-activity-key="operator_action:15"]')).not.toBeNull();
      expect(operatorSection.querySelector(".card-actions button")).not.toBeNull();

      operatorList.scrollTop = 10000;
      operatorList.dispatchEvent(new Event("scroll"));
      await flushUi();

      rows = operatorSection.querySelectorAll('[data-activity-key^="operator_action:"]');
      expect(rows.length).toBeGreaterThan(0);
      expect(rows.length).toBeLessThan(mounted.store.operatorActionTimelineItems.length);
      expect(operatorSection.querySelector('[data-activity-key="operator_action:15"]')).not.toBeNull();
    } finally {
      mounted.unmount();
    }
  });

  it("pins focused target groups and progressively reveals expanded activity items", async () => {
    const mounted = await mountIndexConsoleView({
      focusTarget: {
        target_type: "review_item",
        target_id: "review-13",
        target_ref: "review_item:review-13",
        view_id: "index",
      },
    });

    try {
      const targetGroupsSection = mounted.container.querySelector('[data-testid="index-target-groups-section"]');
      expect(targetGroupsSection).not.toBeNull();

      let groupVirtualList = targetGroupsSection.querySelector('[data-testid="index-target-groups-virtual-list"]');
      if (!groupVirtualList) {
        targetGroupsSection.querySelector('[data-testid="index-toggle-target-groups"]').click();
        await flushUi();
        groupVirtualList = targetGroupsSection.querySelector('[data-testid="index-target-groups-virtual-list"]');
      }
      expect(groupVirtualList).not.toBeNull();
      expect(groupVirtualList.classList.contains("virtual-list")).toBe(true);
      expect(groupVirtualList.querySelector(".virtual-list-row")).not.toBeNull();
      expect(groupVirtualList.style.maxHeight).toBe("640px");

      const groupCards = targetGroupsSection.querySelectorAll('[data-testid^="target-activity-group-review_item:review-"]');
      expect(groupCards.length).toBeGreaterThan(0);
      expect(groupCards.length).toBeLessThan(mounted.store.targetActivityGroups.length);
      expect(mounted.container.querySelector('[data-testid="target-activity-group-review_item:review-13"]')).not.toBeNull();

      groupVirtualList.scrollTop = 10000;
      groupVirtualList.dispatchEvent(new Event("scroll"));
      await flushUi();

      expect(mounted.container.querySelector('[data-testid="target-activity-group-review_item:review-13"]')).not.toBeNull();

      if (!targetGroupsSection.querySelector('[data-testid="target-group-progressive-list"]')) {
        targetGroupsSection.querySelector('[data-testid="target-activity-toggle-review_item:review-13"]').click();
        await flushUi();
      }

      expect(targetGroupsSection.querySelector('[data-testid="target-group-progressive-list"]')).not.toBeNull();

      let activityRows = targetGroupsSection.querySelectorAll('[data-testid^="target-activity-item-operator_action:13:"]');
      expect(activityRows).toHaveLength(8);
      expect(mounted.container.querySelector('[data-testid="target-activity-item-operator_action:13:8"]')).toBeNull();
      expect(mounted.container.querySelector('[data-testid="target-activity-item-operator_action:13:9"]')).toBeNull();
      expect(scrollIntoViewSpy).not.toHaveBeenCalled();

      await animationFrames.flushAll();

      activityRows = mounted.container.querySelectorAll('[data-testid^="target-activity-item-operator_action:13:"]');
      const lateFocusedActivity = mounted.container.querySelector('[data-testid="target-activity-item-operator_action:13:9"]');
      expect(activityRows).toHaveLength(10);
      expect(lateFocusedActivity).not.toBeNull();
      expect(scrollIntoViewSpy).toHaveBeenCalledWith({ block: "nearest", behavior: "smooth" });
      expect(scrollIntoViewSpy.mock.instances.at(-1)).toBe(lateFocusedActivity);
    } finally {
      mounted.unmount();
    }
  });
});

describe("author workspace scroll performance integration", () => {
  let animationFrames;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("mounts author workspace through VirtualList, keeps pinned rows rendered, and keeps forms outside the scroll surfaces", async () => {
    const mounted = await mountAuthorWorkspaceView();

    try {
      const chapterVirtualList = mounted.container.querySelector('[data-testid="author-chapter-virtual-list"]');
      const sceneVirtualList = mounted.container.querySelector('[data-testid="author-scene-virtual-list"]');
      const chapterForm = mounted.container.querySelector('[data-testid="author-chapter-form"]');
      const sceneForm = mounted.container.querySelector('[data-testid="author-scene-form"]');
      const chapterTrack = chapterVirtualList.firstElementChild;
      const sceneTrack = sceneVirtualList.firstElementChild;

      expect(chapterVirtualList).not.toBeNull();
      expect(sceneVirtualList).not.toBeNull();
      expect(chapterVirtualList.classList.contains("virtual-list")).toBe(true);
      expect(sceneVirtualList.classList.contains("virtual-list")).toBe(true);
      expect(chapterVirtualList.style.maxHeight).toBe("520px");
      expect(sceneVirtualList.style.maxHeight).toBe("560px");
      expect(chapterTrack.classList.contains("virtual-list-spacer")).toBe(true);
      expect(sceneTrack.classList.contains("virtual-list-spacer")).toBe(true);
      expect(chapterTrack.style.height).toBe(`${mounted.store.chapters.length * 128}px`);
      expect(sceneTrack.style.height).toBe(`${mounted.store.scenes.length * 188}px`);
      expect(chapterTrack.style.position).toBe("relative");
      expect(sceneTrack.style.position).toBe("relative");
      expect(chapterTrack.firstElementChild.classList.contains("virtual-list-row")).toBe(true);
      expect(sceneTrack.firstElementChild.classList.contains("virtual-list-row")).toBe(true);
      expect(chapterTrack.firstElementChild.style.position).toBe("absolute");
      expect(sceneTrack.firstElementChild.style.position).toBe("absolute");

      const chapterRows = mounted.container.querySelectorAll('[data-testid^="author-chapter-select-CH"]');
      expect(chapterRows.length).toBeGreaterThan(0);
      expect(chapterRows.length).toBeLessThan(mounted.store.chapters.length);
      expect(mounted.container.querySelector('[data-testid="author-chapter-select-CH014"]')).not.toBeNull();

      let sceneRows = mounted.container.querySelectorAll('[data-testid^="author-scene-row-CH014_SC"]');
      expect(sceneRows.length).toBeGreaterThan(0);
      expect(mounted.container.querySelector('[data-testid="author-scene-row-CH014_SC01"]')).not.toBeNull();

      sceneVirtualList.scrollTop = 10000;
      sceneVirtualList.dispatchEvent(new Event("scroll"));
      await flushUi();
      await animationFrames.flushAll();

      sceneRows = mounted.container.querySelectorAll('[data-testid^="author-scene-row-CH014_SC"]');
      expect(sceneRows.length).toBeGreaterThan(0);
      expect(mounted.container.querySelector('[data-testid="author-scene-row-CH014_SC01"]')).not.toBeNull();

      expect(chapterForm).not.toBeNull();
      expect(sceneForm).not.toBeNull();
      expect(chapterVirtualList.contains(chapterForm)).toBe(false);
      expect(chapterVirtualList.contains(sceneForm)).toBe(false);
      expect(sceneVirtualList.contains(chapterForm)).toBe(false);
      expect(sceneVirtualList.contains(sceneForm)).toBe(false);
    } finally {
      mounted.unmount();
    }
  });
});

describe("interop center scroll performance integration", () => {
  let animationFrames;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("virtualizes source comparisons while keeping target jump actions usable", async () => {
    const mounted = await mountInteropCenterView({ comparisonCount: 24 });

    try {
      const comparisonVirtualList = mounted.container.querySelector('[data-testid="interop-comparison-virtual-list"]');

      expect(comparisonVirtualList).not.toBeNull();
      expect(comparisonVirtualList.classList.contains("virtual-list")).toBe(true);
      expect(comparisonVirtualList.style.maxHeight).toBe("640px");
      expect(comparisonVirtualList.querySelector(".virtual-list-row")).not.toBeNull();

      const comparisonCards = mounted.container.querySelectorAll('[data-testid^="interop-source-comparison-"]');
      expect(comparisonCards.length).toBeGreaterThan(0);
      expect(comparisonCards.length).toBeLessThan(mounted.store.activeSourceComparisons.length);
      expect(mounted.container.querySelector('[data-testid="interop-source-comparison-scene_card-INTEROP_001"]')).not.toBeNull();

      mounted.container.querySelector('[data-testid="interop-source-comparison-scene_card-INTEROP_001"] button').click();
      await flushUi();

      expect(mounted.router.activeView.value).toBe("knowledge");
      expect(mounted.router.focusTarget.value.target_ref).toBe("knowledge_entry:scene_card:INTEROP_001");
    } finally {
      mounted.unmount();
    }
  });
});

describe("author trash scroll performance integration", () => {
  let animationFrames;

  beforeEach(() => {
    animationFrames = createAnimationFrameController();
    setActivePinia(createPinia());
    document.body.innerHTML = "";
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback) => animationFrames.request(callback)));
    vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  it("mounts author trash through VirtualList and keeps both trash lists virtualized at runtime", async () => {
    const mounted = await mountAuthorTrashView();

    try {
      const chapterVirtualList = mounted.container.querySelector('[data-testid="author-trash-chapter-virtual-list"]');
      const sceneVirtualList = mounted.container.querySelector('[data-testid="author-trash-scene-virtual-list"]');
      const chapterRestoreButton = mounted.container.querySelector('[data-testid="author-trash-restore-chapters-button"]');
      const chapterPurgeButton = mounted.container.querySelector('[data-testid="author-trash-purge-chapters-button"]');
      const sceneRestoreButton = mounted.container.querySelector('[data-testid="author-trash-restore-scenes-button"]');
      const scenePurgeButton = mounted.container.querySelector('[data-testid="author-trash-purge-scenes-button"]');
      const chapterCheckbox = mounted.container.querySelector('[data-testid="author-trash-chapter-select-CH002"]');
      const sceneCheckbox = mounted.container.querySelector('[data-testid="author-trash-scene-select-CH014_SC02"]');
      const chapterRow = mounted.container.querySelector('[data-testid="author-trash-chapter-row-CH002"]');
      const sceneRow = mounted.container.querySelector('[data-testid="author-trash-scene-row-CH014_SC02"]');

      expect(chapterVirtualList).not.toBeNull();
      expect(sceneVirtualList).not.toBeNull();
      expect(chapterRestoreButton).not.toBeNull();
      expect(chapterPurgeButton).not.toBeNull();
      expect(sceneRestoreButton).not.toBeNull();
      expect(scenePurgeButton).not.toBeNull();
      expect(chapterCheckbox).not.toBeNull();
      expect(sceneCheckbox).not.toBeNull();
      expect(chapterRow).not.toBeNull();
      expect(sceneRow).not.toBeNull();
      expect(chapterVirtualList.classList.contains("virtual-list")).toBe(true);
      expect(sceneVirtualList.classList.contains("virtual-list")).toBe(true);
      expect(chapterVirtualList.style.maxHeight).toBe("560px");
      expect(sceneVirtualList.style.maxHeight).toBe("560px");
      expect(chapterVirtualList.querySelector(".virtual-list-row")).not.toBeNull();
      expect(sceneVirtualList.querySelector(".virtual-list-row")).not.toBeNull();
      expect(chapterRestoreButton.disabled).toBe(true);
      expect(chapterPurgeButton.disabled).toBe(true);
      expect(sceneRestoreButton.disabled).toBe(true);
      expect(scenePurgeButton.disabled).toBe(true);

      const chapterRows = mounted.container.querySelectorAll('[data-testid^="author-trash-chapter-row-"]');
      expect(chapterRows.length).toBeGreaterThan(0);
      expect(chapterRows.length).toBeLessThan(mounted.store.chapters.length);

      let sceneRows = mounted.container.querySelectorAll('[data-testid^="author-trash-scene-row-CH014_SC"]');
      expect(sceneRows.length).toBeGreaterThan(0);
      expect(sceneRows.length).toBeLessThan(mounted.store.scenes.length);

      chapterCheckbox.click();
      sceneCheckbox.click();
      await flushUi();

      expect(chapterCheckbox.checked).toBe(true);
      expect(sceneCheckbox.checked).toBe(true);
      expect(chapterRestoreButton.disabled).toBe(false);
      expect(chapterPurgeButton.disabled).toBe(false);
      expect(sceneRestoreButton.disabled).toBe(false);
      expect(scenePurgeButton.disabled).toBe(false);

      chapterVirtualList.scrollTop = 10000;
      chapterVirtualList.dispatchEvent(new Event("scroll"));
      sceneVirtualList.scrollTop = 10000;
      sceneVirtualList.dispatchEvent(new Event("scroll"));
      await flushUi();
      await animationFrames.flushAll();

      sceneRows = mounted.container.querySelectorAll('[data-testid^="author-trash-scene-row-CH014_SC"]');
      expect(sceneRows.length).toBeGreaterThan(0);
      expect(mounted.container.querySelector('[data-testid="author-trash-chapter-row-CH002"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="author-trash-scene-row-CH014_SC02"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="author-trash-chapter-select-CH002"]')?.checked).toBe(true);
      expect(mounted.container.querySelector('[data-testid="author-trash-scene-select-CH014_SC02"]')?.checked).toBe(true);
    } finally {
      mounted.unmount();
    }
  });
});
