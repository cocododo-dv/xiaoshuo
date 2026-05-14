import { defineStore } from "pinia";

import {
  fetchChapterRunStatus,
  fetchProjectDashboard,
  reviewProjectChapterFinal,
  runProjectChapterJob,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

function projectIdOf(project) {
  return project?.project_id || "";
}

function currentChapterId(state) {
  return state.dashboard?.project?.current_chapter_id || state.dashboard?.current_chapter?.chapter_id || "";
}

export const useWriterFlowStore = defineStore("writerFlow", {
  state: () => ({
    selectedProjectId: "",
    dashboard: null,
    runStatus: null,
    loading: false,
    actionId: "",
    error: "",
    lastActionMessage: "",
    lastApprovalNote: null,
    loaded: false,
  }),
  getters: {
    project: (state) => state.dashboard?.project || null,
    chapters: (state) => state.dashboard?.chapters || [],
    currentChapter: (state) => state.dashboard?.current_chapter || null,
    reviewPacket: (state) => state.dashboard?.review_packet || null,
    referenceProfiles: (state) => state.dashboard?.reference_profiles || [],
    backtrackItems: (state) => state.dashboard?.backtrack_items || [],
    nextAction: (state) => state.dashboard?.next_action || "select_project",
    runtime: (state) => state.dashboard?.runtime || { llm_enabled: null, generation_mode: "unknown" },
    hasOfflineGuard: (state) => state.dashboard?.runtime?.llm_enabled === false,
    progressPercent: (state) => Number(state.runStatus?.progress_pct ?? state.dashboard?.run?.progress_pct ?? 0),
    isRunning: (state) => ["pending", "running", "queued"].includes(String(state.runStatus?.status || "").toLowerCase()),
  },
  actions: {
    applyDashboard(payload = {}) {
      this.dashboard = snapshotPayload(payload || null);
      const projectId = projectIdOf(this.dashboard?.project);
      if (projectId) {
        this.selectedProjectId = projectId;
      }
      return this.dashboard;
    },
    applyRunStatus(payload = {}) {
      this.runStatus = snapshotPayload(payload || null);
      return this.runStatus;
    },
    async loadProject(projectId = this.selectedProjectId) {
      if (!projectId) {
        this.dashboard = null;
        this.loaded = true;
        return null;
      }
      this.loading = true;
      this.actionId = `dashboard:${projectId}`;
      this.error = "";
      try {
        const payload = await fetchProjectDashboard(projectId);
        const dashboard = this.applyDashboard(payload);
        this.loaded = true;
        const chapterId = currentChapterId(this);
        if (dashboard?.next_action === "view_chapter_progress" && chapterId) {
          await this.refreshRunStatus(chapterId);
        }
        return dashboard;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
        this.actionId = "";
      }
    },
    async startCurrentChapterJob(payload = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const chapterId = currentChapterId(this);
      if (!projectId || !chapterId) {
        throw new Error("No current chapter is ready to run.");
      }
      this.actionId = `run-job:${chapterId}`;
      this.error = "";
      try {
        const result = await runProjectChapterJob(projectId, chapterId, payload);
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          review_packet: result?.review_packet || this.reviewPacket,
          next_action: result?.next_action || "view_chapter_progress",
        });
        this.applyRunStatus(result?.run || null);
        this.lastActionMessage = "Chapter run started.";
        return result?.run || null;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async refreshRunStatus(chapterId = currentChapterId(this)) {
      if (!chapterId) {
        this.runStatus = null;
        return null;
      }
      const payload = await fetchChapterRunStatus(chapterId);
      const status = this.applyRunStatus(payload);
      if (["completed", "blocked", "failed"].includes(String(status?.status || "").toLowerCase())) {
        await this.loadProject(this.selectedProjectId || projectIdOf(this.project));
      }
      return status;
    },
    async approveCurrentChapterFinal(payload = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const chapterId = currentChapterId(this) || this.reviewPacket?.chapter_id;
      if (!projectId || !chapterId) {
        throw new Error("No chapter is waiting for final approval.");
      }
      this.actionId = `approve-final:${chapterId}`;
      this.error = "";
      try {
        const result = await reviewProjectChapterFinal(projectId, chapterId, {
          decision: "approve",
          ...(payload || {}),
        });
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          current_chapter: null,
          review_packet: null,
          next_action: result?.project?.status === "completed" ? "completed" : "run_current_chapter",
        });
        this.runStatus = null;
        this.lastApprovalNote = snapshotPayload(result?.approval_note || null);
        this.lastActionMessage = result?.next_chapter_id ? "Chapter approved. Next chapter is ready." : "Project completed.";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async requestCurrentChapterRevision(payload = {}) {
      const projectId = this.selectedProjectId || projectIdOf(this.project);
      const chapterId = currentChapterId(this) || this.reviewPacket?.chapter_id;
      if (!projectId || !chapterId) {
        throw new Error("No chapter is waiting for final review.");
      }
      this.actionId = `final-review-revision:${chapterId}`;
      this.error = "";
      try {
        const result = await reviewProjectChapterFinal(projectId, chapterId, {
          decision: "request_revision",
          ...(payload || {}),
        });
        this.dashboard = snapshotPayload({
          ...(this.dashboard || {}),
          project: result?.project || this.project,
          backtrack_items: result?.backtrack_items || this.backtrackItems,
          review_packet: result?.review_packet || this.reviewPacket,
          next_action: result?.next_action || "resolve_backtrack_items",
        });
        this.lastActionMessage = result?.message || "Revision request recorded.";
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    setChaptersForPreview(chapters = []) {
      this.dashboard = snapshotPayload({
        ...(this.dashboard || {}),
        chapters: snapshotPayloadList(chapters),
      });
    },
  },
});
