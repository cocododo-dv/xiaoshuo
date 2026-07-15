const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const outcomeGateLib = require("./lib/qa-outcome-gate.cjs");
const { observeUiPhase } = require("./lib/ui-phase-evidence.cjs");

let chromium;
try {
  ({ chromium } = require("../frontend/node_modules/playwright"));
} catch {
  ({ chromium } = require("playwright"));
}

const repoRoot = path.resolve(__dirname, "..");
const backendDir = path.join(repoRoot, "backend");
const codexRunDir = path.join(repoRoot, ".codex-run");
const runTimestamp = formatTimestamp(new Date());
const runKey = runTimestamp.replace(/[^0-9]/g, "");
const storySeed = "玻璃雨停在零点";
const resetAuthorState = readBooleanEnv("QA_RESET_AUTHOR_STATE");
const manageDevServices = readBooleanEnv("QA_MANAGE_DEV_SERVICES");
const assumeServicesStopped = readBooleanEnv("QA_ASSUME_SERVICES_STOPPED");
const pythonExecutable = process.env.PYTHON || "python";
const migrationCommandText = "python -m alembic upgrade head";
const resetDryRunCommandText = "python -m novel_system.tools.reset_author_state";
const resetExecuteCommandText = "python -m novel_system.tools.reset_author_state --execute --yes";
const outDirName = `${resetAuthorState ? "reset-" : ""}currentdb-three-chapter-qa-${runTimestamp}`;
const outDir = path.join(repoRoot, "output", "playwright", outDirName);
const logPath = path.join(outDir, "run-log.ndjson");
let frontendUrl = resolveFrontendUrl();
let apiBase = resolveApiBase();
const operatorRef = process.env.PLAYWRIGHT_OPERATOR_REF || `qa.currentdb.three-chapter.${runKey}`;
const referencePath = process.env.REFERENCE_BOOK_PATH || "C:\\Users\\duwei\\Downloads\\龙族.txt";
const referenceCloudPolicy = "segments_only";
const maxSceneJobAttempts = Number(process.env.SCENE_JOB_ATTEMPTS || "3");
// Wave 0（结果闭环治理设计 v1.1 §8）：章节数参数化，第一阶段基准固定 5 章 × 每章 3 场。
// 结果门禁（scripts/playwright_audit_summary.py --outcome-gate）是唯一权威判定：
// 任何计划场景缺少非空后端归档正文，整次运行退出码非零——与步骤 ok 标志无关。
const expectedChapterCount = Math.max(1, Number(process.env.QA_CHAPTER_COUNT || "5"));
const expectedScenesPerChapter = Math.max(1, Number(process.env.QA_SCENES_PER_CHAPTER || "3"));
const terminalJobStatuses = new Set([
  "archived",
  "blocked",
  "cancelled",
  "completed",
  "failed",
  "human_review_required",
  "manual_review_required",
]);

const protectedTerms = [
  "龙族",
  "江南",
  "路明非",
  "楚子航",
  "恺撒",
  "诺诺",
  "陈墨瞳",
  "卡塞尔",
  "昂热",
  "龙王",
  "白王",
  "黑王",
  "青铜与火",
  "血统",
  "屠龙",
];

const chapters = buildChapters(runKey)
  .slice(0, expectedChapterCount)
  .map((chapter) => {
    const scenes = chapter.scenes
      .slice(0, expectedScenesPerChapter)
      .map((scene, index, arr) => ({ ...scene, is_chapter_last: index === arr.length - 1 ? 1 : 0 }));
    return { ...chapter, planned_scene_count: scenes.length, scenes };
  });
const plannedSceneList = chapters.flatMap((chapter) =>
  chapter.scenes.map((scene) => ({ chapter_id: chapter.chapter_id, scene_id: scene.scene_id })),
);
const finalScenes = {}; // 按 scene_id 键控的每场结果记录
const northstarPhases = {}; // 北极星六阶段通道记录（ui / api / missing），如实填报
const result = {
  meta: {
    startedAt: new Date().toISOString(),
    repoRoot,
    outDir,
    frontendUrl,
    apiBase,
    operatorRef,
    storySeed,
    referencePath,
    referenceCloudPolicy,
    currentDb: true,
    noReset: !resetAuthorState,
    resetAuthorState,
    manageDevServices,
    assumeServicesStopped,
    expectedChapterCount,
    expectedScenesPerChapter,
    plannedSceneCount: plannedSceneList.length,
  },
  outcome: null,
  outcomeGate: null,
  steps: [],
  writerExperience: {},
  chapterScores: {},
  chapterSetReview: null,
  protectedTermScan: {},
  llmRouteCoverage: null,
  llmFallbackAudit: null,
  rootCauseFindings: [],
  currentRunBlockers: [],
  sceneRunBlockers: [],
  systemFixes: [],
  screenshots: [],
  layoutFindings: [],
  warnings: [],
  console: [],
  requestFailures: [],
};

function readBooleanEnv(name) {
  return /^(1|true|yes|on)$/i.test(String(process.env[name] || ""));
}

function resolveFrontendUrl() {
  return (
    process.env.PLAYWRIGHT_FRONTEND_URL ||
    readRunFile("frontend.url") ||
    readRunFile("vite.url") ||
    `http://127.0.0.1:${process.env.PLAYWRIGHT_FRONTEND_PORT || "5173"}`
  );
}

function resolveApiBase() {
  return (
    process.env.PLAYWRIGHT_API_BASE ||
    readRunFile("backend.url") ||
    readRunFile("api.url") ||
    `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8001"}`
  );
}

function refreshRuntimeUrls() {
  frontendUrl = resolveFrontendUrl();
  apiBase = resolveApiBase();
  result.meta.frontendUrl = frontendUrl;
  result.meta.apiBase = apiBase;
  return { frontendUrl, apiBase };
}

function formatTimestamp(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("") + "-" + [pad(date.getHours()), pad(date.getMinutes()), pad(date.getSeconds())].join("");
}

function readRunFile(fileName) {
  try {
    const value = fs.readFileSync(path.join(codexRunDir, fileName), "utf8").trim();
    return value || null;
  } catch {
    return null;
  }
}

function ensureOutDir() {
  fs.mkdirSync(outDir, { recursive: true });
}

function writeJson(name, payload) {
  ensureOutDir();
  fs.writeFileSync(path.join(outDir, name), JSON.stringify(payload, null, 2), "utf8");
}

function appendLog(event) {
  ensureOutDir();
  fs.appendFileSync(logPath, `${JSON.stringify({ at: new Date().toISOString(), ...event })}\n`, "utf8");
}

function backendPythonEnv() {
  const currentPythonPath = process.env.PYTHONPATH || "";
  const pythonPath = currentPythonPath ? `src${path.delimiter}${currentPythonPath}` : "src";
  return { ...process.env, PYTHONPATH: pythonPath };
}

function isWindowsCommandScript(filePath) {
  return process.platform === "win32" && /\.(cmd|bat)$/i.test(String(filePath || ""));
}

function commandInvocation(filePath, args = []) {
  if (!isWindowsCommandScript(filePath)) {
    return { filePath, args };
  }
  const commandLine = [filePath, ...args].map(quoteForCmd).join(" ");
  return {
    filePath: process.env.ComSpec || "cmd.exe",
    args: ["/d", "/s", "/c", commandLine],
  };
}

function quoteForCmd(value) {
  const text = String(value);
  if (!text || /[\s&()^=;!'+,`~[\]{}]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function runNativeCommand(label, filePath, args = [], options = {}) {
  const commandText = options.commandText || [filePath, ...args].join(" ");
  const cwd = options.cwd || repoRoot;
  const invocation = commandInvocation(filePath, args);
  appendLog({ type: "native-command-start", label, command: commandText, cwd });
  try {
    const stdio = options.stdioMode === "ignore" ? "ignore" : ["ignore", "pipe", "pipe"];
    const stdout = execFileSync(invocation.filePath, invocation.args, {
      cwd,
      env: options.env || process.env,
      encoding: "utf8",
      stdio,
      timeout: options.timeoutMs || undefined,
      windowsHide: true,
    });
    const item = { label, command: commandText, cwd, ok: true, stdout: preview(stdout || "", options.previewLimit || 1000) };
    appendLog({ type: "native-command-ok", ...item });
    return item;
  } catch (error) {
    const item = {
      label,
      command: commandText,
      cwd,
      ok: false,
      stdout: preview(error?.stdout || "", options.previewLimit || 1000),
      stderr: preview(error?.stderr || error?.message || error, options.previewLimit || 1000),
    };
    appendLog({ type: "native-command-fail", ...item });
    if (options.allowFailure) {
      result.warnings.push(`${label} failed but was allowed: ${item.stderr || item.stdout}`);
      return item;
    }
    const wrapped = new Error(`${label} failed: ${item.stderr || item.stdout || error.message}`);
    wrapped.cause = error;
    throw wrapped;
  }
}

function prepareCleanRunEnvironment() {
  const actions = [];
  if (!resetAuthorState && !manageDevServices) {
    return { skipped: true };
  }

  if (manageDevServices) {
    actions.push(
      runNativeCommand("stop dev services before reset", path.join(repoRoot, "stop-dev.cmd"), [], {
        cwd: repoRoot,
        allowFailure: true,
      }),
    );
  } else if (resetAuthorState) {
    if (!assumeServicesStopped) {
      throw new Error(
        "QA_RESET_AUTHOR_STATE requires QA_MANAGE_DEV_SERVICES=1 or QA_ASSUME_SERVICES_STOPPED=1 before destructive reset.",
      );
    }
    result.warnings.push(
      "QA_RESET_AUTHOR_STATE is enabled with QA_ASSUME_SERVICES_STOPPED; runner will reset author state without stop/start service management.",
    );
  }

  if (resetAuthorState) {
    actions.push(
      runNativeCommand("run alembic migrations before author reset", pythonExecutable, ["-m", "alembic", "upgrade", "head"], {
        cwd: backendDir,
        env: backendPythonEnv(),
        commandText: migrationCommandText,
      }),
    );
    actions.push(
      runNativeCommand("dry-run author-state reset", pythonExecutable, ["-m", "novel_system.tools.reset_author_state"], {
        cwd: backendDir,
        env: backendPythonEnv(),
        commandText: resetDryRunCommandText,
      }),
    );
    actions.push(
      runNativeCommand(
        "execute author-state reset",
        pythonExecutable,
        ["-m", "novel_system.tools.reset_author_state", "--execute", "--yes"],
        {
          cwd: backendDir,
          env: backendPythonEnv(),
          commandText: resetExecuteCommandText,
        },
      ),
    );
  }

  if (manageDevServices) {
    actions.push(
      runNativeCommand("start dev services after reset", path.join(repoRoot, "start-dev.cmd"), [], {
        cwd: repoRoot,
        stdioMode: "ignore",
        timeoutMs: 180000,
      }),
    );
    actions.push({ label: "refresh runtime URLs", ok: true, ...refreshRuntimeUrls() });
  }

  result.meta.environmentPreparation = {
    resetAuthorState,
    manageDevServices,
    assumeServicesStopped,
    actions,
  };
  return result.meta.environmentPreparation;
}

function preview(value, limit = 260) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function idempotencyKey(label) {
  return `${operatorRef}.${label}.${Date.now()}.${Math.random().toString(16).slice(2, 8)}`.replace(/[^a-zA-Z0-9_.:-]/g, "-");
}

function requestHeaders(label, json = true, idempotency = null) {
  const headers = {
    "X-Idempotency-Key": idempotency || idempotencyKey(label),
    "X-Operator-Ref": operatorRef,
  };
  if (json) {
    headers["Content-Type"] = "application/json";
  }
  return headers;
}

async function apiGet(apiPath, timeoutMs = 30000) {
  return fetchEnvelope("GET", apiPath, null, timeoutMs);
}

async function apiPost(apiPath, data = {}, timeoutMs = 30000) {
  return fetchEnvelope("POST", apiPath, data, timeoutMs);
}

async function apiPatch(apiPath, data = {}, timeoutMs = 30000) {
  return fetchEnvelope("PATCH", apiPath, data, timeoutMs);
}

async function fetchEnvelope(method, apiPath, data, timeoutMs) {
  const idempotency = method === "GET" ? null : idempotencyKey(apiPath);
  const maxAttempts = Number(process.env.QA_API_ATTEMPTS || "5");
  let lastError = null;
  for (let attemptNo = 1; attemptNo <= maxAttempts; attemptNo += 1) {
    try {
      return await fetchEnvelopeOnce(method, apiPath, data, timeoutMs, idempotency);
    } catch (error) {
      lastError = error;
      if (attemptNo >= maxAttempts || !isRetryableApiError(error)) {
        throw error;
      }
      const delayMs = Math.min(60000, 1500 * 2 ** (attemptNo - 1));
      result.warnings.push(`${method} ${apiPath} retry ${attemptNo}/${maxAttempts} after ${error.code || error.status || error.name}: ${error.message}`);
      appendLog({ type: "api-retry", method, apiPath, attemptNo, delayMs, code: error.code || null, status: error.status || null });
      await sleep(delayMs);
    }
  }
  throw lastError;
}

async function fetchEnvelopeOnce(method, apiPath, data, timeoutMs, idempotency) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase}${apiPath}`, {
      method,
      headers: method === "GET" ? { "X-Operator-Ref": operatorRef } : requestHeaders(apiPath, true, idempotency),
      body: method === "GET" ? undefined : JSON.stringify(data || {}),
      signal: controller.signal,
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = { raw: text };
    }
    if (!response.ok || payload?.ok === false) {
      const error = new Error(payload?.error?.message || payload?.message || `HTTP ${response.status} ${apiPath}`);
      error.status = response.status;
      error.code = payload?.error?.code || null;
      error.payload = payload;
      throw error;
    }
    return payload?.data ?? payload;
  } finally {
    clearTimeout(timeout);
  }
}

function isRetryableApiError(error) {
  const code = String(error?.code || "");
  const message = String(error?.message || "");
  return (
    code === "DATABASE_BUSY" ||
    code === "SQLITE_BUSY" ||
    error?.status === 503 ||
    error?.name === "AbortError" ||
    /database is busy|retry after|temporar|timeout|timed out|fetch failed|connection|network/i.test(message)
  );
}

async function step(name, fn, options = {}) {
  const started = Date.now();
  try {
    appendLog({ type: "step-start", name });
    const data = await fn();
    const item = { name, ok: true, ms: Date.now() - started, data: compactData(data) };
    result.steps.push(item);
    appendLog({ type: "step-ok", name, ms: item.ms });
    writeJson("qa-live-results.json", result);
    return data;
  } catch (error) {
    const item = {
      name,
      ok: false,
      ms: Date.now() - started,
      error: String(error?.stack || error?.message || error),
      code: error?.code || null,
    };
    result.steps.push(item);
    result.warnings.push(`${name}: ${error?.message || error}`);
    appendLog({ type: "step-fail", name, ms: item.ms, error: item.error });
    writeJson("qa-live-results.json", result);
    if (options.fatal) {
      throw error;
    }
    return null;
  }
}

function compactData(data) {
  if (!data || typeof data !== "object") {
    return data ?? null;
  }
  return JSON.parse(JSON.stringify(data, (key, value) => {
    if (key === "finalText" || key === "content" || key === "text") {
      return preview(value, 420);
    }
    return value;
  }));
}

async function screenshot(page, name) {
  const target = path.join(outDir, `${name}.png`);
  try {
    await page.screenshot({ path: target, fullPage: true });
    result.screenshots.push(path.relative(repoRoot, target).replace(/\\/g, "/"));
    await collectLayoutFindings(page, name);
  } catch (error) {
    result.warnings.push(`screenshot ${name} failed: ${error.message}`);
  }
}

async function collectLayoutFindings(page, screenshotName) {
  try {
    const findings = await page.evaluate((shotName) => {
      const rawRefPattern =
        /\b(?:CDBQA_\d{14}_\d{2}(?:_SC\d+)?|author_draft:[^\s]{24,}|quality:[^\s]{24,}|review_[^\s]{28,}|calibration_line:[^\s]{24,}|chapter_promise:[^\s]{24,})/;
      const rawRefMatchPattern =
        /\b(?:CDBQA_\d{14}_\d{2}(?:_SC\d+)?|author_draft:[^\s]{24,}|quality:[^\s]{24,}|review_[^\s]{28,}|calibration_line:[^\s]{24,}|chapter_promise:[^\s]{24,})/g;
      const visible = (element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const describe = (element) =>
        element.getAttribute("data-testid") ||
        element.className?.toString?.().split(/\s+/).filter(Boolean).slice(0, 3).join(".") ||
        element.tagName.toLowerCase();
      const output = [];
      const doc = document.documentElement;
      if (doc.scrollWidth > doc.clientWidth + 1) {
        output.push({
          screenshot: shotName,
          type: "document-horizontal-overflow",
          detail: `${doc.scrollWidth} > ${doc.clientWidth}`,
        });
      }

      const watchedSelectors = [
        ".writer-room-grid",
        ".author-layout",
        ".deep-desk-shell",
        ".quality-card",
        ".longform-card",
        ".alias-grid .paper",
        ".history-entry",
        ".compact-entity-select",
      ];
      for (const element of document.querySelectorAll(watchedSelectors.join(","))) {
        if (!visible(element)) {
          continue;
        }
        const rect = element.getBoundingClientRect();
        if (rect.right > doc.clientWidth + 8 || rect.left < -8 || element.scrollWidth > element.clientWidth + 8) {
          output.push({
            screenshot: shotName,
            type: "element-overflow",
            target: describe(element),
            detail: `${Math.round(rect.left)}-${Math.round(rect.right)} / scroll ${element.scrollWidth}:${element.clientWidth}`,
          });
        }
      }

      const noisyNodes = Array.from(document.querySelectorAll("body *"))
        .filter((element) => visible(element))
        .filter((element) => !element.closest("pre, code, .json-block, .technical-ref"))
        .map((element) => ({
          target: describe(element),
          text: element.textContent || "",
        }))
        .filter((entry) => rawRefPattern.test(entry.text));
      for (const entry of noisyNodes.slice(0, 12)) {
        output.push({
          screenshot: shotName,
          type: "visible-raw-technical-ref",
          target: entry.target,
          detail: (entry.text.match(rawRefMatchPattern) || []).slice(0, 2).join(" / "),
        });
      }

      return output.slice(0, 30);
    }, screenshotName);
    if (findings.length) {
      result.layoutFindings.push(...findings);
      appendLog({ type: "layout-findings", screenshotName, count: findings.length });
    }
  } catch (error) {
    result.warnings.push(`layout scan ${screenshotName} failed: ${error.message}`);
  }
}

async function prepareBrowser(page) {
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      result.console.push({ type: message.type(), text: message.text() });
    }
  });
  page.on("requestfailed", (request) => {
    result.requestFailures.push({
      url: request.url(),
      method: request.method(),
      error: request.failure()?.errorText || "",
    });
  });
  await page.goto(frontendUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.evaluate(
    ({ nextApiBase, nextOperatorRef }) => {
      localStorage.setItem("novel-system-api-base", nextApiBase);
      localStorage.setItem("novel-system-operator-ref", nextOperatorRef);
      localStorage.removeItem("novel-system:last-workbench-scene-id");
    },
    { nextApiBase: apiBase, nextOperatorRef: operatorRef },
  );
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
}

async function clickIfPresent(page, testId) {
  const locator = page.getByTestId(testId);
  if (await locator.count()) {
    await locator.first().click();
    return true;
  }
  return false;
}

// QA-RIG-HOTFIX(2026-06-27): this three-chapter harness was authored against the legacy
// Vue frontend (:5173), which exposes `data-testid="nav-*"` navigation + per-view content
// test-ids. The React mainline (frontend-react, :5174 — the contract-authoritative QA
// target) has NO such test-ids and routes purely by `location.hash`. Pointed at React, the
// original `visit()` timed out clicking `nav-*` and aborted the whole run. Since every real
// step here is API-driven (apiPost/apiGet/apiPatch) and `visit()` is evidence-only
// (screenshots + fixed experience notes), we degrade navigation gracefully: prefer the Vue
// nav test-id when present, else fall back to React hash routing; the content-test-id wait
// becomes best-effort. Keeps BOTH frontends working and unblocks the React run.
const REACT_HASH_BY_VIEW = {
  reference: "styleref",
  "snowflake-workbench": "snowflake",
  "writer-room": "writer",
  workbench: "scene",
  knowledge: "index",
  deepdesk: "quality",
};

async function visit(page, viewId, testId, screenshotName) {
  let navigated = false;
  try {
    const navLoc = page.getByTestId(`nav-${viewId}`);
    if (await navLoc.count()) {
      await navLoc.first().click({ timeout: 5000 });
      navigated = true;
    }
  } catch {
    // Legacy-Vue nav path unavailable; fall through to React hash routing.
  }
  if (!navigated) {
    const hash = REACT_HASH_BY_VIEW[viewId] || viewId;
    await page.evaluate((h) => { window.location.hash = `#${h}`; }, hash).catch(() => null);
    await page.waitForTimeout(800);
  }
  // React exposes no per-view content test-id; keep readiness wait best-effort (evidence-only).
  await page.getByTestId(testId).waitFor({ timeout: 4000 }).catch(() => null);
  await screenshot(page, screenshotName);
}

