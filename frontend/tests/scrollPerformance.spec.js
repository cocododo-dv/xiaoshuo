// @vitest-environment jsdom

import { KeepAlive, createApp, h, nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AuthorWorkspaceView from "../src/views/AuthorWorkspaceView.vue";
import IndexConsoleView from "../src/views/IndexConsoleView.vue";
import { useShellRouter } from "../src/router";
import { useAuthorWorkspaceStore } from "../src/stores/authorWorkspace";
import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useReviewInboxStore } from "../src/stores/reviewInbox";
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
