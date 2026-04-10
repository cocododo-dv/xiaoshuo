import { defineStore } from "pinia";

import { createReviewItem, fetchKnowledge, fetchKnowledgeDetail, fetchReviewItems } from "../lib/api";

const ITEM_TYPE_TO_OBJECT_TYPE = {
  style_observation: "style_observation",
  style_rule_set: "style_rule",
  banned_rule_cluster: "banned_rule_cluster",
  voice_card_candidate: "voice_card",
  relation_card_candidate: "relation_card",
  world_rule: "world_rule",
  calibration_candidate: "calibration_line",
  foreshadow_open: "foreshadow",
  foreshadow_touch: "foreshadow",
  foreshadow_resolve: "foreshadow",
  scene_summary: "scene_summary",
  chapter_summary: "chapter_summary",
};

function objectTypeForItemType(itemType) {
  return ITEM_TYPE_TO_OBJECT_TYPE[itemType] || "";
}

function lineageKeyForReview(review) {
  const payload = review?.candidate_payload_json || {};
  return payload.lineage_key || payload.scene_id || payload.chapter_id || review?.review_id || "";
}

function candidateVersionFromReview(review) {
  const payload = review?.candidate_payload_json || {};
  return {
    review_id: review.review_id,
    text: review.candidate_text,
    active_flag: false,
    runtime_eligible: false,
    review_status: review.status,
    materialize_status: review.materialize_status,
    target_collection: review.target_collection,
    scope: payload.scope || null,
    scope_ref_id: payload.scope_ref_id || null,
    character_id: payload.character_id || null,
    left_character_id: payload.left_character_id || null,
    right_character_id: payload.right_character_id || null,
    chapter_id: payload.chapter_id || review.chapter_id || null,
    scene_id: payload.scene_id || review.scene_id || null,
  };
}

function mergeKnowledgeAndPendingReviews(knowledgeItems, reviewItems) {
  const merged = new Map();

  for (const item of knowledgeItems || []) {
    merged.set(`${item.object_type}:${item.lineage_key}`, {
      ...item,
      review_refs: [...(item.review_refs || [])],
    });
  }

  for (const review of reviewItems || []) {
    if (review.status === "rejected") {
      continue;
    }
    const objectType = objectTypeForItemType(review.item_type);
    const lineageKey = lineageKeyForReview(review);
    if (!objectType || !lineageKey) {
      continue;
    }
    const key = `${objectType}:${lineageKey}`;
    const existing = merged.get(key);
    const reviewRefList = existing?.review_refs || [];
    const mergedReviewRefs = Array.from(new Set([...reviewRefList, review.review_id]));

    if (!existing) {
      merged.set(key, {
        object_type: objectType,
        lineage_key: lineageKey,
        status: "candidate",
        active_version: null,
        candidate_version: candidateVersionFromReview(review),
        versions: [],
        review_refs: mergedReviewRefs,
        runtime_refs: { mode: "pending_review" },
        bundle_refs: [],
      });
      continue;
    }

    if (review.materialize_status !== "succeeded" || !existing.candidate_version) {
      existing.candidate_version = candidateVersionFromReview(review);
    }
    existing.review_refs = mergedReviewRefs;
  }

  return Array.from(merged.values()).sort((left, right) =>
    `${left.object_type}:${left.lineage_key}`.localeCompare(`${right.object_type}:${right.lineage_key}`),
  );
}

function mergeDetailWithPending(detail, reviewItems) {
  if (!detail) {
    return null;
  }
  const mergedList = mergeKnowledgeAndPendingReviews([detail], reviewItems);
  return mergedList[0] || detail;
}

function parseJsonField(extraPayload) {
  if (!extraPayload?.trim()) {
    return {};
  }
  try {
    return JSON.parse(extraPayload);
  } catch (error) {
    throw new Error("Extra payload must be valid JSON");
  }
}

