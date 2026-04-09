import { defineStore } from "pinia";

import { fetchHumanReviewEvents, fetchWorkbench, runFullScene } from "../lib/api";

export const useWorkbenchStore = defineStore("workbench", {
  state: () => ({
    sceneId: "CH001_SC01",
    data: null,
    humanReviewItems: [],
    loading: false,
    humanReviewLoading: false,
    actionId: "",
    lastRunResult: null,
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
    async runScene(sceneId = this.sceneId) {
      const previousSceneId = this.sceneId;
      this.actionId = "run-scene";
      this.error = "";
      try {
        const result = await runFullScene(sceneId);
        this.lastRunResult = result;
        await this.refreshAll(sceneId);
        return `Ran ${sceneId} through full scene pipeline`;
      } catch (error) {
        this.sceneId = previousSceneId;
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
