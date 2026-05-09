import { apiGet, apiPost, buildQueryPath } from "./client";

export function fetchChapters() {
  return apiGet("/api/v1/chapters");
}

export function fetchChapterManuscripts() {
  return apiGet("/api/v1/chapter-manuscripts");
}

export function fetchChapterManuscriptDetail(chapterId) {
  return apiGet(`/api/v1/chapter-manuscripts/${encodeURIComponent(chapterId)}`);
}

export function fetchLongformControl() {
  return apiGet("/api/v1/longform-control");
}

export function fetchLongformEditorOverview() {
  return apiGet("/api/v1/longform-editor/overview");
}

export function runLongformEditorDiagnose() {
  return apiPost("/api/v1/longform-editor/diagnose");
}

export function fetchLongformEditorCards(filters = {}) {
  return apiGet(
    buildQueryPath("/api/v1/longform-editor/cards", filters, {
      cardType: "card_type",
      chapterId: "chapter_id",
      sceneId: "scene_id",
    }),
  );
}

export function actOnLongformEditorCard(cardId, payload) {
  return apiPost(`/api/v1/longform-editor/cards/${encodeURIComponent(cardId)}/actions`, payload);
}

export function publishLongformGuidance(cardId, payload) {
  return apiPost(`/api/v1/longform-editor/cards/${encodeURIComponent(cardId)}/publish-guidance`, payload);
}

export function fetchAuthorWorkspace(chapterId) {
  return apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/author-workspace`);
}

export function fetchSceneDraft(chapterId) {
  return apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/scene-draft`);
}

export function fetchChapterRunStatus(chapterId) {
  return apiGet(`/api/v1/chapters/${encodeURIComponent(chapterId)}/run-status`);
}

export function fetchAuthorTrash() {
  return apiGet("/api/v1/author-trash");
}

export function saveChapter(payload) {
  return apiPost("/api/v1/chapters", payload);
}

export function saveScene(payload) {
  return apiPost("/api/v1/scenes", payload);
}

export function reorderChapterScenes(chapterId, payload) {
  return apiPost(`/api/v1/chapters/${encodeURIComponent(chapterId)}/scene-order`, payload);
}

export function trashChapters(chapterIds) {
  return apiPost("/api/v1/chapters/trash", { chapter_ids: chapterIds });
}

export function restoreChapters(chapterIds) {
  return apiPost("/api/v1/chapters/restore", { chapter_ids: chapterIds });
}

export function purgeChapters(chapterIds) {
  return apiPost("/api/v1/chapters/purge", { chapter_ids: chapterIds });
}

export function trashScenes(sceneIds) {
  return apiPost("/api/v1/scenes/trash", { scene_ids: sceneIds });
}

export function restoreScenes(sceneIds) {
  return apiPost("/api/v1/scenes/restore", { scene_ids: sceneIds });
}

export function purgeScenes(sceneIds) {
  return apiPost("/api/v1/scenes/purge", { scene_ids: sceneIds });
}

export function runFullScene(sceneId) {
  return apiPost(`/api/v1/scenes/${sceneId}/run/full`);
}

export function startSceneRunJob(sceneId) {
  return apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs`);
}

export function fetchRunJob(jobId) {
  return apiGet(`/api/v1/run-jobs/${encodeURIComponent(jobId)}`);
}

export function runChapterBackfill(chapterId, stageId, strategy) {
  return apiPost(`/api/v1/chapters/${chapterId}/runtime/backfill/${stageId}`, { strategy });
}

export function runChapterFinalAggregate(chapterId) {
  return apiPost(`/api/v1/chapters/${chapterId}/runtime/aggregate/final`);
}

export function setChapterManualHold(chapterId, reason) {
  return apiPost(`/api/v1/chapters/${chapterId}/runtime/manual-hold`, { reason });
}

export function clearChapterManualHold(chapterId) {
  return apiPost(`/api/v1/chapters/${chapterId}/runtime/manual-hold/clear`);
}

export function runChapterFull(chapterId) {
  return apiPost(`/api/v1/chapters/${encodeURIComponent(chapterId)}/run/full`);
}