function commandVersion(command, args = ["--version"]) {
  if (process.platform === "win32") {
    try {
      return execFileSync("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", `${command} ${args.join(" ")}`], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      }).trim();
    } catch {
      // Fall through to direct launcher names.
    }
  }
  const candidates = process.platform === "win32" ? [command, `${command}.cmd`, `${command}.ps1`] : [command];
  for (const candidate of candidates) {
    try {
      return execFileSync(candidate, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
    } catch {
      // Try the next launcher name.
    }
  }
  return null;
}

async function preflight() {
  const referenceExists = fs.existsSync(referencePath);
  const referenceStat = referenceExists ? fs.statSync(referencePath) : null;
  const gitStatus = execFileSync("git", ["status", "--short"], { cwd: repoRoot, encoding: "utf8" }).trim();
  const chaptersStatus = await apiGet("/api/v1/chapters").catch((error) => ({ unavailable: error.message }));
  const systemConfig = await apiGet("/api/v1/system-config").catch((error) => ({ unavailable: error.message }));
  const llmConfig = await apiGet("/api/v1/system-config/llm").catch((error) => ({ unavailable: error.message }));
  result.meta.preflight = {
    npxVersion: commandVersion("npx"),
    referenceExists,
    referenceSize: referenceStat?.size || 0,
    referenceMtime: referenceStat?.mtime?.toISOString?.() || null,
    gitStatus,
    currentActiveChapterCount: chaptersStatus.items?.length ?? null,
    systemStatus: systemConfig.status || "unknown",
    providers: Object.keys(llmConfig.providers || {}),
    nodeCatalogCount: Object.keys(llmConfig.node_catalog || {}).length,
    missingActiveRoutes: llmConfig.missing_active_routes || [],
    blockedRoutes: llmConfig.blocked_routes || [],
    routeReadiness: llmConfig.node_routes || llmConfig.routes || {},
  };
  return result.meta.preflight;
}

async function auditLlmIntegration() {
  const llmConfig = await apiGet("/api/v1/system-config/llm");
  const callAudit = await apiGet("/api/v1/system-config/llm/calls/audit").catch((error) => ({
    unavailable: error.message,
  }));
  const nodeCatalog = llmConfig.node_catalog || {};
  const nodeRoutes = llmConfig.node_routes || {};
  const coverageMatrix = Object.keys(nodeCatalog)
    .sort((left, right) => Number(nodeCatalog[left]?.order ?? 9999) - Number(nodeCatalog[right]?.order ?? 9999))
    .map((nodeId) => {
      const spec = nodeCatalog[nodeId] || {};
      const route = nodeRoutes[nodeId] || {};
      return {
        node_id: nodeId,
        group: spec.group || route.group || "custom",
        status: spec.status || route.status || "active",
        requires_llm: spec.requires_llm !== false && route.requires_llm !== false,
        configured: Boolean(route.configured),
        ready: Boolean(route.ready),
        provider_id: route.provider_id || null,
        model: route.model || null,
        readiness_reason: route.readiness_reason || null,
      };
    });
  result.llmRouteCoverage = {
    readiness: llmConfig.readiness || null,
    missing_active_routes: llmConfig.missing_active_routes || [],
    blocked_routes: llmConfig.blocked_routes || [],
    matrix: coverageMatrix,
  };
  result.llmFallbackAudit = callAudit;
  const offlineCount = Number(callAudit.offline_deterministic_required_count || 0);
  if (offlineCount > 0) {
    result.warnings.push(`LLM audit found ${offlineCount} offline_deterministic calls for LLM-required nodes.`);
  }
  return {
    missing_active_routes: result.llmRouteCoverage.missing_active_routes,
    blocked_routes: result.llmRouteCoverage.blocked_routes,
    offline_deterministic_required_count: offlineCount,
    nodes_without_calls: callAudit.nodes_without_calls || [],
  };
}

async function exerciseUiModesAndPages(page) {
  await clickIfPresent(page, "ui-mode-writer");
  await screenshot(page, "ui-mode-writer");
  await clickIfPresent(page, "ui-mode-advanced");
  await screenshot(page, "ui-mode-advanced");

  const pages = [
    ["snowflake-workbench", "snowflake-workbench-view", "snowflake-planning"],
    ["writer-room", "writer-room-view", "writer-room"],
    ["reference", "reference-learning-view", "reference-learning"],
    ["author", "author-workspace-view", "author-workspace"],
    ["workbench", "scene-workbench-view", "scene-workbench"],
    ["review", "review-inbox-view", "review-inbox"],
    ["quality", "literary-quality-view", "literary-quality"],
    ["manuscripts", "chapter-manuscript-view", "chapter-manuscripts"],
    ["deepdesk", "writer-deep-desk", "writer-deep-desk"],
    ["longform", "longform-control-view", "longform-control"],
    ["knowledge", "knowledge-console-view", "knowledge-console"],
    ["index", "index-console-view", "index-console"],
    ["interop", "interop-center-view", "interop-center"],
    ["config", "system-config-view", "system-config"],
    ["trash", "author-trash-view", "author-trash"],
  ];
  const visited = [];
  for (const [viewId, testId, shot] of pages) {
    try {
      await visit(page, viewId, testId, shot);
      visited.push({ viewId, ok: true });
    } catch (error) {
      visited.push({ viewId, ok: false, error: error.message });
      result.warnings.push(`UI visit ${viewId} failed: ${error.message}`);
    }
  }
  recordExperience("writer mode", 8, "模式切换清楚，主路径会收束到写作者常用入口。");
  recordExperience("advanced mode", 7, "高级信息密度足够，但长链路状态仍需要更明显的下一步提示。");
  return { visited };
}

function throwReferenceLearningBlocker(context) {
  const safeContext = compactData(context);
  const error = new Error(`reference learning did not produce a ready profile: ${JSON.stringify(safeContext)}`);
  error.code = "REFERENCE_PROFILE_NOT_READY";
  error.context = safeContext;
  appendLog({ type: "reference-learning-blocker", context: safeContext });
  throw error;
}

async function exerciseReferenceLearning(page) {
  await visit(page, "reference", "reference-learning-view", "reference-learning-currentdb");
  const imported = await apiPost(
    "/api/v1/reference-books/import-path",
    {
      file_path: referencePath,
      title: `${storySeed} 抽象参考 ${runKey}`,
      author_label: "abstract-reference-only",
      cloud_policy: referenceCloudPolicy,
      analysis_focus: "style_structure",
    },
    120000,
  );
  const bookId = imported.book_id || imported.book?.book_id;
  const started = await apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/runs`, { batch_size: 6 }, 60000);
  const runId = started.run?.run_id || started.run_id;
  const firstAdvance = await apiPost(
    `/api/v1/reference-books/${encodeURIComponent(bookId)}/runs/${encodeURIComponent(runId)}/advance`,
    {},
    600000,
  ).catch((error) => ({ blocked: error.message, code: error.code || null }));
  const profileAdvance = firstAdvance.profile
    ? firstAdvance
    : await apiPost(
        `/api/v1/reference-books/${encodeURIComponent(bookId)}/runs/${encodeURIComponent(runId)}/advance`,
        {},
        600000,
      ).catch((error) => ({ blocked: error.message, code: error.code || null }));
  const tree = await apiGet(`/api/v1/reference-books/${encodeURIComponent(bookId)}/learning-tree`, 60000).catch((error) => ({
    blocked: error.message,
  }));
  const detail = await apiGet(`/api/v1/reference-books/${encodeURIComponent(bookId)}`, 60000).catch((error) => ({ blocked: error.message }));
  const profile =
    profileAdvance.profile ||
    detail.profiles?.find((item) => item.run_id === runId && item.status === "ready") ||
    detail.profiles?.find((item) => item.status === "ready") ||
    detail.profiles?.[0] ||
    null;
  if (!profile?.profile_id || (profile.status && profile.status !== "ready")) {
    throwReferenceLearningBlocker({
      bookId,
      runId,
      firstAdvance,
      profileAdvance,
      detailStatus: detail.status || detail.book?.status || null,
      profileCount: Array.isArray(detail.profiles) ? detail.profiles.length : 0,
      treeSummary: tree.summary || null,
    });
  }
  let applyResult = null;
  if (profile?.profile_id) {
    applyResult = await apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/profiles/${encodeURIComponent(profile.profile_id)}/apply`, {
      scope: "chapter",
      scope_ref_id: chapters[0].chapter_id,
    }).catch((error) => ({ blocked: error.message }));
  }
  if (applyResult?.blocked) {
    throwReferenceLearningBlocker({
      bookId,
      runId,
      profileId: profile.profile_id,
      applyBlocked: applyResult.blocked,
    });
  }
  await screenshot(page, "reference-learning-segments-only");
  recordExperience("reference learning", profile?.profile_id ? 8 : 6, "segments_only 更符合版权安全，但 profile 阶段的等待和阻塞信息仍是信任关键。");
  return {
    bookId,
    runId,
    cloudPolicy: referenceCloudPolicy,
    profileId: profile?.profile_id || null,
    profileKeys: Object.keys(profile?.profile_json || profile?.payload_json || {}),
    learningTreeSummary: tree.summary || null,
    applyReviewIds: (applyResult?.reviews || []).map((item) => item.review_id),
    blocked: firstAdvance.blocked || profileAdvance.blocked || detail.blocked || applyResult?.blocked || null,
  };
}

async function createOriginalWorkspace(page) {
  const title = `${storySeed} · ${runKey}`;
  await visit(page, "home", "home-view", "blank-project-before-create");
  await page.getByTestId("work-switcher").click();
  await page.getByTestId("work-new-open").click();
  await page.getByTestId("work-new-title").fill(title);
  await page.getByTestId("work-new-synopsis").fill("一名档案修复员发现失踪名单会在零点被改写，但公开真相的每一步都可能让证人付出代价。");
  const createdResponse = page.waitForResponse((response) => (
    response.request().method() === "POST"
      && /\/api\/v2\/projects(?:\?|$)/.test(response.url())
  ), { timeout: 30000 });
  await page.getByTestId("work-new-submit").click();
  const response = await createdResponse;
  if (!response.ok()) throw new Error(`UI project creation failed: HTTP ${response.status()}`);
  const payload = await response.json();
  const project = payload?.data?.project;
  if (!project?.project_id) throw new Error("UI project creation response did not include project_id");
  await page.waitForFunction(
    (projectId) => Boolean(window.WsWorks && window.WsWorks.activeId() === projectId),
    project.project_id,
    { timeout: 30000 },
  );
  const catalog = await apiGet(`/api/v2/projects/${encodeURIComponent(project.project_id)}/catalog`);
  if ((catalog?.chapters || []).length !== 0) throw new Error("Northstar project must start with an empty catalog");
  await screenshot(page, "blank-project-created-through-ui");
  recordExperience("project creation", 9, "空白作品由新建对话框创建，后端目录校验为 0 章 0 场。");
  return {
    projectId: project.project_id,
    title,
    chapterIds: [],
    sceneIds: [],
  };
}

