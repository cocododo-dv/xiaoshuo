import { CURSOR_PAGINATION_DEFAULT_LIMIT, normalizeListPayload } from "./cursorPagination";

const API_BASE_KEY = "novel-system-api-base";
const API_BASE_DEFAULT_KEY = "novel-system-api-base-default";
const FALLBACK_API_BASE = "http://127.0.0.1:8000";
const DEFAULT_API_BASE = (import.meta.env.VITE_NOVEL_SYSTEM_API_BASE || FALLBACK_API_BASE).trim();
const OPERATOR_REF_KEY = "novel-system-operator-ref";
const DEFAULT_OPERATOR_REF = "operator";
const LIST_QUERY_ALIASES = {
  pageSize: "page_size",
  workerId: "worker_id",
  stuckOnly: "stuck_only",
};

function isLoopbackApiBase(value) {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      ["127.0.0.1", "localhost"].includes(url.hostname)
    );
  } catch {
    return false;
  }
}

function shouldUseInjectedDefault(stored, storedDefault) {
  if (!stored) {
    return true;
  }
  if (stored === FALLBACK_API_BASE) {
    return true;
  }
  if (storedDefault && stored === storedDefault) {
    return true;
  }
  return !storedDefault && isLoopbackApiBase(stored) && isLoopbackApiBase(DEFAULT_API_BASE);
}

export function getApiBase() {
  if (typeof window === "undefined") {
    return DEFAULT_API_BASE;
  }
  const stored = (window.localStorage.getItem(API_BASE_KEY) || "").trim();
  const storedDefault = (window.localStorage.getItem(API_BASE_DEFAULT_KEY) || "").trim();
  if (shouldUseInjectedDefault(stored, storedDefault)) {
    window.localStorage.setItem(API_BASE_KEY, DEFAULT_API_BASE);
    window.localStorage.setItem(API_BASE_DEFAULT_KEY, DEFAULT_API_BASE);
    return DEFAULT_API_BASE;
  }
  window.localStorage.setItem(API_BASE_DEFAULT_KEY, DEFAULT_API_BASE);
  return stored;
}

