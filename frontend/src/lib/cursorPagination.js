const DEFAULT_LIMIT = 25;
const MAX_LIMIT = 100;

function clampLimit(value, fallback = DEFAULT_LIMIT) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return Math.min(parsed, MAX_LIMIT);
}

export function createCursorPagination(limit = DEFAULT_LIMIT) {
  const normalizedLimit = clampLimit(limit);
  return {
    mode: "cursor",
    limit: normalizedLimit,
    page: null,
    page_size: null,
    returned: 0,
    total: 0,
    has_next: false,
    next_cursor: null,
  };
}

export function createCursorPager(limit = DEFAULT_LIMIT) {
  return {
    cursor: "",
    cursorStack: [],
    pagination: createCursorPagination(limit),
  };
}

export function normalizePagination(pagination, fallbackLimit = DEFAULT_LIMIT) {
  if (!pagination) {
    return createCursorPagination(fallbackLimit);
  }
  return {
    mode: pagination.mode || "cursor",
    limit: clampLimit(pagination.limit ?? pagination.page_size, fallbackLimit),
    page: pagination.page ?? null,
    page_size: pagination.page_size ?? null,
    returned: pagination.returned ?? 0,
    total: pagination.total ?? 0,
    has_next: Boolean(pagination.has_next),
    next_cursor: pagination.next_cursor || null,
  };
}

export function normalizeListPayload(payload, fallbackLimit = DEFAULT_LIMIT) {
  return {
    ...payload,
    items: payload?.items || [],
    pagination: normalizePagination(payload?.pagination, fallbackLimit),
  };
}

export function buildCursorQuery(pager) {
  const query = {
    limit: pager?.pagination?.limit || DEFAULT_LIMIT,
  };
  if (pager?.cursor) {
    query.cursor = pager.cursor;
  }
  return query;
}

export function resetCursorPager(pager, nextLimit = pager?.pagination?.limit || DEFAULT_LIMIT) {
  pager.cursor = "";
  pager.cursorStack = [];
  pager.pagination = createCursorPagination(nextLimit);
}

export function applyCursorPayload(pager, payload) {
  pager.pagination = normalizePagination(payload?.pagination, pager?.pagination?.limit || DEFAULT_LIMIT);
  return payload?.items || [];
}

export function advanceCursorPager(pager) {
  if (!pager?.pagination?.has_next || !pager?.pagination?.next_cursor) {
    return false;
  }
  pager.cursorStack = [...pager.cursorStack, pager.cursor || ""];
  pager.cursor = pager.pagination.next_cursor;
  return true;
}

export function retreatCursorPager(pager) {
  if (!pager?.cursorStack?.length) {
    return false;
  }
  const previousCursor = pager.cursorStack[pager.cursorStack.length - 1] || "";
  pager.cursorStack = pager.cursorStack.slice(0, -1);
  pager.cursor = previousCursor;
  return true;
}

export function filtersSignature(filters = {}) {
  return JSON.stringify(
    Object.keys(filters)
      .sort()
      .reduce((result, key) => {
        result[key] = filters[key];
        return result;
      }, {}),
  );
}

export { DEFAULT_LIMIT as CURSOR_PAGINATION_DEFAULT_LIMIT };
