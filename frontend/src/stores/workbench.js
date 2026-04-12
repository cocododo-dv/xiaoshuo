import { defineStore } from "pinia";

import {
  clearChapterManualHold,
  fetchHumanReviewEvents,
  fetchWorkbench,
  runChapterBackfill as postChapterBackfill,
  runChapterFinalAggregate as postChapterFinalAggregate,
  runFullScene,
  setChapterManualHold as postChapterManualHold,
} from "../lib/api";

export const useWorkbenchStore = defineStore("workbench", {
  state: () => ({
    sceneId: "CH001_SC01",
    data: null,
    humanReviewItems: [],
    loading: false,
    humanReviewLoading: false,
    actionId: "",
    lastRunResult: null,
    lastChapterActionResult: null,
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
    async loadHumanReview(sceneId = this.sceneId) {
      this.humanReviewLoading = true;
      try {
        const payload = await fetchHumanReviewEvents({ sceneId });
        this.humanReviewItems = payload.items || [];
      } catch (error) {
        this.humanReviewItems = [];
        this.error = error.message;
      } finally {
        this.humanReviewLoading = false;
      }
    },
    async refreshAll(sceneId = this.sceneId) {
      await Promise.all([this.load(sceneId), this.loadHumanReview(sceneId)]);
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
    async runChapterBackfill(chapterId, stageId, strategy, sceneId = this.sceneId) {
      this.actionId = `chapter-backfill:${stageId}`;
      this.error = "";
      try {
        const result = await postChapterBackfill(chapterId, stageId, strategy);
        this.lastChapterActionResult = result.receipt;
        await this.refreshAll(sceneId);
        return `Applied ${strategy} to ${stageId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async runChapterFinalAggregate(chapterId, sceneId = this.sceneId) {
      this.actionId = "chapter-final-aggregate";
      this.error = "";
      try {
        const result = await postChapterFinalAggregate(chapterId);
        this.lastChapterActionResult = result.receipt;
        await this.refreshAll(sceneId);
        return `Ran final aggregate for ${chapterId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async setChapterManualHold(chapterId, reason, sceneId = this.sceneId) {
      this.actionId = "chapter-manual-hold-set";
      this.error = "";
      try {
        const result = await postChapterManualHold(chapterId, reason);
        this.lastChapterActionResult = result.receipt;
        await this.refreshAll(sceneId);
        return `Set manual hold for ${chapterId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async clearChapterManualHold(chapterId, sceneId = this.sceneId) {
      this.actionId = "chapter-manual-hold-clear";
      this.error = "";
      try {
        const result = await clearChapterManualHold(chapterId);
        this.lastChapterActionResult = result.receipt;
        await this.refreshAll(sceneId);
        return `Cleared manual hold for ${chapterId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
