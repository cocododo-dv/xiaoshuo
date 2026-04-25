import { defineStore } from "pinia";

import {
  acceptRevisionCandidate,
  clearChapterManualHold,
  fetchHumanReviewEvents,
  fetchRunJob,
  fetchSceneAttempts,
  fetchWorkbench,
  rejectRevisionCandidate,
  runChapterBackfill as postChapterBackfill,
  runChapterFinalAggregate as postChapterFinalAggregate,
  runFullScene,
  runSceneLiteraryBlueprint,
  runSceneWriterReview,
  setChapterManualHold as postChapterManualHold,
  startSceneRunJob,
} from "../lib/api";
import {
  advanceCursorPager,
  applyCursorPayload,
  buildCursorQuery,
  createCursorPager,
  resetCursorPager,
  retreatCursorPager,
} from "../lib/cursorPagination";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

export const LAST_WORKBENCH_SCENE_ID_KEY = "novel-system:last-workbench-scene-id";

function readLastWorkbenchSceneId() {
  if (typeof localStorage === "undefined") {
    return "";
  }
  try {
    return localStorage.getItem(LAST_WORKBENCH_SCENE_ID_KEY) || "";
  } catch {
    return "";
  }
}

function rememberWorkbenchSceneId(sceneId) {
  const value = String(sceneId || "").trim();
  if (!value || typeof localStorage === "undefined") {
    return;
  }
  try {
    localStorage.setItem(LAST_WORKBENCH_SCENE_ID_KEY, value);
  } catch {
    // Storage can be unavailable in private or embedded browser contexts.
  }
}

function forgetWorkbenchSceneId(sceneId) {
  const value = String(sceneId || "").trim();
  if (!value || typeof localStorage === "undefined") {
    return;
  }
  try {
    if (localStorage.getItem(LAST_WORKBENCH_SCENE_ID_KEY) === value) {
      localStorage.removeItem(LAST_WORKBENCH_SCENE_ID_KEY);
    }
  } catch {
    // Storage can be unavailable in private or embedded browser contexts.
  }
}

const RUN_JOB_TERMINAL_STATUSES = new Set([
  "archived",
  "blocked",
  "cancelled",
  "completed",
  "failed",
  "human_review_required",
  "manual_review_required",
]);
const DEFAULT_RUN_JOB_MAX_POLLS = 600;

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function normalizeRunJobPayload(payload) {
  if (!payload) {
    return null;
  }
  const details = payload.payload || payload.payload_json || {};
  const resultSummary = payload.result_summary || payload.result_summary_json || payload.result || {};
  return {
    ...payload,
    scene_id: payload.scene_id || details.scene_id || resultSummary.scene_id || "",
    chapter_id: payload.chapter_id || details.chapter_id || resultSummary.chapter_id || "",
    current_step: payload.current_step || details.current_step || payload.stage || payload.status || "queued",
    stage: payload.stage || payload.current_step || details.current_step || payload.status || "queued",
    result_summary: resultSummary,
    needs_human_review:
      payload.needs_human_review
      || payload.status === "human_review_required"
      || resultSummary.needs_human_review
      || false,
  };
}

function runJobIsTerminal(job) {
  if (!job) {
    return false;
  }
  return RUN_JOB_TERMINAL_STATUSES.has(job.status) || Boolean(job.finished_at);
}

function sceneResultFromRunJob(job) {
  const result = job?.result_summary || {};
  return {
    job_id: job?.job_id || "",
    job_status: job?.status || "",
    current_step: job?.current_step || job?.stage || "",
    scene_status: result.scene_status || result.status || job?.scene_status || job?.status || "",
    current_bundle_id: result.current_bundle_id || result.bundle_id || null,
    current_bundle_hash: result.current_bundle_hash || result.bundle_hash || null,
    current_final_scene_row_id: result.current_final_scene_row_id || result.final_scene_row_id || null,
  };
}

function canFallbackToBlockingRun(error) {
  return error?.status === 404 || error?.status === 405 || error?.code === "NOT_FOUND";
}

