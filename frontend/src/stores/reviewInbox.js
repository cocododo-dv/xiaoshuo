import { defineStore } from "pinia";

import {
  actOnHumanReviewEvent,
  approveReview,
  fetchHumanReviewEvents,
  fetchReviewItem,
  fetchReviewItems,
  releaseReview,
} from "../lib/api";
import {
  advanceCursorPager,
  applyCursorPayload,
  buildCursorQuery,
  createCursorPager,
  filtersSignature,
  resetCursorPager,
  retreatCursorPager,
} from "../lib/cursorPagination";
import { snapshotPayloadList } from "../lib/payloadSnapshot";

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

function mergePinnedReviewItems(items, pinnedItems) {
  if (!pinnedItems?.length) {
    return items;
  }
  const seen = new Set(items.map((item) => item?.review_id).filter(Boolean));
  const missingPinnedItems = pinnedItems.filter((item) => item?.review_id && !seen.has(item.review_id));
  return [...missingPinnedItems, ...items];
}

function releaseConflictKind(error) {
  const message = String(error?.message || "").toLowerCase();
  if (message.includes("candidate is already active")) {
    return "already_active";
  }
  if (message.includes("candidate is not verified")) {
    return "not_verified";
  }
  return "";
}

function reviewReleaseState(item) {
  return item?.release_state && typeof item.release_state === "object" ? item.release_state : {};
}

function isApprovalCompleted(item) {
  return item?.status === "approved" && (item.materialize_status === "succeeded" || Boolean(item.approved_item_row_id));
}

function isReleaseCompleted(item) {
  return reviewReleaseState(item).state === "active";
}

function notVerifiedMessage(reviewId, item = null) {
  const releaseState = reviewReleaseState(item);
  return (
    releaseState.message ||
    `候选尚未通过索引校验：${reviewId}。请先在索引控制台重试校验，成功后再发布。`
  );
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
    pinnedApprovedReviewItems: [],
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
      const pinnedItems = this.reviewFilters.status === "pending" ? this.pinnedApprovedReviewItems : [];
      const snapshotItems = snapshotPayloadList(mergePinnedReviewItems(items, pinnedItems));
      this.items = snapshotItems;
      this.reviewItemLookup = buildLookup(snapshotItems, "review_id");
      this.reviewItemsVersion += 1;
    },
    pinApprovedReview(reviewId, result = {}) {
      const currentItem = this.items.find((item) => item.review_id === reviewId) || {};
      const pinnedItem = {
        ...currentItem,
        ...result,
        review_id: reviewId,
        status: "approved",
        materialize_status: result.materialize_status || currentItem.materialize_status || "succeeded",
        approved_item_row_id: result.approved_item_row_id ?? currentItem.approved_item_row_id ?? null,
        approved_item_id: result.approved_item_id ?? currentItem.approved_item_id ?? null,
      };
      this.pinnedApprovedReviewItems = [
        pinnedItem,
        ...this.pinnedApprovedReviewItems.filter((item) => item.review_id !== reviewId),
      ];
    },
    unpinApprovedReview(reviewId) {
      this.pinnedApprovedReviewItems = this.pinnedApprovedReviewItems.filter((item) => item.review_id !== reviewId);
    },
    assignHumanReviewItems(items) {
      const snapshotItems = snapshotPayloadList(items);
      const lookups = buildHumanReviewLookups(snapshotItems);

      this.humanReviewItems = snapshotItems;
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
    async fetchLatestReviewItem(reviewId) {
      return fetchReviewItem(reviewId);
    },
    async reconcileCompletedReviewAction(reviewId, action) {
      let latest = null;
      try {
        latest = await this.fetchLatestReviewItem(reviewId);
      } catch {
        return "";
      }

      if (action === "approve" && isApprovalCompleted(latest)) {
        this.lastActionResult = latest;
        this.pinApprovedReview(reviewId, latest);
        this.error = "";
        return `当前状态已完成：${reviewId} 已批准。上一条请求返回失败，但最新状态可以继续发布或刷新。`;
      }
      if (action === "release" && isReleaseCompleted(latest)) {
        this.lastActionResult = latest;
        this.unpinApprovedReview(reviewId);
        this.error = "";
        return `当前状态已完成：${reviewId} 已发布到运行时。上一条请求返回失败，但最新状态已经生效。`;
      }
      return "";
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
    async approve(reviewId, payload = {}) {
      this.actionId = reviewId;
      this.error = "";
      try {
        const result = await approveReview(reviewId, payload);
        this.lastActionResult = result;
        this.pinApprovedReview(reviewId, result);
        await this.load({ resetReview: true, resetHumanReview: true, force: true });
        return `已批准 ${reviewId}${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        const reconciled = await this.reconcileCompletedReviewAction(reviewId, "approve");
        if (reconciled) {
          return reconciled;
        }
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
        this.unpinApprovedReview(reviewId);
        await this.load({ resetReview: true, resetHumanReview: true, force: true });
        return `已发布 ${reviewId}${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        const reconciled = await this.reconcileCompletedReviewAction(reviewId, "release");
        if (reconciled) {
          return reconciled;
        }
        const conflictKind = releaseConflictKind(error);
        if (conflictKind === "already_active") {
          this.error = "";
          return `当前状态已完成：${reviewId} 已发布到运行时。`;
        }
        if (conflictKind === "not_verified") {
          let latest = null;
          try {
            latest = await this.fetchLatestReviewItem(reviewId);
          } catch {
          }
          const message = notVerifiedMessage(reviewId, latest);
          this.error = message;
          throw new Error(message);
        }
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async actOnHumanReviewEvent(eventId, action, payload = {}) {
      this.actionId = `${eventId}:${action}`;
      this.error = "";
      try {
        const result = await actOnHumanReviewEvent(eventId, action, payload);
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
