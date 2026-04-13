import { defineStore } from "pinia";

import {
  clearChapterManualHold,
  fetchHumanReviewEvents,
  fetchSceneAttempts,
  fetchWorkbench,
  runChapterBackfill as postChapterBackfill,
  runChapterFinalAggregate as postChapterFinalAggregate,
  runFullScene,
  setChapterManualHold as postChapterManualHold,
} from "../lib/api";
import {
  advanceCursorPager,
  applyCursorPayload,
  buildCursorQuery,
  createCursorPager,
  resetCursorPager,
  retreatCursorPager,
} from "../lib/cursorPagination";

export const useWorkbenchStore = defineStore("workbench", {
  state: () => ({
    sceneId: "CH001_SC01",
    data: null,
    humanReviewItems: [],
    attemptPager: createCursorPager(),
    attemptSceneId: "CH001_SC01",
    attempts: [],
    loading: false,
    humanReviewLoading: false,
    attemptLoading: false,
    actionId: "",
    lastRunResult: null,
    lastChapterActionResult: null,
    error: "",
  }),
  getters: {
    attemptPagination: (state) => state.attemptPager.pagination,
    attemptCursor: (state) => state.attemptPager.cursor,
    attemptCursorStack: (state) => state.attemptPager.cursorStack,
  },
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
    syncAttemptPager(sceneId = this.sceneId, { reset = false } = {}) {
      if (reset || sceneId !== this.attemptSceneId) {
        resetCursorPager(this.attemptPager);
        this.attemptSceneId = sceneId;
      }
    },
    async loadAttempts(sceneId = this.sceneId, { reset = false } = {}) {
      this.attemptLoading = true;
      this.error = "";
      this.syncAttemptPager(sceneId, { reset });
      try {
        const payload = await fetchSceneAttempts(sceneId, buildCursorQuery(this.attemptPager));
        this.attempts = applyCursorPayload(this.attemptPager, payload);
      } catch (error) {
        this.attempts = [];
        this.error = error.message;
      } finally {
        this.attemptLoading = false;
      }
    },
    async refreshAll(sceneId = this.sceneId) {
      this.sceneId = sceneId;
      await Promise.all([this.load(sceneId), this.loadHumanReview(sceneId), this.loadAttempts(sceneId)]);
    },
    async nextAttemptsPage() {
      if (!advanceCursorPager(this.attemptPager)) {
        return;
      }
      await this.loadAttempts(this.sceneId);
    },
    async previousAttemptsPage() {
      if (!retreatCursorPager(this.attemptPager)) {
        return;
      }
      await this.loadAttempts(this.sceneId);
    },
    async runScene(sceneId = this.sceneId) {
      const previousSceneId = this.sceneId;
      this.actionId = "run-scene";
      this.error = "";
      try {
        const result = await runFullScene(sceneId);
        this.lastRunResult = result;
        this.syncAttemptPager(sceneId, { reset: true });
        await this.refreshAll(sceneId);
        return `已运行 ${sceneId} 的完整场景流程`;
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
        return `已对 ${stageId} 应用策略 ${strategy}`;
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
        return `已运行 ${chapterId} 的最终聚合`;
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
        return `已为 ${chapterId} 设置人工挂起`;
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
        return `已清除 ${chapterId} 的人工挂起`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
