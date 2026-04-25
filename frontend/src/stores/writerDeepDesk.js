import { defineStore } from "pinia";

import {
  acceptPassagePatchCandidate,
  createPassagePatchCandidate,
  ensureAuthorDraft as ensureAuthorDraftApi,
  fetchAuthorPreferenceProfile,
  fetchChapterDeepReview,
  fetchChapterManuscriptDetail,
  fetchChapterManuscripts,
  fetchCurrentAuthorDraft,
  fetchSceneDeepReview,
  recordAuthorDraftCandidateEvent as recordAuthorDraftCandidateEventApi,
  rejectPassagePatchCandidate,
  runChapterDeepReview as runChapterDeepReviewApi,
  runSceneDeepReview,
  saveAuthorDraft as saveAuthorDraftApi,
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

function normalizeDraftMode(value) {
  return value === "scene" ? "scene" : "chapter";
}

function replaceOrAppend(content, excerpt, replacement) {
  const current = String(content || "");
  const next = String(replacement || "");
  const needle = String(excerpt || "").trim();
  if (needle && current.includes(needle)) {
    return current.replace(needle, next);
  }
  const trimmed = current.trimEnd();
  return trimmed ? `${trimmed}\n\n${next}` : next;
}

export const useWriterDeepDeskStore = defineStore("writerDeepDesk", {
  state: () => ({
    chapters: [],
    selectedChapterId: "",
    selectedSceneId: "",
    detail: null,
    deepReview: null,
    preferenceProfile: null,
    draftMode: "chapter",
    authorDraft: null,
    draftContent: "",
    draftSavedContent: "",
    selectedExcerpt: "",
    patchCandidates: [],
    pendingCandidateDecisions: [],
    loaded: false,
    stale: false,
    loading: false,
    actionId: "",
    error: "",
  }),
  getters: {
    selectedChapter: (state) => state.chapters.find((chapter) => chapter.chapter_id === state.selectedChapterId) || null,
    availableScenes: (state) => snapshotPayloadList(state.detail?.scenes || []),
    selectedScene() {
      return this.availableScenes.find((scene) => scene.scene_id === this.selectedSceneId) || null;
    },
    draftObjectType: (state) => (state.draftMode === "scene" ? "scene" : "chapter"),
    draftObjectId() {
      return this.draftObjectType === "scene" ? this.selectedSceneId : this.selectedChapterId;
    },
    draftDirty: (state) => String(state.draftContent || "") !== String(state.draftSavedContent || ""),
    draftRevisionNo: (state) => state.authorDraft?.revision_no || 0,
    draftSourceRef: (state) => state.authorDraft?.source_text_ref || "",
    currentText: (state) => state.detail?.aggregate?.content || state.detail?.assembled?.content || "",
    currentSourceRef: (state) => {
      if (state.detail?.aggregate?.row_id) {
        return `chapter_memory:${state.detail.aggregate.row_id}`;
      }
      return state.selectedChapterId ? `chapter_assembled:${state.selectedChapterId}` : "";
    },
    runtimeLayerText() {
      if (this.draftObjectType === "scene") {
        const finalRowId = this.selectedScene?.final_scene?.row_id;
        return finalRowId ? `FinalScene ${finalRowId}` : "该场景暂无运行终稿";
      }
      return this.currentText;
    },
    finalAggregateText: (state) => state.detail?.aggregate?.content || "",
    latestEvaluation: (state) => state.deepReview?.latest_evaluation || null,
    findings() {
      return this.latestEvaluation?.findings || [];
    },
    lensEvaluations: (state) => state.deepReview?.lens_evaluations || [],
    candidateRows(state) {
      return mergeCandidates(state.deepReview?.patch_candidates || [], state.patchCandidates);
    },
    excerptForPatch() {
      return this.selectedExcerpt.trim() || preferredExcerpt(this.draftContent);
    },
  },
  actions: {
    markFresh() {
      this.loaded = true;
      this.stale = false;
    },
    clearAuthorDraft() {
      this.authorDraft = null;
      this.draftContent = "";
      this.draftSavedContent = "";
      this.pendingCandidateDecisions = [];
    },
    syncSelectedScene() {
      const scenes = this.availableScenes;
      if (!scenes.length) {
        this.selectedSceneId = "";
        if (this.draftMode === "scene") {
          this.draftMode = "chapter";
        }
        return;
      }
      if (!scenes.some((scene) => scene.scene_id === this.selectedSceneId)) {
        this.selectedSceneId = scenes[0].scene_id;
      }
    },
    async loadChapters() {
      const payload = await fetchChapterManuscripts();
      this.chapters = snapshotPayloadList(payload.items || []);
      if (!this.chapters.length) {
        this.selectedChapterId = "";
        this.selectedSceneId = "";
        this.detail = null;
        this.deepReview = null;
        this.patchCandidates = [];
        this.clearAuthorDraft();
        return;
      }
      if (!this.chapters.some((chapter) => chapter.chapter_id === this.selectedChapterId)) {
        this.selectedChapterId = this.chapters[0].chapter_id;
      }
    },
    async loadDetail(chapterId = this.selectedChapterId) {
      if (!chapterId) {
        this.detail = null;
        this.clearAuthorDraft();
        return;
      }
      const payload = await fetchChapterManuscriptDetail(chapterId);
      this.selectedChapterId = chapterId;
      this.detail = snapshotPayload(payload);
      this.syncSelectedScene();
    },
    async loadDeepReview() {
      if (!this.draftObjectId) {
        this.deepReview = null;
        this.patchCandidates = [];
        return;
      }
      const payload =
        this.draftObjectType === "scene"
          ? await fetchSceneDeepReview(this.draftObjectId)
          : await fetchChapterDeepReview(this.draftObjectId);
      this.deepReview = snapshotPayload(payload);
      this.patchCandidates = snapshotPayloadList(payload.patch_candidates || []);
    },
    async loadPreference() {
      const payload = await fetchAuthorPreferenceProfile();
      this.preferenceProfile = snapshotPayload(payload.profile || null);
    },
    async loadAuthorDraft({ ensure = true } = {}) {
      if (!this.draftObjectId) {
        this.clearAuthorDraft();
        return null;
      }
      const payload = ensure
        ? await ensureAuthorDraftApi(this.draftObjectType, this.draftObjectId)
        : await fetchCurrentAuthorDraft(this.draftObjectType, this.draftObjectId);
      const draft = snapshotPayload(payload.draft || null);
      this.authorDraft = draft;
      this.draftContent = draft?.content || "";
      this.draftSavedContent = this.draftContent;
      this.pendingCandidateDecisions = [];
      if (!this.selectedExcerpt.trim()) {
        this.selectedExcerpt = preferredExcerpt(this.draftContent);
      }
      return draft;
    },
    async ensureAuthorDraft() {
      return this.loadAuthorDraft({ ensure: true });
    },
    async refreshSelected(preferredChapterId = this.selectedChapterId) {
      await this.loadChapters();
      if (preferredChapterId && this.chapters.some((chapter) => chapter.chapter_id === preferredChapterId)) {
        this.selectedChapterId = preferredChapterId;
      }
      if (this.selectedChapterId) {
        await this.loadDetail(this.selectedChapterId);
        await this.loadAuthorDraft({ ensure: true });
        await this.loadDeepReview();
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
        await this.loadAuthorDraft({ ensure: true });
        await this.loadDeepReview();
        await this.loadPreference();
        this.markFresh();
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async setDraftMode(mode) {
      const nextMode = normalizeDraftMode(mode);
      if (this.draftMode === nextMode) {
        return;
      }
      this.draftMode = nextMode;
      this.error = "";
      this.selectedExcerpt = "";
      this.syncSelectedScene();
      try {
        await this.loadAuthorDraft({ ensure: true });
        await this.loadDeepReview();
      } catch (error) {
        this.error = error.message;
        throw error;
      }
    },
    async selectSceneDraft(sceneId) {
      if (!sceneId || this.selectedSceneId === sceneId) {
        return;
      }
      this.draftMode = "scene";
      this.selectedSceneId = sceneId;
      this.error = "";
      this.selectedExcerpt = "";
      try {
        await this.loadAuthorDraft({ ensure: true });
        await this.loadDeepReview();
      } catch (error) {
        this.error = error.message;
        throw error;
      }
    },
    setDraftContent(value) {
      this.draftContent = String(value || "");
    },
    setSelectedExcerpt(value) {
      this.selectedExcerpt = String(value || "");
    },
    async runCurrentDeepReview() {
      if (this.draftObjectType === "scene") {
        return this.runSceneDeepReview();
      }
      return this.runChapterDeepReview();
    },
    async runChapterDeepReview(chapterId = this.selectedChapterId) {
      this.actionId = "deep-review";
      this.error = "";
      try {
        const result = await runChapterDeepReviewApi(chapterId);
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
    async runSceneDeepReview(sceneId = this.selectedSceneId) {
      this.actionId = "deep-review";
      this.error = "";
      try {
        const result = await runSceneDeepReview(sceneId);
        this.deepReview = snapshotPayload(result);
        this.patchCandidates = snapshotPayloadList(result.patch_candidates || []);
        return `场景深改诊断完成：${result.latest_score ?? "-"}`;
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
        const draft = this.authorDraft || (await this.ensureAuthorDraft());
        const sourceExcerpt = String(payload.source_excerpt || this.excerptForPatch).trim();
        const result = await createPassagePatchCandidate({
          object_type: this.draftObjectType,
          object_id: this.draftObjectId,
          chapter_id: this.selectedChapterId,
          scene_id: this.draftObjectType === "scene" ? this.selectedSceneId : payload.scene_id,
          target_text_ref: draft?.draft_id ? `author_draft:${draft.draft_id}` : this.currentSourceRef,
          source_draft_id: draft?.draft_id || "",
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
    async recordAuthorDraftCandidateEvent(payload = {}) {
      if (!this.authorDraft?.draft_id) {
        return null;
      }
      return recordAuthorDraftCandidateEventApi(this.authorDraft.draft_id, payload);
    },
    async insertCandidateOption(candidate, option = null) {
      if (!candidate?.patch_id) {
        return "";
      }
      const selected = option || candidate.replacement_options?.[0] || null;
      const replacement = selected?.replacement_text || "";
      if (!replacement.trim()) {
        return "";
      }
      this.actionId = `patch-insert:${candidate.patch_id}`;
      this.error = "";
      try {
        const sourceExcerpt = this.selectedExcerpt.trim() || candidate.source_excerpt || "";
        this.draftContent = replaceOrAppend(this.draftContent, sourceExcerpt, replacement);
        const decision = {
          patch_id: candidate.patch_id,
          option_id: selected?.option_id || "",
          label: selected?.label || selected?.tone || "",
        };
        this.pendingCandidateDecisions = snapshotPayloadList([
          decision,
          ...this.pendingCandidateDecisions.filter((item) => item.patch_id !== decision.patch_id),
        ]);
        await this.recordAuthorDraftCandidateEvent({
          event_type: "candidate_inserted",
          patch_id: decision.patch_id,
          option_id: decision.option_id,
          note: "inserted into author draft editor",
          payload_json: {
            label: decision.label,
            source_excerpt: sourceExcerpt,
          },
        });
        return "已放入作者稿编辑器，保存作者稿后才会记录采纳。";
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async saveAuthorDraft(payload = {}) {
      const draft = this.authorDraft || (await this.ensureAuthorDraft());
      if (!draft?.draft_id) {
        return "";
      }
      this.actionId = "draft-save";
      this.error = "";
      const pendingDecisions = snapshotPayloadList(this.pendingCandidateDecisions);
      try {
        const firstDecision = pendingDecisions[0] || {};
        const result = await saveAuthorDraftApi(draft.draft_id, {
          content: this.draftContent,
          base_revision_no: draft.revision_no,
          patch_id: firstDecision.patch_id || payload.patch_id || "",
          option_id: firstDecision.option_id || payload.option_id || "",
          note: payload.note || "saved from writer deep desk",
          ...payload,
        });
        this.authorDraft = snapshotPayload(result.draft || null);
        this.draftContent = this.authorDraft?.content || "";
        this.draftSavedContent = this.draftContent;
        for (const decision of pendingDecisions) {
          await this.recordAuthorDraftCandidateEvent({
            event_type: "candidate_saved",
            patch_id: decision.patch_id,
            option_id: decision.option_id,
            note: "saved into author draft",
          });
          await acceptPassagePatchCandidate(decision.patch_id, {
            selected_option_id: decision.option_id,
            note: "merged into author draft; runtime final untouched",
          });
        }
        this.pendingCandidateDecisions = [];
        await this.loadDeepReview();
        await this.loadPreference();
        return `作者稿已保存到第 ${this.authorDraft?.revision_no || "-"} 版`;
      } catch (error) {
        this.error =
          error.code === "AUTHOR_DRAFT_CONFLICT" ? "作者稿已有新版本，请刷新后再保存。" : error.message;
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
        await this.loadDeepReview();
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
        await this.recordAuthorDraftCandidateEvent({
          event_type: "candidate_rejected",
          patch_id: patchId,
          note: payload.note || "rejected from writer deep desk",
        });
        const result = await rejectPassagePatchCandidate(patchId, payload);
        await this.loadDeepReview();
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
