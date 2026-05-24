// @vitest-environment jsdom

import { createPinia, setActivePinia } from "pinia";
import { createApp, h, nextTick } from "vue";
import { beforeEach, describe, expect, it } from "vitest";

import { useShellRouter } from "../src/router";
import { useReferenceLearningStore } from "../src/stores/referenceLearning";
import { useReviewInboxStore } from "../src/stores/reviewInbox";
import { useSnowflakeWorkbenchStore } from "../src/stores/snowflakeWorkbench";
import { useWriterFlowStore } from "../src/stores/writerFlow";
import { useWriterRoomStore } from "../src/stores/writerRoom";

function mountWithPinia(component) {
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp(component);
  app.use(createPinia());
  app.mount(el);
  return {
    el,
    unmount() {
      app.unmount();
      el.remove();
    },
  };
}

function seedCoreWriterPathDone() {
  const router = useShellRouter();
  const snowflake = useSnowflakeWorkbenchStore();
  const writerFlow = useWriterFlowStore();
  const writerRoom = useWriterRoomStore();
  const reference = useReferenceLearningStore();
  const review = useReviewInboxStore();

  router.reset();
  snowflake.selectedProjectId = "PRJ_COMPLETE";
  snowflake.project = { project_id: "PRJ_COMPLETE", status: "chapter_ready" };
  snowflake.loaded = true;
  snowflake.workspace = {
    project: snowflake.project,
    latest_plan: { plan_id: "PLAN_COMPLETE", status: "approved", plan_json: { chapters: [] } },
    steps: [{ step_key: "scene_details", label: "Scene details", gate_satisfied: true }],
  };

  writerFlow.applyDashboard({
    project: { project_id: "PRJ_COMPLETE", status: "completed" },
    current_chapter: null,
    review_packet: null,
    next_action: "completed",
  });

  writerRoom.applyPayload({
    target: { object_type: "chapter", object_id: "CH_DONE" },
    draft: { draft_id: "draft_done", content: "clean text" },
    primary_text: { source: "author_draft", content: "clean text" },
    proposal_cards: [],
    diagnosis: null,
  });

  reference.loaded = false;
  reference.books = [];
  reference.profiles = [];
  reference.detail = null;
  reference.currentRun = null;
  reference.lastApplicationGuidance = null;
  reference.pendingDecisionCount = 0;

  review.loaded = false;
  review.items = [];
  review.humanReviewItems = [];

  router.navigate("writer-room", { syncUrl: false });
  return { router, reference, review };
}

