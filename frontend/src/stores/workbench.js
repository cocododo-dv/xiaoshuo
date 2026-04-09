import { defineStore } from "pinia";

import { fetchHumanReviewEvents, fetchWorkbench } from "../lib/api";

export const useWorkbenchStore = defineStore("workbench", {
  state: () => ({
    sceneId: "CH001_SC01",
    data: null,
    humanReviewItems: [],
    loading: false,
    humanReviewLoading: false,
    error: "",
  }),
  actions: {
    async load(sceneId = this.sceneId) {
      this.loading = true;
      this.error = "";
      this.sceneId = sceneId;
      try {
        this.data = await fetchWorkbench(sceneId);
      } catch (error) {
        this.data = null;
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async loadHumanReview() {
      this.humanReviewLoading = true;
      try {
        const payload = await fetchHumanReviewEvents();
        this.humanReviewItems = payload.items || [];
      } catch (error) {
        this.humanReviewItems = [];
        this.error = error.message;
      } finally {
        this.humanReviewLoading = false;
      }
    },
    async refreshAll(sceneId = this.sceneId) {
      await Promise.all([this.load(sceneId), this.loadHumanReview()]);
    },
  },
});