export function setApiBase(value) {
  const normalized = value.trim() || DEFAULT_API_BASE;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(API_BASE_KEY, normalized);
    window.localStorage.setItem(API_BASE_DEFAULT_KEY, DEFAULT_API_BASE);
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

function buildUrlFromBase(baseUrl, path) {
  return `${String(baseUrl || DEFAULT_API_BASE).trim().replace(/\/+$/, "")}${path}`;
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

function buildListQueryPath(path, filters = {}, aliases = {}) {
  return buildQueryPath(path, filters, {
    ...LIST_QUERY_ALIASES,
    ...aliases,
  });
}

function normalizeRequestError(error) {
  if (error instanceof Error) {
    if (error.code || error.status) {
      return error;
    }
    if (error.message === "Failed to fetch") {
      return new Error(`连接接口失败，请确认 API 地址和后端服务是否可用。当前 API 地址：${getApiBase()}`);
    }
    return error;
  }
  return new Error("请求失败。");
}

async function parseEnvelope(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok || payload?.ok === false) {
    const responseError = payload?.error || {};
    const fallbackMessage =
      responseError.code === "DATABASE_BUSY"
        ? "数据库正忙，请稍后重试。"
        : `请求失败：${response.status}`;
    const error = new Error(responseError.message || fallbackMessage);
    error.code = responseError.code || null;
    error.status = response.status;
    error.details = responseError.details || {};
    throw error;
  }
  return payload?.data;
}

export async function apiGet(path) {
  try {
    const response = await fetch(buildUrl(path));
    return parseEnvelope(response);
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

export async function apiGetFromBase(baseUrl, path) {
  try {
    const response = await fetch(buildUrlFromBase(baseUrl, path));
    return parseEnvelope(response);
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

export async function apiPost(path, body = {}) {
  try {
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
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

export async function apiPatch(path, body = {}) {
  try {
    const response = await fetch(buildUrl(path), {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-Operator-Ref": getOperatorRef(),
      },
      body: JSON.stringify(body),
    });
    return parseEnvelope(response);
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

async function apiAdminPost(path, body = {}, adminToken = "") {
  try {
    const headers = {
      "Content-Type": "application/json",
      "X-Operator-Ref": getOperatorRef(),
    };
    if (adminToken) {
      headers["X-Admin-Token"] = adminToken;
    }
    const response = await fetch(buildUrl(path), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    return parseEnvelope(response);
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

async function apiPostForm(path, formData) {
  try {
    const response = await fetch(buildUrl(path), {
      method: "POST",
      headers: {
        "X-Idempotency-Key": buildIdempotencyKey(path),
        "X-Operator-Ref": getOperatorRef(),
      },
      body: formData,
    });
    return parseEnvelope(response);
  } catch (error) {
    throw normalizeRequestError(error);
  }
}

export function fetchSystemConfig() {
  return apiGet("/api/v1/system-config");
}

export function fetchSystemConfigAtBase(baseUrl) {
  return apiGetFromBase(baseUrl, "/api/v1/system-config");
}

export function saveSystemConfigDraft(payload, adminToken) {
  return apiAdminPost("/api/v1/system-config/drafts", payload, adminToken);
}

export function activateSystemConfigSnapshot(snapshotId, adminToken) {
  return apiAdminPost(`/api/v1/system-config/${encodeURIComponent(snapshotId)}/activate`, {}, adminToken);
}

export function testSystemConfigProvider(payload, adminToken) {
  return apiAdminPost("/api/v1/system-config/test-provider", payload, adminToken);
}

export function exportSystemConfigCategory(category) {
  return apiGet(`/api/v1/system-config/export/${encodeURIComponent(category)}`);
}

export function fetchLlmConfig() {
  return apiGet("/api/v1/system-config/llm");
}

export function saveLlmProviderConfig(payload, adminToken) {
  return apiAdminPost("/api/v1/system-config/llm/providers", payload, adminToken);
}

export function saveLlmNodeRoutes(payload, adminToken) {
  return apiAdminPost("/api/v1/system-config/llm/node-routes", payload, adminToken);
}

export function probeLlmProvider(providerId, payload = {}, adminToken) {
  return apiAdminPost(`/api/v1/system-config/llm/providers/${encodeURIComponent(providerId)}/probe`, payload, adminToken);
}

export function fetchLiteraryEvalLatest() {
  return apiGet("/api/v1/literary-eval/latest");
}

export function runLiteraryEval(payload = { mode: "baseline" }) {
  return apiPost("/api/v1/literary-eval/run", payload);
}

export function fetchLiteraryQualityOverview(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/literary-quality/overview", filters, {
      textLayer: "text_layer",
      chapterId: "chapter_id",
      riskType: "risk_type",
      minSeverity: "min_severity",
    }),
  );
}

export function analyzeLiteraryQualityText(payload) {
  return apiPost("/api/v1/literary-quality/analyze-text", payload);
}

export function fetchStyleProfileContract() {
  return apiGet("/api/v1/style-profile/contract");
}

export function extractStyleProfile(payload) {
  return apiPost("/api/v1/style-profile/extract", payload);
}

export function submitStyleProfileCandidate(payload) {
  return apiPost("/api/v1/style-profile/review-candidate", payload);
}

export function fetchReferenceBooks() {
  return apiGet("/api/v1/reference-books");
}

export function fetchReferenceBook(bookId) {
  return apiGet(`/api/v1/reference-books/${encodeURIComponent(bookId)}`);
}

export function fetchReferenceLearningTree(bookId) {
  return apiGet(`/api/v1/reference-books/${encodeURIComponent(bookId)}/learning-tree`);
}

export function fetchReferenceSegmentExcerpt(bookId, segmentId) {
  return apiGet(
    `/api/v1/reference-books/${encodeURIComponent(bookId)}/segments/${encodeURIComponent(segmentId)}/excerpt`,
  );
}

export function importReferenceBookPath(payload) {
  return apiPost("/api/v1/reference-books/import-path", payload);
}

export function importReferenceBookUpload({ file, title = "", author_label = "", cloud_policy, analysis_focus = "style_structure" }) {
  const formData = new FormData();
  formData.set("file", file);
  if (title) {
    formData.set("title", title);
  }
  if (author_label) {
    formData.set("author_label", author_label);
  }
  formData.set("cloud_policy", cloud_policy);
  formData.set("analysis_focus", analysis_focus);
  return apiPostForm("/api/v1/reference-books/import-upload", formData);
}

export function startReferenceLearningRun(bookId, payload = { batch_size: 8 }) {
  return apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/runs`, payload);
}

export function advanceReferenceLearningRun(bookId, runId) {
  return apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/runs/${encodeURIComponent(runId)}/advance`);
}

export function applyReferenceProfile(bookId, profileId, payload) {
  return apiPost(
    `/api/v1/reference-books/${encodeURIComponent(bookId)}/profiles/${encodeURIComponent(profileId)}/apply`,
    payload,
  );
}

export function fetchWorkbench(sceneId) {
  return apiGet(`/api/v1/scenes/${sceneId}/workbench`);
}

export function fetchSceneGenerationHistory(sceneId) {
  return apiGet(`/api/v1/scenes/${sceneId}/generation-history`);
}

export function fetchSceneWriterReview(sceneId) {
  return apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/writer-review`);
}

export function runSceneWriterReview(sceneId) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/writer-review/run`);
}

export function runSceneLiteraryBlueprint(sceneId) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/literary-blueprint`);
}

export function fetchChapterWriterReview(chapterId) {
  return apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/writer-review`);
}

export function runChapterWriterReview(chapterId) {
  return apiPost(`/api/v1/chapters/${encodeURIComponent(chapterId)}/writer-review/run`);
}

export function fetchSceneDeepReview(sceneId) {
  return apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/deep-review`);
}

export function runSceneDeepReview(sceneId) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/deep-review`);
}

export function fetchSceneQualityState(sceneId) {
  return apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/quality-state`);
}

export function generateSceneQualityContract(sceneId) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/quality-contract`);
}

export function runSceneAutoRewrite(sceneId, payload = { mode: "auto" }) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/auto-rewrite`, payload);
}

export function promoteAutoRewriteRun(runId) {
  return apiPost(`/api/v1/auto-rewrite-runs/${encodeURIComponent(runId)}/promote`);
}

export function rollbackAutoRewriteRun(runId) {
  return apiPost(`/api/v1/auto-rewrite-runs/${encodeURIComponent(runId)}/rollback`);
}

export function fetchChapterDeepReview(chapterId) {
  return apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/deep-review`);
}