async function exerciseSnowflake(page) {
  await visit(page, "snowflake-workbench", "snowflake-workbench-view", "snowflake-workbench-currentdb");
  const plan = buildSnowflakeImportPlan(chapters);
  const planningReceipt = await observeUiPhase(page, "snowflake_planning", async ({ click, fill }) => {
    await click(page.getByTestId("snow-import-open"));
    await page.getByTestId("snow-import-dialog").waitFor({ timeout: 10000 });
    await fill(page.getByTestId("snow-import-json"), JSON.stringify(plan));
    await click(page.getByTestId("snow-import-submit"));
    await page.getByTestId("snow-import-dialog").waitFor({ state: "hidden", timeout: 120000 });
  });
  recordUiPhase(planningReceipt, "作者在雪花页导入十步结构化计划；浏览器依次保存并批准 10/10 步。" );
  await screenshot(page, "snowflake-planning-ui-approved");

  await page.getByTestId("snow-step-outline").click();
  await page.getByTestId("snow-materialize").waitFor({ timeout: 30000 });
  page.once("dialog", (dialog) => dialog.accept());
  const materializeReceipt = await observeUiPhase(page, "materialization", async ({ click }) => {
    await click(page.getByTestId("snow-materialize"));
    await page.getByTestId("snow-go-draft").waitFor({ timeout: 120000 });
  });
  recordUiPhase(materializeReceipt, "作者点击采用到章节编排；浏览器完成 materialize 与 outline approve 两步。" );

  const projectId = await page.evaluate(() => window.WsWorks && window.WsWorks.activeId());
  const catalog = await apiGet(`/api/v2/projects/${encodeURIComponent(projectId)}/catalog`);
  const materialized = catalog?.chapters || [];
  const materializedScenes = materialized.flatMap((chapter) => chapter.scenes || []);
  if (materialized.length !== expectedChapterCount || materializedScenes.length !== plannedSceneList.length) {
    throw new Error(`UI materialization mismatch: chapters=${materialized.length}, scenes=${materializedScenes.length}`);
  }
  await screenshot(page, "snowflake-materialized-through-ui");
  await page.getByTestId("snow-go-draft").click();
  await page.getByTestId("scene-queue-item").first().waitFor({ timeout: 30000 });
  const queueCount = await page.getByTestId("scene-queue-item").count();
  if (queueCount !== plannedSceneList.length) throw new Error(`UI queue mismatch: expected ${plannedSceneList.length}, got ${queueCount}`);
  recordExperience("snowflake planning", 9, "十步结构导入与五章十五场物化均由作者界面触发，目录仅用 API 只读复核。");
  return { seed: storySeed, projectId, plannedChapters: materialized.length, plannedScenes: materializedScenes.length };
}

async function exerciseWriterRoomAndDrafts(page) {
  const sceneId = chapters[0].scenes[0].scene_id;
  const ensured = await apiPost(`/api/v1/author-drafts/scene/${encodeURIComponent(sceneId)}/ensure-blank`, {});
  const draft = ensured.draft || ensured;
  const saved = await apiPatch(`/api/v1/author-drafts/${encodeURIComponent(draft.draft_id)}`, {
    base_revision_no: draft.revision_no,
    content:
      "零点前，玻璃雨像被城市屏住的呼吸，停在候车厅顶棚。沈闻把失踪名单反扣在掌心，先听见未来落下来的声音。",
    note: "current DB QA seed draft",
  });
  await visit(page, "writer-room", "writer-room-view", "writer-room-currentdb");
  recordExperience("writer room", 8, "小修写作入口适合作者直接接管文本，保存草稿后的状态反馈可信。");
  return { draftId: draft.draft_id, revisionNo: saved.draft?.revision_no || saved.revision_no || null };
}

async function exerciseReviewInbox(page, reviewIds = []) {
  const reviewId = `review_currentdb_${runKey}`;
  await apiPost("/api/v1/review-items", {
    review_id: reviewId,
    item_type: "calibration_candidate",
    chapter_id: chapters[0].chapter_id,
    scene_id: chapters[0].scenes[0].scene_id,
    status: "pending",
    candidate_text: "原创线索以选择代价推动，不搬运参考书专名、设定和标志性桥段。",
    active_on_approve: 1,
    candidate_payload_json: {
      lineage_key: `CAL_CURRENTDB_${runKey}`,
      text: "线索先以物证出现，解释延后；每章结尾必须产生选择代价或新的证人保护压力。",
      scope: "chapter",
      scope_ref_id: chapters[0].chapter_id,
    },
  }, 60000);
  const approval = await approveAndReleaseReviewItem(reviewId).catch((error) => ({
    approved: { blocked: error.message },
    released: { blocked: error.message },
  }));
  const approved = approval.approved;
  const released = approval.released;
  for (const candidateId of reviewIds.filter(Boolean)) {
    await apiPost(`/api/v1/review-items/${encodeURIComponent(candidateId)}/approve`, {}).catch((error) =>
      result.warnings.push(`reference apply review ${candidateId} deferred: ${error.message}`),
    );
  }
  await visit(page, "review", "review-inbox-view", "review-inbox-currentdb");
  recordExperience("review", released?.released || approved?.released ? 8 : 6, "审核箱能完成批准链路；release/verify 的阻塞需要在 UI 上直接说明下一步。");
  return { reviewId, approved, released };
}

async function approveAndReleaseReviewItem(reviewId) {
  const approved = await apiPost(`/api/v1/review-items/${encodeURIComponent(reviewId)}/approve`, {}, 60000);
  const verifyJobId = (approved.job_ids || []).find((jobId) => String(jobId).startsWith("verify_"));
  if (verifyJobId) {
    await apiPost(`/api/v1/index/verify/${encodeURIComponent(verifyJobId)}/retry`, {}, 60000).catch((error) =>
      result.warnings.push(`verify deferred for ${reviewId}: ${error.message}`),
    );
  }
  const released = await apiPost(`/api/v1/review-items/${encodeURIComponent(reviewId)}/release`, {}, 60000).catch((error) => {
    if (String(error.message || "").includes("already active")) {
      return { released: true, alreadyActive: true };
    }
    result.warnings.push(`release deferred for ${reviewId}: ${error.message}`);
    return { blocked: error.message };
  });
  return { approved, released };
}

async function createKnowledgeReview(spec) {
  await apiPost("/api/v1/review-items", {
    review_id: spec.review_id,
    item_type: spec.item_type,
    chapter_id: spec.chapter_id || chapters[0].chapter_id,
    scene_id: spec.scene_id || chapters[0].scenes[0].scene_id,
    status: "pending",
    candidate_text: spec.candidate_text,
    active_on_approve: 1,
    candidate_payload_json: spec.candidate_payload_json,
  }, 60000);
  const approval = await approveAndReleaseReviewItem(spec.review_id);
  return {
    reviewId: spec.review_id,
    itemType: spec.item_type,
    released: approval.released?.released === true || approval.approved?.released === true,
    approvedItemId: approval.approved?.approved_item_id || null,
  };
}

async function exerciseCharacterKnowledge(page) {
  await visit(page, "knowledge", "knowledge-console-view", "knowledge-character-currentdb");
  const specs = [
    {
      review_id: `review_currentdb_voice_shenwen_${runKey}`,
      item_type: "voice_card_candidate",
      candidate_text:
        "Voice profile for Shen Wen: restrained archive restorer, evidence-first observations, moral pressure shown through precise actions.",
      candidate_payload_json: {
        lineage_key: "VOICE_CHAR_SHENWEN",
        character_id: "CHAR_SHENWEN",
        text:
          "Shen Wen speaks in compact, measured sentences. He notices material evidence before naming fear, and delays confession until a choice has a cost.",
      },
    },
    {
      review_id: `review_currentdb_voice_xuzhao_${runKey}`,
      item_type: "voice_card_candidate",
      candidate_text:
        "Voice profile for Xu Zhao: acoustic engineer, skeptical and technical, uses measurements to hide anxiety.",
      candidate_payload_json: {
        lineage_key: "VOICE_CHAR_XUZHAO",
        character_id: "CHAR_XUZHAO",
        text:
          "Xu Zhao turns panic into measurements and dry technical comments. Trust appears when she risks the evidence chain for a living witness.",
      },
    },
    {
      review_id: `review_currentdb_voice_witness_${runKey}`,
      item_type: "voice_card_candidate",
      candidate_text: "Voice profile for the living witness: careful, fragmentary, protective of exact times and locations.",
      candidate_payload_json: {
        lineage_key: "VOICE_CHAR_WITNESS_A",
        character_id: "CHAR_WITNESS_A",
        text:
          "The witness speaks in cautious fragments, protecting names and locations while giving one exact sensory detail per answer.",
      },
    },
    {
      review_id: `review_currentdb_voice_guqing_${runKey}`,
      item_type: "voice_card_candidate",
      candidate_text: "Voice profile for Gu Qing: information broker, half ally half threat, prices everything before feeling anything.",
      candidate_payload_json: {
        lineage_key: "VOICE_CHAR_GUQING",
        character_id: "CHAR_GUQING",
        text:
          "Gu Qing speaks in offers and deadlines. Every sentence carries a price tag or an exit route; sincerity only leaks out in the last clause.",
      },
    },
    ...chapters.map((chapter, index) => ({
      review_id: `review_currentdb_calibration_${index + 1}_${runKey}`,
      item_type: "calibration_candidate",
      chapter_id: chapter.chapter_id,
      scene_id: chapter.scenes[0].scene_id,
      candidate_text:
        "Chapter calibration: clue first, explanation later, one visible choice cost at the end, and no source-book named transfer.",
      candidate_payload_json: {
        lineage_key: `CAL_CURRENTDB_${runKey}_${index + 1}`,
        scope: "chapter",
        scope_ref_id: chapter.chapter_id,
        text:
          "Reveal evidence before explanation; end the chapter with a visible choice cost or witness-protection consequence; avoid protected source names and recognizable bridges.",
      },
    })),
    {
      review_id: `review_currentdb_relation_shenwen_xuzhao_${runKey}`,
      item_type: "relation_card_candidate",
      candidate_text:
        "Relation profile: Shen Wen needs proof discipline; Xu Zhao needs speed. Trust grows when both protect a witness instead of winning the argument.",
      candidate_payload_json: {
        lineage_key: "REL_CHAR_SHENWEN_CHAR_XUZHAO",
        left_character_id: "CHAR_SHENWEN",
        right_character_id: "CHAR_XUZHAO",
        text:
          "Shen Wen and Xu Zhao argue over whether evidence or speed should lead. Their alliance becomes real when they accept a slower public truth to keep a witness alive.",
      },
    },
  ];
  const published = [];
  for (const spec of specs) {
    published.push(await createKnowledgeReview(spec));
  }
  await screenshot(page, "knowledge-character-cards-currentdb");
  recordExperience(
    "knowledge",
    8,
    "Character voice/relation cards make scene generation dependable, but the system should surface these as one-click preflight actions before a run starts.",
  );
  return { published };
}

async function exerciseKnowledgeAndIndex(page) {
  await visit(page, "knowledge", "knowledge-console-view", "knowledge-console-currentdb");
  const recovery = await apiPost("/api/v1/runtime/recovery/sweep", {}, 60000).catch((error) => ({ blocked: error.message }));
  const promotions = await apiPost("/api/v1/runtime/promotions/run-due", {}, 60000).catch((error) => ({ blocked: error.message }));
  await visit(page, "index", "index-console-view", "index-console-currentdb");
  recordExperience("knowledge", 7, "知识沉淀能承接审核候选，但普通作者需要更短的命名和作用域说明。");
  recordExperience("index", 7, "索引页对开发者透明，对写作者偏技术；恢复和发布收据有价值。");
  return { recovery, promotions };
}

