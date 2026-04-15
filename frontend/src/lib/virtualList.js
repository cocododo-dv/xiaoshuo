function resolveItemKey(item, itemKey) {
  if (typeof itemKey === "function") {
    return itemKey(item);
  }

  return item?.[itemKey];
}

function resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight) {
  const item = items[index];
  const key = resolveItemKey(item, itemKey);

  return measuredHeights[key] ?? estimatedItemHeight;
}

function buildHeightProfile(items, itemKey, measuredHeights, estimatedItemHeight) {
  const heights = new Array(items.length);
  const offsets = new Array(items.length + 1);
  offsets[0] = 0;

  for (let index = 0; index < items.length; index += 1) {
    const height = resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight);
    heights[index] = height;
    offsets[index + 1] = offsets[index] + height;
  }

  return {
    heights,
    offsets,
    totalHeight: offsets[items.length] ?? 0,
  };
}

function buildRenderedEntries({
  items,
  indexes,
  itemKey,
  heightProfile,
  pinnedIndexes,
  visibleStartIndex,
  visibleEndIndex,
}) {
  const pinned = new Set(pinnedIndexes);

  return indexes
    .sort((left, right) => left - right)
    .map((index) => {
      const item = items[index];
      const height = heightProfile.heights[index];

      return {
        index,
        key: resolveItemKey(item, itemKey),
        item,
        offsetTop: heightProfile.offsets[index],
        height,
        pinned: pinned.has(index),
        inViewport: index >= visibleStartIndex && index < visibleEndIndex,
      };
    });
}

export function resolvePinnedIndexes(items, itemKey, pinnedKeys = []) {
  const pinned = new Set(pinnedKeys.filter((key) => key !== null && key !== undefined));

  return items
    .map((item, index) => ({ index, key: resolveItemKey(item, itemKey) }))
    .filter((entry) => pinned.has(entry.key))
    .map((entry) => entry.index)
    .sort((left, right) => left - right);
}

export function resolveVisibleIndexes({
  items,
  itemKey,
  viewportHeight,
  scrollTop,
  estimatedItemHeight,
  overscan,
  measuredHeights = {},
  heightProfile,
}) {
  if (!items.length) {
    return { startIndex: 0, endIndex: 0 };
  }

  if (viewportHeight <= 0) {
    return { startIndex: 0, endIndex: 0 };
  }

  const profile = heightProfile ?? buildHeightProfile(items, itemKey, measuredHeights, estimatedItemHeight);
  const clampedScrollTop = Math.max(scrollTop, 0);
  const viewportBottom = clampedScrollTop + viewportHeight;

  let startVisibleIndex = 0;
  while (
    startVisibleIndex < items.length &&
    profile.offsets[startVisibleIndex + 1] <= clampedScrollTop
  ) {
    startVisibleIndex += 1;
  }

  let endVisibleIndex = startVisibleIndex;
  while (endVisibleIndex < items.length && profile.offsets[endVisibleIndex] < viewportBottom) {
    endVisibleIndex += 1;
  }

  const rawStart = Math.max(startVisibleIndex - overscan, 0);
  const rawEnd = Math.min(endVisibleIndex + overscan, items.length);

  return {
    startIndex: rawStart,
    endIndex: rawEnd,
  };
}

export function buildVirtualWindow({
  items,
  itemKey,
  viewportHeight,
  scrollTop,
  estimatedItemHeight,
  overscan = 2,
  threshold = 20,
  measuredHeights = {},
  pinnedKeys = [],
}) {
  const heightProfile = buildHeightProfile(items, itemKey, measuredHeights, estimatedItemHeight);
  const totalHeight = heightProfile.totalHeight;

  if (items.length <= threshold) {
    const renderedEntries = buildRenderedEntries({
      items,
      indexes: Array.from({ length: items.length }, (_, index) => index),
      itemKey,
      heightProfile,
      pinnedIndexes: resolvePinnedIndexes(items, itemKey, pinnedKeys),
      visibleStartIndex: 0,
      visibleEndIndex: items.length,
    });

    return {
      virtualized: false,
      visibleItems: items,
      visibleKeys: items.map((item) => resolveItemKey(item, itemKey)),
      topSpacerHeight: 0,
      bottomSpacerHeight: 0,
      totalHeight,
      renderedEntries,
    };
  }

  const { startIndex, endIndex } = resolveVisibleIndexes({
    items,
    itemKey,
    viewportHeight,
    scrollTop,
    estimatedItemHeight,
    overscan,
    measuredHeights,
    heightProfile,
  });
  const pinnedIndexes = resolvePinnedIndexes(items, itemKey, pinnedKeys);
  const indexes = new Set([
    ...Array.from({ length: endIndex - startIndex }, (_, offset) => startIndex + offset),
    ...pinnedIndexes,
  ]);
  const orderedIndexes = [...indexes].sort((left, right) => left - right);
  const renderedEntries = buildRenderedEntries({
    items,
    indexes: orderedIndexes,
    itemKey,
    heightProfile,
    pinnedIndexes,
    visibleStartIndex: startIndex,
    visibleEndIndex: endIndex,
  });
  const visibleItems = items.slice(startIndex, endIndex);
  const hasVisibleSlice = endIndex > startIndex;
  const topSpacerHeight = hasVisibleSlice ? heightProfile.offsets[startIndex] : 0;
  const bottomSpacerHeight = hasVisibleSlice ? totalHeight - heightProfile.offsets[endIndex] : totalHeight;

  return {
    virtualized: true,
    visibleItems,
    visibleKeys: visibleItems.map((item) => resolveItemKey(item, itemKey)),
    topSpacerHeight,
    bottomSpacerHeight,
    totalHeight,
    renderedEntries,
  };
}