describe("writer path progress", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
    useShellRouter().reset();
  });

  it("maps writer path store state into stable task statuses without loading data", async () => {
    const { useWriterPathProgress } = await import("../src/composables/useWriterPathProgress.js");
    const snowflake = useSnowflakeWorkbenchStore();
    const writerFlow = useWriterFlowStore();
    const writerRoom = useWriterRoomStore();
    const reference = useReferenceLearningStore();
    const review = useReviewInboxStore();

    snowflake.selectedProjectId = "PRJ_PATH";
    snowflake.project = { project_id: "PRJ_PATH" };
    snowflake.workspace = {
      current_step_key: "one_sentence_summary",
      ready_to_materialize: false,
      steps: [{ step_key: "one_sentence_summary", label: "One sentence" }],
    };
    snowflake.dirtyStepKeys = { one_sentence_summary: true };

    writerRoom.applyPayload({
      target: { object_type: "scene", object_id: "CH001_SC01" },
      draft: { draft_id: "draft_scene", content: "saved text" },
      primary_text: { content: "saved text" },
      proposal_cards: [{ proposal_id: "P1", status: "candidate" }],
    });
    writerRoom.draftContent = "changed text";

    reference.books = [{ book_id: "BOOK_1", title: "Reference" }];
    reference.loaded = true;
    reference.pendingDecisionCount = 1;

    review.loaded = true;
    review.items = [{ review_id: "R2", status: "needs_author" }];
    review.humanReviewItems = [{ event_id: "H1", status: "resolved" }];
    writerFlow.applyDashboard({
      project: { project_id: "PRJ_PATH", status: "chapter_running", current_chapter_id: "CH001" },
      current_chapter: { chapter_id: "CH001", chapter_goal: "Draft the chapter" },
      next_action: "view_chapter_progress",
    });
    writerFlow.runStatus = { status: "running", progress_pct: 40, completed_count: 1, scene_count: 3 };

    const { items } = useWriterPathProgress();
    const byId = Object.fromEntries(items.value.map((item) => [item.viewId, item]));

    expect(byId["snowflake-workbench"]).toEqual(expect.objectContaining({
      status: "blocked",
      isLoaded: true,
      countLabel: "未保存",
    }));
    expect(byId["writer-room"]).toEqual(expect.objectContaining({
      status: "blocked",
      isLoaded: true,
      countLabel: "未保存",
    }));
    expect(byId["writer-flow"]).toEqual(expect.objectContaining({
      status: "running",
      isLoaded: true,
      countLabel: "40%",
    }));
    expect(byId.reference).toEqual(expect.objectContaining({
      status: "blocked",
      isLoaded: true,
      countLabel: "1 待审",
    }));
    expect(byId.review).toEqual(expect.objectContaining({
      status: "blocked",
      isLoaded: true,
      countLabel: "1 待决策",
    }));
  });

  it("reports done and todo states for clean loaded and unloaded writer path steps", async () => {
    const { useWriterPathProgress } = await import("../src/composables/useWriterPathProgress.js");
    const snowflake = useSnowflakeWorkbenchStore();
    const writerFlow = useWriterFlowStore();
    const writerRoom = useWriterRoomStore();
    const reference = useReferenceLearningStore();
    const review = useReviewInboxStore();

    snowflake.selectedProjectId = "PRJ_DONE";
    snowflake.project = { project_id: "PRJ_DONE" };
    snowflake.loaded = true;
    snowflake.workspace = {
      current_step_key: "scene_list",
      ready_to_materialize: true,
      steps: [{ step_key: "scene_list", label: "Scene list", gate_satisfied: true }],
    };

    writerRoom.applyPayload({
      target: { object_type: "chapter", object_id: "CH001" },
      draft: { draft_id: "draft_chapter", content: "clean text" },
      primary_text: { content: "clean text" },
      proposal_cards: [],
      diagnosis: { status: "ready" },
    });

    reference.loaded = true;
    reference.books = [{ book_id: "BOOK_READY", title: "Reference" }];
    reference.profiles = [{ profile_id: "PROFILE_READY", status: "ready" }];

    review.loaded = true;
    review.items = [];
    review.humanReviewItems = [];
    writerFlow.applyDashboard({
      project: { project_id: "PRJ_DONE", status: "chapter_final_review", current_chapter_id: "CH001" },
      current_chapter: { chapter_id: "CH001", chapter_goal: "Clean chapter" },
      review_packet: { chapter_id: "CH001", body: "ready body", body_source: "assembled" },
      next_action: "approve_chapter_final",
    });

    const { items } = useWriterPathProgress();
    const byId = Object.fromEntries(items.value.map((item) => [item.viewId, item]));

    expect(byId["snowflake-workbench"].status).toBe("done");
    expect(byId["writer-flow"].status).toBe("active");
    expect(byId["writer-room"].status).toBe("done");
    expect(byId.reference.status).toBe("done");
    expect(byId.review.status).toBe("done");

    setActivePinia(createPinia());
    useShellRouter().reset();
    const fresh = useWriterPathProgress();
    const freshById = Object.fromEntries(fresh.items.value.map((item) => [item.viewId, item]));

    expect(freshById["snowflake-workbench"].status).toBe("todo");
    expect(freshById["writer-flow"].status).toBe("todo");
    expect(freshById["writer-room"].status).toBe("todo");
    expect(freshById.reference.status).toBe("todo");
    expect(freshById.review.status).toBe("todo");
  });

  it("distinguishes materialization, outline review, and approved structure handoff states", async () => {
    const { useWriterPathProgress } = await import("../src/composables/useWriterPathProgress.js");
    const snowflake = useSnowflakeWorkbenchStore();
    const writerFlow = useWriterFlowStore();

    snowflake.selectedProjectId = "PRJ_HANDOFF";
    snowflake.project = { project_id: "PRJ_HANDOFF", status: "outline_draft" };
    snowflake.loaded = true;
    snowflake.workspace = {
      project: { project_id: "PRJ_HANDOFF", status: "outline_draft" },
      ready_to_materialize: true,
      latest_plan: null,
      materialization_gate: { status: "ready", items: [] },
      steps: [{ step_key: "scene_details", label: "Scene details", gate_satisfied: true }],
    };

    const progress = useWriterPathProgress();
    let snowflakeItem = progress.items.value.find((item) => item.viewId === "snowflake-workbench");
    expect(snowflakeItem).toEqual(expect.objectContaining({
      status: "active",
      primaryTarget: "snowflake-workbench",
    }));

    snowflake.workspace.latest_plan = { plan_id: "PLAN_1", status: "pending_review", plan_json: { chapters: [] } };
    snowflakeItem = progress.items.value.find((item) => item.viewId === "snowflake-workbench");
    expect(snowflakeItem).toEqual(expect.objectContaining({
      status: "active",
      primaryTarget: "snowflake-workbench",
    }));

    snowflake.workspace.latest_plan = { plan_id: "PLAN_1", status: "approved", plan_json: { chapters: [] } };
    snowflake.project = { project_id: "PRJ_HANDOFF", status: "chapter_ready", current_chapter_id: "PRJ_HANDOFF_CH01" };
    snowflake.workspace.project = snowflake.project;
    writerFlow.applyDashboard({
      project: snowflake.project,
      current_chapter: { chapter_id: "PRJ_HANDOFF_CH01" },
      next_action: "run_current_chapter",
    });

    snowflakeItem = progress.items.value.find((item) => item.viewId === "snowflake-workbench");
    expect(snowflakeItem).toEqual(expect.objectContaining({
      status: "done",
      primaryTarget: "writer-flow",
    }));

    progress.navigateToItem(snowflakeItem);
    expect(useShellRouter().activeView.value).toBe("writer-flow");
  });

  it("renders an interactive accessible breadcrumb and navigates core and optional steps", async () => {
    const { default: WriterPathProgress } = await import("../src/components/WriterPathProgress.vue");
    const router = useShellRouter();
    router.reset();

    const wrapper = mountWithPinia({
      render: () => h(WriterPathProgress),
    });

    try {
      const root = wrapper.el.querySelector('[data-testid="writer-path-progress"]');
      const summary = wrapper.el.querySelector('[data-testid="writer-path-active-summary"]');
      const breadcrumb = wrapper.el.querySelector('[data-testid="journey-breadcrumb"]');
      const nav = wrapper.el.querySelector('nav.journey-main-path');
      const stepConceive = wrapper.el.querySelector('[data-testid="journey-step-构思"]');
      const stepDraft = wrapper.el.querySelector('[data-testid="journey-step-起草"]');
      const stepPolish = wrapper.el.querySelector('[data-testid="journey-step-打磨"]');
      const reviewButton = wrapper.el.querySelector('[data-testid="journey-optional-review"]');

      expect(root).not.toBeNull();
      expect(breadcrumb).not.toBeNull();
      expect(summary.getAttribute("role")).toBe("status");
      expect(summary.getAttribute("aria-live")).toBe("polite");
      expect(root.textContent).toContain("还没开始");

      // Core three phases are real buttons inside a labelled nav.
      expect(nav).not.toBeNull();
      expect(nav.getAttribute("aria-label")).toBe("创作旅程");
      for (const btn of [stepConceive, stepDraft, stepPolish]) {
        expect(btn).not.toBeNull();
        expect(btn.tagName).toBe("BUTTON");
      }

      // Fresh path → 构思 is the active step and is the only one marked current.
      expect(stepConceive.getAttribute("aria-current")).toBe("step");
      expect(stepDraft.getAttribute("aria-current")).toBeNull();
      expect(stepPolish.getAttribute("aria-current")).toBeNull();

      // Clicking the 起草 phase navigates to its canonical view (writer-flow).
      stepDraft.click();
      await nextTick();
      expect(router.activeView.value).toBe("writer-flow");

      reviewButton.click();
      await nextTick();
      expect(router.activeView.value).toBe("review");
    } finally {
      wrapper.unmount();
    }
  });

  it("routes the guidance CTA to the handoff target for applied-reference and cleared-review states", async () => {
    const { useWriterPathProgress } = await import("../src/composables/useWriterPathProgress.js");
    const router = useShellRouter();
    const reference = useReferenceLearningStore();
    const review = useReviewInboxStore();

    reference.loaded = true;
    reference.books = [{ book_id: "BOOK_APPLIED", title: "Reference" }];
    reference.lastApplicationGuidance = { reviews: ["RV1"] };

    review.loaded = true;
    review.items = [];
    review.humanReviewItems = [];

    const progress = useWriterPathProgress();
    const byId = () => Object.fromEntries(progress.items.value.map((item) => [item.viewId, item]));

    const referenceCard = byId().reference;
    expect(referenceCard).toEqual(expect.objectContaining({ status: "active", primaryTarget: "review" }));
    progress.navigateToItem(referenceCard);
    expect(router.activeView.value).toBe("review");

    const reviewCard = byId().review;
    expect(reviewCard).toEqual(expect.objectContaining({ status: "done", primaryTarget: "writer-room" }));
    progress.navigateToItem(reviewCard);
    expect(router.activeView.value).toBe("writer-room");
  });

  it("does not let optional todo work extend the completed core writer path", async () => {
    const { useNextStep } = await import("../src/composables/useNextStep.js");
    const { reference } = seedCoreWriterPathDone();
    const nextStep = useNextStep();

    expect(nextStep.ctaLabel.value).toBe("全部完成");
    expect(nextStep.ctaDisabled.value).toBe(true);

    reference.loaded = true;
    reference.books = [{ book_id: "BOOK_BLOCKED", title: "Reference" }];
    reference.pendingDecisionCount = 1;

    expect(nextStep.status.value).toBe("blocked");
    expect(nextStep.headline.value).toBe("学风格");
    expect(nextStep.ctaDisabled.value).toBe(false);

    reference.pendingDecisionCount = 0;

    expect(nextStep.status.value).toBe("active");
    expect(nextStep.headline.value).toBe("学风格");
    expect(nextStep.ctaDisabled.value).toBe(false);
  });
});

