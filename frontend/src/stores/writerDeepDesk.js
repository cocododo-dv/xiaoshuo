import { defineStore } from "pinia";

import {
  acceptPassagePatchCandidate,
  createPassagePatchCandidate,
  fetchAuthorPreferenceProfile,
  fetchChapterDeepReview,
  fetchChapterManuscriptDetail,
  fetchChapterManuscripts,
  rejectPassagePatchCandidate,
  runChapterDeepReview,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

function preferredExcerpt(text) {
  const firstParagraph = String(text || "")
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .find(Boolean);
  return (firstParagraph || String(text || "").trim()).slice(0, 260);
}

function mergeCandidates(primary = [], secondary = []) {
  const seen = new Set();
  return [...primary, ...secondary].filter((candidate) => {
    const id = candidate?.patch_id;
    if (!id || seen.has(id)) {
      return false;
    }
    seen.add(id);
    return true;
  });
}

export const useWriterDeepDeskStore = defineStore("writerDeepDesk", {
  state: () => ({
    chapters: [],
    selectedChapterId: "",
    detail: null,
    deepReview: null,
    preferenceProfile: null,
    selectedExcerpt: "",
    patchCandidates: [],
    loaded: false,
    stale: false,
    loading: false,
    actionId: "",
    error: "",
  }),
  getters: {
    selectedChapter: (state) => state.chapters.find((chapter) => chapter.chapter_id === state.selectedChapterId) || null,
    currentText: (state) => state.detail?.aggregate?.content || state.detail?.assembled?.content || "",
    currentSourceRef: (state) => {
      if (state.detail?.aggregate?.row_id) {
        return `chapter_memory:${state.detail.aggregate.row_id}`;
      }
      return state.selectedChapterId ? `chapter_assembled:${state.selectedChapterId}` : "";
    },
    latestEvaluation: (state) => state.deepReview?.latest_evaluation || null,
    findings() {
      return this.latestEvaluation?.findings || [];
    },
    lensEvaluations: (state) => state.deepReview?.lens_evaluations || [],
    candidateRows(state) {
      return mergeCandidates(state.deepReview?.patch_candidates || [], state.patchCandidates);
    },
    excerptForPatch() {
      return this.selectedExcerpt.trim() || preferredExcerpt(this.currentText);
    },
  },
  actions: {
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    async loadChapters() {
      const payload = await fetchChapterManuscripts();
      this.chapters = snapshotPayloadList(payload.items || []);
      if (!this.chapters.length) {
        this.selectedChapterId = "";
        this.detail = null;
        this.deepReview = null;
        this.patchCandidates = [];
        return;
      }
      if (!this.chapters.some((chapter) => chapter.chapter_id === this.selectedChapterId)) {
        this.selectedChapterId = this.chapters[0].chapter_id;
      }
    },
    async loadDetail(chapterId = this.selectedChapterId) {
      if (!chapterId) {
        this.detail = null;
        return;
      }
      const payload = await fetchChapterManuscriptDetail(chapterId);
      this.selectedChapterId = chapterId;
      this.detail = snapshotPayload(payload);
      if (!this.selectedExcerpt.trim()) {
        this.selectedExcerpt = preferredExcerpt(this.currentText);
      }
    },
    async loadDeepReview(chapterId = this.selectedChapterId) {
      if (!chapterId) {
        this.deepReview = null;
        this.patchCandidates = [];
        return;
      }
      const payload = await fetchChapterDeepReview(chapterId);
      this.deepReview = snapshotPayload(payload);
      this.patchCandidates = snapshotPayloadList(payload.patch_candidates || []);
    },
    async loadPreference() {
      const payload = await fetchAuthorPreferenceProfile();
      this.preferenceProfile = snapshotPayload(payload.profile || null);
    },
    async refreshSelected(preferredChapterId = this.selectedChapterId) {
      await this.loadChapters();
      if (preferredChapterId && this.chapters.some((chapter) => chapter.chapter_id === preferredChapterId)) {
        this.selectedChapterId = preferredChapterId;
      }
      if (this.selectedChapterId) {
        await this.loadDetail(this.selectedChapterId);
        await this.loadDeepReview(this.selectedChapterId);
      }
      await this.loadPreference();
    },
    async initialize({ force = false } = {}) {
      if (this.loaded && !this.stale && !force) {
        return;
      }
      this.loading = true;
      this.error = "";
      try {
        await this.refreshSelected(this.selectedChapterId);
        this.markFresh();
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async ensureLoaded(options = {}) {
      await this.initialize(options);
    },
    async selectChapter(chapterId) {
      this.loading = true;
      this.error = "";
      try {
        this.selectedExcerpt = "";
        await this.loadDetail(chapterId);
        await this.loadDeepReview(chapterId);
        await this.loadPreference();
        this.markFresh();
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    setSelectedExcerpt(value) {
      this.selectedExcerpt = String(value || "");
    },
    async runChapterDeepReview(chapterId = this.selectedChapterId) {
      this.actionId = "deep-review";
      this.error = "";
      try {
        const result = await runChapterDeepReview(chapterId);
        this.deepReview = snapshotPayload(result);
        this.patchCandidates = snapshotPayloadList(result.patch_candidates || []);
        return `深改诊断完成：${result.latest_score ?? "-"}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async createPassagePatchCandidate(payload = {}) {
      this.actionId = "patch-create";
      this.error = "";
      try {
        const sourceExcerpt = String(payload.source_excerpt || this.excerptForPatch).trim();
        const result = await createPassagePatchCandidate({
          object_type: "chapter",
          object_id: this.selectedChapterId,
          chapter_id: this.selectedChapterId,
          target_text_ref: this.currentSourceRef,
          issue_dimension: payload.issue_dimension || this.findings[0]?.dimension || "dialogue_subtext",
          source_excerpt: sourceExcerpt,
          ...payload,
        });
        const candidate = snapshotPayload(result.candidate);
        this.patchCandidates = snapshotPayloadList([candidate, ...this.candidateRows]);
        await this.loadPreference();
        return `已生成局部候选：${candidate.patch_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async acceptPassagePatchCandidate(patchId, payload = {}) {
      this.actionId = `patch-accept:${patchId}`;
      this.error = "";
      try {
        const result = await acceptPassagePatchCandidate(patchId, payload);
        await this.loadDeepReview(this.selectedChapterId);
        await this.loadPreference();
        return `已记录采纳：${result.candidate?.patch_id || patchId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async rejectPassagePatchCandidate(patchId, payload = {}) {
      this.actionId = `patch-reject:${patchId}`;
      this.error = "";
      try {
        const result = await rejectPassagePatchCandidate(patchId, payload);
        await this.loadDeepReview(this.selectedChapterId);
        await this.loadPreference();
        return `已记录拒绝：${result.candidate?.patch_id || patchId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
