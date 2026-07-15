// FE-ALIGN Phase 2: 自 frontend/src/lib/api/client.js 移植（两端共享同一契约）。
// 信封 {ok,data,error,request_id} / X-Idempotency-Key / X-Operator-Ref /
// novel-system-api-base 逻辑保持一致；去掉 Vue 端的 cursorPagination 依赖。

const API_BASE_KEY = "novel-system-api-base";
const API_BASE_DEFAULT_KEY = "novel-system-api-base-default";
const FALLBACK_API_BASE = "http://127.0.0.1:8000";
const DEFAULT_API_BASE = (import.meta.env.VITE_NOVEL_SYSTEM_API_BASE || FALLBACK_API_BASE).trim();
const OPERATOR_REF_KEY = "novel-system-operator-ref";
const DEFAULT_OPERATOR_REF = "operator";

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

/* ---- 幂等键：操作意图级（审计 P-3）----
   旧实现每次请求都生成新键，后端的去重/重放/在途 409 机制被整体绕过
   （双击 = 两个键 = 两次执行）。现按「方法+路径+载荷」签名持键：
   - 请求在途或失败重试 → 复用同一键（后端可 409 拦截 / 重放缓存结果）；
   - 请求成功 → 丢弃签名（下一次同载荷调用视为新的用户意图，配新键）。 */
const IDEMPOTENCY_KEYS_MAX = 200;
const inflightIdempotencyKeys = new Map();

function requestSignature(method, path, body) {
  let payload = "";
  try {
    payload = body === undefined ? "" : JSON.stringify(body);
  } catch {
    payload = String(body);
  }
  return `${method} ${path} ${payload}`;
}

function acquireIdempotencyKey(method, path, body) {
  const signature = requestSignature(method, path, body);
  let key = inflightIdempotencyKeys.get(signature);
  if (!key) {
    key = `${path}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    if (inflightIdempotencyKeys.size >= IDEMPOTENCY_KEYS_MAX) {
      const oldest = inflightIdempotencyKeys.keys().next().value;
      inflightIdempotencyKeys.delete(oldest);
    }
    inflightIdempotencyKeys.set(signature, key);
  }
  return { key, signature };
}

function releaseIdempotencyKey(signature) {
  inflightIdempotencyKeys.delete(signature);
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

function normalizeRequestError(error, clientRequestId = null) {
  if (error instanceof ApiRequestError) {
    return error;
  }
  if (error && error.name === "AbortError") {
    return new ApiRequestError("请求已取消。", {
      code: "REQUEST_ABORTED",
      status: 0,
      details: { retryable: true, reachedServer: null },
      clientRequestId,
      retryable: true,
    });
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

export async function apiGet(path, { signal } = {}) {
  const clientRequestId = buildClientRequestId();
  try {
    const response = await fetch(buildUrl(path), { signal });
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}

export async function apiPost(path, body = {}, { signal } = {}) {
  const clientRequestId = buildClientRequestId();
  const { key, signature } = acquireIdempotencyKey("POST", path, body);
  try {
    const response = await fetch(buildUrl(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Idempotency-Key": key,
        "X-Operator-Ref": getOperatorRef(),
        "X-Client-Request-Id": clientRequestId,
      },
      body: JSON.stringify(body),
      signal,
    });
    const data = await parseEnvelope(response, clientRequestId);
    releaseIdempotencyKey(signature);
    return data;
  } catch (error) {
    const normalized = normalizeRequestError(error, clientRequestId);
    // 在途冲突/可重试失败保留键供重试重放；确定性失败（4xx 校验类）丢键防脏复用
    if (!normalized.retryable && normalized.code !== "IDEMPOTENCY_REQUEST_IN_PROGRESS") {
      releaseIdempotencyKey(signature);
    }
    throw normalized;
  }
}

export function cancelRunJob(jobId, options) {
  return apiPost(`/api/v1/run-jobs/${encodeURIComponent(jobId)}/cancel`, {}, options);
}

export function getLatestSceneRunJob(sceneId, options) {
  return apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs/latest`, options);
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

export async function apiPut(path, body = {}) {
  const clientRequestId = buildClientRequestId();
  try {
    const response = await fetch(buildUrl(path), {
      method: "PUT",
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

/* ---- 管理面(X-Admin-Token)变体 ----
   系统配置写接口需要管理令牌;无令牌配置的本地后端对 loopback 放行,
   此时 adminToken 传空即可。令牌存取由调用方(WsAiProviders)负责。 */

export async function apiAdminGet(path, adminToken = "") {
  const clientRequestId = buildClientRequestId();
  try {
    const headers = { "X-Client-Request-Id": clientRequestId };
    if (adminToken) headers["X-Admin-Token"] = adminToken;
    const response = await fetch(buildUrl(path), { headers });
    return parseEnvelope(response, clientRequestId);
  } catch (error) {
    throw normalizeRequestError(error, clientRequestId);
  }
}

export async function apiAdminPost(path, body = {}, adminToken = "") {
  const clientRequestId = buildClientRequestId();
  const { key, signature } = acquireIdempotencyKey("POST", path, body);
  try {
    const headers = {
      "Content-Type": "application/json",
      "X-Idempotency-Key": key,
      "X-Operator-Ref": getOperatorRef(),
      "X-Client-Request-Id": clientRequestId,
    };
    if (adminToken) headers["X-Admin-Token"] = adminToken;
    const response = await fetch(buildUrl(path), {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    const data = await parseEnvelope(response, clientRequestId);
    releaseIdempotencyKey(signature);
    return data;
  } catch (error) {
    const normalized = normalizeRequestError(error, clientRequestId);
    if (!normalized.retryable && normalized.code !== "IDEMPOTENCY_REQUEST_IN_PROGRESS") {
      releaseIdempotencyKey(signature);
    }
    throw normalized;
  }
}

export async function apiAdminDelete(path, adminToken = "") {
  const clientRequestId = buildClientRequestId();
  const { key, signature } = acquireIdempotencyKey("DELETE", path, undefined);
  try {
    const headers = {
      "X-Idempotency-Key": key,
      "X-Operator-Ref": getOperatorRef(),
      "X-Client-Request-Id": clientRequestId,
    };
    if (adminToken) headers["X-Admin-Token"] = adminToken;
    const response = await fetch(buildUrl(path), { method: "DELETE", headers });
    const data = await parseEnvelope(response, clientRequestId);
    releaseIdempotencyKey(signature);
    return data;
  } catch (error) {
    const normalized = normalizeRequestError(error, clientRequestId);
    if (!normalized.retryable && normalized.code !== "IDEMPOTENCY_REQUEST_IN_PROGRESS") {
      releaseIdempotencyKey(signature);
    }
    throw normalized;
  }
}

export async function apiDelete(path) {
  const clientRequestId = buildClientRequestId();
  const { key, signature } = acquireIdempotencyKey("DELETE", path, undefined);
  try {
    const response = await fetch(buildUrl(path), {
      method: "DELETE",
      headers: {
        "X-Idempotency-Key": key,
        "X-Operator-Ref": getOperatorRef(),
        "X-Client-Request-Id": clientRequestId,
      },
    });
    const data = await parseEnvelope(response, clientRequestId);
    releaseIdempotencyKey(signature);
    return data;
  } catch (error) {
    const normalized = normalizeRequestError(error, clientRequestId);
    if (!normalized.retryable && normalized.code !== "IDEMPOTENCY_REQUEST_IN_PROGRESS") {
      releaseIdempotencyKey(signature);
    }
    throw normalized;
  }
}