function buildCreatePayload(form) {
  const itemType = form.itemType;
  const candidateText = form.candidateText?.trim() || "";
  const reviewId = form.reviewId?.trim() || "";
  const lineageKey = form.lineageKey?.trim() || form.sceneId?.trim() || form.chapterId?.trim() || reviewId;
  const payload = {
    review_id: reviewId,
    scene_id: form.sceneId?.trim() || null,
    chapter_id: form.chapterId?.trim() || null,
    item_type: itemType,
    candidate_text: candidateText,
    active_on_approve: Number(form.activeOnApprove ?? 1),
    candidate_payload_json: {
      lineage_key: lineageKey,
      text: candidateText,
      ...parseJsonField(form.extraPayload || ""),
    },
  };

  if (form.scope?.trim()) {
    payload.candidate_payload_json.scope = form.scope.trim();
  }
  if (form.scopeRefId?.trim()) {
    payload.candidate_payload_json.scope_ref_id = form.scopeRefId.trim();
  }
  if (form.sceneId?.trim()) {
    payload.candidate_payload_json.scene_id = form.sceneId.trim();
  }
  if (form.chapterId?.trim()) {
    payload.candidate_payload_json.chapter_id = form.chapterId.trim();
  }
  if (form.characterId?.trim()) {
    payload.candidate_payload_json.character_id = form.characterId.trim();
  }
  if (form.leftCharacterId?.trim()) {
    payload.candidate_payload_json.left_character_id = form.leftCharacterId.trim();
  }
  if (form.rightCharacterId?.trim()) {
    payload.candidate_payload_json.right_character_id = form.rightCharacterId.trim();
  }
  if (form.ruleTier?.trim()) {
    payload.candidate_payload_json.rule_tier = form.ruleTier.trim();
  }
  return payload;
}

export const useKnowledgeConsoleStore = defineStore("knowledgeConsole", {
  state: () => ({
    items: [],
    pendingReviewItems: [],
    detail: null,
    supportedObjectTypes: [],
    objectTypeFilter: "",
    loading: false,
    actionId: "",
    lastCreateResult: null,
    error: "",
  }),
  actions: {
    async load(objectType = this.objectTypeFilter) {
      this.loading = true;
      this.error = "";
      this.objectTypeFilter = objectType || "";
      try {
        const [knowledgePayload, reviewPayload] = await Promise.all([
          fetchKnowledge(this.objectTypeFilter),
          fetchReviewItems(),
        ]);
        this.pendingReviewItems = reviewPayload.items || [];
        this.items = mergeKnowledgeAndPendingReviews(knowledgePayload.items || [], this.pendingReviewItems).filter(
          (item) => !this.objectTypeFilter || item.object_type === this.objectTypeFilter,
        );
        this.supportedObjectTypes = Array.from(
          new Set([
            ...(knowledgePayload.supported_object_types || []),
            ...Object.values(ITEM_TYPE_TO_OBJECT_TYPE),
          ]),
        ).sort();
        if (this.detail) {
          this.detail = mergeDetailWithPending(this.detail, this.pendingReviewItems);
        }
      } catch (error) {
        this.items = [];
        this.pendingReviewItems = [];
        this.supportedObjectTypes = [];
        this.detail = null;
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async selectItem(objectType, lineageKey) {
      this.actionId = `detail:${objectType}:${lineageKey}`;
      this.error = "";
      try {
        const existing = this.items.find(
          (item) => item.object_type === objectType && item.lineage_key === lineageKey,
        );
        if (existing && (!existing.versions || existing.versions.length === 0)) {
          this.detail = existing;
          return existing;
        }
        const detail = await fetchKnowledgeDetail(objectType, lineageKey);
        this.detail = mergeDetailWithPending(detail, this.pendingReviewItems);
        return this.detail;
      } catch (error) {
        this.detail = null;
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async createCandidate(form) {
      this.actionId = "create";
      this.error = "";
      try {
        const payload = buildCreatePayload(form);
        const result = await createReviewItem(payload);
        this.lastCreateResult = result;
        await this.load(this.objectTypeFilter);
        return `Created candidate ${result.review_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
