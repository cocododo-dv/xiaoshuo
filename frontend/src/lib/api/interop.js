import { apiGet, apiPost } from "./client";

export function previewBundleWorksheet(worksheetYaml) {
  return apiPost("/api/v1/interop/preview/bundle-worksheet", { worksheet_yaml: worksheetYaml });
}

export function importBundleWorksheet(worksheetYaml) {
  return apiPost("/api/v1/interop/import/bundle-worksheet", { worksheet_yaml: worksheetYaml });
}

export function fetchBundleWorksheetExport(bundleId) {
  return apiGet(`/api/v1/interop/export/bundle-worksheet/${encodeURIComponent(bundleId)}`);
}

export function fetchReplayFinalScene(rowId) {
  return apiGet(`/api/v1/replay/final-scene/${encodeURIComponent(rowId)}`);
}

export function fetchReplayDraft(rowId) {
  return apiGet(`/api/v1/replay/draft/${encodeURIComponent(rowId)}`);
}
