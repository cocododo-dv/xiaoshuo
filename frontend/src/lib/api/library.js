import { apiDelete, apiGet, apiPatch, apiPost } from "./client";

export function fetchLibraryOverview(projectId) {
  return apiGet(`/api/v2/projects/${encodeURIComponent(projectId)}/library`);
}

export function createLibraryEntity(projectId, payload = {}) {
  return apiPost(`/api/v2/projects/${encodeURIComponent(projectId)}/library/entities`, payload);
}

export function updateLibraryEntity(projectId, entityId, payload = {}) {
  return apiPatch(
    `/api/v2/projects/${encodeURIComponent(projectId)}/library/entities/${encodeURIComponent(entityId)}`,
    payload,
  );
}

export function createLibraryRelation(projectId, payload = {}) {
  return apiPost(`/api/v2/projects/${encodeURIComponent(projectId)}/library/relations`, payload);
}

export function deleteLibraryRelation(projectId, relationId) {
  return apiDelete(
    `/api/v2/projects/${encodeURIComponent(projectId)}/library/relations/${encodeURIComponent(relationId)}`,
  );
}
