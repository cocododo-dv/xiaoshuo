import { apiGet, apiPatch, apiPost, apiPut } from "./client";

export function fetchTowerAnchors(projectId) {
  return apiGet(`/api/v2/projects/${encodeURIComponent(projectId)}/longform/anchors`);
}

export function createTowerAnchor(projectId, payload = {}) {
  return apiPost(`/api/v2/projects/${encodeURIComponent(projectId)}/longform/anchors`, payload);
}

export function updateTowerAnchor(projectId, anchorId, payload = {}) {
  return apiPatch(
    `/api/v2/projects/${encodeURIComponent(projectId)}/longform/anchors/${encodeURIComponent(anchorId)}`,
    payload,
  );
}

export function fetchChapterContract(projectId, chapterId) {
  return apiGet(
    `/api/v2/projects/${encodeURIComponent(projectId)}/longform/chapters/${encodeURIComponent(chapterId)}/contract`,
  );
}

export function updateChapterContract(projectId, chapterId, payload = {}) {
  return apiPut(
    `/api/v2/projects/${encodeURIComponent(projectId)}/longform/chapters/${encodeURIComponent(chapterId)}/contract`,
    payload,
  );
}

export function transitionChapterContract(projectId, chapterId, payload = {}) {
  return apiPost(
    `/api/v2/projects/${encodeURIComponent(projectId)}/longform/chapters/${encodeURIComponent(chapterId)}/contract/transition`,
    payload,
  );
}

export function fetchChapterAudit(projectId, chapterId) {
  return apiGet(
    `/api/v2/projects/${encodeURIComponent(projectId)}/longform/chapters/${encodeURIComponent(chapterId)}/audit`,
  );
}

export function createChapterAuditFinding(projectId, chapterId, payload = {}) {
  return apiPost(
    `/api/v2/projects/${encodeURIComponent(projectId)}/longform/chapters/${encodeURIComponent(chapterId)}/audit`,
    payload,
  );
}

export function adjudicateChapterAuditFinding(projectId, findingId, payload = {}) {
  return apiPost(
    `/api/v2/projects/${encodeURIComponent(projectId)}/longform/audit/${encodeURIComponent(findingId)}/adjudicate`,
    payload,
  );
}
