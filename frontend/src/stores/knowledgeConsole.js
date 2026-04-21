import { defineStore } from "pinia";

import {
  actOnHumanReviewEvent,
  approveReview,
  createReviewItem,
  fetchKnowledgeEntries,
  fetchKnowledgeEntryDetail,
  fetchKnowledgeEntryWorkflow,
  releaseReview,
  retryVerify,
} from "../lib/api";
import { snapshotPayload, snapshotPayloadList } from "../lib/payloadSnapshot";

const ITEM_TYPE_TO_OBJECT_TYPE = {
  style_observation: "style_observation",
  style_rule_set: "style_rule",
  narrative_pattern: "narrative_pattern",
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

const EMPTY_FILTERS = Object.freeze({
  objectType: "",
  scope: "",
  scopeRefId: "",
  status: "",
});

function objectTypeForItemType(itemType) {
  return ITEM_TYPE_TO_OBJECT_TYPE[itemType] || "";
}

function normalizeFilters(value = EMPTY_FILTERS) {
  if (typeof value === "string") {
    return {
      ...EMPTY_FILTERS,
      objectType: value,
    };
  }

  return {
    ...EMPTY_FILTERS,
    objectType: value?.objectType || value?.object_type || "",
    scope: value?.scope || "",
    scopeRefId: value?.scopeRefId || value?.scope_ref_id || "",
    status: value?.status || "",
  };
}

function filtersSignature(filters) {
  return JSON.stringify(normalizeFilters(filters));
}

function itemMatchesFilters(item, filters) {
  const normalized = normalizeFilters(filters);
  const version = item?.active_version || item?.candidate_version || {};

  if (normalized.objectType && item.object_type !== normalized.objectType) {
    return false;
  }
  if (normalized.scope && version.scope !== normalized.scope) {
    return false;
  }
  if (normalized.scopeRefId && version.scope_ref_id !== normalized.scopeRefId) {
    return false;
  }
  if (normalized.status && item.status !== normalized.status) {
    return false;
  }
  return true;
}

function parseJsonField(extraPayload) {
  if (!extraPayload?.trim()) {
    return {};
  }
  try {
    return JSON.parse(extraPayload);
  } catch (error) {
    throw new Error("附加载荷必须是有效的 JSON");
  }
}

function parseListField(value) {
  if (Array.isArray(value)) {
    return value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim());
  }
  if (!value?.trim()) {
    return [];
  }
  return value.split(/[,，、;；\s]+/).map((item) => item.trim()).filter(Boolean);
}