export function runChapterDeepReview(chapterId) {
  return apiPost(`/api/v1/chapters/${encodeURIComponent(chapterId)}/deep-review`);
}

export function createPassagePatchCandidate(payload) {
  return apiPost("/api/v1/passages/patch-candidates", payload);
}

export function acceptPassagePatchCandidate(patchId, payload = {}) {
  return apiPost(`/api/v1/passage-patch-candidates/${encodeURIComponent(patchId)}/accept`, payload);
}

export function rejectPassagePatchCandidate(patchId, payload = {}) {
  return apiPost(`/api/v1/passage-patch-candidates/${encodeURIComponent(patchId)}/reject`, payload);
}

export function fetchCurrentAuthorDraft(objectType, objectId) {
  return apiGet(
    `/api/v1/author-drafts/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/current`,
  );
}

export function fetchAuthorDeskSnapshot(objectType, objectId) {
  return apiGet(
    `/api/v1/author-desk/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/snapshot`,
  );
}

export function fetchAuthorDraftEvents(draftId) {
  return apiGet(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/events`);
}

export function ensureAuthorDraft(objectType, objectId) {
  return apiPost(
    `/api/v1/author-drafts/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/ensure`,
  );
}

export function ensureBlankAuthorDraft(objectType, objectId) {
  return apiPost(
    `/api/v1/author-drafts/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/ensure-blank`,
  );
}

export function deriveAuthorDraftFromGeneration(draftId) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/derive-from-generation`);
}