describe("writer path state machine", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
    useShellRouter().reset();
  });

  function stores() {
    return {
      router: useShellRouter(),
      snowflake: useSnowflakeWorkbenchStore(),
      writerFlow: useWriterFlowStore(),
      writerRoom: useWriterRoomStore(),
      reference: useReferenceLearningStore(),
      review: useReviewInboxStore(),
    };
  }

  function seedSnowflakeApproved(s) {
    s.snowflake.selectedProjectId = "PRJ_SM";
    s.snowflake.project = { project_id: "PRJ_SM", status: "chapter_ready" };
    s.snowflake.loaded = true;
    s.snowflake.workspace = {
      project: s.snowflake.project,
      latest_plan: { plan_id: "PLAN_SM", status: "approved", plan_json: { chapters: [] } },
      steps: [{ step_key: "scene_details", label: "Scene details", gate_satisfied: true }],
    };
  }

  function seedCoreComplete(s) {
    seedSnowflakeApproved(s);
    s.writerFlow.applyDashboard({
      project: { project_id: "PRJ_SM", status: "completed" },
      current_chapter: null,
      review_packet: null,
      next_action: "completed",
    });
    s.writerRoom.applyPayload({
      target: { object_type: "chapter", object_id: "CH_DONE" },
      draft: { draft_id: "draft_done", content: "clean text" },
      primary_text: { source: "author_draft", content: "clean text" },
      proposal_cards: [],
      diagnosis: null,
    });
    s.router.navigate("writer-room", { syncUrl: false });
  }

  // Each row pins one resolved state of the path machine end-to-end through
  // useWriterPathProgress → useNextStep, asserting the user-visible contract.
  const scenarios = [
    {
      name: "fresh project → todo / start CTA / no handoff",
      seed: (s) => { s.router.navigate("snowflake-workbench", { syncUrl: false }); },
      expected: { status: "todo", headline: "想清楚故事", ctaLabel: "开始这一步", ctaDisabled: false, primaryTarget: "snowflake-workbench" },
    },
    {
      name: "long action running → running CTA is disabled",
      seed: (s) => {
        s.snowflake.selectedProjectId = "PRJ_RUN";
        s.snowflake.project = { project_id: "PRJ_RUN" };
        s.snowflake.loaded = true;
        s.snowflake.workspace = { steps: [{ step_key: "one_sentence_summary", label: "One" }] };
        s.snowflake.actionId = "ACT_RUN";
        s.router.navigate("snowflake-workbench", { syncUrl: false });
      },
      expected: { status: "running", headline: "想清楚故事", ctaLabel: "正在处理…", ctaDisabled: true, primaryTarget: "snowflake-workbench" },
    },
    {
      name: "structure approved on snowflake view → done, hands off to writer-flow",
      seed: (s) => { seedSnowflakeApproved(s); s.router.navigate("snowflake-workbench", { syncUrl: false }); },
      expected: { status: "done", headline: "想清楚故事", ctaLabel: "进入下一步", ctaDisabled: false, primaryTarget: "writer-flow" },
    },
    {
      name: "core path fully complete on writer-room → path complete",
      seed: (s) => { seedCoreComplete(s); },
      expected: { status: "done", headline: "打磨正文", ctaLabel: "全部完成", ctaDisabled: true, primaryTarget: "writer-room" },
    },
    {
      name: "completed core + blocked optional → extends into the blocker",
      seed: (s) => {
        seedCoreComplete(s);
        s.reference.loaded = true;
        s.reference.books = [{ book_id: "BOOK_B", title: "Reference" }];
        s.reference.pendingDecisionCount = 1;
      },
      expected: { status: "blocked", headline: "学风格", ctaLabel: "去处理这一步", ctaDisabled: false, primaryTarget: "reference" },
    },
    {
      name: "completed core + active optional handoff → routes to review",
      seed: (s) => {
        seedCoreComplete(s);
        s.reference.loaded = true;
        s.reference.books = [{ book_id: "BOOK_A", title: "Reference" }];
        s.reference.lastApplicationGuidance = { reviews: ["RV1"] };
      },
      expected: { status: "active", headline: "学风格", ctaLabel: "去这一步", ctaDisabled: false, primaryTarget: "review" },
    },
    {
      name: "deep link into an advanced view → falls back to first core item",
      seed: (s) => { s.router.navigate("knowledge", { syncUrl: false }); },
      expected: { status: "todo", headline: "想清楚故事", ctaLabel: "开始这一步", ctaDisabled: false, primaryTarget: "snowflake-workbench" },
    },
    {
      name: "deep link advanced + blocked review → activeItem falls back to the blocker",
      seed: (s) => {
        s.review.loaded = true;
        s.review.items = [{ review_id: "R2", status: "needs_author" }];
        s.review.humanReviewItems = [];
        s.router.navigate("knowledge", { syncUrl: false });
      },
      expected: { status: "blocked", headline: "等你确认", ctaLabel: "去处理这一步", ctaDisabled: false, primaryTarget: "review" },
    },
  ];

  it.each(scenarios)("$name", async ({ seed, expected }) => {
    const { useNextStep } = await import("../src/composables/useNextStep.js");
    seed(stores());
    const nextStep = useNextStep();
    expect({
      status: nextStep.status.value,
      headline: nextStep.headline.value,
      ctaLabel: nextStep.ctaLabel.value,
      ctaDisabled: nextStep.ctaDisabled.value,
      primaryTarget: nextStep.primaryTarget.value,
    }).toEqual(expected);
  });
});