async function exerciseSceneWorkbench(page) {
  await visit(page, "workbench", "scene-workbench-view", "scene-workbench-currentdb");
  const queue = page.getByTestId("scene-queue-item");
  if (await queue.count() !== plannedSceneList.length) {
    throw new Error(`scene queue must contain ${plannedSceneList.length} items before UI execution`);
  }
  let candidateReceipt;
  let archiveReceipt;
  let candidateSelections = 0;
  const requiredCandidateSelections = Math.min(3, plannedSceneList.length);
  const sceneReceipt = await observeUiPhase(page, "scene_execution", async (sceneUi) => {
    candidateReceipt = await observeUiPhase(page, "candidate_selection", async (candidateUi) => {
      archiveReceipt = await observeUiPhase(page, "archive", async (archiveUi) => {
        for (let index = 0; index < plannedSceneList.length; index += 1) {
          const planned = plannedSceneList[index];
          const sceneId = planned.scene_id;
          const startedAt = Date.now();
          await sceneUi.click(queue.nth(index));
          await page.getByTestId("scene-start").waitFor({ timeout: 30000 });

          const createJobResponse = page.waitForResponse((response) => (
            response.request().method() === "POST"
              && new RegExp(`/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs(?:\\?|$)`).test(response.url())
          ), { timeout: 30000 });
          await sceneUi.click(page.getByTestId("scene-start"));
          const started = await createJobResponse;
          if (!started.ok()) throw new Error(`${sceneId} UI run job creation failed: HTTP ${started.status()}`);

          // Recovery controls can coexist with a disabled archive button. Always
          // choose the actionable recovery before any terminal decision control.
          let decision = await waitForVisibleTestId(page, ["scene-budget-topup", "scene-create-cards", "scene-candidate-select", "scene-hard-rewrite", "scene-start", "scene-archive"], 360000);
          let recoveryActions = 0;
          let candidateHandled = false;
          let disabledArchiveObservations = 0;
          while (true) {
            if (decision === "scene-archive") {
              if (!await page.getByTestId("scene-archive").isDisabled()) break;
              disabledArchiveObservations += 1;
              if (disabledArchiveObservations >= 5) break;
              await sleep(1000);
              decision = await waitForVisibleTestId(page, ["scene-budget-topup", "scene-create-cards", "scene-candidate-select", "scene-hard-rewrite", "scene-start", "scene-archive"], 360000);
              continue;
            }
            disabledArchiveObservations = 0;
            if (["scene-create-cards", "scene-budget-topup", "scene-hard-rewrite", "scene-start"].includes(decision)) {
              recoveryActions += 1;
              if (recoveryActions > 16) throw new Error(`${sceneId} exceeded the UI recovery action limit`);
              const retryResponse = page.waitForResponse((response) => (
                response.request().method() === "POST"
                  && new RegExp(`/api/v1/scenes/${encodeURIComponent(sceneId)}/(?:run/jobs|resume-after-selection)(?:\\?|$)`).test(response.url())
              ), { timeout: 360000 }).then(response => ({ response }), error => ({ error }));
              let topupResponse = null;
              if (decision === "scene-budget-topup") {
                topupResponse = page.waitForResponse((response) => (
                  response.request().method() === "POST"
                    && new RegExp(`/api/v1/scenes/${encodeURIComponent(sceneId)}/budget/topup(?:\\?|$)`).test(response.url())
                ), { timeout: 30000 }).then(response => ({ response }), error => ({ error }));
              }
              try {
                await sceneUi.click(page.getByTestId(decision), { timeout: 5000 });
              } catch (error) {
                if (!/detached|Timeout/i.test(String(error && error.message))) throw error;
                decision = await waitForVisibleTestId(page, ["scene-budget-topup", "scene-create-cards", "scene-candidate-select", "scene-hard-rewrite", "scene-start", "scene-archive"], 360000);
                continue;
              }
              if (topupResponse) {
                const topupOutcome = await topupResponse;
                if (topupOutcome.error) throw topupOutcome.error;
                const toppedUp = topupOutcome.response;
                if (!toppedUp.ok()) throw new Error(`${sceneId} UI budget topup failed: HTTP ${toppedUp.status()}`);
              }
              const retryOutcome = await retryResponse;
              if (retryOutcome.error) throw retryOutcome.error;
              const retried = retryOutcome.response;
              if (!retried.ok()) throw new Error(`${sceneId} UI retry after ${decision} failed: HTTP ${retried.status()}`);
            } else if (decision === "scene-candidate-select") {
              if (candidateHandled) throw new Error(`${sceneId} exposed candidate selection twice without an explicit reopen`);
              const selectResponse = page.waitForResponse((response) => (
                response.request().method() === "POST"
                  && new RegExp(`/api/v1/scenes/${encodeURIComponent(sceneId)}/style-candidates/[^/]+/select(?:\\?|$)`).test(response.url())
              ), { timeout: 30000 });
              const resumeResponse = page.waitForResponse((response) => (
                response.request().method() === "POST"
                  && new RegExp(`/api/v1/scenes/${encodeURIComponent(sceneId)}/resume-after-selection(?:\\?|$)`).test(response.url())
              ), { timeout: 360000 });
              await candidateUi.click(page.getByTestId("scene-candidate-select").first());
              const [selected, resumed] = await Promise.all([selectResponse, resumeResponse]);
              if (!selected.ok() || !resumed.ok()) {
                throw new Error(`${sceneId} UI candidate selection/resume failed: ${selected.status()}/${resumed.status()}`);
              }
              candidateSelections += 1;
              candidateHandled = true;
              // HTTP response arrives before CandidatePicker finishes its
              // workbench hydrate + parent state update.  Wait for that stale
              // selected view to unmount before reading the next decision,
              // otherwise the transition frame looks like a second selection.
              await page.getByTestId("scene-candidate-select").first().waitFor({ state: "hidden", timeout: 30000 });
            } else {
              throw new Error(`${sceneId} exposed unsupported UI decision ${decision}`);
            }
            decision = await waitForVisibleTestId(page, ["scene-budget-topup", "scene-create-cards", "scene-candidate-select", "scene-hard-rewrite", "scene-start", "scene-archive"], 360000);
          }

          const archiveButton = page.getByTestId("scene-archive");
          if (await archiveButton.isDisabled()) {
            const blocked = await collectSceneOutput(sceneId);
            throw new Error(`${sceneId} UI archive is blocked: ${JSON.stringify(blocked.hardQc || blocked.humanReviewSummary || {})}`);
          }
          const archiveResponse = page.waitForResponse((response) => (
            response.request().method() === "POST"
              && new RegExp(`/api/v1/scenes/${encodeURIComponent(sceneId)}/adopt-current(?:\\?|$)`).test(response.url())
          ), { timeout: 60000 });
          // 起草台会在写作器已有正文时要求作者确认覆盖。C2 的操作者动作就是
          // “明确采纳”，因此在同一 UI 点击里显式接受该确认；不接受会被浏览器
          // 默认取消，随后等待 adopt-current 的证据会诚实超时。
          const acceptAdoptionDialog = (dialog) => dialog.accept();
          page.once("dialog", acceptAdoptionDialog);
          try {
            await archiveUi.click(archiveButton);
          } finally {
            page.removeListener("dialog", acceptAdoptionDialog);
          }
          const adopted = await archiveResponse;
          if (!adopted.ok()) throw new Error(`${sceneId} UI archive failed: HTTP ${adopted.status()}`);

          const output = await waitForArchivedSceneOutput(sceneId, 60000);
          finalScenes[sceneId] = {
            runJob: null,
            attemptNo: 1,
            durationMs: Date.now() - startedAt,
            tokens: tokensFromOutput(null, output),
            blockReason: null,
            ...output,
          };
          writeJson("final-scenes.json", finalScenes);
          await screenshot(page, `scene-ui-${String(index + 1).padStart(2, "0")}-${sceneId.toLowerCase()}`);
        }
      }, { minimums: { "adopt-current": plannedSceneList.length } });
    }, { minimums: {
      "candidate-select": requiredCandidateSelections,
      "selection-resume": requiredCandidateSelections,
    } });
  }, { minimums: { "run-job-create": plannedSceneList.length } });

  if (candidateSelections < requiredCandidateSelections) {
    throw new Error(
      `Northstar requires at least ${requiredCandidateSelections} UI candidate selections, got ${candidateSelections}`,
    );
  }
  recordUiPhase(sceneReceipt, `起草台逐场点击运行，浏览器创建 ${plannedSceneList.length} 个异步任务。`);
  recordUiPhase(candidateReceipt, `关键场景经匿名候选界面完成 ${candidateSelections} 次终选并续跑。`);
  recordUiPhase(archiveReceipt, `作者逐场点击采纳并归档，浏览器完成 ${plannedSceneList.length} 次 adopt-current。`);
  const blockedCount = result.sceneRunBlockers.length;
  recordExperience(
    "scene generation",
    blockedCount ? 6 : 8,
    blockedCount
      ? "界面暴露了需处理的真实阻断，未把有稿或任务结束冒充归档。"
      : `十五场全部经界面起草、${candidateSelections} 场匿名终选并由作者采纳归档。`,
  );
  return finalScenes;
}

async function waitForVisibleTestId(page, testIds, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const testId of testIds) {
      const locator = page.getByTestId(testId).first();
      const visible = await locator.count() && await locator.isVisible().catch(() => false);
      const enabled = testId === "scene-archive" || await locator.isEnabled().catch(() => false);
      if (visible && enabled) {
        await sleep(testId === "scene-start" ? 2500 : 150);
        if (await locator.isVisible().catch(() => false)
          && (testId === "scene-archive" || await locator.isEnabled().catch(() => false))) return testId;
      }
    }
    await sleep(1000);
  }
  throw new Error(`timed out waiting for UI decision: ${testIds.join(", ")}`);
}

async function waitForArchivedSceneOutput(sceneId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let latest = null;
  while (Date.now() < deadline) {
    latest = await collectSceneOutput(sceneId);
    if (latest.sceneStatus === "archived" && latest.finalRowId && latest.finalText.trim()) return latest;
    await sleep(1000);
  }
  throw new Error(`${sceneId} did not reach archived non-empty state after UI adoption: ${JSON.stringify(latest)}`);
}

function isContinuableSceneRunState(sceneStatus) {
  return new Set([
    "hard_qc_partial_rewrite_required",
    "hard_qc_full_rewrite_required",
    "near_final_revision_required",
  ]).has(String(sceneStatus || ""));
}

function isRetryableSceneRunBlocker(job, output) {
  const reason = retryableSceneRunReason(job, output);
  return /capacity|temporar|timeout|timed out|fetch failed|rate limit|retryable|connection|network/i.test(reason);
}

function retryableSceneRunReason(job, output) {
  const pieces = [
    job?.error_code,
    job?.error_text,
    output?.hardQc?.issues?.map((item) => `${item.issue_key || ""} ${item.message || ""}`).join("\n"),
    output?.softQc?.issues?.map((item) => `${item.issue_key || ""} ${item.message || ""}`).join("\n"),
    output?.nearFinalSummary?.findings?.map((item) => `${item.failure_class || ""} ${item.message || item.finding || ""}`).join("\n"),
  ];
  return pieces.filter(Boolean).join("\n");
}

async function pollSceneRunJob(jobId, sceneId, timeoutMs = 900000) {
  const started = Date.now();
  let latest = null;
  while (Date.now() - started < timeoutMs) {
    latest = await apiGet(`/api/v1/run-jobs/${encodeURIComponent(jobId)}`, 30000);
    appendLog({ type: "scene-job", sceneId, jobId, status: latest.status, phase: latest.current_step || null });
    if (terminalJobStatuses.has(latest.status)) {
      return latest;
    }
    await sleep(5000);
  }
  throw new Error(`timed out waiting for scene run job ${jobId} (${sceneId}); latest=${JSON.stringify(latest)}`);
}

async function collectSceneOutput(sceneId) {
  const payload = await apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/workbench`, 60000);
  return {
    sceneId,
    chapterId: payload.chapter_goal?.chapter_id || null,
    sceneStatus: payload.scene_run_state?.scene_status || null,
    bundleId: payload.bundle?.bundle_id || null,
    finalRowId: payload.final_scene?.row_id || payload.scene_run_state?.current_final_scene_row_id || null,
    finalText: payload.final_scene?.content || "",
    hardQc: payload.hard_qc_summary || null,
    softQc: payload.soft_qc_summary || null,
    nearFinalSummary: payload.near_final_summary || null,
    humanReviewSummary: payload.human_review_summary || null,
    rewriteCounters: payload.rewrite_counters || null,
    attempts: payload.attempts || [],
    source_safety_scan: payload.source_safety_scan || null,
    generationSummary: payload.generation_summary || null,
  };
}

async function exerciseChapterManuscripts(page) {
  await visit(page, "manuscripts", "chapter-manuscript-view", "chapter-manuscripts-currentdb");
  const aggregates = {};
  const rows = page.getByTestId("manuscript-chapter-item");
  if (await rows.count() !== chapters.length) throw new Error(`manuscript UI expected ${chapters.length} chapters`);
  const receipt = await observeUiPhase(page, "chapter_aggregation", async ({ click }) => {
    for (let index = 0; index < chapters.length; index += 1) {
      const chapter = chapters[index];
      await click(rows.nth(index));
      const aggregateResponse = page.waitForResponse((response) => (
        response.request().method() === "POST"
          && new RegExp(`/api/v1/chapters/${encodeURIComponent(chapter.chapter_id)}/runtime/aggregate/final(?:\\?|$)`).test(response.url())
      ), { timeout: 120000 });
      await click(page.getByTestId("chapter-aggregate"));
      const response = await aggregateResponse;
      if (!response.ok()) throw new Error(`${chapter.chapter_id} UI aggregate failed: HTTP ${response.status()}`);
      aggregates[chapter.chapter_id] = await apiGet(`/api/v1/chapter-manuscripts/${encodeURIComponent(chapter.chapter_id)}`);
      const aggregate = aggregates[chapter.chapter_id];
      if (aggregate?.completion_status !== "complete" || !aggregate?.assembled?.content?.trim()) {
        throw new Error(`${chapter.chapter_id} aggregate verification is incomplete`);
      }
    }
  }, { minimums: { "final-aggregate": chapters.length } });
  recordUiPhase(receipt, `成稿中心逐章点击生成/刷新汇总，浏览器完成 ${chapters.length} 次 final aggregate。`);
  recordExperience("manuscripts", 9, "五章汇总由成稿中心按钮触发，并以服务端 FinalScene 拼接结果只读复核。");
  await screenshot(page, "chapter-manuscripts-aggregate");
  return aggregates;
}

// Earlier first-blocker scene-run logic was removed; current runs collect blockers and continue across all three chapters.

async function exerciseQualityAndChapterSet(page) {
  await visit(page, "quality", "literary-quality-view", "literary-quality-currentdb");
  await clickIfPresent(page, "quality-tab-chapter-set");
  await screenshot(page, "literary-quality-chapter-set-panel");
  const review = await apiPost(
    "/api/v1/literary-quality/chapter-set-review",
    {
      chapter_ids: chapters.map((item) => item.chapter_id),
      text_layer: "runtime_final_scene",
      protected_terms: protectedTerms,
    },
    120000,
  );
  result.chapterSetReview = review;
  recordExperience("quality", review.reference_safety_findings?.length ? 6 : 8, "章组复审把单场景质量提升为跨章治理，适合发现重复意象和承诺未兑现。");
  return review;
}

async function exerciseDeepDeskAndLongform(page) {
  const sceneId = chapters[0].scenes[0].scene_id;
  const chapterId = chapters[0].chapter_id;
  await visit(page, "deepdesk", "writer-deep-desk", "writer-deep-desk-currentdb");
  const sceneReview = await apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/deep-review`, {}, 120000).catch((error) => ({
    blocked: error.message,
  }));
  const writerReview = await apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/writer-review/run`, {}, 120000).catch((error) => ({
    blocked: error.message,
  }));
  await visit(page, "longform", "longform-control-view", "longform-control-currentdb");
  const longform = await apiPost("/api/v1/longform-editor/diagnose", {}, 120000).catch((error) => ({ blocked: error.message }));
  recordExperience("deep edit", sceneReview.blocked ? 6 : 8, "深改台具备审稿视角，但长任务阻塞时需要显式列出可继续的人工动作。");
  recordExperience("longform", longform.blocked ? 6 : 8, "长篇控制适合追踪承诺兑现、伏笔债和参考安全，和章组复审形成互补。");
  return { chapterId, sceneId, sceneReview, writerReview, longform };
}

async function exerciseInterop(page) {
  await visit(page, "interop", "interop-center-view", "interop-center-currentdb");
  const firstSceneId = chapters[0].scenes[0].scene_id;
  const sourceScene = finalScenes[firstSceneId] || {};
  const worksheetBundleId = `bundle_currentdb_${runKey}`;
  const worksheet = `
bundle_id: ${worksheetBundleId}
scene_id: ${firstSceneId}
chapter_id: ${chapters[0].chapter_id}
hash_contract_version: BSHASH_v1
hash_alg: sha256
execution_mode: P1_scripted
created_by_action: currentdb_three_chapter_qa
snapshot:
  contract_version: BSHASH_v1
  stage_allowlist_name: bundle_build_allowlist_v1
  scene_id: ${firstSceneId}
  chapter_id: ${chapters[0].chapter_id}
  source_version_refs:
    chapter_goal: ${chapters[0].chapter_id}
    scene_card: ${firstSceneId}
  resolved_ref_ids:
    relation_ids: []
    world_rule_ids: []
    open_foreshadow_ids: []
  ordered_injections:
    - slot: chapter_goal
      ref_id: ${chapters[0].chapter_id}
      digest_key: chapter_goal
    - slot: scene_card
      ref_id: ${firstSceneId}
      digest_key: scene_card
  inline_digests:
    chapter_goal: glass rain at midnight records future disappearances
    scene_card: original near-future mystery with witness protection choice