export function fetchAuthorDraftProposals(draftId) {
  return apiGet(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/proposals`);
}

export function generateAuthorDraftProposal(draftId, payload = {}) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/proposals/generate`, payload);
}

export function generateAuthorDraftProposalSet(draftId, payload = {}) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/proposals/generate-set`, payload);
}

export function applyAuthorDraftProposal(proposalId, payload = {}) {
  return apiPost(`/api/v1/author-draft-proposals/${encodeURIComponent(proposalId)}/apply`, payload);
}

export function rejectAuthorDraftProposal(proposalId, payload = {}) {
  return apiPost(`/api/v1/author-draft-proposals/${encodeURIComponent(proposalId)}/reject`, payload);
}

export function saveAuthorDraft(draftId, payload) {
  return apiPatch(`/api/v1/author-drafts/${encodeURIComponent(draftId)}`, payload);
}

export function applyAuthorDraftPatchOption(draftId, payload) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/apply-patch-option`, payload);
}

export function recordAuthorDraftCandidateEvent(draftId, payload) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/candidate-events`, payload);
}

export function extractAuthorDraftStructure(draftId, payload = {}) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/structure-extract`, payload);
}

export function applyAuthorStructureCandidate(candidateId, payload = {}) {
  return apiPost(`/api/v1/author-structure-candidates/${encodeURIComponent(candidateId)}/apply`, payload);
}

export function rejectAuthorStructureCandidate(candidateId, payload = {}) {
  return apiPost(`/api/v1/author-structure-candidates/${encodeURIComponent(candidateId)}/reject`, payload);
}

export function fetchAuthorPreferenceProfile() {
  return apiGet("/api/v1/author-preference-profile");
}

export function acceptRevisionCandidate(revisionId, payload = {}) {
  return apiPost(`/api/v1/revision-candidates/${encodeURIComponent(revisionId)}/accept`, payload);
}

export function rejectRevisionCandidate(revisionId, payload = {}) {
  return apiPost(`/api/v1/revision-candidates/${encodeURIComponent(revisionId)}/reject`, payload);
}

export function fetchChapters() {
  return apiGet("/api/v1/chapters");
}

export function fetchChapterManuscripts() {
  return apiGet("/api/v1/chapter-manuscripts");
}

export function fetchChapterManuscriptDetail(chapterId) {
  return apiGet(`/api/v1/chapter-manuscripts/${encodeURIComponent(chapterId)}`);
}

export function fetchLongformControl() {
  return apiGet("/api/v1/longform-control");
}

export function fetchLongformEditorOverview() {
  return apiGet("/api/v1/longform-editor/overview");
}

export function runLongformEditorDiagnose() {
  return apiPost("/api/v1/longform-editor/diagnose");
}

export function fetchLongformEditorCards(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/longform-editor/cards", filters, {
      cardType: "card_type",
      chapterId: "chapter_id",
      sceneId: "scene_id",
    }),
  );
}

export function actOnLongformEditorCard(cardId, payload) {
  return apiPost(`/api/v1/longform-editor/cards/${encodeURIComponent(cardId)}/actions`, payload);
}

export function publishLongformGuidance(cardId, payload) {
  return apiPost(`/api/v1/longform-editor/cards/${encodeURIComponent(cardId)}/publish-guidance`, payload);
}

export function fetchReferenceSafetyOverview() {
  return apiGet("/api/v1/reference-safety/overview");
}

