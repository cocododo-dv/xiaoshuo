import { apiGet, apiPatch, apiPost } from "./client";

export function fetchSnowflakeWorkspaceProjects() {
  return apiGet("/api/v2/projects");
}

export function createSnowflakeWorkspaceProject(payload) {
  return apiPost("/api/v2/projects", payload);
}

export function fetchSnowflakeWorkspace(projectId) {
  return apiGet(`/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace`);
}

export function generateSnowflakeWorkspaceStep(projectId, stepKey, payload = {}) {
  return apiPost(
    `/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/steps/${encodeURIComponent(stepKey)}/generate`,
    payload,
  );
}

export function updateSnowflakeWorkspaceStep(projectId, stepKey, payload = {}) {
  return apiPatch(
    `/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/steps/${encodeURIComponent(stepKey)}`,
    payload,
  );
}

export function approveSnowflakeWorkspaceStep(projectId, stepKey, payload = {}) {
  return apiPost(
    `/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/steps/${encodeURIComponent(stepKey)}/approve`,
    payload,
  );
}

export function fetchSnowflakeStepHistory(projectId, stepKey, { includeDraft = false } = {}) {
  const query = includeDraft ? "?include_draft=true" : "";
  return apiGet(
    `/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/steps/${encodeURIComponent(stepKey)}/history${query}`,
  );
}

export function restoreSnowflakeWorkspaceStep(projectId, stepKey, payload = {}) {
  return apiPost(
    `/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/steps/${encodeURIComponent(stepKey)}/restore`,
    payload,
  );
}

export function requestSnowflakeWorkspaceAssistant(projectId, payload = {}) {
  return apiPost(`/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/assistant`, payload);
}

export function requestSnowflakeSceneTriageSuggestions(projectId, payload = {}) {
  return apiPost(
    `/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/scene-triage/suggest`,
    payload,
  );
}

export function saveSnowflakeSceneTriage(projectId, payload = {}) {
  return apiPost(`/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/scene-triage`, payload);
}

export function updateSnowflakeWorkspaceScene(projectId, scenePlanId, payload = {}) {
  return apiPatch(
    `/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/scenes/${encodeURIComponent(scenePlanId)}`,
    payload,
  );
}

export function applySnowflakeSceneTriageRepair(projectId, triageId, payload = {}) {
  return apiPost(
    `/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/scene-triage/${encodeURIComponent(triageId)}/apply`,
    payload,
  );
}

export function materializeSnowflakeWorkspace(projectId, payload = {}) {
  return apiPost(`/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/materialize`, payload);
}

export function approveSnowflakeWorkspaceOutline(projectId, payload = {}) {
  return apiPost(`/api/v2/projects/${encodeURIComponent(projectId)}/snowflake-workspace/outline/approve`, payload);
}
