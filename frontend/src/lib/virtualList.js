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

function sumItemHeights(items, startIndex, endIndex, itemKey, measuredHeights, estimatedItemHeight) {
  let total = 0;

  for (let index = startIndex; index < endIndex; index += 1) {
    total += resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight);
  }

  return total;
}

function buildRenderedEntries({
  items,
  indexes,
  itemKey,
  measuredHeights,
  estimatedItemHeight,
  pinnedIndexes,
  visibleStartIndex,
  visibleEndIndex,
}) {
  return indexes
    .sort((left, right) => left - right)
    .map((index) => {
      const item = items[index];
      const height = resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight);

      return {
        index,
        key: resolveItemKey(item, itemKey),
        item,
        offsetTop: sumItemHeights(items, 0, index, itemKey, measuredHeights, estimatedItemHeight),
        height,
        pinned: pinnedIndexes.includes(index),
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
  viewportHeight,
  scrollTop,
  estimatedItemHeight,
  overscan,
}) {
  if (!items.length) {
    return { startIndex: 0, endIndex: 0 };
  }

  const rawStart = Math.max(Math.floor(scrollTop / estimatedItemHeight) - overscan, 0);
  const rawCount = Math.ceil(viewportHeight / estimatedItemHeight) + overscan * 2;
  const rawEnd = Math.min(rawStart + rawCount, items.length);

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
  const totalHeight = sumItemHeights(items, 0, items.length, itemKey, measuredHeights, estimatedItemHeight);

  if (items.length <= threshold) {
    const renderedEntries = buildRenderedEntries({
      items,
      indexes: Array.from({ length: items.length }, (_, index) => index),
      itemKey,
      measuredHeights,
      estimatedItemHeight,
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
    viewportHeight,
    scrollTop,
    estimatedItemHeight,
    overscan,
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
    measuredHeights,
    estimatedItemHeight,
    pinnedIndexes,
    visibleStartIndex: startIndex,
    visibleEndIndex: endIndex,
  });
  const visibleItems = renderedEntries.map((entry) => entry.item);
  const hasVisibleSlice = endIndex > startIndex;
  const topSpacerHeight = hasVisibleSlice
    ? sumItemHeights(items, 0, startIndex, itemKey, measuredHeights, estimatedItemHeight)
    : 0;
  const bottomSpacerHeight = hasVisibleSlice
    ? sumItemHeights(items, endIndex, items.length, itemKey, measuredHeights, estimatedItemHeight)
    : sumItemHeights(items, 0, items.length, itemKey, measuredHeights, estimatedItemHeight);

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
