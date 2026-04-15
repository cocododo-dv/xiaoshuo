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

function findViewportStartIndex(offsets, scrollTop) {
  let low = 0;
  let high = offsets.length - 2;

  while (low <= high) {
    const mid = Math.floor((low + high) / 2);

    if (offsets[mid + 1] <= scrollTop) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  return low;
}

function findViewportEndIndex(offsets, viewportBottom) {
  let low = 0;
  let high = offsets.length - 2;

  while (low <= high) {
    const mid = Math.floor((low + high) / 2);

    if (offsets[mid] < viewportBottom) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  return low;
}

export function buildHeightProfile(items, itemKey, measuredHeights, estimatedItemHeight) {
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

  return indexes.map((index) => {
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
  overscan = 0,
  measuredHeights = {},
  heightProfile,
}) {
  if (!items.length) {
    return {
      viewportStartIndex: 0,
      viewportEndIndex: 0,
      renderStartIndex: 0,
      renderEndIndex: 0,
    };
  }

  if (viewportHeight <= 0) {
    return {
      viewportStartIndex: 0,
      viewportEndIndex: 0,
      renderStartIndex: 0,
      renderEndIndex: 0,
    };
  }

  const profile = heightProfile ?? buildHeightProfile(items, itemKey, measuredHeights, estimatedItemHeight);
  const maxScrollTop = Math.max(profile.totalHeight - viewportHeight, 0);
  const clampedScrollTop = Math.min(Math.max(scrollTop, 0), maxScrollTop);
  const viewportBottom = clampedScrollTop + viewportHeight;

  const viewportStartIndex = findViewportStartIndex(profile.offsets, clampedScrollTop);
  const viewportEndIndex = findViewportEndIndex(profile.offsets, viewportBottom);
  const renderStartIndex = Math.max(viewportStartIndex - overscan, 0);
  const renderEndIndex = Math.min(viewportEndIndex + overscan, items.length);

  return {
    viewportStartIndex,
    viewportEndIndex,
    renderStartIndex,
    renderEndIndex,
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
  heightProfile,
  pinnedIndexes,
}) {
  const resolvedHeightProfile =
    heightProfile ?? buildHeightProfile(items, itemKey, measuredHeights, estimatedItemHeight);
  const resolvedPinnedIndexes =
    pinnedIndexes ?? resolvePinnedIndexes(items, itemKey, pinnedKeys);
  const totalHeight = resolvedHeightProfile.totalHeight;

  if (items.length <= threshold) {
    const { viewportStartIndex, viewportEndIndex } = resolveVisibleIndexes({
      items,
      itemKey,
      viewportHeight,
      scrollTop,
      estimatedItemHeight,
      measuredHeights,
      heightProfile: resolvedHeightProfile,
    });
    const renderedEntries = buildRenderedEntries({
      items,
      indexes: Array.from({ length: items.length }, (_, index) => index),
      itemKey,
      heightProfile: resolvedHeightProfile,
      pinnedIndexes: resolvedPinnedIndexes,
      visibleStartIndex: viewportStartIndex,
      visibleEndIndex: viewportEndIndex,
    });

    return {
      virtualized: false,
      visibleItems: items.slice(viewportStartIndex, viewportEndIndex),
      visibleKeys: items
        .slice(viewportStartIndex, viewportEndIndex)
        .map((item) => resolveItemKey(item, itemKey)),
      topSpacerHeight: 0,
      bottomSpacerHeight: 0,
      totalHeight,
      renderedEntries,
    };
  }

  const {
    viewportStartIndex,
    viewportEndIndex,
    renderStartIndex,
    renderEndIndex,
  } = resolveVisibleIndexes({
    items,
    itemKey,
    viewportHeight,
    scrollTop,
    estimatedItemHeight,
    overscan,
    measuredHeights,
    heightProfile: resolvedHeightProfile,
  });
  const indexes = new Set([
    ...Array.from({ length: renderEndIndex - renderStartIndex }, (_, offset) => renderStartIndex + offset),
    ...resolvedPinnedIndexes,
  ]);
  const orderedIndexes = [...indexes].sort((left, right) => left - right);
  const renderedEntries = buildRenderedEntries({
    items,
    indexes: orderedIndexes,
    itemKey,
    heightProfile: resolvedHeightProfile,
    pinnedIndexes: resolvedPinnedIndexes,
    visibleStartIndex: viewportStartIndex,
    visibleEndIndex: viewportEndIndex,
  });
  const visibleItems = items.slice(viewportStartIndex, viewportEndIndex);
  const hasVisibleSlice = viewportEndIndex > viewportStartIndex;
  const topSpacerHeight = hasVisibleSlice ? resolvedHeightProfile.offsets[viewportStartIndex] : 0;
  const bottomSpacerHeight = hasVisibleSlice
    ? totalHeight - resolvedHeightProfile.offsets[viewportEndIndex]
    : totalHeight;

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
