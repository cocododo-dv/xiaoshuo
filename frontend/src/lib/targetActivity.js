function groupTargetRef(group) {
  return group?.target?.target_ref || "";
}

function activityTimestampValue(item) {
  const timestamp = Date.parse(item?.timestamp || "");
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

export function nextExpandedTargetRefs(currentExpandedRefs, groups, focusTargetRef) {
  const validRefs = new Set((groups || []).map(groupTargetRef).filter(Boolean));

  if (focusTargetRef && validRefs.has(focusTargetRef)) {
    return [focusTargetRef];
  }

  return (currentExpandedRefs || []).filter((targetRef) => validRefs.has(targetRef));
}

export function toggleExpandedTargetRef(currentExpandedRefs, targetRef) {
  if (!targetRef) {
    return currentExpandedRefs || [];
  }

  const expandedRefs = [...(currentExpandedRefs || [])];
  const existingIndex = expandedRefs.indexOf(targetRef);
  if (existingIndex >= 0) {
    expandedRefs.splice(existingIndex, 1);
    return expandedRefs;
  }
  expandedRefs.push(targetRef);
  return expandedRefs;
}

export function orderedActivityItems(items) {
  return [...(items || [])].sort((left, right) => {
    const timestampDelta = activityTimestampValue(right) - activityTimestampValue(left);
    if (timestampDelta !== 0) {
      return timestampDelta;
    }
    return String(left?.activity_key || "").localeCompare(String(right?.activity_key || ""));
  });
}

export function focusedActivityKeyForGroup(group, focusTargetRef) {
  if (groupTargetRef(group) !== focusTargetRef) {
    return "";
  }
  return orderedActivityItems(group?.activity_items || [])[0]?.activity_key || "";
}
