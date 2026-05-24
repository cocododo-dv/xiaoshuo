import { CURSOR_PAGINATION_DEFAULT_LIMIT, normalizeListPayload } from "../cursorPagination";

export { CURSOR_PAGINATION_DEFAULT_LIMIT, normalizeListPayload };

const API_BASE_KEY = "novel-system-api-base";
const API_BASE_DEFAULT_KEY = "novel-system-api-base-default";
const FALLBACK_API_BASE = "http://127.0.0.1:8000";
const DEFAULT_API_BASE = (import.meta.env.VITE_NOVEL_SYSTEM_API_BASE || FALLBACK_API_BASE).trim();
const OPERATOR_REF_KEY = "novel-system-operator-ref";
const DEFAULT_OPERATOR_REF = "operator";
export const LIST_QUERY_ALIASES = {
  pageSize: "page_size",
  workerId: "worker_id",
  stuckOnly: "stuck_only",
};

function isLoopbackApiBase(value) {
  try {
    const url = new URL(value);
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      ["127.0.0.1", "localhost"].includes(url.hostname)
    );
  } catch {
    return false;
  }
}

function shouldUseInjectedDefault(stored, storedDefault) {
  if (!stored) {
    return true;
  }
  if (stored === FALLBACK_API_BASE) {
    return true;
  }
  if (storedDefault && stored === storedDefault) {
    return true;
  }
  return !storedDefault && isLoopbackApiBase(stored) && isLoopbackApiBase(DEFAULT_API_BASE);
}

export function getApiBase() {
  if (typeof window === "undefined") {
    return DEFAULT_API_BASE;
  }
  const stored = (window.localStorage.getItem(API_BASE_KEY) || "").trim();
  const storedDefault = (window.localStorage.getItem(API_BASE_DEFAULT_KEY) || "").trim();
  if (shouldUseInjectedDefault(stored, storedDefault)) {
    window.localStorage.setItem(API_BASE_KEY, DEFAULT_API_BASE);
    window.localStorage.setItem(API_BASE_DEFAULT_KEY, DEFAULT_API_BASE);
    return DEFAULT_API_BASE;
  }
  window.localStorage.setItem(API_BASE_DEFAULT_KEY, DEFAULT_API_BASE);
  return stored;
}

export function setApiBase(value) {
  const normalized = value.trim() || DEFAULT_API_BASE;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(API_BASE_KEY, normalized);
    window.localStorage.setItem(API_BASE_DEFAULT_KEY, DEFAULT_API_BASE);
  }
  return normalized;
}

export function getOperatorRef() {
  if (typeof window === "undefined") {
    return DEFAULT_OPERATOR_REF;
  }
  return window.localStorage.getItem(OPERATOR_REF_KEY) || DEFAULT_OPERATOR_REF;
}

export function setOperatorRef(value) {
  const normalized = value.trim() || DEFAULT_OPERATOR_REF;
  if (typeof window !== "undefined") {
    window.localStorage.setItem(OPERATOR_REF_KEY, normalized);
  }
  return normalized;
}

export function buildUrl(path) {
  return `${getApiBase()}${path}`;
}

function buildUrlFromBase(baseUrl, path) {
  return `${String(baseUrl || DEFAULT_API_BASE).trim().replace(/\/+$/, "")}${path}`;
}

function buildIdempotencyKey(path) {
  return `${path}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function buildClientRequestId() {
  return `client_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export class ApiRequestError extends Error {
  constructor(message, {
    code = null,
    status = null,
    details = {},
    requestId = null,
    clientRequestId = null,
    retryable = false,
  } = {}) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.status = status;
    this.details = details || {};
    this.requestId = requestId;
    this.clientRequestId = clientRequestId;
    this.retryable = Boolean(retryable);
  }
}

export function buildQueryPath(path, filters = {}, aliases = {}) {
  const params = new URLSearchParams();
  Object.entries(filters || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") {
      return;
    }
    params.set(aliases[key] || key, value);
  });
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

