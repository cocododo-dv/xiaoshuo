import { apiGet, apiPost, buildQueryPath } from "./client";

export function fetchLiteraryEvalLatest() {
  return apiGet("/api/v1/literary-eval/latest");
}

export function runLiteraryEval(payload = { mode: "baseline" }) {
  return apiPost("/api/v1/literary-eval/run", payload);
}

export function fetchLiteraryQualityOverview(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/literary-quality/overview", filters, {
      textLayer: "text_layer",
      chapterId: "chapter_id",
      riskType: "risk_type",
      minSeverity: "min_severity",
    }),
  );
}

export function analyzeLiteraryQualityText(payload) {
  return apiPost("/api/v1/literary-quality/analyze-text", payload);
}

export function runLiteraryQualityChapterSetReview(payload) {
  return apiPost("/api/v1/literary-quality/chapter-set-review", payload);
}

export function fetchStyleProfileContract() {
  return apiGet("/api/v1/style-profile/contract");
}

export function extractStyleProfile(payload) {
  return apiPost("/api/v1/style-profile/extract", payload);
}

export function submitStyleProfileCandidate(payload) {
  return apiPost("/api/v1/style-profile/review-candidate", payload);
}
