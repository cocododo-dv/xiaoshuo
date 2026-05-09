// @vitest-environment jsdom

import { createPinia, setActivePinia } from "pinia";
import { createApp, h, nextTick } from "vue";
import { beforeEach, describe, expect, it } from "vitest";

import { useShellRouter } from "../src/router";
import { useReferenceLearningStore } from "../src/stores/referenceLearning";
import { useReviewInboxStore } from "../src/stores/reviewInbox";
import { useSnowflakeWorkbenchStore } from "../src/stores/snowflakeWorkbench";
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

describe("writer path progress", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
    useShellRouter().reset();
  });

  it("maps writer path store state into stable task statuses without loading data", async () => {
    const { useWriterPathProgress } = await import("../src/composables/useWriterPathProgress.js");
    const snowflake = useSnowflakeWorkbenchStore();
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
    reference.currentRound = {
      findings: [{ finding_id: "F1", review: { review_id: "R1", status: "pending" } }],
    };

    review.loaded = true;
    review.items = [{ review_id: "R2", status: "needs_author" }];
    review.humanReviewItems = [{ event_id: "H1", status: "resolved" }];

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
    reference.detail = {
      book: { book_id: "BOOK_READY" },
      profiles: [{ profile_id: "PROFILE_READY", status: "ready" }],
    };

    review.loaded = true;
    review.items = [];
    review.humanReviewItems = [];

    const { items } = useWriterPathProgress();
    const byId = Object.fromEntries(items.value.map((item) => [item.viewId, item]));

    expect(byId["snowflake-workbench"].status).toBe("done");
    expect(byId["writer-room"].status).toBe("done");
    expect(byId.reference.status).toBe("done");
    expect(byId.review.status).toBe("done");

    setActivePinia(createPinia());
    useShellRouter().reset();
    const fresh = useWriterPathProgress();
    const freshById = Object.fromEntries(fresh.items.value.map((item) => [item.viewId, item]));

    expect(freshById["snowflake-workbench"].status).toBe("todo");
    expect(freshById["writer-room"].status).toBe("todo");
    expect(freshById.reference.status).toBe("todo");
    expect(freshById.review.status).toBe("todo");
  });

  it("renders accessible task buttons and navigates through the writer path", async () => {
    const { default: WriterPathProgress } = await import("../src/components/WriterPathProgress.vue");
    const router = useShellRouter();
    router.reset();

    const wrapper = mountWithPinia({
      render: () => h(WriterPathProgress),
    });

    try {
      const root = wrapper.el.querySelector('[data-testid="writer-path-progress"]');
      const summary = wrapper.el.querySelector('[data-testid="writer-path-active-summary"]');
      const reviewButton = wrapper.el.querySelector('[data-testid="writer-path-item-review"]');
      const activeButton = wrapper.el.querySelector('[data-testid="writer-path-item-snowflake-workbench"]');

      expect(root).not.toBeNull();
      expect(summary.getAttribute("role")).toBe("status");
      expect(summary.getAttribute("aria-live")).toBe("polite");
      expect(activeButton.getAttribute("aria-current")).toBe("step");
      expect(root.textContent).toContain("未开始");
      expect(root.textContent).toContain("下一步");

      reviewButton.click();
      await nextTick();

      expect(router.activeView.value).toBe("review");
      expect(wrapper.el.querySelector('[data-testid="writer-path-item-review"]').getAttribute("aria-current")).toBe("step");
    } finally {
      wrapper.unmount();
    }
  });
});
