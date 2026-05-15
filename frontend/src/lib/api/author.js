import { apiGet, apiPatch, apiPost } from "./client";

export function fetchCurrentAuthorDraft(objectType, objectId) {
  return apiGet(
    `/api/v1/author-drafts/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/current`,
  );
}

export function fetchAuthorDeskSnapshot(objectType, objectId) {
  return apiGet(
    `/api/v1/author-desk/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/snapshot`,
  );
}

export function fetchWriterRoom(objectType, objectId) {
  return apiGet(
    `/api/v1/writer-room/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}`,
  );
}

export function openProjectChapterDraft(projectId, payload = {}) {
  return apiPost(`/api/v1/projects/${encodeURIComponent(projectId)}/chapter-drafts/open`, payload);
}

export function fetchAuthorDraftEvents(draftId) {
  return apiGet(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/events`);
}

export function ensureAuthorDraft(objectType, objectId) {
  return apiPost(
    `/api/v1/author-drafts/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/ensure`,
  );
}

export function ensureBlankAuthorDraft(objectType, objectId) {
  return apiPost(
    `/api/v1/author-drafts/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}/ensure-blank`,
  );
}

export function fetchProjectDiscoveryDraft(projectId) {
  return apiGet(`/api/v1/projects/${encodeURIComponent(projectId)}/discovery-draft/current`);
}

export function ensureProjectDiscoveryDraft(projectId) {
  return apiPost(`/api/v1/projects/${encodeURIComponent(projectId)}/discovery-draft/ensure`);
}

export function deriveAuthorDraftFromGeneration(draftId) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/derive-from-generation`);
}

export function fetchAuthorDraftProposals(draftId) {
  return apiGet(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/proposals`);
}

export function generateAuthorDraftProposal(draftId, payload = {}) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/proposals/generate`, payload);
}

export function generateAuthorDraftProposalSet(draftId, payload = {}) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/proposals/generate-set`, payload);
}

export function applyAuthorDraftProposal(proposalId, payload = {}) {
  return apiPost(`/api/v1/author-draft-proposals/${encodeURIComponent(proposalId)}/apply`, payload);
}

export function fetchAuthorDraftProposalDiff(draftId, proposalId) {
  return apiGet(
    `/api/v1/author-drafts/${encodeURIComponent(draftId)}/proposals/${encodeURIComponent(proposalId)}/diff`,
  );
}

export function applyAuthorDraftScopedProposal(draftId, payload = {}) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/apply-proposal`, payload);
}

export function rejectAuthorDraftProposal(proposalId, payload = {}) {
  return apiPost(`/api/v1/author-draft-proposals/${encodeURIComponent(proposalId)}/reject`, payload);
}

export function saveAuthorDraft(draftId, payload) {
  return apiPatch(`/api/v1/author-drafts/${encodeURIComponent(draftId)}`, payload);
}

export function applyAuthorDraftPatchOption(draftId, payload) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/apply-patch-option`, payload);
}

export function recordAuthorDraftCandidateEvent(draftId, payload) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/candidate-events`, payload);
}

export function extractAuthorDraftStructure(draftId, payload = {}) {
  return apiPost(`/api/v1/author-drafts/${encodeURIComponent(draftId)}/structure-extract`, payload);
}

export function applyAuthorStructureCandidate(candidateId, payload = {}) {
  return apiPost(`/api/v1/author-structure-candidates/${encodeURIComponent(candidateId)}/apply`, payload);
}

export function applyAuthorStructureCandidateToSnowflake(candidateId, payload = {}) {
  return apiPost(
    `/api/v1/author-structure-candidates/${encodeURIComponent(candidateId)}/apply-to-snowflake`,
    payload,
  );
}

export function rejectAuthorStructureCandidate(candidateId, payload = {}) {
  return apiPost(`/api/v1/author-structure-candidates/${encodeURIComponent(candidateId)}/reject`, payload);
}

export function fetchAuthorPreferenceProfile() {
  return apiGet("/api/v1/author-preference-profile");
}

export function acceptRevisionCandidate(revisionId, payload = {}) {
  return apiPost(`/api/v1/revision-candidates/${encodeURIComponent(revisionId)}/accept`, payload);
}

export function rejectRevisionCandidate(revisionId, payload = {}) {
  return apiPost(`/api/v1/revision-candidates/${encodeURIComponent(revisionId)}/reject`, payload);
}
