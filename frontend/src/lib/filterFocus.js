export function getVisibleHumanReviewItems(humanReviewItems, selectedEventSource, recoveryItems) {
  if (selectedEventSource) {
    return (humanReviewItems || []).filter((item) => item.event_source === selectedEventSource);
  }
  return [...(recoveryItems || [])];
}

export function isReviewFocusVisible(focusTarget, reviewItems, humanReviewItems) {
  if (focusTarget?.target_type === "review_item") {
    return (reviewItems || []).some((item) => item.review_id === focusTarget.target_id);
  }
  if (focusTarget?.target_type === "human_review_event") {
    return (humanReviewItems || []).some((item) => item.event_id === focusTarget.target_id);
  }
  return true;
}

export function isIndexFocusVisible(focusTarget, aliasScopes, jobs, targetActivityGroups) {
  if (focusTarget?.target_type === "verify_job" || focusTarget?.target_type === "reindex_job") {
    return (jobs || []).some((item) => item.job_id === focusTarget.target_id);
  }
  if (focusTarget?.target_ref) {
    return (targetActivityGroups || []).some((group) => group?.target?.target_ref === focusTarget.target_ref);
  }
  return true;
}
