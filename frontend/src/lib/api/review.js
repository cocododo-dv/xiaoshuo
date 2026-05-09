import { apiGet, apiPost, buildListQueryPath, CURSOR_PAGINATION_DEFAULT_LIMIT, normalizeListPayload } from "./client";

export function fetchReviewItems(filters = {}) {
  return apiGet(
    buildListQueryPath("/api/v1/review-items", filters, {
      itemType: "item_type",
      targetCollection: "target_collection",
      sceneId: "scene_id",
      chapterId: "chapter_id",
    }),
  ).then((payload) => normalizeListPayload(payload, CURSOR_PAGINATION_DEFAULT_LIMIT));
}

export function fetchReviewItem(reviewId) {
  return apiGet(`/api/v1/review-items/${encodeURIComponent(reviewId)}`);
}

export function createReviewItem(payload) {
  return apiPost("/api/v1/review-items", payload);
}

export function approveReview(reviewId, payload = {}) {
  return apiPost(`/api/v1/review-items/${reviewId}/approve`, payload);
}

export function rejectReview(reviewId, payload = {}) {
  return apiPost(`/api/v1/review-items/${reviewId}/reject`, payload);
}

export function releaseReview(reviewId) {
  return apiPost(`/api/v1/review-items/${reviewId}/release`);
}
