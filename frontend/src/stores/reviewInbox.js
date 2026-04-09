import { defineStore } from "pinia";

import { approveReview, fetchReviewItems, releaseReview } from "../lib/api";

export const useReviewInboxStore = defineStore("reviewInbox", {
  state: () => ({
    items: [],
    loading: false,
    actionId: "",
    error: "",
  }),
  actions: {
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchReviewItems();
        this.items = payload.items || [];
      } catch (error) {
        this.items = [];
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async approve(reviewId) {
      this.actionId = reviewId;
      this.error = "";
      try {
        await approveReview(reviewId);
        await this.load();
        return `Approved ${reviewId}`;
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
        await releaseReview(reviewId);
        await this.load();
        return `Released ${reviewId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