function releaseConflictKind(error) {
  if (error?.status !== 409) {
    return "";
  }
  const message = String(error?.message || "").toLowerCase();
  if (message.includes("already active")) {
    return "already_active";
  }
  if (message.includes("not verified")) {
    return "not_verified";
  }
  return "";
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
  if (form.displayName?.trim()) {
    payload.candidate_payload_json.display_name = form.displayName.trim();
  }
  const pronouns = parseListField(form.pronouns || "");
  if (pronouns.length) {
    payload.candidate_payload_json.pronouns = pronouns;
  }
  if (form.role?.trim()) {
    payload.candidate_payload_json.role = form.role.trim();
  }
  const aliases = parseListField(form.aliases || "");
  if (aliases.length) {
    payload.candidate_payload_json.aliases = aliases;
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
    selectedObjectType: "",
    selectedLineageKey: "",
    supportedObjectTypes: [],
    filters: { ...EMPTY_FILTERS },
    filtersKey: filtersSignature(EMPTY_FILTERS),
    detailRequestId: 0,
    loaded: false,
    stale: false,
    loading: false,
    actionId: "",
    lastCreateResult: null,
    lastActionResult: null,
    error: "",
  }),
  actions: {
    markStale() {
      this.stale = true;
    },
    markFresh(nextFilters = this.filters) {
      this.loaded = true;
      this.stale = false;
      this.filtersKey = filtersSignature(nextFilters);
    },
    async load(nextFilters = this.filters, { force = false } = {}) {
      const normalizedFilters = normalizeFilters(nextFilters);
      const nextFiltersKey = filtersSignature(normalizedFilters);
      if (this.loaded && !this.stale && !force && nextFiltersKey === this.filtersKey) {
        return;
      }

      this.loading = true;
      this.error = "";
      this.filters = normalizedFilters;
      const requestId = ++this.detailRequestId;

      try {
        const knowledgePayload = await fetchKnowledgeEntries(this.filters);
        this.pendingReviewItems = snapshotPayloadList([]);
        this.items = snapshotPayloadList((knowledgePayload.items || []).filter((item) => itemMatchesFilters(item, this.filters)));
        this.supportedObjectTypes = snapshotPayloadList(Array.from(
          new Set([
            ...(knowledgePayload.supported_object_types || []),
            ...Object.values(ITEM_TYPE_TO_OBJECT_TYPE),
          ]),
        ).sort());

        if (requestId === this.detailRequestId) {
          const selectedItem = this.selectedObjectType && this.selectedLineageKey
            ? this.items.find(
              (item) => item.object_type === this.selectedObjectType && item.lineage_key === this.selectedLineageKey,
            )
            : null;
          this.detail = selectedItem && itemMatchesFilters(selectedItem, this.filters) ? selectedItem : null;
        }

        this.markFresh(this.filters);
      } catch (error) {
        this.items = snapshotPayloadList([]);
        this.pendingReviewItems = snapshotPayloadList([]);
        this.supportedObjectTypes = snapshotPayloadList([]);
        this.detail = null;
        this.loaded = false;
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async ensureLoaded(options = {}) {
      const nextFilters = options.filters ?? this.filters;
      await this.load(nextFilters, options);
    },
    async selectItem(objectType, lineageKey) {
      const requestId = ++this.detailRequestId;
      this.actionId = `detail:${objectType}:${lineageKey}`;
      this.error = "";
      this.selectedObjectType = objectType;
      this.selectedLineageKey = lineageKey;
      try {
        const existing = this.items.find(
          (item) => item.object_type === objectType && item.lineage_key === lineageKey,
        );
        const optimisticDetail = existing && itemMatchesFilters(existing, this.filters) ? existing : null;
        if (requestId === this.detailRequestId && optimisticDetail) {
          this.detail = optimisticDetail;
        }
        const [detail, workflow] = await Promise.all([
          fetchKnowledgeEntryDetail(objectType, lineageKey),
          fetchKnowledgeEntryWorkflow(objectType, lineageKey),
        ]);
        if (requestId !== this.detailRequestId) {
          return this.detail;
        }
        const mergedDetail = snapshotPayload({ ...detail, workflow });
        this.detail = mergedDetail && itemMatchesFilters(mergedDetail, this.filters) ? mergedDetail : optimisticDetail;
        return this.detail;
      } catch (error) {
        if (requestId !== this.detailRequestId) {
          return this.detail;
        }
        this.detail = null;
        this.error = error.message;
        throw error;
      } finally {
        if (requestId === this.detailRequestId) {
          this.actionId = "";
        }
      }
    },
    async refreshSelection(objectType = this.selectedObjectType, lineageKey = this.selectedLineageKey, options = {}) {
      await this.load(this.filters, { force: true, ...options });
      if (!objectType || !lineageKey) {
        return null;
      }
      return this.selectItem(objectType, lineageKey);
    },
    async createCandidate(form) {
      this.actionId = "create";
      this.error = "";
      try {
        const payload = buildCreatePayload(form);
        const result = await createReviewItem(payload);
        this.lastCreateResult = result;
        const objectType = objectTypeForItemType(payload.item_type);
        const lineageKey =
          payload.candidate_payload_json?.lineage_key
          || payload.candidate_payload_json?.scene_id
          || payload.candidate_payload_json?.chapter_id
          || payload.review_id;
        await this.refreshSelection(objectType, lineageKey);
        return `已创建候选 ${result.review_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async approveReview(reviewId, payload = {}) {
      this.actionId = `approve:${reviewId}`;
      this.error = "";
      try {
        const result = await approveReview(reviewId, payload);
        this.lastActionResult = result;
        await this.refreshSelection();
        return `已批准 ${reviewId}${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async retryVerifyJob(jobId) {
      this.actionId = `verify:${jobId}`;
      this.error = "";
      try {
        const result = await retryVerify(jobId);
        this.lastActionResult = result;
        await this.refreshSelection();
        return `已重试校验 ${jobId}${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async releaseReview(reviewId) {
      this.actionId = `release:${reviewId}`;
      this.error = "";
      try {
        const result = await releaseReview(reviewId);
        this.lastActionResult = result;
        await this.refreshSelection();
        return `已发布 ${reviewId}${result.actor_ref ? `，操作员 ${result.actor_ref}` : ""}`;
      } catch (error) {
        const conflictKind = releaseConflictKind(error);
        if (conflictKind === "already_active") {
          this.lastActionResult = { review_id: reviewId, release_status: "already_active" };
          await this.refreshSelection();
          this.error = "";
          return `已是最新发布状态：${reviewId}`;
        }
        if (conflictKind === "not_verified") {
          const message = `候选尚未通过校验：${reviewId}。请先重试校验，成功后再发布。`;
          try {
            await this.refreshSelection();
          } catch {
          }
          this.error = message;
          throw new Error(message);
        }
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
    async actOnHumanReviewEvent(eventId, action) {
      this.actionId = `human-review:${eventId}:${action}`;
      this.error = "";
      try {
        const result = await actOnHumanReviewEvent(eventId, action);
        this.lastActionResult = result;
        await this.refreshSelection();
        return `已对 ${eventId} 执行动作 ${action}（${result.status || "已更新"}）`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.actionId = "";
      }
    },
  },
});
