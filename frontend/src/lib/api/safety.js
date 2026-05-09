import { apiGet, apiPost } from "./client";

export function fetchReferenceSafetyOverview() {
  return apiGet("/api/v1/reference-safety/overview");
}

export function extractReferenceSafetyProfile(bookId) {
  return apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/safety-profile/extract`);
}

export function scanSourceSafety(payload) {
  return apiPost("/api/v1/source-safety/scan", payload);
}
