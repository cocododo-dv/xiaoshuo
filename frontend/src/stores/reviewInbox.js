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

function buildLookup(items, key) {
  return (items || []).reduce((lookup, item) => {
    const value = item?.[key];
    if (value) {
      lookup[value] = true;
    }
    return lookup;
  }, {});
}

function buildHumanReviewLookups(items) {
  const byId = {};
  const bySource = {};
  const recoveryOpenById = {};
  const recoveryOpenItems = [];

  (items || []).forEach((item) => {
    if (!item?.event_id) {
      return;
    }

    byId[item.event_id] = true;

    if (!bySource[item.event_source]) {
      bySource[item.event_source] = {};
    }
    bySource[item.event_source][item.event_id] = true;

    if (item.event_source === "idempotency_recovery" && item.status !== "resolved") {
      recoveryOpenById[item.event_id] = true;
      recoveryOpenItems.push(item);
    }
  });

  return {
    byId,
    bySource,
    recoveryOpenById,
    recoveryOpenItems,
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
    reviewItemsVersion: 0,
    reviewItemLookup: {},
    humanReviewItems: [],
    humanReviewItemsVersion: 0,
    humanReviewItemLookup: {},
    humanReviewItemLookupBySource: {},
    systemRecoveryItemsCache: [],
    systemRecoveryItemLookup: {},
    lastActionResult: null,
    loaded: false,
    stale: false,
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
    systemRecoveryItems: (state) => state.systemRecoveryItemsCache,
    hasReviewItem: (state) => (reviewId) => Boolean(reviewId && state.reviewItemLookup[reviewId]),
    hasHumanReviewEvent: (state) => (eventId) => Boolean(eventId && state.humanReviewItemLookup[eventId]),
    hasVisibleHumanReviewEvent: (state) => (eventId, eventSource = "") => {
      if (!eventId) {
        return false;
      }
      if (eventSource) {
        return Boolean(state.humanReviewItemLookupBySource[eventSource]?.[eventId]);
      }
      return Boolean(state.systemRecoveryItemLookup[eventId]);
    },
  },
  actions: {
    markStale() {
      this.stale = true;
    },
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    clearReviewFilters() {
      this.reviewFilters = createReviewFilters();
      this.markStale();
    },
    clearHumanReviewFilters() {
      this.humanReviewFilters = createHumanReviewFilters();
      this.markStale();
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
    assignReviewItems(items) {
      this.items = items;
      this.reviewItemLookup = buildLookup(items, "review_id");
      this.reviewItemsVersion += 1;
    },
    assignHumanReviewItems(items) {
      const lookups = buildHumanReviewLookups(items);

      this.humanReviewItems = items;
      this.humanReviewItemLookup = lookups.byId;
      this.humanReviewItemLookupBySource = lookups.bySource;
      this.systemRecoveryItemsCache = lookups.recoveryOpenItems;
      this.systemRecoveryItemLookup = lookups.recoveryOpenById;
      this.humanReviewItemsVersion += 1;
    },
    async loadReviewItems({ reset = false } = {}) {
      this.syncReviewPager({ reset });
      const payload = await fetchReviewItems({
        ...this.reviewFilters,
        ...buildCursorQuery(this.reviewPager),
      });
      this.assignReviewItems(applyCursorPayload(this.reviewPager, payload));
    },
    async loadHumanReviewItems({ reset = false } = {}) {
      this.syncHumanReviewPager({ reset });
      const payload = await fetchHumanReviewEvents({
        ...this.humanReviewFilters,
        ...buildCursorQuery(this.humanReviewPager),
      });
      this.assignHumanReviewItems(applyCursorPayload(this.humanReviewPager, payload));
    },
    async load({ resetReview = false, resetHumanReview = false, force = false } = {}) {
      if (this.loaded && !this.stale && !force && !resetReview && !resetHumanReview) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await Promise.all([
          this.loadReviewItems({ reset: resetReview }),
          this.loadHumanReviewItems({ reset: resetHumanReview }),
        ]);
        this.markFresh();
      } catch (error) {
        this.assignReviewItems([]);
        this.assignHumanReviewItems([]);
        this.loaded = false;
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async ensureLoaded(options = {}) {
      await this.load(options);
    },
    async nextReviewPage() {
      if (!advanceCursorPager(this.reviewPager)) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.loadReviewItems();
        this.markFresh();
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
        this.markFresh();
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
        this.markFresh();
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
        this.markFresh();
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
        await this.load({ resetReview: true, resetHumanReview: true, force: true });
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
        await this.load({ resetReview: true, resetHumanReview: true, force: true });
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
        await this.load({ resetReview: true, resetHumanReview: true, force: true });
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
