function resolveItemKey(item, itemKey) {
  if (typeof itemKey === "function") {
    return itemKey(item);
  }

  return item?.[itemKey];
}

function resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight) {
  const item = items[index];
  const key = resolveItemKey(item, itemKey);

  return measuredHeights[key] || estimatedItemHeight;
}

export function resolvePinnedIndexes(items, itemKey, pinnedKeys = []) {
  const pinned = new Set(pinnedKeys.filter(Boolean));

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
  measuredHeights,
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
    measuredHeights,
  });
  const pinnedIndexes = resolvePinnedIndexes(items, itemKey, pinnedKeys);
  const indexes = new Set([
    ...Array.from({ length: endIndex - startIndex }, (_, offset) => startIndex + offset),
    ...pinnedIndexes,
  ]);
  const orderedIndexes = [...indexes].sort((left, right) => left - right);
  const visibleItems = orderedIndexes.map((index) => items[index]);
  const firstRenderedIndex = orderedIndexes[0] || 0;
  const lastRenderedIndex = orderedIndexes[orderedIndexes.length - 1] || 0;

  let topSpacerHeight = 0;
  for (let index = 0; index < firstRenderedIndex; index += 1) {
    topSpacerHeight += resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight);
  }

  let bottomSpacerHeight = 0;
  for (let index = lastRenderedIndex + 1; index < items.length; index += 1) {
    bottomSpacerHeight += resolveItemHeight(items, index, itemKey, measuredHeights, estimatedItemHeight);
  }

  return {
    virtualized: true,
    visibleItems,
    visibleKeys: visibleItems.map((item) => resolveItemKey(item, itemKey)),
    topSpacerHeight,
    bottomSpacerHeight,
  };
}
