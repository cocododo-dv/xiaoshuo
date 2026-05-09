import { apiAdminPost, apiGet, apiGetFromBase } from "./client";

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

export function setDefaultLlmProvider(providerId, adminToken) {
  return apiAdminPost(`/api/v1/system-config/llm/providers/${encodeURIComponent(providerId)}/default`, {}, adminToken);
}

export function saveLlmNodeRoutes(payload, adminToken) {
  return apiAdminPost("/api/v1/system-config/llm/node-routes", payload, adminToken);
}

export function syncMissingLlmNodeRoutes(payload = { activate: true }, adminToken) {
  return apiAdminPost("/api/v1/system-config/llm/node-routes/sync-missing", payload, adminToken);
}

export function probeLlmProvider(providerId, payload = {}, adminToken) {
  return apiAdminPost(`/api/v1/system-config/llm/providers/${encodeURIComponent(providerId)}/probe`, payload, adminToken);
}
