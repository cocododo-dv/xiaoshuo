import { apiGet, apiPost, apiPostForm } from "./client";

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
