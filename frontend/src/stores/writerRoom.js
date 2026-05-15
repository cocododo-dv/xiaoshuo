import { defineStore } from "pinia";

import {
  applyAuthorDraftScopedProposal,
  ensureAuthorDraft,
  ensureBlankAuthorDraft,
  fetchAuthorDraftProposalDiff,
  fetchChapters,
  fetchWriterRoom,
  generateAuthorDraftProposalSet,
  openProjectChapterDraft,
  rejectAuthorDraftProposal,
  saveAuthorDraft as saveAuthorDraftApi,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

const PROPOSAL_KIND_LABELS = {
  structure_note: "结构提示",
  whole_draft: "整段候选",
  local_patch: "局部改法",
  dialogue_pass: "对白深改",
  language_pass: "语言压缩",
  continuation: "续写",
  near_final_rewrite: "近终稿重写",
};

function targetFromPayload(payload = {}) {
  const target = payload.target || {};
  const navigation = payload.navigation || {};
  return {
    objectType: target.object_type || target.objectType || payload.object_type || "scene",
    objectId:
      target.object_id
      || target.objectId
      || navigation.selected_scene_id
      || navigation.selected_chapter_id
      || "",
  };
}

function proposalIdOf(proposal) {
  return typeof proposal === "string" ? proposal : proposal?.proposal_id || "";
}

function upsertById(items, item, idKey) {
  if (!item?.[idKey]) {
    return snapshotPayloadList(items);
  }
  return snapshotPayloadList([
    item,
    ...(items || []).filter((row) => row?.[idKey] !== item[idKey]),
  ]);
}

function mergeById(existing, incoming, idKey) {
  const incomingItems = snapshotPayloadList(incoming || []).filter((item) => item?.[idKey]);
  const incomingIds = new Set(incomingItems.map((item) => item[idKey]));
  return snapshotPayloadList([
    ...incomingItems,
    ...(existing || []).filter((item) => !incomingIds.has(item?.[idKey])),
  ]);
}

function proposalCardFromProposal(proposal = {}) {
  const proposalKind = proposal.proposal_kind || proposal.proposal_type || "whole_draft";
  return {
    proposal_id: proposal.proposal_id,
    draft_id: proposal.draft_id,
    proposal_kind: proposalKind,
    proposal_type: proposal.proposal_type,
    display_kind: proposal.display_kind || PROPOSAL_KIND_LABELS[proposalKind] || "可采纳改法",
    status: proposal.status,
    merge_status: proposal.merge_status,
    rationale: proposal.rationale || "",
    excerpt: proposal.excerpt || proposal.replacement_text || proposal.content || "",
    target_range: proposal.target_range || null,
    source_evaluation_id: proposal.source_evaluation_id || "",
  };
}

function draftFromEnsureResult(result = {}, primaryText = {}) {
  const draft = snapshotPayload(result.draft || null);
  const content = draft?.content || primaryText?.content || "";
  return {
    draft,
    content,
    proposals: snapshotPayloadList(result.open_draft_proposals || []),
    authorPreferenceSummary: snapshotPayload(result.author_preference_summary || {}),
  };
}

export const useWriterRoomStore = defineStore("writerRoom", {
  state: () => ({
    objectType: "scene",
    objectId: "",
    writerRoomPayload: null,
    target: null,
    navigation: {
      chapters: [],
      scenes: [],
    },
    chapter: null,
    sceneCard: null,
    draft: null,
    primaryText: {
      source: "empty",
      source_ref: "",
      content: "",
      revision_no: 0,
    },
    diagnosis: null,
    authorTopIssue: null,
    keepAdvice: "",
    sceneForm: "",
    proposals: [],
    proposalCards: [],
    contextPressure: [],
    longformCards: [],
    dailyFocus: [],
    authorPreferenceSummary: {},
    nextActions: [],
    proposalDiff: null,
    proposalMode: "near_final",
    draftContent: "",
    draftSavedContent: "",
    loading: false,
    actionId: "",
    error: "",
    loaded: false,
  }),
  getters: {
    selectedChapterId: (state) =>
      state.navigation?.selected_chapter_id
      || state.target?.chapter_id
      || state.chapter?.chapter_id
      || "",
    selectedSceneId: (state) =>
      state.navigation?.selected_scene_id
      || state.target?.scene_id
      || state.sceneCard?.scene_id
      || "",
    topIssue: (state) => state.authorTopIssue || state.diagnosis?.top_issue || null,
    scoreVisible: (state) => Boolean(state.diagnosis?.score_visible),
    draftDirty: (state) => String(state.draftContent || "") !== String(state.draftSavedContent || ""),
    currentDraftId: (state) => state.draft?.draft_id || "",
  },
  actions: {
    applyPayload(payload = {}) {
      const { objectType, objectId } = targetFromPayload(payload);
      this.objectType = objectType;
      this.objectId = objectId;
      this.writerRoomPayload = snapshotPayload(payload || null);
      this.target = snapshotPayload(payload.target || null);
      this.navigation = snapshotPayload({
        chapters: [],
        scenes: [],
        ...(payload.navigation || {}),
      });
      this.chapter = snapshotPayload(payload.chapter || null);
      this.sceneCard = snapshotPayload(payload.scene_card || null);
      this.draft = snapshotPayload(payload.draft || null);
      this.primaryText = snapshotPayload(
        payload.primary_text || {
          source: "empty",
          source_ref: "",
          content: "",
          revision_no: 0,
        },
      );
      this.diagnosis = snapshotPayload(payload.diagnosis || null);
      this.authorTopIssue = snapshotPayload(payload.top_issue || payload.diagnosis?.top_issue || null);
      this.keepAdvice = payload.keep_advice || payload.diagnosis?.keep || "";
      this.sceneForm = payload.scene_form || payload.sceneCard?.scene_type || payload.scene_card?.scene_type || "";
      this.proposals = snapshotPayloadList(payload.proposals || []);
      this.proposalCards = snapshotPayloadList(
        (payload.proposal_cards || []).length
          ? payload.proposal_cards
          : this.proposals.map((proposal) => proposalCardFromProposal(proposal)),
      );
      this.contextPressure = snapshotPayloadList(payload.context_pressure || []);
      this.longformCards = snapshotPayloadList(
        (payload.longform_cards || []).length ? payload.longform_cards : this.contextPressure,
      );
      this.dailyFocus = snapshotPayloadList(payload.daily_focus || []);
      this.authorPreferenceSummary = snapshotPayload(payload.author_preference_summary || {});
      this.nextActions = snapshotPayloadList(payload.next_actions || []);
      this.proposalDiff = null;
      this.draftContent = this.draft?.content || this.primaryText?.content || "";
      this.draftSavedContent = this.draftContent;
      this.loaded = true;
      return this.writerRoomPayload;
    },
    async load(objectType = "scene", objectId = this.objectId) {
      if (!objectId) {
        return this.loadDefault();
      }
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchWriterRoom(objectType, objectId);
        return this.applyPayload(payload || {});
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async openChapterDraft(projectId, payload = {}) {
      if (!projectId) {
        throw new Error("Project is required before opening a chapter draft.");
      }
      this.loading = true;
      this.error = "";
      try {
        const result = await openProjectChapterDraft(projectId, payload || {});
        return this.applyPayload(result || {});
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async loadDefault() {
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchChapters();
        const chapters = snapshotPayloadList(payload.items || payload.chapters || payload || []);
        const firstChapter = chapters[0] || null;
        const firstScene =
          (Array.isArray(firstChapter?.scenes) && firstChapter.scenes[0])
          || (Array.isArray(firstChapter?.scene_cards) && firstChapter.scene_cards[0])
          || null;
        if (firstScene?.scene_id) {
          return await this.load("scene", firstScene.scene_id);
        }
        if (firstChapter?.chapter_id) {
          return await this.load("chapter", firstChapter.chapter_id);
        }
        this.applyPayload({
          target: { object_type: "scene", object_id: "" },
          navigation: { chapters, scenes: [] },
          primary_text: { source: "empty", source_ref: "", content: "", revision_no: 0 },
          diagnosis: { status: "empty", score_visible: false },
          next_actions: [],
        });
        return this.writerRoomPayload;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    setDraftContent(value) {
      this.draftContent = String(value || "");
    },
    async ensureDraft() {
      if (this.draft?.draft_id) {
        return this.draft;
      }
      if (!this.objectId) {
        return null;
      }
      this.actionId = "draft-ensure";
      this.error = "";
      try {
        const result = await ensureAuthorDraft(this.objectType, this.objectId);
        const normalized = draftFromEnsureResult(result, this.primaryText);
        this.draft = normalized.draft;
        this.draftContent = normalized.content;
        this.draftSavedContent = this.draftContent;
        this.proposals = normalized.proposals.length ? normalized.proposals : snapshotPayloadList(this.proposals);
        this.proposalCards = snapshotPayloadList(this.proposals.map((proposal) => proposalCardFromProposal(proposal)));
        this.authorPreferenceSummary = Object.keys(normalized.authorPreferenceSummary).length
          ? normalized.authorPreferenceSummary
          : snapshotPayload(this.authorPreferenceSummary);
        return this.draft;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async ensureBlankDraft() {
      if (!this.objectId) {
        return null;
      }
      this.actionId = "draft-ensure-blank";
      this.error = "";
      try {
        const result = await ensureBlankAuthorDraft(this.objectType, this.objectId);
        const normalized = draftFromEnsureResult(result, { content: "" });
        this.draft = normalized.draft;
        this.draftContent = normalized.draft?.content || "";
        this.draftSavedContent = this.draftContent;
        this.proposals = normalized.proposals.length ? normalized.proposals : snapshotPayloadList(this.proposals);
        this.proposalCards = snapshotPayloadList(this.proposals.map((proposal) => proposalCardFromProposal(proposal)));
        this.authorPreferenceSummary = Object.keys(normalized.authorPreferenceSummary).length
          ? normalized.authorPreferenceSummary
          : snapshotPayload(this.authorPreferenceSummary);
        return this.draft;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async saveDraft(payload = {}) {
      const draft = this.draft || (await this.ensureDraft());
      if (!draft?.draft_id) {
        return null;
      }
      this.actionId = "draft-save";
      this.error = "";
      try {
        const result = await saveAuthorDraftApi(draft.draft_id, {
          content: this.draftContent,
          base_revision_no: draft.revision_no,
          note: payload.note || "saved from writer room",
          ...payload,
        });
        this.draft = snapshotPayload(result.draft || null);
        this.primaryText = snapshotPayload({
          ...(this.primaryText || {}),
          source: "author_draft",
          source_ref: this.draft?.draft_id ? `author_draft:${this.draft.draft_id}` : this.primaryText?.source_ref || "",
          content: this.draft?.content || "",
          revision_no: this.draft?.revision_no || 0,
        });
        this.draftContent = this.draft?.content || "";
        this.draftSavedContent = this.draftContent;
        return this.draft;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async previewProposal(proposal) {
      const proposalId = proposalIdOf(proposal);
      const draft = this.draft || (await this.ensureDraft());
      if (!draft?.draft_id || !proposalId) {
        return null;
      }
      this.actionId = `proposal-preview:${proposalId}`;
      this.error = "";
      try {
        const diff = await fetchAuthorDraftProposalDiff(draft.draft_id, proposalId);
        this.proposalDiff = snapshotPayload(diff || null);
        return this.proposalDiff;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async applyProposal(proposal, payload = {}) {
      const proposalId = proposalIdOf(proposal);
      const draft = this.draft || (await this.ensureDraft());
      if (!draft?.draft_id || !proposalId) {
        return null;
      }
      this.actionId = `proposal-apply:${proposalId}`;
      this.error = "";
      try {
        let diff = this.proposalDiff?.proposal_id === proposalId ? this.proposalDiff : null;
        if (!diff) {
          diff = await fetchAuthorDraftProposalDiff(draft.draft_id, proposalId);
          this.proposalDiff = snapshotPayload(diff || null);
        }
        if (diff?.merge_status === "conflict") {
          const error = new Error("当前草稿已经变化，请先重新预览差异。");
          error.code = "WRITER_ROOM_PROPOSAL_CONFLICT";
          throw error;
        }
        const result = await applyAuthorDraftScopedProposal(draft.draft_id, {
          proposal_id: proposalId,
          apply_mode: payload.apply_mode || payload.proposal_kind || undefined,
          note: payload.note || "applied from writer room",
          ...payload,
        });
        const appliedProposal = snapshotPayload(result.proposal || null);
        this.proposals = upsertById(this.proposals, appliedProposal, "proposal_id");
        this.proposalCards = upsertById(this.proposalCards, proposalCardFromProposal(appliedProposal), "proposal_id");
        this.draft = snapshotPayload(result.draft || null);
        this.primaryText = snapshotPayload({
          ...(this.primaryText || {}),
          source: "author_draft",
          source_ref: this.draft?.draft_id ? `author_draft:${this.draft.draft_id}` : this.primaryText?.source_ref || "",
          content: this.draft?.content || "",
          revision_no: this.draft?.revision_no || 0,
        });
        this.draftContent = this.draft?.content || "";
        this.draftSavedContent = this.draftContent;
        this.authorPreferenceSummary = snapshotPayload(result.author_preference_summary || this.authorPreferenceSummary);
        if (result.open_draft_proposals?.length) {
          this.proposals = snapshotPayloadList([
            ...result.open_draft_proposals,
            ...this.proposals.filter((item) => item.proposal_id === proposalId),
          ]);
          this.proposalCards = snapshotPayloadList(this.proposals.map((proposal) => proposalCardFromProposal(proposal)));
        }
        this.proposalDiff = null;
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async generateProposalSet(payload = {}) {
      const draft = this.draft || (await this.ensureDraft());
      if (!draft?.draft_id) {
        return null;
      }
      const mode = payload.mode || this.proposalMode || "near_final";
      this.actionId = "proposal-generate-set";
      this.error = "";
      try {
        const result = await generateAuthorDraftProposalSet(draft.draft_id, {
          mode,
          instruction: payload.instruction || "",
          target_range: payload.target_range || undefined,
          source_evaluation_id: payload.source_evaluation_id || this.diagnosis?.evaluation_id || undefined,
        });
        const generated = snapshotPayloadList(result.proposals || []);
        this.proposalMode = result.mode || mode;
        this.proposals = mergeById(this.proposals, generated, "proposal_id");
        this.proposalCards = mergeById(
          this.proposalCards,
          generated.map((proposal) => proposalCardFromProposal(proposal)),
          "proposal_id",
        );
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async rejectProposal(proposal, payload = {}) {
      const proposalId = proposalIdOf(proposal);
      if (!proposalId) {
        return null;
      }
      this.actionId = `proposal-reject:${proposalId}`;
      this.error = "";
      try {
        const result = await rejectAuthorDraftProposal(proposalId, {
          note: payload.note || "rejected from writer room",
          decision_reason: payload.decision_reason || "",
          ...payload,
        });
        const rejectedProposal = snapshotPayload(result.proposal || null);
        this.proposals = upsertById(this.proposals, rejectedProposal, "proposal_id");
        this.proposalCards = upsertById(this.proposalCards, proposalCardFromProposal(rejectedProposal), "proposal_id");
        this.authorPreferenceSummary = snapshotPayload(result.author_preference_summary || this.authorPreferenceSummary);
        return result;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
