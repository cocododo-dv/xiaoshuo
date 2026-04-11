import { defineStore } from "pinia";

import { actOnHumanReviewEvent, approveReview, fetchHumanReviewEvents, fetchReviewItems, releaseReview } from "../lib/api";

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
    items: [],
    humanReviewItems: [],
    lastActionResult: null,
    loading: false,
    actionId: "",
    error: "",
  }),
  getters: {
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
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const [reviewPayload, humanReviewPayload] = await Promise.all([
          fetchReviewItems(this.reviewFilters),
          fetchHumanReviewEvents(this.humanReviewFilters),
        ]);
        this.items = reviewPayload.items || [];
        this.humanReviewItems = humanReviewPayload.items || [];
      } catch (error) {
        this.items = [];
        this.humanReviewItems = [];
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
        await this.load();
        return `Approved ${reviewId}${result.actor_ref ? ` as ${result.actor_ref}` : ""}`;
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
        await this.load();
        return `Released ${reviewId}${result.actor_ref ? ` as ${result.actor_ref}` : ""}`;
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
        await this.load();
        return `Applied ${action} to ${eventId} (${result.status || "updated"})`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