export function extractReferenceSafetyProfile(bookId) {
  return apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/safety-profile/extract`);
}

export function scanSourceSafety(payload) {
  return apiPost("/api/v1/source-safety/scan", payload);
}

export function fetchAuthorWorkspace(chapterId) {
  return apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/author-workspace`);
}

export function fetchSceneDraft(chapterId) {
  return apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/scene-draft`);
}

export function fetchChapterRunStatus(chapterId) {
  return apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/run-status`);
}

export function fetchAuthorTrash() {
  return apiGet("/api/v1/author-trash");
}

export function saveChapter(payload) {
  return apiPost("/api/v1/chapters", payload);
}

export function saveScene(payload) {
  return apiPost("/api/v1/scenes", payload);
}

export function reorderChapterScenes(chapterId, payload) {
  return apiPost(`/api/v1/chapters/${encodeURIComponent(chapterId)}/scene-order`, payload);
}

export function trashChapters(chapterIds) {
  return apiPost("/api/v1/chapters/trash", { chapter_ids: chapterIds });
}

export function restoreChapters(chapterIds) {
  return apiPost("/api/v1/chapters/restore", { chapter_ids: chapterIds });
}

export function purgeChapters(chapterIds) {
  return apiPost("/api/v1/chapters/purge", { chapter_ids: chapterIds });
}

export function trashScenes(sceneIds) {
  return apiPost("/api/v1/scenes/trash", { scene_ids: sceneIds });
}

export function restoreScenes(sceneIds) {
  return apiPost("/api/v1/scenes/restore", { scene_ids: sceneIds });
}

export function purgeScenes(sceneIds) {
  return apiPost("/api/v1/scenes/purge", { scene_ids: sceneIds });
}

export function runFullScene(sceneId) {
  return apiPost(`/api/v1/scenes/${sceneId}/run/full`);
}

export function startSceneRunJob(sceneId) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs`);
}

export function fetchRunJob(jobId) {
  return apiGet(`/api/v1/run-jobs/${encodeURIComponent(jobId)}`);
}

export function runChapterBackfill(chapterId, stageId, strategy) {
  return apiPost(`/api/v1/chapters/${chapterId}/runtime/backfill/${stageId}`, { strategy });
}

export function runChapterFinalAggregate(chapterId) {
  return apiPost(`/api/v1/chapters/${chapterId}/runtime/aggregate/final`);
}

export function setChapterManualHold(chapterId, reason) {
  return apiPost(`/api/v1/chapters/${chapterId}/runtime/manual-hold`, { reason });
}

export function clearChapterManualHold(chapterId) {
  return apiPost(`/api/v1/chapters/${chapterId}/runtime/manual-hold/clear`);
}

export function runChapterFull(chapterId) {
  return apiPost(`/api/v1/chapters/${encodeURIComponent(chapterId)}/run/full`);
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
    buildListQueryPath("/api/v1/review-items", filters, {
      itemType: "item_type",
      targetCollection: "target_collection",
      sceneId: "scene_id",
      chapterId: "chapter_id",
    }),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}

export function fetchReviewItem(reviewId) {
  return apiGet(`/api/v1/review-items/${encodeURIComponent(reviewId)}`);
}

export function createReviewItem(payload) {
  return apiPost("/api/v1/review-items", payload);
}

export function approveReview(reviewId, payload = {}) {
  return apiPost(`/api/v1/review-items/${reviewId}/approve`, payload);
}

export function rejectReview(reviewId, payload = {}) {
  return apiPost(`/api/v1/review-items/${reviewId}/reject`, payload);
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

export function actOnHumanReviewEvent(eventId, action) {
  return apiPost(`/api/v1/human-review-events/${eventId}/actions`, { action });
}

export function fetchSceneAttempts(sceneId, filters = {}) {
  return apiGet(
    buildListQueryPath(`/api/v1/scenes/${sceneId}/attempts`, filters),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}