`.trim();
  const previewData = await apiPost("/api/v1/interop/preview/bundle-worksheet", { worksheet_yaml: worksheet }, 30000).catch((error) => ({
    blocked: error.message,
  }));
  const importData = await apiPost("/api/v1/interop/import/bundle-worksheet", { worksheet_yaml: worksheet }, 30000).catch((error) => ({
    blocked: error.message,
  }));
  const exportBundleId = sourceScene.bundleId || importData.bundle?.bundle_id || worksheetBundleId;
  const exportData = await apiGet(`/api/v1/interop/export/bundle-worksheet/${encodeURIComponent(exportBundleId)}`, 30000).catch((error) => ({
    blocked: error.message,
  }));
  const replayData = sourceScene.finalRowId
    ? await apiGet(`/api/v1/replay/final-scene/${encodeURIComponent(sourceScene.finalRowId)}`, 30000).catch((error) => ({
        blocked: error.message,
      }))
    : null;
  await screenshot(page, "interop-center-roundtrip");
  recordExperience("interop", previewData.blocked ? 6 : 8, "导入导出对开发定位很有效，写作者只需要看到包络摘要和可回放成稿。");
  return {
    worksheetBundleId,
    previewStatus: previewData.hash_validation?.status || previewData.blocked || null,
    importedBundleId: importData.bundle?.bundle_id || null,
    exportedBundleId: exportData.bundle_id || exportBundleId,
    replayFinalRowId: sourceScene.finalRowId || null,
    replayEnvelopeBundleId: replayData?.bundle_id || null,
  };
}

async function exerciseTrash(page) {
  const chapterId = `CDBQA_TRASH_${runKey}`;
  const sceneId = `${chapterId}_SC01`;
  await apiPost("/api/v1/chapters", {
    chapter_id: chapterId,
    planned_scene_count: 1,
    mid_aggregate_enabled: 0,
    chapter_goal: "隔离测试章节：用于当前库 QA 回收站生命周期。",
    main_plot_push: "仅测试回收、恢复和清除，不进入原创三章。",
    emotional_target: "无",
    ending_effect: "无",
    must_not: "不得被三章生成引用。",
    notes: "current DB trash QA",
  });
  await apiPost("/api/v1/scenes", {
    scene_id: sceneId,
    chapter_id: chapterId,
    scene_seq: 1,
    scene_goal: "隔离测试场景：用于回收站生命周期。",
    beats_json: ["创建", "移入回收站", "恢复", "随章节清除"],
    onstage_chars_json: [],
    is_chapter_last: 1,
  });
  await apiPost("/api/v1/scenes/trash", { scene_ids: [sceneId], reason: "current DB QA trash scene lifecycle" });
  await visit(page, "trash", "author-trash-view", "author-trash-currentdb");
  await apiPost("/api/v1/scenes/restore", { scene_ids: [sceneId] });
  await apiPost("/api/v1/chapters/trash", { chapter_ids: [chapterId], reason: "current DB QA trash chapter lifecycle" });
  await apiPost("/api/v1/chapters/purge", { chapter_ids: [chapterId] });
  await screenshot(page, "author-trash-purged-currentdb");
  recordExperience("trash", 8, "回收站生命周期清楚，适合隔离测试，未污染三章主线。");
  return { chapterId, sceneId, purgedChapterId: chapterId };
}

function scanProtectedTerms(text) {
  const hits = protectedTerms
    .map((term) => ({ term, count: countOccurrences(text, term) }))
    .filter((item) => item.count > 0);
  return { safe: hits.length === 0, blocked_terms: hits };
}

function countOccurrences(text, term) {
  if (!term) {
    return 0;
  }
  let count = 0;
  let index = String(text || "").indexOf(term);
  while (index !== -1) {
    count += 1;
    index = String(text || "").indexOf(term, index + term.length);
  }
  return count;
}

function evaluateChapterScores() {
  result.chapterScores = {};
  result.protectedTermScan = {};
  for (const chapter of chapters) {
    const sceneOutputs = chapter.scenes.map((scene) => ({
      scene,
      output: finalScenes[scene.scene_id] || {},
    }));
    const allArchived = sceneOutputs.every(
      ({ output }) => output.sceneStatus === "archived" && output.finalRowId && (output.finalText || "").length > 0,
    );
    // Wave 0 实施项 4：空章节不得生成正常文学分数或"暂无明显风险"。
    // 旧实现对空文本仍给 scoreByTokens 保底 4 分、originality 9、sourceLeakRisk 10——
    // 空章节拿满分安全，正是"无稿但绿灯"的评分侧变体。无稿时只输出守卫标记。
    if (!allArchived) {
      result.chapterScores[chapter.chapter_id] = {
        no_draft: true,
        status_by_scene: Object.fromEntries(
          sceneOutputs.map(({ scene, output }) => [scene.scene_id, output.sceneStatus || "not_started"]),
        ),
        note: "无稿：章内存在未归档或空正文场景，不生成文学评分与来源安全结论。",
      };
      result.protectedTermScan[chapter.chapter_id] = {
        skipped: true,
        reason: "no archived final text; safety verdict withheld",
      };
      continue;
    }
    const finalText = sceneOutputs.map(({ output }) => output.finalText || "").join("\n");
    const safety = scanProtectedTerms(finalText);
    result.protectedTermScan[chapter.chapter_id] = safety;
    result.chapterScores[chapter.chapter_id] = {
      sceneIds: chapter.scenes.map((scene) => scene.scene_id),
      finalRowIds: sceneOutputs.map(({ output }) => output.finalRowId || null),
      status: "archived",
      characters: finalText.length,
      originality: safety.safe ? 9 : 4,
      conflictProgression: scoreByTokens(finalText, ["选择", "代价", "保护", "公开", "失踪", "反证"]),
      characterTension: scoreByTokens(finalText, ["沈闻", "许照", "证人", "不能", "必须", "风险"]),
      sceneCausality: scoreByTokens(finalText, ["因为", "所以", "发现", "反证", "决定", "记录"]),
      continuity: scoreByTokens(finalText, ["玻璃雨", "零点", "废线站", "真相", "证人"]),
      sourceLeakRisk: safety.safe ? 10 : 0,
      source_safety_scan: sceneOutputs.map(({ scene, output }) => ({
        scene_id: scene.scene_id,
        scan: output.source_safety_scan || null,
      })),
      leakTerms: safety.blocked_terms.map((item) => item.term),
      excerpt: preview(finalText, 360),
    };
  }
}

function tokensFromOutput(job, output) {
  return outcomeGateLib.tokensFromOutput(job, output);
}

function recordUiPhase(receipt, evidence) {
  if (!receipt || receipt.lane !== "ui" || !receipt.phase) {
    throw new Error("Northstar phase cannot be recorded without a validated UI receipt");
  }
  northstarPhases[receipt.phase] = {
    ...receipt,
    evidence,
  };
}

// Wave 0 结果门禁：唯一权威判定在 scripts/playwright_audit_summary.py（pytest 全覆盖）；
// outcome 结构组装与判定器调用在 scripts/lib/qa-outcome-gate.cjs（两个 harness 共用）。
// 判定器不可执行时按失败处理，不得视为通过。
function runOutcomeGate() {
  return outcomeGateLib.runOutcomeGate({
    repoRoot,
    outDir,
    pythonExecutable,
    result,
    chapters,
    finalScenes,
    expectedChapterCount,
    expectedScenesPerChapter,
    northstarPhases,
    writeJson,
    appendLog,
  });
}

function scoreByTokens(text, tokens) {
  const found = tokens.filter((token) => String(text || "").includes(token)).length;
  return Math.max(4, Math.min(10, 4 + found));
}

function recordExperience(name, score, note) {
  result.writerExperience[name] = {
    score,
    note,
    friction: score >= 8 ? "low" : score >= 6 ? "medium" : "high",
    trust: score >= 8 ? "high" : score >= 6 ? "medium" : "low",
  };
}

function deriveCurrentRunBlockerFindings() {
  const blockers = [];
  for (const stepItem of result.steps) {
    if (!stepItem.ok) {
      blockers.push({
        source: "step",
        name: stepItem.name,
        code: stepItem.code || null,
        evidence: preview(stepItem.error, 420),
      });
    }
  }
  for (const chapter of chapters) {
    for (const scene of chapter.scenes) {
      const output = finalScenes[scene.scene_id] || {};
      const sceneStatus = output.sceneStatus || "not_started";
      if (sceneStatus === "archived" && output.finalRowId && (output.finalText || "").length > 0) {
        continue;
      }
      const hardQc = output.hardQc || output.runJob?.result_summary?.latest_qc || null;
      const issueKeys = issueKeysFromQc(hardQc);
      blockers.push({
        source: "scene",
        chapterId: chapter.chapter_id,
        sceneId: scene.scene_id,
        sceneStatus,
        finalRowId: output.finalRowId || null,
        jobStatus: output.runJob?.status || null,
        jobErrorCode: output.runJob?.error_code || null,
        jobErrorText: preview(output.runJob?.error_text, 360),
        primaryIssueKey: hardQc?.primary_issue_key || issueKeys[0] || null,
        issueKeys,
        nextAction:
          output.nearFinalSummary?.failure_class ||
          output.nearFinalSummary?.revision_candidate_id ||
          hardQc?.next_action ||
          output.runJob?.result_summary?.next_action ||
          "inspect current scene blocker",
      });
    }
  }
  result.currentRunBlockers = blockers;
  return blockers;
}

function issueKeysFromQc(qcSummary) {
  const explicit = Array.isArray(qcSummary?.issue_keys) ? qcSummary.issue_keys.filter(Boolean) : [];
  const fromIssues = (qcSummary?.issues || [])
    .map((item) => item?.issue_key || item?.dimension || item?.code || null)
    .filter(Boolean);
  return Array.from(new Set([...explicit, ...fromIssues].map(String)));
}

function fillRootCauseFindings() {
  const chapterSetSafety = result.chapterSetReview?.reference_safety_findings || [];
  const currentRunBlockers = deriveCurrentRunBlockerFindings();
  result.rootCauseFindings = [
    {
      issue: "三章生成的文学质感上限仍受当前模型输出能力影响",
      classification: "model-quality",
      rootCause: "比喻新鲜度、人物潜台词和段落节奏主要由生成模型决定，系统只能通过约束和复审降低偏差。",
      evidence: "chapterScores 记录 originality、conflictProgression、characterTension 和人工备注槽。",
      resolution: "保留为模型质量观察，不把审美不足误判为系统故障。",
    },
    {
      issue: "参考学习可能把抽象借鉴滑向专名或标志意象复用",
      classification: "system-design",
      rootCause: "参考 profile 和最终成稿如果不带独立安全检查，用户难以确认只学技法。",
      evidence: `referenceCloudPolicy=${referenceCloudPolicy}; protectedTermScan=${JSON.stringify(result.protectedTermScan)}`,
      resolution: "新增 profile 结构化安全字段、章组复审 reference_safety_findings，并由 runner 进行保护词扫描。",
    },
    {
      issue: "单场景质检无法发现跨章承诺未兑现和重复模式",
      classification: "workflow",
      rootCause: "质量治理缺少 chapter-set 粒度，三章故事的揭示、回收和重复意象散落在多个页面。",
      evidence: `chapterSetReview repeated_patterns=${JSON.stringify((result.chapterSetReview?.repeated_patterns || []).slice(0, 5))}`,
      resolution: "新增 /api/v1/literary-quality/chapter-set-review，并在文学质量 UI 暴露章组复审面板。",
    },
    {
      issue: "长任务进度不透明会降低写作者信任",
      classification: "UI/automation",
      rootCause: "参考学习、场景运行和审核发布需要展示阻塞、下一步和 job 状态，而不是只等待按钮恢复。",
      evidence: `requestFailures=${result.requestFailures.length}; warnings=${result.warnings.length}`,
      resolution: "runner 记录 run-job 轮询、learning-tree、screenshots、warnings，并要求 UI 面板展示 long task/next action。",
    },
    {
      issue: "上下文预算如果不区分任务，容易在硬质检时保留风格而牺牲事实",
      classification: "prompt/context",
      rootCause: "起草、硬质检和章组复审对上下文保留优先级不同。",
      evidence: "context budget now carries task_kind policies: drafting, hard_qc, chapter_review.",
      resolution: "实现 task-aware context budgeting，起草保留风格校准，硬质检保留事实约束，章组复审保留承诺兑现和记忆。",
    },
  ];
  result.rootCauseFindings.push({
    issue: "New original character scenes can fail late when voice/relation knowledge cards are missing",
    classification: "system-design/workflow",
    rootCause:
      "Scene cards can save a POV and two onstage character IDs before the active VOICE_/REL_ cards exist; without preflight gating this turns into a bundle-stage job failure.",
    evidence: "Current DB QA exposed BUNDLE_SOURCE_MISSING for VOICE_CHAR_SHENWEN before character cards were seeded.",
    resolution:
      "Run jobs now preserve preflight blockers in job state; this runner also creates minimal voice/relation cards through review approval before scene generation.",
  });
  result.rootCauseFindings.push({
    issue: "Old global calibration can contaminate a new current-DB project",
    classification: "system-design/context",
    rootCause:
      "Current DB keeps active global calibration rows from earlier QA; hard QC treated an unrelated old calibration phrase as mandatory for the new story.",
    evidence: "A previous run was blocked by missing_calibration_line for an unrelated gate calibration.",
    resolution:
      "Scoped chapter/scene calibration now overrides global calibration; the runner also verifies and releases a chapter-scoped calibration for this story.",
  });
  result.rootCauseFindings.push({
    issue: "Model repeatedly missed externally visible choice machinery under hard QC and near-final gates",
    classification: "model-quality/prompt-workflow",
    rootCause:
      "Even after the scene card spelled out concrete actions and costs, the model alternated between summary-heavy drafts and missing relationship-turn details.",
    evidence: currentRunBlockers.length
      ? JSON.stringify(currentRunBlockers.slice(0, 3))
      : "No current scene blocker was observed in this run; keep this as a model-quality risk category for future hard-QC failures.",
    resolution:
      "The runner now treats partial/near-final revision states as continuable, but the remaining blocker should be handled by human review or a stronger deterministic rewrite plan.",
  });
  if (currentRunBlockers.length) {
    result.rootCauseFindings.push({
      issue: "Current run has unresolved blocker evidence",
      classification: "system-design/prompt-workflow/model-quality",
      rootCause:
        "The QA report must separate current operational blockers from historical observations so the writer can see whether to retry, edit, approve, or change inputs.",
      evidence: JSON.stringify(currentRunBlockers.slice(0, 5)),
      resolution:
        "Persist currentRunBlockers with step/job status, issue keys, evidence preview and next action; only classify system-side issues for deterministic fixes.",
    });
  }
  if (chapterSetSafety.length) {
    result.rootCauseFindings.push({
      issue: "生成文本命中受保护参考词",
      classification: "system-design",
      rootCause: "最终文本安全扫描命中，不应进入无提示归档。",
      evidence: JSON.stringify(chapterSetSafety),
      resolution: "进入 deepdesk 修订或人工复核，清除命中词后重跑章组复审。",
    });
  }
  result.systemFixes = [
    {
      fix: "current-DB Playwright QA runner",
      status: "implemented",
      verification: "writes qa-live-results.json, final-scenes.json, report.md and screenshots under timestamped currentdb-three-chapter-qa output.",
    },
    {
      fix: "reference profile structured craft and safety payload",
      status: "implemented",
      verification: "profile JSON may include craft_metrics, applicability, anti_copy_rules, evidence_safety_summary without migration.",
    },
    {
      fix: "chapter-set literary quality endpoint",
      status: "implemented",
      verification: "POST /api/v1/literary-quality/chapter-set-review returns cross-chapter scores, repeated patterns, payoff checks and safety findings.",
    },
    {
      fix: "task-aware context budgeting",
      status: "implemented",
      verification: "apply_context_budget accepts task_kind for drafting, hard_qc and chapter_review preservation policy.",
    },
    {
      fix: "scene run job preflight blocker exposure",
      status: "implemented",
      verification: "blocked preflight now returns a blocked run job with error_code, next_action and run_preflight instead of failing later in bundle build.",
    },
    {
      fix: "current-DB original character knowledge seeding",
      status: "implemented",
      verification: "runner creates active VOICE_/REL_ cards through review approval before starting original scene jobs.",
    },
    {
      fix: "scoped calibration isolation for current DB",
      status: "implemented",
      verification: "chapter/scene calibration lines override unrelated global calibration lines during bundle build.",
    },
    {
      fix: "retryable API and scene-job continuation",
      status: "implemented",
      verification: "runner retries DATABASE_BUSY/provider-capacity failures and continues hard/near-final revision branches up to SCENE_JOB_ATTEMPTS.",
    },
    {
      fix: "more executable three-chapter scene cards",
      status: "implemented",
      verification: "scene briefs now spell out visible choices, paid costs and ending actions instead of relying on abstract moral pressure.",
    },
    {
      fix: "Literary Quality UI chapter-set panel",
      status: "implemented",
      verification: "quality-tab-chapter-set exposes chapter ID input, scores, repeated patterns and reference safety.",
    },
  ];
}

function buildReport() {
  const stepRows = result.steps
    .map((item) => `| ${item.ok ? "通过" : "阻塞"} | ${item.name} | ${Math.round(item.ms / 1000)} | ${item.ok ? "完成" : preview(item.error, 140)} |`)
    .join("\n");
  const experienceRows = Object.entries(result.writerExperience)
    .map(([name, item]) => `| ${name} | ${item.score}/10 | ${item.friction} | ${item.trust} | ${item.note} |`)
    .join("\n");
  const chapterSections = chapters
    .map((chapter) => {
      const score = result.chapterScores[chapter.chapter_id] || {};
      const sceneLines = chapter.scenes
        .map((scene) => {
          const output = finalScenes[scene.scene_id] || {};
          return `- ${scene.scene_id}：状态 ${output.sceneStatus || "not_started"}，最终行 ${output.finalRowId || "未生成"}，字数 ${(output.finalText || "").length}，tokens ${output.tokens ?? "-"}，耗时 ${output.durationMs != null ? Math.round(output.durationMs / 1000) + "s" : "-"}，重试 ${output.attemptNo ?? 0}${output.blockReason ? `，阻断 ${preview(output.blockReason, 120)}` : ""}`;
        })
        .join("\n");
      const scoreLine = score.no_draft
        ? `- 评分：无稿——不生成文学评分与来源安全结论（${score.note || "no draft"}）`
        : `- 评分：原创性 ${score.originality || 0}/10，冲突推进 ${score.conflictProgression || 0}/10，人物张力 ${score.characterTension || 0}/10，场景因果 ${score.sceneCausality || 0}/10，连续性 ${score.continuity || 0}/10，源书泄漏风险控制 ${score.sourceLeakRisk || 0}/10