export function buildListQueryPath(path, filters = {}, aliases = {}) {
  return buildQueryPath(path, filters, {
    ...LIST_QUERY_ALIASES,
    ...aliases,
  });
}

function normalizeRequestError(error, clientRequestId = null) {
  if (error instanceof ApiRequestError) {
    return error;
  }
  if (error instanceof Error) {
    if (error.code || error.status) {
      return error;
    }
    if (error.message === "Failed to fetch") {
      return new ApiRequestError(`连接接口失败，请确认 API 地址和后端服务是否可用。当前 API 地址：${getApiBase()}`, {
        code: "NETWORK_ERROR",
        status: 0,
        details: { retryable: true, apiBase: getApiBase(), reachedServer: false },
        clientRequestId,
        retryable: true,
      });
    }
    return error;
  }
  return new ApiRequestError("请求失败。", {
    code: "REQUEST_FAILED",
    status: 0,
    details: { retryable: true, reachedServer: false },
    clientRequestId,
    retryable: true,
  });
}

async function parseEnvelope(response, clientRequestId = null) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok || payload?.ok === false) {
    const responseError = payload?.error || {};
    const fallbackMessage =
      responseError.code === "DATABASE_BUSY"
        ? "数据库正忙，请稍后重试。"
        : `请求失败：${response.status}`;
    const details = responseError.details || {};
    throw new ApiRequestError(responseError.message || fallbackMessage, {
      code: responseError.code || null,
      status: response.status,
      details,
      requestId: payload?.request_id || null,
      clientRequestId,
      retryable: Boolean(details.retryable || response.status === 429 || response.status >= 500),
    });
  }
  return payload?.data;
}

export async function apiGet(path) {
  const clientRequestId = buildClientRequestId();
  try {
    const response = await fetch(buildUrl(path));
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}

export async function apiGetFromBase(baseUrl, path) {
  const clientRequestId = buildClientRequestId();
  try {
    const response = await fetch(buildUrlFromBase(baseUrl, path));
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}

export async function apiPost(path, body = {}) {
  const clientRequestId = buildClientRequestId();
  try {
    const response = await fetch(buildUrl(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Idempotency-Key": buildIdempotencyKey(path),
        "X-Operator-Ref": getOperatorRef(),
        "X-Client-Request-Id": clientRequestId,
      },
      body: JSON.stringify(body),
    });
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}

export async function apiPatch(path, body = {}) {
  const clientRequestId = buildClientRequestId();
  try {
    const response = await fetch(buildUrl(path), {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-Operator-Ref": getOperatorRef(),
        "X-Client-Request-Id": clientRequestId,
      },
      body: JSON.stringify(body),
    });
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}

export async function apiAdminPost(path, body = {}, adminToken = "") {
  const clientRequestId = buildClientRequestId();
  try {
    const headers = {
      "Content-Type": "application/json",
      "X-Operator-Ref": getOperatorRef(),
      "X-Client-Request-Id": clientRequestId,
    };
    if (adminToken) {
      headers["X-Admin-Token"] = adminToken;
    }
    const response = await fetch(buildUrl(path), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}

export async function apiPostForm(path, formData) {
  const clientRequestId = buildClientRequestId();
  try {
    const response = await fetch(buildUrl(path), {
      method: "POST",
      headers: {
        "X-Idempotency-Key": buildIdempotencyKey(path),
        "X-Operator-Ref": getOperatorRef(),
        "X-Client-Request-Id": clientRequestId,
      },
      body: formData,
    });
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}

export async function apiDelete(path) {
  const clientRequestId = buildClientRequestId();
  try {
    const response = await fetch(buildUrl(path), {
      method: "DELETE",
      headers: {
        "X-Idempotency-Key": buildIdempotencyKey(path),
        "X-Operator-Ref": getOperatorRef(),
        "X-Client-Request-Id": clientRequestId,
      },
    });
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}
