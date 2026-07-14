// Style Reference v1.1 — 前端 API client(PR-5)
// 后端 18 端点位于 /api/v2/style-reference/*(PR-4 实装,commit 21a0978)
// client.js 自动注入 X-Idempotency-Key / X-Operator-Ref / X-Client-Request-Id

import { apiDelete, apiGet, apiPost, apiPostForm } from "./client";

// Runtime truth: preview callers consume `SystemPromptFragments` from the
// `injection-preview` endpoints directly; there is no public `/inject` API.

const PREFIX = "/api/v2/style-reference";

// --- Books ---

export function importStyleReferenceBookPath(payload) {
  return apiPost(`${PREFIX}/books/import-path`, payload);
}

export function importStyleReferenceBookUpload({
  file,
  title,
  authorLabel = "",
  cloudPolicy,
  rightsDeclaration = null,
}) {
  const formData = new FormData();
  formData.set("file", file);
  formData.set("title", title);
  if (authorLabel) {
    formData.set("author_label", authorLabel);
  }
  formData.set("cloud_policy", cloudPolicy);
  if (rightsDeclaration) {
    formData.set("rights_declaration", JSON.stringify(rightsDeclaration));
  }
  return apiPostForm(`${PREFIX}/books/import-upload`, formData);
}

export function listStyleReferenceBooks({ status } = {}) {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiGet(`${PREFIX}/books${query}`);
}

export function fetchStyleReferenceBook(bookId) {
  return apiGet(`${PREFIX}/books/${encodeURIComponent(bookId)}`);
}

export function deleteStyleReferenceBook(bookId) {
  return apiDelete(`${PREFIX}/books/${encodeURIComponent(bookId)}`);
}

export function reclassifyStyleReferenceBook(bookId) {
  return apiPost(`${PREFIX}/books/${encodeURIComponent(bookId)}/reclassify`, {});
}

// --- Runs ---

export function startStyleReferenceRun(bookId, { layers = null } = {}) {
  const payload = layers ? { layers } : {};
  return apiPost(`${PREFIX}/books/${encodeURIComponent(bookId)}/runs`, payload);
}

export function fetchStyleReferenceRun(runId) {
  return apiGet(`${PREFIX}/runs/${encodeURIComponent(runId)}`);
}

export function cancelStyleReferenceRun(runId) {
  return apiPost(`${PREFIX}/runs/${encodeURIComponent(runId)}/cancel`, {});
}

export function listStyleReferenceRunFindings(runId, { subDimension, findingKind, status, include } = {}) {
  const params = new URLSearchParams();
  if (subDimension) params.set("sub_dimension", subDimension);
  if (findingKind) params.set("finding_kind", findingKind);
  if (status) params.set("status", status);
  if (include) params.set("include", include);
  const query = params.toString();
  return apiGet(`${PREFIX}/runs/${encodeURIComponent(runId)}/findings${query ? `?${query}` : ""}`);
}

// --- Findings review ---

export function reviewStyleReferenceFinding(findingId, { decision, comment = null }) {
  return apiPost(`${PREFIX}/findings/${encodeURIComponent(findingId)}/review`, {
    decision,
    comment,
  });
}

// --- Synthesize ---

export function synthesizeStyleReferenceProfile(runId) {
  return apiPost(`${PREFIX}/runs/${encodeURIComponent(runId)}/synthesize`, {});
}

// --- Profiles ---

export function listStyleReferenceProfiles({ bookId, status } = {}) {
  const params = new URLSearchParams();
  if (bookId) params.set("book_id", bookId);
  if (status) params.set("status", status);
  const query = params.toString();
  return apiGet(`${PREFIX}/profiles${query ? `?${query}` : ""}`);
}

export function fetchStyleReferenceProfile(profileId) {
  return apiGet(`${PREFIX}/profiles/${encodeURIComponent(profileId)}`);
}

export function previewStyleReferenceProfile(profileId) {
  return apiPost(`${PREFIX}/profiles/${encodeURIComponent(profileId)}/preview`, {});
}

export function applyStyleReferenceProfile(profileId, { scope, scopeRefId = null, taskType = "scene_generation", strategy = "A" }) {
  return apiPost(`${PREFIX}/profiles/${encodeURIComponent(profileId)}/apply`, {
    scope,
    scope_ref_id: scopeRefId,
    task_type: taskType,
    strategy,
  });
}

// --- Bindings ---

export function listStyleReferenceBindings(profileId, { taskType } = {}) {
  const query = taskType ? `?task_type=${encodeURIComponent(taskType)}` : "";
  return apiGet(`${PREFIX}/profiles/${encodeURIComponent(profileId)}/bindings${query}`);
}

export function deleteStyleReferenceBinding(bindingId) {
  return apiDelete(`${PREFIX}/bindings/${encodeURIComponent(bindingId)}`);
}

// --- Validation (PR-7) ---

export function validateStyleReferenceGenerated(profileId, {
  generatedText,
  targetKind = "manual",
  targetRefId = null,
  mode = "async_full",
  taskContext = null,
} = {}) {
  return apiPost(`${PREFIX}/profiles/${encodeURIComponent(profileId)}/validate`, {
    generated_text: generatedText,
    target_kind: targetKind,
    target_ref_id: targetRefId,
    mode,
    task_context: taskContext,
  });
}

export function fetchStyleReferenceValidationReport(reportId) {
  return apiGet(`${PREFIX}/reports/${encodeURIComponent(reportId)}`);
}

export function listStyleReferenceValidationReports(profileId, { verdict } = {}) {
  const query = verdict ? `?verdict=${encodeURIComponent(verdict)}` : "";
  return apiGet(`${PREFIX}/profiles/${encodeURIComponent(profileId)}/reports${query}`);
}

// --- Metrics (PR-10) ---

export function fetchStyleReferenceMetrics({ windowHours = 168 } = {}) {
  return apiGet(`${PREFIX}/metrics?window_hours=${encodeURIComponent(windowHours)}`);
}

// PR-22 — injection 调用量每日趋势(零填充连续轴)
export function fetchStyleReferenceMetricsDaily({ windowDays = 14 } = {}) {
  return apiGet(`${PREFIX}/metrics/daily?window_days=${encodeURIComponent(windowDays)}`);
}

// --- Injection preview (PR-9) ---

export function fetchBindingInjectionPreview(bindingId) {
  return apiGet(`${PREFIX}/bindings/${encodeURIComponent(bindingId)}/injection-preview`);
}

export function dryrunInjectionPreview(profileId, {
  strategy = "A",
  taskType = "scene_generation",
  intensity = 50,
  subDimensions = [],
  includePositive = true,
  includeForbidden = true,
  includeMetric = false,
} = {}) {
  return apiPost(`${PREFIX}/profiles/${encodeURIComponent(profileId)}/injection-preview`, {
    strategy,
    task_type: taskType,
    intensity,
    sub_dimensions: subDimensions,
    include_positive: includePositive,
    include_forbidden: includeForbidden,
    include_metric: includeMetric,
  });
}