function isNoAggregateReceipt(receipt = {}) {
  const values = [
    receipt.status,
    receipt.result,
    receipt.code,
    receipt.reason,
    receipt.reason_code,
    receipt.message,
  ]
    .filter(Boolean)
    .map((value) => String(value).toLowerCase());
  return values.some((value) => value.includes("no_op") || value.includes("no_scene_memories"));
}

export const useWorkbenchStore = defineStore("workbench", {
  state: () => ({
    sceneId: readLastWorkbenchSceneId(),
    data: null,
    humanReviewItems: [],
    attemptPager: createCursorPager(),
    attemptSceneId: readLastWorkbenchSceneId(),
    attempts: [],
    loaded: false,
    stale: false,
    loading: false,
    humanReviewLoading: false,
    attemptLoading: false,
    actionId: "",
    lastRunResult: null,
    runJob: null,
    runJobPolling: false,
    lastChapterActionResult: null,
    error: "",
  }),
  getters: {
    attemptPagination: (state) => state.attemptPager.pagination,
    attemptCursor: (state) => state.attemptPager.cursor,
    attemptCursorStack: (state) => state.attemptPager.cursorStack,
  },
  actions: {
    markStale() {
      this.stale = true;
    },
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    async load(sceneId = this.sceneId) {
      const nextSceneId = String(sceneId || "").trim();
      if (!nextSceneId) {
        this.sceneId = "";
        this.data = null;
        this.error = "";
        return;
      }
      this.loading = true;
      this.error = "";
      this.sceneId = nextSceneId;
      try {
        this.data = snapshotPayload(await fetchWorkbench(nextSceneId));
        rememberWorkbenchSceneId(nextSceneId);
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
        this.humanReviewItems = snapshotPayloadList(payload.items || []);
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
        this.attempts = snapshotPayloadList(applyCursorPayload(this.attemptPager, payload));
      } catch (error) {
        this.attempts = [];
        this.error = error.message;
      } finally {
        this.attemptLoading = false;
      }
    },
    async refreshAll(sceneId = this.sceneId, { force = false } = {}) {
      const nextSceneId = String(sceneId || this.sceneId || "").trim();
      if (!nextSceneId) {
        this.sceneId = "";
        this.data = null;
        this.humanReviewItems = [];
        this.attempts = [];
        this.error = "";
        this.loaded = false;
        return;
      }
      if (this.loaded && !this.stale && !force && nextSceneId === this.sceneId) {
        return;
      }
      this.sceneId = nextSceneId;
      await Promise.all([
        this.load(nextSceneId),
        this.loadHumanReview(nextSceneId),
        this.loadAttempts(nextSceneId, { reset: force || nextSceneId !== this.attemptSceneId }),
      ]);
      if (!this.error) {
        rememberWorkbenchSceneId(nextSceneId);
        this.markFresh();
      } else {
        if (!this.data && readLastWorkbenchSceneId() === nextSceneId) {
          forgetWorkbenchSceneId(nextSceneId);
          this.sceneId = "";
          this.humanReviewItems = [];
          this.attempts = [];
          this.syncAttemptPager("", { reset: true });
        }
        this.loaded = false;
      }
    },
    async ensureLoaded({ force = false, sceneId = this.sceneId } = {}) {
      await this.refreshAll(sceneId, { force });
    },
    async nextAttemptsPage() {
      if (!advanceCursorPager(this.attemptPager)) {
        return;
      }
      await this.loadAttempts(this.sceneId);
      this.markFresh();
    },
    async previousAttemptsPage() {
      if (!retreatCursorPager(this.attemptPager)) {
        return;
      }
      await this.loadAttempts(this.sceneId);
      this.markFresh();
    },
    async pollRunJob(jobId, sceneId = this.sceneId, { intervalMs = 1200, maxPolls = DEFAULT_RUN_JOB_MAX_POLLS } = {}) {
      if (!jobId) {
        return null;
      }
      this.runJobPolling = true;
      try {
        for (let pollIndex = 0; pollIndex < maxPolls; pollIndex += 1) {
          const job = normalizeRunJobPayload(await fetchRunJob(jobId));
          this.runJob = snapshotPayload(job);
          if (runJobIsTerminal(job)) {
            this.lastRunResult = snapshotPayload(sceneResultFromRunJob(job));
            this.syncAttemptPager(sceneId, { reset: true });
            await this.refreshAll(sceneId, { force: true });
            return job;
          }
          if (pollIndex < maxPolls - 1) {
            await delay(intervalMs);
          }
        }
        return this.runJob;
      } finally {
        this.runJobPolling = false;
      }
    },
    async runScene(sceneId = this.sceneId) {
      const previousSceneId = this.sceneId;
      this.actionId = "run-scene";
      this.error = "";
      try {
        const job = normalizeRunJobPayload(await startSceneRunJob(sceneId));
        this.runJob = snapshotPayload(job);
        if (runJobIsTerminal(job)) {
          this.lastRunResult = snapshotPayload(sceneResultFromRunJob(job));
          await this.refreshAll(sceneId, { force: true });
          return `场景运行任务已完成：${sceneId}`;
        }
        const firstPoll = await this.pollRunJob(job.job_id, sceneId, { intervalMs: 0, maxPolls: 1 });
        if (runJobIsTerminal(firstPoll)) {
          return `场景运行任务已完成：${sceneId}`;
        }
        this.pollRunJob(job.job_id, sceneId).catch((error) => {
          this.error = error.message;
        });
        return `已启动场景运行任务 ${job.job_id || sceneId}`;
      } catch (error) {
        if (!canFallbackToBlockingRun(error)) {
          this.sceneId = previousSceneId;
          this.error = error.message;
          throw error;
        }
        const result = await runFullScene(sceneId);
        this.lastRunResult = snapshotPayload(result);
        this.runJob = null;
        this.syncAttemptPager(sceneId, { reset: true });
        await this.refreshAll(sceneId, { force: true });
        return `已使用兼容模式运行 ${sceneId} 的完整场景流程`;
      } finally {
        this.actionId = "";
      }
    },
    async runWriterReview(sceneId = this.sceneId) {
      this.actionId = "writer-review";
      this.error = "";
      try {
        const result = await runSceneWriterReview(sceneId);
        await this.load(sceneId);
        this.markFresh();
        return `作家诊断已完成：${result.latest_score ?? result.evaluation?.overall_score ?? "-"}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async generateBlueprint(sceneId = this.sceneId) {
      this.actionId = "scene-blueprint";
      this.error = "";
      try {
        const result = await runSceneLiteraryBlueprint(sceneId);
        await this.load(sceneId);
        this.markFresh();
        return `Scene blueprint ready: ${result.row_id || sceneId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async acceptRevision(revisionId, sceneId = this.sceneId) {
      this.actionId = `revision-accept:${revisionId}`;
      this.error = "";
      try {
        const result = await acceptRevisionCandidate(revisionId, { note: "author accepted from scene workbench" });
        await this.load(sceneId);
        this.markFresh();
        return `已采纳修订候选：${result.revision?.revision_id || revisionId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async rejectRevision(revisionId, sceneId = this.sceneId) {
      this.actionId = `revision-reject:${revisionId}`;
      this.error = "";
      try {
        const result = await rejectRevisionCandidate(revisionId, { note: "author rejected from scene workbench" });
        await this.load(sceneId);
        this.markFresh();
        return `已拒绝修订候选：${result.revision?.revision_id || revisionId}`;
      } catch (error) {
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
        this.lastChapterActionResult = snapshotPayload(result.receipt);
        await this.refreshAll(sceneId, { force: true });
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
        this.lastChapterActionResult = snapshotPayload(result.receipt);
        await this.refreshAll(sceneId, { force: true });
        if (isNoAggregateReceipt(result.receipt)) {
          return "无可聚合内容";
        }
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
        this.lastChapterActionResult = snapshotPayload(result.receipt);
        await this.refreshAll(sceneId, { force: true });
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
        this.lastChapterActionResult = snapshotPayload(result.receipt);
        await this.refreshAll(sceneId, { force: true });
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
