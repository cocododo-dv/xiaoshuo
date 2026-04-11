const API_BASE_KEY = "novel-system-api-base";
const DEFAULT_API_BASE = "http://127.0.0.1:8000";
const OPERATOR_REF_KEY = "novel-system-operator-ref";
const DEFAULT_OPERATOR_REF = "operator";

export function getApiBase() {
  if (typeof window === "undefined") {
    return DEFAULT_API_BASE;
  }
  return window.localStorage.getItem(API_BASE_KEY) || DEFAULT_API_BASE;
}

export function setApiBase(value) {
  const normalized = value.trim() || DEFAULT_API_BASE;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(API_BASE_KEY, normalized);
  }
  return normalized;
}

export function getOperatorRef() {
  if (typeof window === "undefined") {
    return DEFAULT_OPERATOR_REF;
  }
  return window.localStorage.getItem(OPERATOR_REF_KEY) || DEFAULT_OPERATOR_REF;
}

export function setOperatorRef(value) {
  const normalized = value.trim() || DEFAULT_OPERATOR_REF;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(OPERATOR_REF_KEY, normalized);
  }
  return normalized;
}

function buildUrl(path) {
  return `${getApiBase()}${path}`;
}

function buildIdempotencyKey(path) {
  return `${path}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function buildQueryPath(path, filters = {}, aliases = {}) {
  const params = new URLSearchParams();
  Object.entries(filters || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") {
      return;
    }
    params.set(aliases[key] || key, value);
  });
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

async function parseEnvelope(response) {
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error?.message || `Request failed: ${response.status}`);
  }
  return payload.data;
}

export async function apiGet(path) {
  const response = await fetch(buildUrl(path));
  return parseEnvelope(response);
}

export async function apiPost(path, body = {}) {
  const response = await fetch(buildUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Idempotency-Key": buildIdempotencyKey(path),
      "X-Operator-Ref": getOperatorRef(),
    },
    body: JSON.stringify(body),
  });
  return parseEnvelope(response);
}

export function fetchWorkbench(sceneId) {
  return apiGet(`/api/v1/scenes/${sceneId}/workbench`);
}

export function runFullScene(sceneId) {
  return apiPost(`/api/v1/scenes/${sceneId}/run/full`);
}

export function previewBundleWorksheet(worksheetYaml) {
  return apiPost("/api/v1/interop/preview/bundle-worksheet", { worksheet_yaml: worksheetYaml });
}

export function importBundleWorksheet(worksheetYaml) {
  return apiPost("/api/v1/interop/import/bundle-worksheet", { worksheet_yaml: worksheetYaml });
}

export function fetchBundleWorksheetExport(bundleId) {
  return apiGet(`/api/v1/interop/export/bundle-worksheet/${encodeURIComponent(bundleId)}`);
}

export function fetchReplayFinalScene(rowId) {
  return apiGet(`/api/v1/replay/final-scene/${encodeURIComponent(rowId)}`);
}

export function fetchReplayDraft(rowId) {
  return apiGet(`/api/v1/replay/draft/${encodeURIComponent(rowId)}`);
}

export function fetchReviewItems(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/review-items", filters, {
      itemType: "item_type",
      targetCollection: "target_collection",
      sceneId: "scene_id",
      chapterId: "chapter_id",
    }),
  );
}

export function createReviewItem(payload) {
  return apiPost("/api/v1/review-items", payload);
}

export function approveReview(reviewId) {
  return apiPost(`/api/v1/review-items/${reviewId}/approve`);
}

export function releaseReview(reviewId) {
  return apiPost(`/api/v1/review-items/${reviewId}/release`);
}

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
    buildQueryPath("/api/v1/index/jobs", filters, {
      objectType: "object_type",
      jobType: "job_type",
      reviewId: "review_id",
      aliasScope: "alias_scope",
    }),
  );
}

export function fetchIndexRuntimeLedger(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/index/runtime-ledger", filters, {
      targetRef: "target_ref",
      actorRef: "actor_ref",
    }),
  );
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
    buildQueryPath("/api/v1/human-review-events", filters, {
      eventSource: "event_source",
      sceneId: "scene_id",
      chapterId: "chapter_id",
    }),
  );
}

export function actOnHumanReviewEvent(eventId, action) {
  return apiPost(`/api/v1/human-review-events/${eventId}/actions`, { action });
}
