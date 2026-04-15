// @vitest-environment jsdom

import { createApp, nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
      expect(mounted.container.querySelector('[data-testid="review-inbox-virtual-list"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="human-review-progressive-list"]')).not.toBeNull();
      expect(mounted.container.querySelector('[data-testid="review-inbox-virtual-list"]').style.maxHeight).toBe("640px");

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
