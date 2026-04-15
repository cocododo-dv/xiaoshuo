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
  if (items.length <= threshold) {
    return {
      virtualized: false,
      visibleItems: items,
      visibleKeys: items.map((item) => resolveItemKey(item, itemKey)),
      topSpacerHeight: 0,
      bottomSpacerHeight: 0,
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
  const visibleItems = orderedIndexes.map((index) => items[index]);
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
  };
}
