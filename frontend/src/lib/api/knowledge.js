import { apiGet, apiPost, buildQueryPath, buildListQueryPath, CURSOR_PAGINATION_DEFAULT_LIMIT, normalizeListPayload } from "./client";

export function fetchKnowledge(filters = "") {
  const normalized =
    typeof filters === "string"
      ? { objectType: filters }
      : {
          objectType: filters?.objectType || filters?.object_type || "",
          scope: filters?.scope || "",
          scopeRefId: filters?.scopeRefId || filters?.scope_ref_id || "",
          status: filters?.status || "",
        };
  const params = new URLSearchParams();
  if (normalized.objectType) {
    params.set("object_type", normalized.objectType);
  }
  if (normalized.scope) {
    params.set("scope", normalized.scope);
  }
  if (normalized.scopeRefId) {
    params.set("scope_ref_id", normalized.scopeRefId);
  }
  if (normalized.status) {
    params.set("status", normalized.status);
  }
  const queryString = params.toString();
  const query = queryString ? `?${queryString}` : "";
  return apiGet(`/api/v1/knowledge${query}`);
}

export function fetchKnowledgeDetail(objectType, lineageKey) {
  return apiGet(`/api/v1/knowledge/${encodeURIComponent(objectType)}/${encodeURIComponent(lineageKey)}`);
}

export function fetchKnowledgeEntries(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/knowledge-entries", filters, {
      objectType: "object_type",
      scopeRefId: "scope_ref_id",
    }),
  );
}

export function fetchKnowledgeEntryDetail(objectType, lineageKey) {
  return apiGet(`/api/v1/knowledge-entries/${encodeURIComponent(objectType)}/${encodeURIComponent(lineageKey)}`);
}

export function fetchKnowledgeEntryWorkflow(objectType, lineageKey) {
  return apiGet(
    `/api/v1/knowledge-entries/${encodeURIComponent(objectType)}/${encodeURIComponent(lineageKey)}/workflow`,
  );
}

export function fetchAliasScopes(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/index/alias-scopes", filters, {
      objectType: "object_type",
      scopeRefId: "scope_ref_id",
      verifyStatus: "verify_status",
    }),
  );
}

export function fetchIndexJobs(filters = {}) {
  return apiGet(
    buildListQueryPath("/api/v1/index/jobs", filters, {
      objectType: "object_type",
      jobType: "job_type",
      reviewId: "review_id",
      aliasScope: "alias_scope",
    }),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}

export function fetchVectorAliasScopes(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/vector-alias-scopes", filters, {
      objectType: "object_type",
      scopeRefId: "scope_ref_id",
      verifyStatus: "verify_status",
    }),
  );
}

export function fetchJobs(filters = {}) {
  return apiGet(
    buildListQueryPath("/api/v1/jobs", filters, {
      objectType: "object_type",
      jobType: "job_type",
      reviewId: "review_id",
      aliasScope: "alias_scope",
    }),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}

export function fetchIndexRuntimeLedger(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/index/runtime-ledger", filters, {
      targetRef: "target_ref",
      actorRef: "actor_ref",
    }),
  );
}

export function fetchActivityEvents(filters = {}) {
  return apiGet(
    buildListQueryPath("/api/v1/activity-events", filters, {
      targetRef: "target_ref",
      actorRef: "actor_ref",
    }),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}

export function fetchTargetActivityGroups(filters = {}) {
  return apiGet(
    buildListQueryPath("/api/v1/target-activity-groups", filters, {
      targetRef: "target_ref",
      actorRef: "actor_ref",
    }),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}

export function fetchTargetActivityGroupItems(targetRef, filters = {}) {
  return apiGet(
    buildListQueryPath(`/api/v1/target-activity-groups/${encodeURIComponent(targetRef)}/items`, filters, {
      actorRef: "actor_ref",
    }),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}

export function retryVerify(jobId) {
  return apiPost(`/api/v1/index/verify/${jobId}/retry`);
}

export function runRecoverySweep() {
  return apiPost("/api/v1/runtime/recovery/sweep");
}

export function runDuePromotions() {
  return apiPost("/api/v1/runtime/promotions/run-due");
}

export function fetchHumanReviewEvents(filters = {}) {
  return apiGet(
    buildListQueryPath("/api/v1/human-review-events", filters, {
      eventSource: "event_source",
      sceneId: "scene_id",
      chapterId: "chapter_id",
    }),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}

export function actOnHumanReviewEvent(eventId, action, payload = {}) {
  return apiPost(`/api/v1/human-review-events/${eventId}/actions`, { action, ...(payload || {}) });
}
