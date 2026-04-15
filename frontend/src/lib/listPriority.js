export function prioritizeMatchingItem(items, predicate) {
  const source = items || [];
  if (!source.length) {
    return [];
  }

  const matchIndex = source.findIndex((item) => predicate(item));
  if (matchIndex <= 0) {
    return source;
  }

  return [
    source[matchIndex],
    ...source.slice(0, matchIndex),
    ...source.slice(matchIndex + 1),
  ];
}
