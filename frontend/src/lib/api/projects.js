import { apiGet, apiPatch, apiPost } from "./client";

export function fetchProjects() {
  return apiGet("/api/v1/projects");
}

export function createProject(payload) {
  return apiPost("/api/v1/projects", payload);
}

export function fetchProjectDashboard(projectId) {
  return apiGet(`/api/v1/projects/${encodeURIComponent(projectId)}/dashboard`);
}

export function fetchProjectBacktrackItems(projectId) {
  return apiGet(`/api/v1/projects/${encodeURIComponent(projectId)}/backtrack-items`);
}

export function resolveProjectBacktrackItem(projectId, itemId, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/backtrack-items/${encodeURIComponent(itemId)}/resolve`,
    payload,
  );
}

export function fetchProjectSnowflake(projectId) {
  return apiGet(`/api/v1/projects/${encodeURIComponent(projectId)}/snowflake`);
}

export function generateSnowflakeStep(projectId, stepKey, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/snowflake/steps/${encodeURIComponent(stepKey)}/generate`,
    payload,
  );
}

export function updateSnowflakeArtifact(projectId, artifactId, payload = {}) {
  return apiPatch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/snowflake/artifacts/${encodeURIComponent(artifactId)}`,
    payload,
  );
}

export function approveSnowflakeArtifact(projectId, artifactId, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/snowflake/artifacts/${encodeURIComponent(artifactId)}/approve`,
    payload,
  );
}

export function materializeSnowflakeOutlinePlan(projectId, payload = {}) {
  return apiPost(`/api/v1/projects/${encodeURIComponent(projectId)}/snowflake/materialize-outline-plan`, payload);
}

export function generateProjectOutlinePlan(projectId, payload = {}) {
  return apiPost(`/api/v1/projects/${encodeURIComponent(projectId)}/outline-plan`, payload);
}

export function approveProjectOutlinePlan(projectId, planId, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/outline-plan/${encodeURIComponent(planId)}/approve`,
    payload,
  );
}

export function runProjectChapter(projectId, chapterId, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/chapters/${encodeURIComponent(chapterId)}/run`,
    payload,
  );
}

export function runProjectChapterJob(projectId, chapterId, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/chapters/${encodeURIComponent(chapterId)}/run-job`,
    payload,
  );
}

export function approveProjectChapterFinal(projectId, chapterId, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/chapters/${encodeURIComponent(chapterId)}/approve-final`,
    payload,
  );
}

export function confirmProjectChapterRead(projectId, chapterId, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/chapters/${encodeURIComponent(chapterId)}/read-confirm`,
    payload,
  );
}

export function reviewProjectChapterFinal(projectId, chapterId, payload = {}) {
  return apiPost(
    `/api/v1/projects/${encodeURIComponent(projectId)}/chapters/${encodeURIComponent(chapterId)}/final-review`,
    payload,
  );
}

export function attachProjectReferenceProfile(projectId, profileId) {
  return apiPost(`/api/v1/projects/${encodeURIComponent(projectId)}/reference-profiles`, {
    profile_id: profileId,
  });
}