- source_safety_scan：${JSON.stringify(score.source_safety_scan || null)}
- 摘录：${score.excerpt || ""}`;
      return `### ${chapter.chapter_id}（${chapter.scenes.length} 场）
${sceneLines}
- 章字数：${score.characters || 0}
${scoreLine}
`;
    })
    .join("\n");
  const rootCauseRows = result.rootCauseFindings
    .map((item) => `| ${item.issue} | ${item.classification} | ${item.rootCause} | ${item.resolution} |`)
    .join("\n");
  const llmCoverageRows =
    (result.llmRouteCoverage?.matrix || [])
      .filter((item) => item.requires_llm)
      .map((item) => `| ${item.node_id} | ${item.group} | ${item.configured ? "yes" : "no"} | ${item.ready ? "yes" : "no"} | ${item.provider_id || "-"} | ${item.model || "-"} | ${item.readiness_reason || "-"} |`)
      .join("\n") || "| - | - | - | - | - | - | - |";
  const fallbackRows =
    (result.llmFallbackAudit?.offline_deterministic_required_calls || [])
      .map((item) => `| ${item.llm_call_id} | ${item.node_id} | ${item.step || "-"} | ${item.scene_id || "-"} | ${item.chapter_id || "-"} |`)
      .join("\n") || "| - | clean | - | - | - |";
  const fixRows = result.systemFixes.map((item) => `| ${item.fix} | ${item.status} | ${item.verification} |`).join("\n");
  const screenshots = result.screenshots.map((item) => `- ${item}`).join("\n") || "- 无截图";
  const layoutFindings =
    result.layoutFindings
      .map((item) => `| ${item.screenshot} | ${item.type} | ${item.target || "-"} | ${preview(item.detail, 120)} |`)
      .join("\n") || "| - | clean | - | 未发现布局巡检问题 |";
  const gate = result.outcomeGate;
  const gateBlock = gate
    ? `## 结果门禁（唯一权威判定）

- 判定：**${gate.passed ? "通过" : "失败"}**${gate.error ? `（${gate.error}）` : ""}
- 详情：outcome-gate-verdict.md（每场归档/字数/token/耗时/阻断明细）
- 语义：${expectedChapterCount} 章 × ${expectedScenesPerChapter} 场全部存在非空后端归档正文才算成稿成功；步骤表只是诊断证据，不构成成稿判定。
- 通道要求：北极星六阶段（雪花规划/物化/场景执行/候选终选/归档/章节聚合）必须全部由浏览器交互触发并携带 UI 网络回执；任一阶段缺回执即整轮失败。`
    : `## 结果门禁（唯一权威判定）

- 判定：**失败**（门禁未执行——运行提前中止或判定器不可用；门禁未执行不得视为通过）`;
  return `# Current-DB 五章小说结果闭环 QA 报告（${expectedChapterCount} 章 × ${expectedScenesPerChapter} 场）

生成时间：${new Date().toISOString()}

${gateBlock}

## 环境
- 当前库：${resetAuthorState ? "是，运行前重置作者态" : "是，不 reset"}
- 作者态重置：${resetAuthorState ? "是，已执行迁移检查、dry-run 和 --execute reset" : "否"}
- 服务托管：${manageDevServices ? "runner 已 stop/start 本地前后端并刷新 .codex-run URL" : "外部已启动或手动管理"}
- 故事种子：${storySeed}
- 前端：${frontendUrl}
- 后端：${apiBase}
- 操作者：${operatorRef}
- 参考书：${referencePath}
- 参考策略：${referenceCloudPolicy}
- 输出目录：${outDir}
- 脏工作树：${preview(result.meta.preflight?.gitStatus || "clean", 500)}

## 步骤证据（仅诊断，不构成成稿判定）
| 结果 | 步骤 | 耗时秒 | 备注 |
| --- | --- | ---: | --- |
${stepRows}

## 资深创作者体验审查
| 功能页/链路 | 评分 | 摩擦 | 信任 | 观察 |
| --- | ---: | --- | --- | --- |
${experienceRows}

## 各章创作结果
${chapterSections}

## 章组质量与参考安全
- 章组复审：${JSON.stringify(result.chapterSetReview || null)}
- 保护词扫描：${JSON.stringify(result.protectedTermScan)}
- 报告不保存参考书长摘录；只记录抽象 profile 键、学习树摘要、生成结果摘录与安全扫描。

## LLM route coverage and local fallback audit
- Missing active routes: ${JSON.stringify(result.llmRouteCoverage?.missing_active_routes || [])}
- Blocked routes: ${JSON.stringify(result.llmRouteCoverage?.blocked_routes || [])}

| Node | Group | Configured | Ready | Provider | Model | Reason |
| --- | --- | --- | --- | --- | --- | --- |
${llmCoverageRows}

| LLM call | Node | Step | Scene | Chapter |
| --- | --- | --- | --- | --- |
${fallbackRows}

## 开发根因与修复
| Issue | Classification | Root cause | Resolution |
| --- | --- | --- | --- |
${rootCauseRows}

| 修复 | 状态 | 验证 |
| --- | --- | --- |
${fixRows}

## 布局巡检
| 截图 | 类型 | 目标 | 详情 |
| --- | --- | --- | --- |
${layoutFindings}

## 截图与日志
${screenshots}
- ${path.relative(repoRoot, logPath).replace(/\\/g, "/")}

