import { defineStore } from "pinia";

import { actOnHumanReviewEvent, approveReview, fetchHumanReviewEvents, fetchReviewItems, releaseReview } from "../lib/api";
import {
  advanceCursorPager,
  applyCursorPayload,
  buildCursorQuery,
  createCursorPager,
  filtersSignature,
  resetCursorPager,
  retreatCursorPager,
} from "../lib/cursorPagination";

function createReviewFilters() {
  return {
    status: "",
    itemType: "",
    targetCollection: "",
    sceneId: "",
    chapterId: "",
  };
}

function createHumanReviewFilters() {
  return {
    status: "",
    eventSource: "",
    priority: "",
    owner: "",
    sceneId: "",
    chapterId: "",
  };
}

export const useReviewInboxStore = defineStore("reviewInbox", {
  state: () => ({
    reviewFilters: createReviewFilters(),
    humanReviewFilters: createHumanReviewFilters(),
    reviewPager: createCursorPager(),
    humanReviewPager: createCursorPager(),
    reviewFilterSignature: filtersSignature(createReviewFilters()),
    humanReviewFilterSignature: filtersSignature(createHumanReviewFilters()),
    items: [],
    humanReviewItems: [],
    lastActionResult: null,
    loading: false,
    actionId: "",
    error: "",
  }),
  getters: {
    reviewPagination: (state) => state.reviewPager.pagination,
    reviewCursor: (state) => state.reviewPager.cursor,
    reviewCursorStack: (state) => state.reviewPager.cursorStack,
    humanReviewPagination: (state) => state.humanReviewPager.pagination,
    humanReviewCursor: (state) => state.humanReviewPager.cursor,
    humanReviewCursorStack: (state) => state.humanReviewPager.cursorStack,
    systemRecoveryItems: (state) =>
      (state.humanReviewItems || []).filter(
        (item) => item.event_source === "idempotency_recovery" && item.status !== "resolved",
      ),
  },
  actions: {
    clearReviewFilters() {
      this.reviewFilters = createReviewFilters();
    },
    clearHumanReviewFilters() {
      this.humanReviewFilters = createHumanReviewFilters();
    },
    syncReviewPager({ reset = false } = {}) {
      const nextSignature = filtersSignature(this.reviewFilters);
      if (reset || nextSignature !== this.reviewFilterSignature) {
        resetCursorPager(this.reviewPager);
      }
      this.reviewFilterSignature = nextSignature;
    },
    syncHumanReviewPager({ reset = false } = {}) {
      const nextSignature = filtersSignature(this.humanReviewFilters);
      if (reset || nextSignature !== this.humanReviewFilterSignature) {
        resetCursorPager(this.humanReviewPager);
      }
      this.humanReviewFilterSignature = nextSignature;
    },
    async loadReviewItems({ reset = false } = {}) {
      this.syncReviewPager({ reset });
      const payload = await fetchReviewItems({
        ...this.reviewFilters,
        ...buildCursorQuery(this.reviewPager),
      });
      this.items = applyCursorPayload(this.reviewPager, payload);
    },
    async loadHumanReviewItems({ reset = false } = {}) {
      this.syncHumanReviewPager({ reset });
      const payload = await fetchHumanReviewEvents({
        ...this.humanReviewFilters,
        ...buildCursorQuery(this.humanReviewPager),
      });
      this.humanReviewItems = applyCursorPayload(this.humanReviewPager, payload);
    },
    async load({ resetReview = false, resetHumanReview = false } = {}) {
      this.loading = true;
      this.error = "";
      try {
        await Promise.all([
          this.loadReviewItems({ reset: resetReview }),
          this.loadHumanReviewItems({ reset: resetHumanReview }),
        ]);
      } catch (error) {
        this.items = [];
        this.humanReviewItems = [];
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async nextReviewPage() {
      if (!advanceCursorPager(this.reviewPager)) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.loadReviewItems();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async previousReviewPage() {
      if (!retreatCursorPager(this.reviewPager)) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.loadReviewItems();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async nextHumanReviewPage() {
      if (!advanceCursorPager(this.humanReviewPager)) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.loadHumanReviewItems();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async previousHumanReviewPage() {
      if (!retreatCursorPager(this.humanReviewPager)) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.loadHumanReviewItems();
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async approve(reviewId) {
      this.actionId = reviewId;
      this.error = "";
      try {
        const result = await approveReview(reviewId);
        this.lastActionResult = result;
        await this.load({ resetReview: true, resetHumanReview: true });
        return `已批准 ${reviewId}${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async release(reviewId) {
      this.actionId = reviewId;
      this.error = "";
      try {
        const result = await releaseReview(reviewId);
        this.lastActionResult = result;
        await this.load({ resetReview: true, resetHumanReview: true });
        return `已发布 ${reviewId}${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async actOnHumanReviewEvent(eventId, action) {
      this.actionId = `${eventId}:${action}`;
      this.error = "";
      try {
        const result = await actOnHumanReviewEvent(eventId, action);
        this.lastActionResult = result;
        await this.load({ resetReview: true, resetHumanReview: true });
        return `已对 ${eventId} 执行动作 ${action}（${result.status || "已更新"}）`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
