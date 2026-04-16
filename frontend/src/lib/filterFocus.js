export function getVisibleHumanReviewItems(humanReviewItems, selectedEventSource, recoveryItems, selectedStatus = "") {
  if (selectedEventSource === "idempotency_recovery" && !selectedStatus) {
    return [...(recoveryItems || [])];
  }
  if (selectedEventSource) {
    return (humanReviewItems || []).filter(
      (item) => item.event_source === selectedEventSource && (!selectedStatus || item.status === selectedStatus),
    );
  }
  if (selectedStatus) {
    return (humanReviewItems || []).filter((item) => item.status === selectedStatus);
  }
  return [...(recoveryItems || [])];
}

function hasVisibleItem(source, targetId, key) {
  if (typeof source === "function") {
    return source(targetId);
  }
  return (source || []).some((item) => item?.[key] === targetId);
}

export function isReviewFocusVisible(focusTarget, reviewItems, humanReviewItems) {
  if (focusTarget?.target_type === "review_item") {
    return hasVisibleItem(reviewItems, focusTarget.target_id, "review_id");
  }
  if (focusTarget?.target_type === "human_review_event") {
    return hasVisibleItem(humanReviewItems, focusTarget.target_id, "event_id");
  }
  return true;
}

export function shouldClearReviewFocus(
  activeView,
  loading,
  refreshPending,
  focusTarget,
  reviewItems,
  humanReviewItems,
) {
  if (activeView !== "review" || loading || refreshPending) {
    return false;
  }
  return !isReviewFocusVisible(focusTarget, reviewItems, humanReviewItems);
}

export function isIndexFocusVisible(focusTarget, aliasScopes, jobs, targetActivityGroups) {
  if (focusTarget?.target_type === "verify_job" || focusTarget?.target_type === "reindex_job") {
    return hasVisibleItem(jobs, focusTarget.target_id, "job_id");
  }
  if (focusTarget?.target_ref) {
    if (typeof targetActivityGroups === "function") {
      return targetActivityGroups(focusTarget.target_ref);
    }
    return (targetActivityGroups || []).some((group) => group?.target?.target_ref === focusTarget.target_ref);
  }
  return true;
}

export function shouldClearIndexFocus(
  activeView,
  loading,
  refreshPending,
  focusTarget,
  aliasScopes,
  jobs,
  targetActivityGroups,
) {
  if (activeView !== "index" || loading || refreshPending) {
    return false;
  }
  return !isIndexFocusVisible(focusTarget, aliasScopes, jobs, targetActivityGroups);
}