## 残余风险
- 真实模型质量、供应商响应和人工审核状态会影响三章能否一次归档；本脚本记录真实 blocker，不伪造成功。
- 当前库保留 QA 章节、参考 profile、审核项和运行日志；ID 已带时间戳避免碰撞。
`;
}

function buildSnowflakeImportPlan(chapterPlan) {
  const characterSheets = [
    {
      character_id: "CHAR_SHENWEN", display_name: "沈闻", role: "主角",
      goal: "在零点前找出失踪名单的改写入口并保护仍活着的证人。",
      ambition: "让档案不再替权力决定谁可以被忘记。", values: ["真相", "证人安全"],
      conflict: "公开越快越接近真相，却会把证人暴露给仍掌握名单写权的人。",
      epiphany: "真正的负责不是抢先公开，而是让活人能承受真相落地的代价。",
      one_sentence_summary: "修复员以自己的名字作饵，阻止零点名单继续吞掉证人。",
      one_paragraph_summary: "沈闻先相信完整公开就能终止失踪，但每一条证据都会抬高证人的风险；他被迫分阶段交付真相，最终拒绝接过名单写权。",
    },
    {
      character_id: "CHAR_XUZHAO", display_name: "许照", role: "盟友",
      goal: "用可验证的调度缺口帮助沈闻拿到原始带，同时阻止他成为新的篡改者。",
      ambition: "证明技术可以保护普通人，而不是只替系统提速。", values: ["可验证", "不越线"],
      conflict: "他追求快速证伪，却必须一次次为证人安全压住效率冲动。",
      epiphany: "最重要的技术决定有时是拒绝按下那个看似能立刻解决问题的按钮。",
      one_sentence_summary: "许照用调度证据守住行动底线。",
      one_paragraph_summary: "许照从只相信效率的技术员，变成能在关键时刻拦住沈闻签下最后一次篡改的人。",
    },
    {
      character_id: "CHAR_GUQING", display_name: "顾磬", role: "对手与镜像",
      goal: "迫使沈闻理解名单是一套接力制度，并诱导他接过下一班写权。",
      ambition: "让名单系统继续以秩序之名运转。", values: ["秩序", "可控牺牲"],
      conflict: "他能控制信息节奏，却无法控制沈闻与许照拒绝成为接班人的选择。",
      epiphany: "他始终拒绝承认任何个体都不该被制度当作可计算损耗。",
      one_sentence_summary: "顾磬用真相的一部分换取新接班人。",
      one_paragraph_summary: "顾磬不断递出半真半假的路线，让沈闻靠近源头，却在终局发现两人宁愿承受失败也不接过名单写权。",
    },
  ];
  const shortParagraphs = chapterPlan.map((chapter, index) => (
    `第${index + 1}章《${chapter.chapter_goal}》把线索推进到下一层，但每一次发现都抬高证人、盟友或主角本人的代价；${chapter.ending_effect}`
  ));
  const outlineParagraphs = [
    chapterPlan.slice(0, 2).map((chapter, index) => `${String(index + 1).padStart(2, "0")} ${chapter.chapter_goal.slice(0, 18)}：${chapter.main_plot_push || chapter.chapter_goal}`).join("\n"),
    chapterPlan.slice(2, 4).map((chapter, index) => `${String(index + 3).padStart(2, "0")} ${chapter.chapter_goal.slice(0, 18)}：${chapter.main_plot_push || chapter.chapter_goal}`).join("\n"),
    chapterPlan.slice(4).map((chapter, index) => `${String(index + 5).padStart(2, "0")} ${chapter.chapter_goal.slice(0, 18)}：${chapter.main_plot_push || chapter.chapter_goal}`).join("\n"),
    "五章因果链从名单异动推进到广播源头，最终用拒绝接班完成主题反转。",
  ];
  const sceneRows = chapterPlan.flatMap((chapter, chapterIndex) => chapter.scenes.map((scene, sceneIndex) => {
    const rowUid = `qa_${scene.scene_id.toLowerCase()}`;
    const pressure = scene.writer_brief_json?.scene_pressure || "证据正在被倒计时销毁，任何迟疑都会让证人承担不可逆风险。";
    const title = `第${chapterIndex + 1}章·场${sceneIndex + 1} ${scene.location || "零点档案站"}`;
    return {
      row_uid: rowUid,
      scene_id: scene.scene_id,
      chapter_id: chapter.chapter_id,
      chapter_title: chapter.chapter_goal.slice(0, 24),
      chapter_goal: chapter.chapter_goal,
      scene_seq: scene.scene_seq,
      pov_character_id: scene.pov_character_id || "CHAR_SHENWEN",
      title,
      summary: scene.scene_goal,
      primary_form: "proactive",
      scene_type: "proactive",
      chapter_role: `${chapter.main_plot_push || chapter.chapter_goal}；本场必须改变下一场的目标与风险。`,
      location: scene.location || "零点档案站",
      crucible: `${pressure}；人物被倒计时、证人安全和不可逆公开风险同时困住，不能退出。`,
      scene_crucible: `${pressure}；人物被倒计时、证人安全和不可逆公开风险同时困住，不能退出。`,
      goal: `${scene.scene_goal}；结果必须在页面上可见并能明确判断是否达成。`,
      conflict: `${pressure}；阻力第一次封锁证据，第二次转而威胁证人，第三次又用更高且不可逆的代价彻底逼迫主角改变行动方案。`,
      setback: `${scene.exit_change || scene.hook || "线索改变了下一场目标"}；即使暂时成功，也必须失去时间、信任或安全窗口这一具体代价。`,
      cost_requirement: "主角每次推进都要消耗证人信任、暴露安全窗口，或永久关闭一种更轻松的选择。",
      target_length_band: scene.target_length_band || "short",
      must_include_text: scene.must_include_text || "必须兑现本场因果转折。",
      exit_change: scene.exit_change || "本场结果迫使下一场改换目标。",
      hook: scene.hook || "新的风险在场末显形。",
      beats_json: scene.beats_json || [],
      writer_brief_json: scene.writer_brief_json || {},
    };
  }));

  const bibles = characterSheets.map((character) => ({
    character_id: character.character_id,
    display_name: character.display_name,
    role: character.role,
    physical_profile: { age: "三十岁上下", height: "普通", appearance: "长时间接触旧档案，指腹留有细小纸痕", style: "克制实用" },
    personality_profile: { strongest_trait: "在压力下仍追问证据", weakest_trait: "容易把责任全部揽到自己身上", humor: "干涩", preferences: ["可验证的事实"] },
    environment_profile: { home: "南岸城旧档案区", family_background: "与旧案有未解关联", education: "档案与信息技术", work: "档案修复与调查", relationships: "与同盟既互信又互相守住底线" },
    psychological_profile: { best_memory: "第一次修复出完整名字", worst_memory: "没能及时保护证人", deepest_fear: "自己成为新的名单书写者", greatest_hope: "普通人重新拥有自己的明天", philosophy: "真相必须以活人能承受的方式落地", self_image: "证据守门人", public_image: "冷静的修复员", character_arc: character.epiphany },
  }));

  return {
    schema: "snowflake-canonical-plan-v1",
    steps: {
      book_brief: {
        category: "都市悬疑长篇", target_reader: "喜欢硬线索、道德选择与连续因果升级的成年悬疑读者",
        story_kind: "档案修复员追查零点失踪名单，但每次公开都会把证人推向更高风险的原创都市悬疑",
        delight_reason: "线索越接近源头，保护证人与公开真相的冲突和代价越不可逆",
        genre_promise: "五章持续交付可验证线索、压力升级、选择代价与非超自然收束",
        expected_reader_emotion: "持续压迫、逼近真相的拉力，以及角色拒绝免费选择后的释然",
        safety_rules: ["纯原创基准，不使用参考书", "不得复制受保护人物、设定、桥段或标志性句式"],
      },
      one_sentence_summary: { summary: "档案修复员必须在零点前终止会改写失踪名单的接力网络，却发现每次公开真相都可能失去证人。" },
      one_paragraph_summary: {
        sentences: [
          "沈闻发现失踪名单会在零点被改写，必须找到仍活着的证人。",
          "第一场灾难逼他承认证据公开会暴露证人，他失去一次完整公开的机会。",
          "第二场灾难让伪造签名落到自己头上，盟友也可能因风险退出。",
          "第三场灾难把沈闻写进下一张名单，逼他用自己作饵直取广播源头。",
          "他最终拒绝接过写权，以分阶段公开让名单终止，却为这场胜利付出永久嫌疑的代价。",
        ],
        moral_premise: "真相不是免费公开的战利品；负责意味着让活人能承受它落地的代价。",
      },
      character_sheets: { characters: characterSheets },
      short_synopsis: { paragraphs: shortParagraphs },
      character_synopses: { characters: characterSheets.map((character) => ({ character_id: character.character_id, display_name: character.display_name, role: character.role, synopsis: `${character.one_paragraph_summary} 旧伤迫使其追求目标，却也制造与同盟的冲突；最终变化是：${character.epiphany}` })) },
      long_synopsis: { paragraphs: outlineParagraphs.map((paragraph, index) => `${paragraph}\n第${index + 1}阶段的压力继续升级，角色每次选择都失去时间、信任或安全窗口，不能无代价回退。`) },
      character_bibles: { characters: bibles },
      scene_list: { scenes: sceneRows.map(({ goal, conflict, setback, scene_crucible, cost_requirement, target_length_band, must_include_text, exit_change, hook, beats_json, writer_brief_json, title, ...row }) => row) },
      scene_details: { scenes: sceneRows },
    },
  };
}

function buildChapters(suffix) {
  const prefix = `CDBQA_${suffix}`;
  const forbidden = "不得照搬参考书原句、专名、人物、学院组织、血统体系、屠龙或标志性桥段。";
  return [
    {
      chapter_id: `${prefix}_01`,
      planned_scene_count: 3,
      chapter_goal: "第一章：零点玻璃雨落在未来失踪名单上，城市档案修复师沈闻发现记录并非预言，而是有人提前写入的失踪顺序。",
      main_plot_push: "建立玻璃雨、零点广播、未来失踪名单三者因果，逼沈闻从旁观修复者变成证人保护者。",
      emotional_target: "沈闻从职业冷静被迫转入道德焦虑：若公开名单，可能加速名单上的人消失。",
      ending_effect: "他找到名单第一个还活着的人，却发现对方已经收到明天零点的玻璃雨碎片。",
      must_not: "不得出现参考书专名、人物、学院、龙血、屠龙、龙王或可识别桥段；只允许抽象节奏参考。",
      notes: `${storySeed} current DB QA 第一章，原创近未来悬疑奇想。`,
      writer_brief_json: {
        audience_contract: "近未来悬疑奇想，冷静物证推进，不用热血战斗桥段。",
        voice: "克制、精确、带一点城市异象的冷光。",
        must_deliver: ["零点玻璃雨", "未来失踪记录", "保护证人的选择雏形"],
        avoid: protectedTerms,
      },
      scenes: [
        {
          scene_id: `${prefix}_01_SC01`,
          scene_seq: 1,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN"],
          location: "近未来南岸城零点档案站",
          scene_goal: "沈闻在例行修复中发现零点玻璃雨档案里出现未来日期的失踪名单，反查后确认失踪顺序早于事件本身被写入。",
          beats_json: [
            "零点玻璃雨停在站顶",
            "档案屏出现未来日期",
            "沈闻按修复流程做完整性校验",
            "反查失踪顺序发现写入时间异常",
            "名单日期比当前时间晚三小时"
          ],
          must_include_text: "玻璃雨在零点停住；名单日期比当前时间晚三小时；沈闻必须先按职业流程校验再承认异常；写入时间早于失踪事件本身。",
          forbidden_text: forbidden,
          exit_change: "沈闻从把异常当故障处理，转为确认有人提前写入失踪顺序。",
          hook: "名单不是预测，是排期。",
          target_length_band: "short",
          scene_type: "inciting_clue",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "职业流程要求上报公开，直觉告诉他公开会加速失踪。",
            texture: "玻璃、站厅回声、雨停在半空的静电感。",
            choice_under_pressure: "按流程上报存档，或暂缓上报私自反查写入源。",
            power_shift: "沈闻从流水线修复员变成唯一知情人。",
            new_information: "失踪名单的写入时间早于失踪事件。",
            emotional_turn: "技术性好奇转为后颈发凉的道德警觉。",
            image_anchor: "停在半空的玻璃雨。",
            reader_aftertaste: "未来并非预言，而是有人提前安排的名单。",
          },
        },
        {
          scene_id: `${prefix}_01_SC02`,
          scene_seq: 2,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "零点档案站主控台",
          scene_goal: "许照发现沈闻私自反查并拦阻他冲动公开，沈闻在公开倒计时内拔掉通讯线保护名单第一人，被系统标记为篡改嫌疑人。",
          beats_json: [
            "许照发现主控台未授权查询",
            "屏幕倒影里许照下颌收紧",
            "两人争执公开还是暂缓",
            "公开倒计时启动",
            "沈闻拔掉通讯线阻止公开",
            "系统把沈闻标记为篡改嫌疑人"
          ],
          must_include_text: "许照的神态变化必须出现在屏幕倒影里；沈闻必须拔掉通讯线阻止名单公开；系统必须把沈闻标记为篡改嫌疑人。",
          forbidden_text: forbidden,
          exit_change: "沈闻从旁观修复者变成握有危险证据的嫌疑人，许照从质疑者变成半个知情人。",
          hook: "篡改嫌疑人的标记落在唯一想保护名单的人头上。",
          target_length_band: "short",
          scene_type: "pressure_choice",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "公开倒计时逼沈闻在暴露证人与保住职业身份之间二选一。",
            texture: "主控台冷光、倒计时蜂鸣、通讯线断开的脆响。",
            choice_under_pressure: "拔线保护第一个活人，或保留联网公开证据。",
            power_shift: "许照从质疑者变成拦住他冲动公开的人。",
            new_information: "名单第一人仍活着并已被系统锁定位置。",
            emotional_turn: "沈闻意识到自己正在决定一个活人的风险。",
            image_anchor: "被拔断的通讯线在桌沿晃。",
            reader_aftertaste: "保护证人的代价是自己先成为嫌疑人。",
          },
        },
        {
          scene_id: `${prefix}_01_SC03`,
          scene_seq: 3,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO", "CHAR_WITNESS_A"],
          location: "零点档案站候车厅",
          scene_goal: "名单第一人林晚推门进站，伞面嵌着明天才会落下的玻璃雨碎片，沈闻决定先于系统找到并保护证人。",
          beats_json: [
            "候车厅广播报出零点整",
            "名单第一人推门进站",
            "伞面上嵌着明天的玻璃雨碎片",
            "林晚只肯给出一个精确时间",
            "沈闻决定先于系统保护证人"
          ],
          must_include_text: "名单第一人必须带着明天玻璃雨碎片进站；证人说话谨慎零碎、每次只给一个精确细节；沈闻必须当场决定保护证人而非上报。",
          forbidden_text: forbidden,
          exit_change: "沈闻从确认阴谋转为背负具体的活人，保护对象从名单变成人。",
          hook: "明天才会落下的玻璃雨已经嵌在今晚的伞面上。",
          target_length_band: "short",
          scene_type: "threshold_reveal",
          is_chapter_last: 1,
          writer_brief_json: {
            scene_pressure: "证人就在眼前，系统的锁定也在收紧。",
            texture: "伞面碎片折光、候车厅空椅、夜班末车的风。",
            choice_under_pressure: "当场带走证人，或按程序移交并暴露她。",
            power_shift: "林晚从名单上的编号变成有戒心的活人，掌握他们不知道的时间线。",
            new_information: "玻璃雨碎片会先于事件出现在受害者身边。",
            emotional_turn: "沈闻的道德焦虑落地为对具体一个人的责任。",
            image_anchor: "伞面上明天的碎片。",
            reader_aftertaste: "保护一个人，等于向整个排期系统宣战。",
          },
        },
      ],
    },
    {
      chapter_id: `${prefix}_02`,
      planned_scene_count: 3,
      chapter_goal: "第二章：沈闻和声学工程师许照进入地下废线站，利用倒放广播证明失踪记录被人篡改，未来不是命运而是操作痕迹。",
      main_plot_push: "把玻璃雨名单推进到地下废线站反证，揭开有人用零点广播制造失踪顺序。",
      emotional_target: "沈闻与许照从互相试探变成临时同盟，但两人都付出暴露私人隐瞒的代价。",
      ending_effect: "废线站播放幸存者证词，证明幕后者正在监听他们的每一次选择。",
      must_not: "不得复刻参考书人物关系、组织设定、战斗桥段、血统体系或专名。",
      notes: `${storySeed} current DB QA 第二章，地下废线站反证。`,
      writer_brief_json: {
        audience_contract: "调查反转章，物证必须推翻第一章的误解。",
        voice: "压低解释，先让空间和声音提供证据。",
        must_deliver: ["地下废线站", "倒放广播反证", "同盟代价"],
        avoid: protectedTerms,
      },
      scenes: [
        {
          scene_id: `${prefix}_02_SC01`,
          scene_seq: 1,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "南岸城地下废线站检修口",
          scene_goal: "沈闻和许照撬开废线站检修门潜入，布设倒放设备，在墙上的太阳色潮位图旁找到旧广播的物理接口。",
          beats_json: [
            "沿废轨避开巡检探头",
            "撬开废线站检修门",
            "墙上出现太阳色潮位图",
            "许照布设倒放设备",
            "旧广播接口仍有微弱电流"
          ],
          must_include_text: "废线站墙上必须有太阳色潮位图；进入必须经由撬开的检修门；旧广播接口必须仍带电。",
          forbidden_text: forbidden,
          exit_change: "两人从地面调查转入幕后者的物理管道，第一次踏进对方的地盘。",
          hook: "废弃三年的广播接口，电流是活的。",
          target_length_band: "short",
          scene_type: "infiltration_setup",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "巡检周期只留给他们四十分钟。",
            texture: "废轨潮气、瓷砖缝里的电流、探头扫过的红点。",
            choice_under_pressure: "冒险接入带电接口，或撤回等下一个巡检窗口。",
            power_shift: "许照的专业设备第一次成为行动的主导。",
            new_information: "废线站并未真正废弃，有人维持着供电。",
            emotional_turn: "沈闻从依赖档案转为依赖一个不完全可信的同伴。",
            image_anchor: "太阳色潮位图。",
            reader_aftertaste: "他们以为在潜入废墟，其实走进了运转中的机器。",
          },
        },
        {
          scene_id: `${prefix}_02_SC02`,
          scene_seq: 2,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "南岸城地下废线站广播间",
          scene_goal: "倒放零点广播还原出幸存者呼吸和三声玻璃撞击，声纹对上失踪名单，许照被迫承认自己曾参与系统维护。",
          beats_json: [
            "倒放零点广播",
            "噪声里浮出幸存者呼吸",
            "三声玻璃撞击对上名单时间戳",
            "声纹比对锁定失踪者",
            "许照承认曾参与系统维护"
          ],
          must_include_text: "倒放广播必须出现幸存者呼吸和三声玻璃撞击；声纹必须对上失踪名单；许照必须在此场承认参与过系统维护。",
          forbidden_text: forbidden,
          exit_change: "失踪案从悬案变成有操作痕迹的人为篡改，同盟关系因坦白而换血。",
          hook: "证明未来被篡改的声音，是许照亲手装的广播放出来的。",
          target_length_band: "short",
          scene_type: "investigation_reversal",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "反证成立的同时，同伴的旧身份浮出水面。",
            texture: "倒放的电流嘶声、呼吸声、玻璃三响。",
            choice_under_pressure: "沈闻必须决定是否继续把证据链交给刚暴露旧身份的许照。",
            power_shift: "许照从被怀疑的维护者转为掌握关键声纹的人。",
            new_information: "倒放广播里的幸存者呼吸证明失踪顺序被人为篡改。",
            emotional_turn: "沈闻从单独承担秘密转为承认自己需要同盟。",
            image_anchor: "倒放中的旧广播喇叭。",
            reader_aftertaste: "真相靠近一步，信任先付了利息。",
          },
        },
        {
          scene_id: `${prefix}_02_SC03`,
          scene_seq: 3,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "南岸城地下废线站出口",
          scene_goal: "两人取走反证磁带触发监听反制，证人藏身地的伪装电源被迫切断，广播在身后报出沈闻此刻的心跳。",
          beats_json: [
            "决定取走实体磁带",
            "取带触发静默警报",
            "证人藏身地伪装电源被切断",
            "死线亮起封锁退路",
            "广播报出沈闻此刻的心跳"
          ],
          must_include_text: "二人必须取走实体磁带；取走磁带必须导致证人藏身地伪装电源被切断；离开时广播必须报出沈闻此刻的心跳。",
          forbidden_text: forbidden,
          exit_change: "沈闻确认幕后者在实时监听，被迫暂时信任许照连夜转移证人。",
          hook: "废线站死线亮起，广播报出沈闻此刻的心跳。",
          target_length_band: "short",
          scene_type: "cost_trigger",
          is_chapter_last: 1,
          writer_brief_json: {
            scene_pressure: "拿走反证就等于向监听者自报位置。",
            texture: "死线红光、磁带外壳的凉、心跳被广播念出来的错位感。",
            choice_under_pressure: "取走磁带暴露证人位置，或销毁磁带保住证人却失去反证。",
            power_shift: "幕后者第一次直接出手，主动权易手。",
            new_information: "幕后者能实时监听并反制他们的每一次选择。",
            emotional_turn: "胜利感在走出门前变成被注视的寒意。",
            image_anchor: "亮起的死线。",
            reader_aftertaste: "他们拿到了证据，也交出了证人的坐标。",
          },
        },
      ],
    },
    {
      chapter_id: `${prefix}_03`,
      planned_scene_count: 3,
      chapter_goal: "第三章：沈闻和许照在无灯船坞打开隐藏档案，必须选择立即公开真相，还是先转移仍活着的证人。",
      main_plot_push: "闭合玻璃雨、废线站反证和证人名单，明确幕后篡改动机，并留下下一阶段追查入口。",
      emotional_target: "沈闻的正义冲动转为责任选择：真相不是越快公开越安全。",
      ending_effect: "二人选择先保护证人，再分阶段公开证据；幕后者的第二枚零点钟影出现。",
      must_not: "不得出现参考书专名、人物、设定、标志性意象、学院组织、血统或可识别剧情同构。",
      notes: `${storySeed} current DB QA 第三章，公开真相与保护证人的选择。`,
      writer_brief_json: {
        audience_contract: "选择与代价章，同时保留更大阴谋。",
        voice: "克制但有伦理压力，避免宣讲式真相独白。",
        must_deliver: ["隐藏档案", "公开真相的代价", "保护证人优先"],
        avoid: protectedTerms,
      },
      scenes: [
        {
          scene_id: `${prefix}_03_SC01`,
          scene_seq: 1,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "南岸城无灯船坞",
          scene_goal: "两人潜入无灯船坞，用玻璃雨碎片作钥匙打开隐藏档案柜，找到幸存者录音与原始定位页。",
          beats_json: [
            "潜入无灯船坞",
            "水面没有倒影",
            "玻璃雨碎片嵌进档案柜锁槽",
            "档案柜弹开",
            "找到幸存者录音和定位页"
          ],
          must_include_text: "无灯船坞的水面没有倒影；隐藏档案必须用玻璃雨碎片作钥匙；柜内必须同时有幸存者录音与原始定位页。",
          forbidden_text: forbidden,
          exit_change: "调查从追证据转为持有能定罪也能杀人的完整档案。",
          hook: "打开档案柜的钥匙，是受害者身边掉落的碎片。",
          target_length_band: "short",
          scene_type: "hidden_archive",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "档案在手，每多持有一分钟就多一分暴露。",
            texture: "没有倒影的水面、船坞铁锈、碎片入锁的咔哒。",
            choice_under_pressure: "当场翻录副本，或整柜带走。",
            power_shift: "沈闻从被追踪者短暂变成握有全部底牌的人。",
            new_information: "定位页记录着每个幸存者的实时坐标。",
            emotional_turn: "拿到一切的瞬间，责任比恐惧更重。",
            image_anchor: "嵌在锁槽里的玻璃雨碎片。",
            reader_aftertaste: "最锋利的证据，同时是最精确的猎杀清单。",
          },
        },
        {
          scene_id: `${prefix}_03_SC02`,
          scene_seq: 2,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "无灯船坞隐藏档案间",
          scene_goal: "两人评估公开风险：完整证据会暴露证人位置，沈闻决定剪掉坐标后分阶段公开部分证据。",
          beats_json: [
            "许照演算公开后的追踪路径",
            "确认完整公开会暴露证人",
            "争论真相的时效与人命的权重",
            "沈闻决定剪掉坐标",
            "拟定分阶段公开顺序"
          ],
          must_include_text: "公开完整证据会暴露证人位置的推演必须成立；沈闻必须决定剪掉坐标后公开部分证据；分阶段公开顺序必须在场内定下。",
          forbidden_text: forbidden,
          exit_change: "沈闻从追求立刻公开，转为接受延迟真相以保护活人。",
          hook: "真相被剪掉一角，才配得上安全落地。",
          target_length_band: "short",
          scene_type: "ethical_dilemma",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "每延迟一小时公开，名单可能新增一个名字。",
            texture: "档案间灯泡的嗡鸣、剪刀口的反光、纸页边缘。",
            choice_under_pressure: "上传完整证据，或只公开剪掉坐标的部分。",
            power_shift: "沈闻从冲动的正义方转为承担延迟代价的决策者。",
            new_information: "幸存者仍被实时追踪，篡改者不止一个。",
            emotional_turn: "正义冲动冷却为对时序的精密责任。",
            image_anchor: "被剪下的坐标纸角。",
            reader_aftertaste: "他们选择让真相慢一步，让活人快一步。",
          },
        },
        {
          scene_id: `${prefix}_03_SC03`,
          scene_seq: 3,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO", "CHAR_WITNESS_A"],
          location: "无灯船坞外雾墙码头",
          scene_goal: "沈闻烧毁原始定位页，证人车队离开船坞；雾墙上投出第二枚零点钟影，宣告篡改者不止一个。",
          beats_json: [
            "剪掉坐标后公开部分证据",
            "沈闻烧毁原始定位页",
            "林晚在车窗里回望",
            "证人车队离开船坞",
            "雾墙投出第二枚零点钟影"
          ],
          must_include_text: "沈闻必须亲手烧毁原始定位页；证人车队必须离开船坞；结尾必须出现第二枚零点钟影。",
          forbidden_text: forbidden,
          exit_change: "第一阶段以保护证人收束，追查对象从单个篡改者扩展为一个网络。",
          hook: "船坞外的雾墙投出第二枚零点钟影，说明篡改者不止一个。",
          target_length_band: "short",
          scene_type: "ethical_reveal",
          is_chapter_last: 1,
          writer_brief_json: {
            scene_pressure: "烧掉定位页意味着连他们自己也找不到证人了。",
            texture: "纸页卷曲的火光、雾墙、车灯远去。",
            choice_under_pressure: "保留一份加密副本，或烧到一页不剩。",
            power_shift: "沈闻交出对证人行踪的最后控制权，换取她真正的安全。",
            new_information: "第二枚零点钟影证明篡改是多人接力。",
            emotional_turn: "如释重负与更大阴谋压顶同时到来。",
            image_anchor: "雾墙上的第二枚钟影。",
            reader_aftertaste: "赢下的不是公开胜利，而是证人撤离的时间。",
          },
        },
      ],
    },
    {
      chapter_id: `${prefix}_04`,
      planned_scene_count: 3,
      chapter_goal: "第四章：沈闻追查第二枚零点钟影，在潮汐钟楼发现篡改记录盖着自己的修复签名，并被迫与半盟半敌的顾磬交易。",
      main_plot_push: "把单人篡改升级为接力网络，引入内部人顾磬与广播调度表，同时让沈闻背上被伪造的签名。",
      emotional_target: "沈闻从追查者变成被构陷者，学会与不可信的人做有限交易。",
      ending_effect: "按调度表设下的饵反被将计就计，新名单出现，第一个名字是沈闻自己。",
      must_not: "不得出现参考书专名、人物、组织、血统体系或可识别桥段；不得引入超自然战斗。",
      notes: `${storySeed} current DB QA 第四章，钟影溯源与身份构陷。`,
      writer_brief_json: {
        audience_contract: "构陷与交易章，敌我边界模糊，信息差驱动。",
        voice: "冷静里带一点被背叛的钝痛，交易对话短促。",
        must_deliver: ["潮汐钟楼", "被伪造的修复签名", "顾磬与调度表"],
        avoid: protectedTerms,
      },
      scenes: [
        {
          scene_id: `${prefix}_04_SC01`,
          scene_seq: 1,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "南岸城潮汐钟楼档案室",
          scene_goal: "两人溯源第二枚钟影到潮汐钟楼，在投影机走带痕迹里发现篡改记录，每一条都盖着沈闻的修复签名。",
          beats_json: [
            "钟影角度反推投射源",
            "潜入潮汐钟楼档案室",
            "投影机走带痕迹犹新",
            "调出篡改记录",
            "每条记录盖着沈闻的修复签名"
          ],
          must_include_text: "钟影必须被反推到潮汐钟楼；篡改记录必须逐条盖着沈闻的修复签名；投影机必须有近期使用痕迹。",
          forbidden_text: forbidden,
          exit_change: "沈闻从追查者变成档案意义上的头号嫌疑人，敌人先他一步偷走了他的身份。",
          hook: "追到源头，源头署着他自己的名字。",
          target_length_band: "short",
          scene_type: "identity_trap",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "报警等于自首，沉默等于坐实。",
            texture: "钟楼齿轮油味、投影走带声、签名的压痕。",
            choice_under_pressure: "销毁伪造记录自保，或保留它作为反查笔迹的证据。",
            power_shift: "幕后网络从隐身转为主动构陷，沈闻失去清白身位。",
            new_information: "篡改者能完美复刻沈闻的修复签名。",
            emotional_turn: "愤怒之下是一层更冷的认知：对方了解他的一切。",
            image_anchor: "盖着他签名的篡改记录。",
            reader_aftertaste: "他一直在修复档案，档案却被用来改写他。",
          },
        },
        {
          scene_id: `${prefix}_04_SC02`,
          scene_seq: 2,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO", "CHAR_GUQING"],
          location: "潮汐钟楼底层机房",
          scene_goal: "许照的前同事顾磬现身，半盟半敌，用零点广播调度表交换沈闻手里的反证磁带副本，交易在互不信任中成立。",
          beats_json: [
            "顾磬堵住机房唯一出口",
            "亮出许照的旧工牌自证来历",
            "开价：调度表换磁带副本",
            "许照识破调度表缺了一页",
            "顾磬补上缺页，交易成立"
          ],
          must_include_text: "顾磬必须以许照旧同事身份现身；交易必须是调度表换磁带副本；许照必须当场识破调度表缺页。",
          forbidden_text: forbidden,
          exit_change: "调查获得幕后网络的时刻表，代价是反证副本流入立场不明者手中。",
          hook: "能出卖幕后者的人，同样能出卖他们。",
          target_length_band: "short",
          scene_type: "uneasy_alliance",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "不交易就空手而归，交易就武装了一个立场不明的人。",
            texture: "机房低频震动、旧工牌的磨边、递出磁带的迟疑。",
            choice_under_pressure: "交出完整副本，或偷偷抹掉副本里的关键三分钟。",
            power_shift: "顾磬以信息掮客身份入局，三方博弈开始。",
            new_information: "零点广播按调度表接力运行，存在换班空窗。",
            emotional_turn: "沈闻学会在不信任里计算可交易的边界。",
            image_anchor: "缺了一页又被补上的调度表。",
            reader_aftertaste: "他们买到了时刻表，也卖出了一份风险。",
          },
        },
        {
          scene_id: `${prefix}_04_SC03`,
          scene_seq: 3,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "零点档案站临时据点",
          scene_goal: "两人按调度表空窗设饵引篡改者现身，反被将计就计：饵未咬钩，新名单在零点生成，第一个名字是沈闻。",
          beats_json: [
            "按调度表空窗布设假证人档案",
            "零点整广播准时切换",
            "饵无人咬钩",
            "新名单在屏上生成",
            "第一个名字是沈闻"
          ],
          must_include_text: "设饵必须依据顾磬的调度表空窗；饵必须落空；新名单第一个名字必须是沈闻本人。",
          forbidden_text: forbidden,
          exit_change: "沈闻从设局者沦为名单上的猎物，调度表的真实性与顾磬的立场同时存疑。",
          hook: "他们钓鱼，鱼把他们写进了下一张名单。",
          target_length_band: "short",
          scene_type: "reversal_trap",
          is_chapter_last: 1,
          writer_brief_json: {
            scene_pressure: "对方不但识破了饵，还证明能随时把任何人写进名单。",
            texture: "据点里两块屏幕的冷光、零点整的静默、名字浮现。",
            choice_under_pressure: "立即转移躲名单，或将计就计用自己当真饵。",
            power_shift: "幕后网络展示对名单的即时写权，主动权彻底易手。",
            new_information: "名单可以被实时改写，沈闻已被列为下一个失踪者。",
            emotional_turn: "从猎手到猎物的失重感，被沈闻压成冷静的赌性。",
            image_anchor: "屏上自己的名字。",
            reader_aftertaste: "调度表也许是真的，陷阱也是。",
          },
        },
      ],
    },
    {
      chapter_id: `${prefix}_05`,
      planned_scene_count: 3,
      chapter_goal: "第五章：沈闻以名单上的自己为饵直取零点广播源头，发现篡改是接力值守的网络，最终以分阶段公开终止名单。",
      main_plot_push: "闭合调度表、伪造签名与名单写权三条线，兑现分阶段公开，终止失踪排期并留下续作钩子。",
      emotional_target: "沈闻完成从自保到担责的弧线：用自己的名字作赌注，换所有名字下线。",
      ending_effect: "名单终止，玻璃雨真正落地；顾磬消失，只留下一枚新钟影残片。",
      must_not: "不得出现参考书专名、人物、组织、血统体系或可识别桥段；结局不得靠超自然力量解围。",
      notes: `${storySeed} current DB QA 第五章，零点源头与收束。`,
      writer_brief_json: {
        audience_contract: "收束章：对决靠信息差与时序，不靠武力；代价必须可见。",
        voice: "节奏收紧，短句推进，结尾留一口余温。",
        must_deliver: ["零点广播源机房", "以自己为饵的交换", "名单终止与新钟影残片"],
        avoid: protectedTerms,
      },
      scenes: [
        {
          scene_id: `${prefix}_05_SC01`,
          scene_seq: 1,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO"],
          location: "零点广播源机房外廊",
          scene_goal: "两人循调度表进入零点广播源机房，发现篡改由多人接力值守，墙上排班表的下一班签名栏空着。",
          beats_json: [
            "循调度表空窗接近机房",
            "值守座位还留着体温",
            "墙上贴着接力排班表",
            "历班签名对上伪造笔迹",
            "下一班签名栏空着"
          ],
          must_include_text: "机房必须呈现多人接力值守的痕迹；排班表必须挂在墙上且下一班签名栏为空；历班签名必须与伪造沈闻签名同源。",
          forbidden_text: forbidden,
          exit_change: "敌人从一个'幕后者'具体化为一张排班表，沈闻明白名单不会因抓到一个人而停。",
          hook: "排班表的下一班，还没人签名。",
          target_length_band: "short",
          scene_type: "source_reveal",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "换班空窗正在倒数，他们站在别人的岗位上。",
            texture: "机房恒温的风、座椅余温、排班表纸角卷边。",
            choice_under_pressure: "拆毁设备一了百了，或保全设备取走全部原始带。",
            power_shift: "沈闻第一次站在名单的写入端。",
            new_information: "篡改是制度化的接力值守，不是单人作案。",
            emotional_turn: "复仇式的愤怒被'拆一台机器救不了名单'的清醒替代。",
            image_anchor: "空着的下一班签名栏。",
            reader_aftertaste: "系统作恶时，空缺的岗位比作恶的人更可怕。",
          },
        },
        {
          scene_id: `${prefix}_05_SC02`,
          scene_seq: 2,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO", "CHAR_GUQING"],
          location: "零点广播源机房",
          scene_goal: "顾磬现身机房摊牌，沈闻提出用自己在名单上的位置作饵换全部原始带，许照拦下并用调度表缺口伪造换班空窗完成偷换。",
          beats_json: [
            "顾磬从值守暗门现身摊牌",
            "沈闻开价：以自己为饵换原始带",
            "许照拦下签名的手",
            "用调度表缺口伪造换班空窗",
            "原始带整箱偷换到手"
          ],
          must_include_text: "沈闻必须主动提出以自己为饵；许照必须在他签字前拦下；原始带必须经伪造换班空窗偷换而非武力夺取。",
          forbidden_text: forbidden,
          exit_change: "沈闻把最后一次篡改让给了拒绝篡改的人：他们没有写名单，而是偷走了名单的原稿。",
          hook: "终止名单的办法，差一点就是再写一次名单。",
          target_length_band: "short",
          scene_type: "sacrifice_bargain",
          is_chapter_last: 0,
          writer_brief_json: {
            scene_pressure: "签下去名单立刻少一个名字，也多一个篡改者。",
            texture: "原始带箱的重量、签名笔尖悬停、暗门风声。",
            choice_under_pressure: "亲手签最后一次篡改，或赌许照的伪造空窗。",
            power_shift: "许照从技术支援变成道德底线的执剑人。",
            new_information: "顾磬要的从来不是磁带，而是有人接他的班。",
            emotional_turn: "沈闻承认：肯为名单赴死容易，肯不碰写权才难。",
            image_anchor: "悬在签名栏上方的笔尖。",
            reader_aftertaste: "他们赢在没有变成自己要终结的东西。",
          },
        },
        {
          scene_id: `${prefix}_05_SC03`,
          scene_seq: 3,
          pov_character_id: "CHAR_SHENWEN",
          onstage_chars_json: ["CHAR_SHENWEN", "CHAR_XUZHAO", "CHAR_WITNESS_A"],
          location: "南岸城零点档案站天台",
          scene_goal: "分阶段公开如期兑现，名单在零点终止，玻璃雨第一次真正落地；顾磬去向不明，只留下一枚新钟影残片。",
          beats_json: [
            "第三阶段证据准时公开",
            "零点广播沉默",
            "名单状态翻为已终止",
            "玻璃雨落地摔碎",
            "林晚归还伞面碎片",
            "残片盒里多出一枚新钟影残片"
          ],
          must_include_text: "分阶段公开必须按第三章定下的顺序兑现；名单必须在零点显示终止；玻璃雨必须真正落地；结尾必须出现顾磬留下的新钟影残片。",
          forbidden_text: forbidden,
          exit_change: "五章弧线收束：名单终止、证人自由、沈闻背着可赦免的篡改嫌疑换来全部真相落地。",
          hook: "雨落干净了，残片盒里躺着下一场雨。",
          target_length_band: "short",
          scene_type: "resolution_hook",
          is_chapter_last: 1,
          writer_brief_json: {
            scene_pressure: "公开的最后一步仍可能引来清算，零点前无人敢庆祝。",
            texture: "天台夜风、真正下落的雨、碎片盒的轻响。",
            choice_under_pressure: "把新钟影残片上报，或私下继续追。",
            power_shift: "名单写权归零，普通人重新拥有自己的明天。",
            new_information: "顾磬消失前留下新钟影残片：网络仍有残余。",
            emotional_turn: "警惕松开一半，另一半留给下一枚钟影。",
            image_anchor: "落地摔碎的玻璃雨。",
            reader_aftertaste: "真相分期兑付完毕，续章的雨已经在盒子里。",
          },
        },
      ],
    },
  ];
}

async function main() {
  ensureOutDir();
  writeJson("qa-live-results.json", result);
  if (resetAuthorState || manageDevServices) {
    await step("prepare clean author state and local services", prepareCleanRunEnvironment, { fatal: true });
  }
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  try {
    await prepareBrowser(page);
    await step("preflight current DB, tools and provider routes", preflight, { fatal: true });
    const blankProject = await step("create a genuinely blank project through the UI", () => createOriginalWorkspace(page), { fatal: true });
    const snowflake = await step("import, approve and materialize the five-chapter snowflake through the UI", () => exerciseSnowflake(page), { fatal: true });
    await step("run, select and archive all planned scenes through the UI", () => exerciseSceneWorkbench(page), { fatal: true });
    await step("aggregate all chapter manuscripts through the UI", () => exerciseChapterManuscripts(page), { fatal: true });
    await step("LLM route coverage and fallback audit", () => auditLlmIntegration());
    result.meta.created = { ...blankProject, ...snowflake };
  } finally {
    await context.close().catch(() => null);
    await browser.close().catch(() => null);
    evaluateChapterScores();
    fillRootCauseFindings();
    result.meta.finishedAt = new Date().toISOString();
    writeJson("final-scenes.json", finalScenes);
    // Wave 0：结果门禁是唯一权威判定——步骤全绿但任一计划场景无非空归档正文，
    // 退出码必须非零（删除"步骤完成即通过"的旧语义）。
    const gatePassed = runOutcomeGate();
    writeJson("qa-live-results.json", result);
    fs.writeFileSync(path.join(outDir, "report.md"), buildReport(), "utf8");
    if (!gatePassed) {
      process.exitCode = 1;
      console.error(
        `outcome gate FAIL: 五章基准要求 ${expectedChapterCount} 章 × ${expectedScenesPerChapter} 场全部存在非空后端归档正文；详见 ${path.join(outDir, "outcome-gate-verdict.md")}`,
      );
    }
  }
}

if (require.main === module) {
  main().catch((error) => {
    ensureOutDir();
    result.meta.finishedAt = new Date().toISOString();
    result.meta.fatalError = String(error?.stack || error?.message || error);
    evaluateChapterScores();
    fillRootCauseFindings();
    writeJson("final-scenes.json", finalScenes);
    runOutcomeGate();
    writeJson("qa-live-results.json", result);
    fs.writeFileSync(path.join(outDir, "report.md"), buildReport(), "utf8");
    appendLog({ type: "fatal", error: result.meta.fatalError });
    console.error(error);
    process.exitCode = 1;
  });
}

module.exports = { buildChapters, buildSnowflakeImportPlan };
