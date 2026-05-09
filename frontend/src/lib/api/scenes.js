import { apiGet, apiPost, buildListQueryPath, CURSOR_PAGINATION_DEFAULT_LIMIT, normalizeListPayload } from "./client";

export function fetchWorkbench(sceneId) {
  return apiGet(`/api/v1/scenes/${sceneId}/workbench`);
}

export function fetchSceneExecutionContract(sceneId) {
  return apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/execution-contract`);
}

export function generateSceneExecutionContract(sceneId) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/execution-contract`);
}

export function runSceneTriage(sceneId) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/triage`);
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

export function fetchSceneAttempts(sceneId, filters = {}) {
  return apiGet(
    buildListQueryPath(`/api/v1/scenes/${sceneId}/attempts`, filters),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}
