export function shouldProgressivelyRender({ enabled, itemCount, threshold }) {
  return enabled && itemCount > threshold;
}

export function nextProgressiveCount({ renderedCount, itemCount, batchSize }) {
  return Math.min(renderedCount + batchSize, itemCount);
}

export function buildProgressivePlan({ items, enabled, initialCount, batchSize, threshold }) {
  const itemCount = items.length;

  if (!shouldProgressivelyRender({ enabled, itemCount, threshold })) {
    return {
      items,
      renderedItems: items,
      renderedCount: itemCount,
      pending: false,
      batchSize,
      threshold,
    };
  }

  const renderedCount = Math.min(initialCount, itemCount);

  return {
    items,
    renderedItems: items.slice(0, renderedCount),
    renderedCount,
    pending: renderedCount < itemCount,
    batchSize,
    threshold,
  };
}
