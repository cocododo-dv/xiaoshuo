const API_BASE_KEY = "novel-system-api-base";
const DEFAULT_API_BASE = "http://127.0.0.1:8000";

export function getApiBase() {
  if (typeof window === "undefined") {
    return DEFAULT_API_BASE;
  }
  return window.localStorage.getItem(API_BASE_KEY) || DEFAULT_API_BASE;
}

export function setApiBase(value) {
  const normalized = value.trim() || DEFAULT_API_BASE;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(API_BASE_KEY, normalized);
  }
  return normalized;
}

function buildUrl(path) {
  return `${getApiBase()}${path}`;
}

function buildIdempotencyKey(path) {
  return `${path}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

async function parseEnvelope(response) {
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error?.message || `Request failed: ${response.status}`);
  }
  return payload.data;
}

export async function apiGet(path) {
  const response = await fetch(buildUrl(path));
  return parseEnvelope(response);
}

export async function apiPost(path, body = {}) {
  const response = await fetch(buildUrl(path), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Idempotency-Key": buildIdempotencyKey(path),
    },
    body: JSON.stringify(body),
  });
  return parseEnvelope(response);
}

export function fetchWorkbench(sceneId) {
  return apiGet(`/api/v1/scenes/${sceneId}/workbench`);
}

export function fetchReviewItems() {
  return apiGet("/api/v1/review-items");
}

export function approveReview(reviewId) {
  return apiPost(`/api/v1/review-items/${reviewId}/approve`);
}

export function releaseReview(reviewId) {
  return apiPost(`/api/v1/review-items/${reviewId}/release`);
}

export function fetchAliasScopes() {
  return apiGet("/api/v1/index/alias-scopes");
}

export function fetchIndexJobs() {
  return apiGet("/api/v1/index/jobs");
}

export function retryVerify(jobId) {
  return apiPost(`/api/v1/index/verify/${jobId}/retry`);
}

export function runRecoverySweep() {
  return apiPost("/api/v1/runtime/recovery/sweep");
}

export function fetchHumanReviewEvents() {
  return apiGet("/api/v1/human-review-events");
}
