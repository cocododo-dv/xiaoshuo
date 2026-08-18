const fs = require("node:fs");
const path = require("node:path");
const {
  buildChapterScores,
  buildExperienceScores,
} = require("./lib/longzu-literary-scoring.cjs");
const outcomeGateLib = require("./lib/qa-outcome-gate.cjs");

let chromium;
try {
  ({ chromium } = require("../frontend-react/node_modules/playwright"));
} catch {
  ({ chromium } = require("playwright"));
}

const repoRoot = path.resolve(__dirname, "..");
const codexRunDir = path.join(repoRoot, ".codex-run");
const runClock = new Date();
const runHms = [
  String(runClock.getHours()).padStart(2, "0"),
  String(runClock.getMinutes()).padStart(2, "0"),
  String(runClock.getSeconds()).padStart(2, "0"),
].join("");
const runTimestamp = `20260423-${runHms}`;
const outDirName = `longzu-full-cloud-qa-20260423-${runHms}`;
const outDir = path.join(repoRoot, "output", "playwright", outDirName);
const logPath = path.join(outDir, "run-log.ndjson");
const frontendUrl =
  process.env.PLAYWRIGHT_FRONTEND_URL ||
  readRunFile("frontend.url") ||
  readRunFile("vite.url") ||
  "http://127.0.0.1:5173";
const apiBase =
  process.env.PLAYWRIGHT_API_BASE ||
  readRunFile("backend.url") ||
  readRunFile("api.url") ||
  `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8001"}`;
const operatorRef = process.env.PLAYWRIGHT_OPERATOR_REF || `qa.longzu.full-cloud.${runTimestamp}`;
const referencePath = process.env.REFERENCE_BOOK_PATH || "C:\\Users\\duwei\\Downloads\\龙族.txt";
const pythonExecutable = process.env.PYTHON || "python";
// Wave 0：本 lane 是参考安全通道，计划为 3 章 × 每章 1 场；结果门禁期望值取自自身计划。
// 五章北极星基准是 run-currentdb-three-chapter-qa.cjs（默认 5×3）。
const expectedChapterCount = Math.max(1, Number(process.env.QA_CHAPTER_COUNT || "3"));
const expectedScenesPerChapter = Math.max(1, Number(process.env.QA_SCENES_PER_CHAPTER || "1"));
const terminalJobStatuses = new Set([
  "archived",
  "blocked",
  "cancelled",
  "completed",
  "failed",
  "human_review_required",
  "manual_review_required",
]);

const result = {
  meta: {
    startedAt: new Date().toISOString(),
    repoRoot,
    outDir,
    frontendUrl,
    apiBase,
    operatorRef,
    referencePath,
    referenceCloudPolicy: "allow_full_cloud",
    expectedChapterCount,
    expectedScenesPerChapter,
  },
  outcome: null,
  outcomeGate: null,
  steps: [],
  experienceScores: {},
  chapterScores: {},
  rootCauseFindings: [],
  systemFixes: [],
  screenshots: [],
  warnings: [],
  console: [],
  requestFailures: [],
};

const finalScenes = {};
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

const chapterPlan = [
  {
    chapter_id: "CHOR01",
    planned_scene_count: 1,
    chapter_goal: "第一章：档案修复师林岑收到一枚盐钟残片，发现旧城潮汛记录被人改写。",
    main_plot_push: "建立盐钟残片、旧城潮汛档案和失踪记录之间的第一层因果，把篡改者的存在推到台前。",
    emotional_target: "让林岑从职业性的谨慎，转入被私人记忆刺痛后的主动追查。",
    ending_effect: "残片在夜里敲出不属于当前年份的潮汛回声，迫使林岑承认档案正在被活人改写。",
    must_not: "不得出现梦醒、系统提示、参考书专名、原书人物、学院组织、血统等级或可识别桥段。",
    notes: "原创三章闭环 QA 第一章；只学习抽象节奏，不复刻源书设定。",
    scenes: [{
      scene_id: "CHOR01_SC01",
      scene_seq: 1,
      pov_character_id: "CHAR_LINCEN",
      onstage_chars_json: ["CHAR_LINCEN", "CHAR_XUWANG"],
      location: "旧城档案修复所的盐蚀库房",
      scene_goal: "林岑修复一盒受潮旧档时收到盐钟残片，借声纹和纸纹发现二十年前潮汛记录被同一规律删改。",
      beats_json: ["清点受潮档案", "收到盐钟残片", "比对潮汛声纹", "发现缺页反向索引", "决定联系许望"],
      must_include_text: "盐钟残片边缘有蓝白盐霜；潮汛记录缺页的编号连成一条倒置船线。",
      forbidden_text: "不得照搬参考书句子；不得出现源书人物、组织、专名、血统、龙王或学院式战斗设定。",
      exit_change: "林岑从被动修档转为主动调查，并把第一份证据交给许望验证。",
      hook: "盐钟在无人触碰时响了一下，档案盒里多出一页明天的潮位表。",
      target_length_band: "short",
      scene_type: "inciting_clue",
      is_chapter_last: 1,
    }],
  },
  {
    chapter_id: "CHOR02",
    planned_scene_count: 1,
    chapter_goal: "第二章：林岑与声学工程师许望进入雾堤下的废弃监听站，找到失踪案的反证。",
    main_plot_push: "把盐钟声纹与监听站旧磁带合流，证明失踪者并非遇难，而是被人为抹去行踪。",
    emotional_target: "让林岑和许望在互相试探中形成临时信任，代价是两人都暴露各自隐瞒的动机。",
    ending_effect: "监听站播放出失踪者活着的证词，却同时暴露有人正在实时监听他们。",
    must_not: "不得复刻参考书人物、组织、地名、课堂、血统或战斗桥段；不得使用源书式专名。",
    notes: "原创三章闭环 QA 第二章。",
    scenes: [{
      scene_id: "CHOR02_SC01",
      scene_seq: 1,
      pov_character_id: "CHAR_LINCEN",
      onstage_chars_json: ["CHAR_LINCEN", "CHAR_XUWANG"],
      location: "雾堤下的废弃监听站",
      scene_goal: "林岑和许望进入监听站，复原一卷被盐水泡坏的磁带，找到能推翻官方失踪结论的反证。",
      beats_json: ["穿过雾堤检修门", "修复旧磁带", "破解反向声纹", "发现幸存者编号", "监听站被远程唤醒"],
      must_include_text: "监听站墙面贴满太阳色潮位图；磁带倒放时出现幸存者的呼吸和三声盐钟。",
      forbidden_text: "不得复制参考书句法或桥段；不得出现源书人物、学院、社团、血统、战斗体系或专名。",
      exit_change: "二人确认失踪案存在人为遮蔽，并取得指向无灯船坞的反证。",
      hook: "监听站的死线路突然亮起，扬声器报出林岑的实时心跳。",
      target_length_band: "short",
      scene_type: "investigation_reversal",
      is_chapter_last: 1,
    }],
  },
  {
    chapter_id: "CHOR03",
    planned_scene_count: 1,
    chapter_goal: "第三章：两人在无灯船坞打开隐藏档案，必须决定公开真相还是先保护幸存者。",
    main_plot_push: "让盐钟残片、监听站反证和隐藏档案闭合，明确幕后篡改动机，同时留下下一段追查入口。",
    emotional_target: "把林岑的正义冲动推向责任选择：真相并非越快公开越安全。",
    ending_effect: "二人选择先转移幸存者，公开证据被拆成两份，危险也因此升级。",
    must_not: "不得出现源书专名、设定、人物关系或可识别场景；不得把参考文本改写成同构剧情。",
    notes: "原创三章闭环 QA 第三章。",
    scenes: [{
      scene_id: "CHOR03_SC01",
      scene_seq: 1,
      pov_character_id: "CHAR_LINCEN",
      onstage_chars_json: ["CHAR_LINCEN", "CHAR_XUWANG"],
      location: "无灯船坞的隐藏档案间",
      scene_goal: "林岑和许望在无灯船坞打开隐藏档案，确认幸存者仍被追踪，必须在公开真相和保护人之间做选择。",
      beats_json: ["潜入无灯船坞", "打开盐钟对应的档案柜", "找到幸存者录音", "判断公开风险", "拆分证据并转移幸存者"],
      must_include_text: "无灯船坞的水面没有倒影；隐藏档案用盐钟残片作钥匙，开柜时潮声倒退三秒。",
      forbidden_text: "不得复刻参考书原句、专名、超自然体系、学院组织或标志性桥段。",
      exit_change: "林岑从单纯追求公开真相，转向先保护活人并设计分阶段披露。",
      hook: "船坞外的雾墙上投出第二枚盐钟的影子，说明篡改者不止一个。",
      target_length_band: "short",
      scene_type: "ethical_reveal",
      is_chapter_last: 1,
    }],
  },
];

const chapters = chapterPlan
  .slice(0, expectedChapterCount)
  .map((chapter) => {
    const scenes = chapter.scenes
      .slice(0, expectedScenesPerChapter)
      .map((scene, index, arr) => ({ ...scene, is_chapter_last: index === arr.length - 1 ? 1 : 0 }));
    return { ...chapter, planned_scene_count: scenes.length, scenes };
  });
const northstarPhases = {}; // 北极星六阶段通道记录（ui / api / missing），如实填报

function recordPhase(phase, lane, evidence) {
  northstarPhases[phase] = { phase, lane, evidence };
}

// Wave 0 结果门禁：权威判定在 scripts/playwright_audit_summary.py；
// outcome 组装与调用在 scripts/lib/qa-outcome-gate.cjs（与 currentdb harness 共用）。
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

function appendLog(event) {
  ensureOutDir();
  fs.appendFileSync(logPath, `${JSON.stringify({ at: new Date().toISOString(), ...event })}\n`, "utf8");
}

function writeJson(name, payload) {
  ensureOutDir();
  fs.writeFileSync(path.join(outDir, name), JSON.stringify(payload, null, 2), "utf8");
}

function preview(value, limit = 220) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function idKey(label) {
  return `${label}-${Date.now()}-${Math.random().toString(16).slice(2)}`.replace(/[^a-zA-Z0-9_.:-]/g, "-");
}

function requestHeaders(label) {
  return {
    "Content-Type": "application/json",
    "X-Idempotency-Key": idKey(label),
    "X-Operator-Ref": operatorRef,
  };
}

async function apiGet(apiPath, timeoutMs = 30000) {
  return fetchEnvelope("GET", apiPath, null, timeoutMs);
}

async function apiPost(apiPath, data = {}, timeoutMs = 30000, options = {}) {
  return fetchEnvelope("POST", apiPath, data, timeoutMs, options);
}

async function fetchEnvelope(method, apiPath, data, timeoutMs, options = {}) {
  const headers = method === "POST" ? requestHeaders(apiPath) : { "X-Operator-Ref": operatorRef };
  const attempts = options.retry === false ? 1 : options.attempts || 3;
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fetchEnvelopeOnce(method, apiPath, data, timeoutMs, headers);
    } catch (error) {
      lastError = error;
      if (attempt >= attempts || !isTransientFetchError(error)) {
        throw error;
      }
      appendLog({ type: "http-retry", method, apiPath, attempt, error: error.message || String(error) });
      await new Promise((resolve) => setTimeout(resolve, 1500 * attempt));
    }
  }
  throw lastError;
}

function isTransientFetchError(error) {
  const message = String(error?.message || error || "").toLowerCase();
  return error?.name === "AbortError" || message.includes("fetch failed") || message.includes("econnreset") || message.includes("terminated");
}

function isRecoverableReferenceAdvanceError(error) {
  const message = String(error?.message || error || "");
  const code = error?.code || error?.payload?.error?.code || "";
  return isTransientFetchError(error) || code === "IDEMPOTENCY_REQUEST_IN_PROGRESS" || message.includes("IDEMPOTENCY_REQUEST_IN_PROGRESS");
}

async function fetchEnvelopeOnce(method, apiPath, data, timeoutMs, headers) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase}${apiPath}`, {
      method,
      headers,
      body: method === "POST" ? JSON.stringify(data || {}) : undefined,
      signal: controller.signal,
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error(`${method} ${apiPath} returned non-JSON ${response.status}: ${error.message}`);
    }
    if (!response.ok || payload.ok === false) {
      const error = new Error(`${method} ${apiPath} failed ${response.status}: ${payload?.error?.message || response.statusText}`);
      error.status = response.status;
      error.code = payload?.error?.code || null;
      error.payload = payload;
      throw error;
    }
    return payload.data;
  } finally {
    clearTimeout(timeout);
  }
}

async function advanceReferenceLearning(bookId, runId, phase) {
  const apiPath = `/api/v1/reference-books/${encodeURIComponent(bookId)}/runs/${encodeURIComponent(runId)}/advance`;
  try {
    return await apiPost(apiPath, {}, 600000, { retry: false });
  } catch (error) {
    if (!isRecoverableReferenceAdvanceError(error)) {
      throw error;
    }
    appendLog({
      type: "reference-advance-recover",
      bookId,
      runId,
      phase,
      error: error.message || String(error),
    });
    return waitReferenceAdvanceRecovery(bookId, runId, phase);
  }
}

async function waitReferenceAdvanceRecovery(bookId, runId, phase, timeoutMs = 600000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const tree = await apiGet(`/api/v1/reference-books/${encodeURIComponent(bookId)}/learning-tree`, 60000);
    const run = (tree.runs || []).find((item) => item.run_id === runId);
    if (run) {
      const rounds = run.rounds || [];
      const round = rounds[rounds.length - 1] || null;
      if (phase === "round" && (run.status === "waiting_review" || (round?.findings || []).length > 0)) {
        return { run, round, recovered: true };
      }
      if (phase === "profile") {
        const profiles = tree.profiles || [];
        const profile =
          profiles.find((item) => item.profile_id === run.profile_id) ||
          profiles.find((item) => item.run_id === runId && item.status === "ready") ||
          null;
        if (run.status === "completed" || profile) {
          return { run, round, profile, recovered: true };
        }
      }
      if (run.status === "failed") {
        throw new Error(`reference learning run ${runId} failed while recovering ${phase}`);
      }
    }
    await sleep(5000);
  }
  throw new Error(`timed out recovering reference learning ${phase} for run ${runId}`);
}

async function step(name, fn, options = {}) {
  const started = Date.now();
  appendLog({ type: "step-start", name });
  try {
    const data = await fn();
    const item = { name, ok: true, ms: Date.now() - started, data: summarize(data) };
    result.steps.push(item);
    appendLog({ type: "step-ok", name, ms: item.ms });
    writeJson("qa-live-results.json", result);
    return data;
  } catch (error) {
    const item = {
      name,
      ok: false,
      ms: Date.now() - started,
      error: String(error && error.stack ? error.stack : error),
      payload: error?.payload || null,
    };
    result.steps.push(item);
    result.warnings.push(`${name}: ${error.message || error}`);
    appendLog({ type: "step-fail", name, ms: item.ms, error: item.error });
    writeJson("qa-live-results.json", result);
    if (options.fatal) {
      throw error;
    }
    return null;
  }
}

function summarize(data) {
  if (!data || typeof data !== "object") {
    return data;
  }
  const clone = JSON.parse(JSON.stringify(data));
  for (const item of Object.values(clone)) {
    if (item && typeof item === "object" && item.finalText) {
      item.finalText = preview(item.finalText);
    }
  }
  if (clone.finalText) {
    clone.finalText = preview(clone.finalText);
  }
  return clone;
}

async function screenshot(page, name) {
  const target = path.join(outDir, `${name}.png`);
  try {
    await page.screenshot({ path: target, fullPage: true });
    result.screenshots.push(path.relative(repoRoot, target).replace(/\\/g, "/"));
  } catch (error) {
    result.warnings.push(`screenshot ${name} failed: ${error.message}`);
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

async function visit(page, viewId, testId, screenshotName) {
  await page.getByTestId(`nav-${viewId}`).click();
  await page.getByTestId(testId).waitFor({ timeout: 30000 });
  await screenshot(page, screenshotName);
}

async function preflight() {
  const referenceExists = fs.existsSync(referencePath);
  const referenceStat = referenceExists ? fs.statSync(referencePath) : null;
  const systemConfig = await apiGet("/api/v1/system-config").catch((error) => ({ unavailable: error.message }));
  const llmConfig = await apiGet("/api/v1/system-config/llm").catch((error) => ({ unavailable: error.message }));
  result.meta.preflight = {
    referenceExists,
    referenceSize: referenceStat?.size || 0,
    referenceMtime: referenceStat?.mtime?.toISOString?.() || null,
    systemStatus: systemConfig?.status || "unknown",
    providers: Object.keys(llmConfig?.providers || {}),
  };
  return result.meta.preflight;
}

async function exerciseSystemConfig(page) {
  await visit(page, "config", "system-config-view", "system-config");
  const contract = await apiGet("/api/v1/style-profile/contract").catch((error) => ({ blocked: error.message }));
  const baseline = await apiPost("/api/v1/literary-eval/run", { mode: "baseline" }, 120000).catch((error) => ({
    blocked: error.message,
  }));
  return { contractVersion: contract.contract_version || contract.version || null, baselineMode: baseline.report?.mode || baseline.blocked || null };
}

async function exerciseReferenceLearning(page) {
  if (!fs.existsSync(referencePath)) {
    throw new Error(`reference book missing: ${referencePath}`);
  }
  await visit(page, "reference", "reference-learning-view", "reference-learning");
  const importData = await apiPost(
    "/api/v1/reference-books/import-path",
    {
      file_path: referencePath,
      title: "抽象节奏参考",
      author_label: "source-reference",
      cloud_policy: "allow_full_cloud",
      analysis_focus: "style_structure",
    },
    120000,
  );
  const bookId = importData.book_id || importData.book?.book_id;
  const startData = await apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/runs`, { batch_size: 8 }, 60000);
  const runId = startData.run?.run_id || startData.run_id;
  const firstAdvance = await advanceReferenceLearning(bookId, runId, "round");
  const findings = firstAdvance.round?.findings || [];
  const decisions = [];
  for (let index = 0; index < findings.length; index += 1) {
    const finding = findings[index];
    const reviewId = finding.review?.review_id || finding.review_id;
    if (!reviewId) {
      continue;
    }
    const text = `${finding.finding_type || ""} ${finding.dimension || ""} ${finding.summary || ""} ${finding.review?.candidate_text || ""}`;
    const leakTerms = protectedTerms.filter((term) => text.includes(term));
    const reject = leakTerms.length > 0 || (index === findings.length - 1 && decisions.some((item) => item.decision === "approved"));
    if (reject) {
      await apiPost(`/api/v1/review-items/${encodeURIComponent(reviewId)}/reject`, {
        reason: leakTerms.length ? `contains protected source terms: ${leakTerms.join(", ")}` : "QA rejection path coverage",
      });
      decisions.push({ reviewId, decision: "rejected", leakTerms });
    } else {
      await apiPost(`/api/v1/review-items/${encodeURIComponent(reviewId)}/approve`, {});
      decisions.push({ reviewId, decision: "approved", leakTerms: [] });
    }
  }
  const profileAdvance = await advanceReferenceLearning(bookId, runId, "profile").catch((error) => ({ blocked: error.message }));
  const detail = await apiGet(`/api/v1/reference-books/${encodeURIComponent(bookId)}`);
  const learningTree = await apiGet(`/api/v1/reference-books/${encodeURIComponent(bookId)}/learning-tree`);
  const profile = profileAdvance.profile || detail.profiles?.find((item) => item.status === "ready") || detail.profiles?.[0] || null;
  let applyData = null;
  if (profile?.profile_id) {
    applyData = await apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/profiles/${encodeURIComponent(profile.profile_id)}/apply`, {
      scope: "chapter",
      scope_ref_id: "CHOR01",
    });
  }
  await screenshot(page, "reference-learning-tree");
  return {
    bookId,
    runId,
    cloudPolicy: importData.book?.cloud_policy || "allow_full_cloud",
    decisions,
    learningTreeSummary: learningTree.summary,
    profileId: profile?.profile_id || null,
    profileSafety: profile?.coverage?.safety_summary || null,
    applyReviewIds: (applyData?.reviews || []).map((item) => item.review_id),
  };
}

async function exerciseReviewInbox(page, reviewIds = []) {
  const pinReviewId = `review_full_cloud_pin_${Date.now()}`;
  await apiPost("/api/v1/review-items", {
    review_id: pinReviewId,
    item_type: "calibration_candidate",
    chapter_id: "CHOR01",
    scene_id: "CHOR01_SC01",
    status: "pending",
    candidate_text: "QA pin：批准后同卡继续发布，验证审核收件箱闭环。",
    active_on_approve: 1,
    candidate_payload_json: {
      lineage_key: `CAL_FULL_CLOUD_PIN_${Date.now()}`,
      text: "证据公开前先保护活人，再分阶段发布可验证材料。",
      scope: "scene",
      scope_ref_id: "CHOR01_SC01",
      chapter_id: "CHOR01",
      scene_id: "CHOR01_SC01",
    },
  });
  await visit(page, "review", "review-inbox-view", "review-inbox");
  const pinPublished = await approveAndPublishReview(pinReviewId);
  for (const reviewId of reviewIds.filter(Boolean)) {
    const detail = await apiGet(`/api/v1/review-items/${encodeURIComponent(reviewId)}`).catch(() => null);
    if (detail?.status === "pending") {
      await approveAndPublishReview(reviewId).catch((error) =>
        result.warnings.push(
          `applied review publish deferred for ${reviewId}: ${error.message}; root cause: review verify/release gate; next step: inspect review inbox release_state`,
        ),
      );
    }
  }
  await screenshot(page, "review-inbox-after-release");
  return { pinReviewId, pinReleased: pinPublished.released === true, appliedReviewIds: reviewIds.filter(Boolean) };
}

async function createAuthorWorkspace(page) {
  await visit(page, "author", "author-workspace-view", "author-workspace");
  for (const chapter of chapters) {
    await apiPost("/api/v1/chapters", {
      chapter_id: chapter.chapter_id,
      planned_scene_count: chapter.planned_scene_count,
      mid_aggregate_enabled: 0,
      chapter_goal: chapter.chapter_goal,
      main_plot_push: chapter.main_plot_push,
      emotional_target: chapter.emotional_target,
      ending_effect: chapter.ending_effect,
      must_not: chapter.must_not,
      notes: chapter.notes,
    });
    for (const scene of chapter.scenes) {
      await apiPost("/api/v1/scenes", { ...scene, chapter_id: chapter.chapter_id });
    }
  }
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
  await visit(page, "author", "author-workspace-view", "author-workspace-created");
  recordPhase(
    "materialization",
    "api",
    "章节与场景卡经 /api/v1/chapters、/api/v1/scenes 深链创建；UI 仅作证据面板。",
  );
  return {
    chapters: chapters.map((item) => item.chapter_id),
    scenes: chapters.flatMap((item) => item.scenes.map((scene) => scene.scene_id)),
  };
}

async function approveAndPublishReview(reviewId) {
  const approved = await apiPost(`/api/v1/review-items/${encodeURIComponent(reviewId)}/approve`, {});
  const verifyJobId = (approved.job_ids || []).find((jobId) => String(jobId).startsWith("verify_"));
  if (verifyJobId) {
    await apiPost(`/api/v1/index/verify/${encodeURIComponent(verifyJobId)}/retry`, {}).catch((error) =>
      result.warnings.push(
        `verify deferred for ${reviewId}: ${error.message}; root cause: vector verify gate; next step: inspect release_state and retry verify`,
      ),
    );
  }
  if (approved.released !== true) {
    const releaseResult = await apiPost(`/api/v1/review-items/${encodeURIComponent(reviewId)}/release`, {}).catch((error) =>
      {
        if (String(error.message || "").includes("already active")) {
          return { released: true, alreadyActive: true };
        }
        result.warnings.push(
          `release deferred for ${reviewId}: ${error.message}; root cause: verify/release gate or already-active row; next step: inspect review inbox release_state`,
        );
        return null;
      },
    );
    if (releaseResult?.released === true) {
      approved.released = true;
    }
  }
  return approved;
}

async function createKnowledgeReview(spec) {
  await apiPost("/api/v1/review-items", {
    review_id: spec.review_id,
    item_type: spec.item_type,
    chapter_id: spec.chapter_id || "CHOR01",
    scene_id: spec.scene_id || "CHOR01_SC01",
    status: "pending",
    candidate_text: spec.candidate_text,
    active_on_approve: 1,
    candidate_payload_json: spec.candidate_payload_json,
  });
  const approved = await approveAndPublishReview(spec.review_id);
  return {
    reviewId: spec.review_id,
    itemType: spec.item_type,
    approvedItemId: approved.approved_item_id || null,
    released: approved.released === true,
  };
}

async function exerciseKnowledgeConsole(page) {
  await visit(page, "knowledge", "knowledge-console-view", "knowledge-console");
  const suffix = Date.now();
  const specs = [
    {
      review_id: `review_full_cloud_voice_lincen_${suffix}`,
      item_type: "voice_card_candidate",
      candidate_text: "Voice profile for Lin Cen: observant, restrained, tactile evidence first, emotional disclosure late.",
      candidate_payload_json: {
        lineage_key: "VOICE_CHAR_LINCEN",
        character_id: "CHAR_LINCEN",
        text: "Lin Cen speaks in short diagnostic sentences. She notices material traces before naming emotion.",
      },
    },
    {
      review_id: `review_full_cloud_voice_xuwang_${suffix}`,
      item_type: "voice_card_candidate",
      candidate_text: "Voice profile for Xu Wang: technical, dry humor, turns fear into measurable sound.",
      candidate_payload_json: {
        lineage_key: "VOICE_CHAR_XUWANG",
        character_id: "CHAR_XUWANG",
        text: "Xu Wang explains pressure through instruments, then lets a brief dry joke reveal unease.",
      },
    },
    {
      review_id: `review_full_cloud_relation_${suffix}`,
      item_type: "relation_card_candidate",
      candidate_text: "Relation profile: Lin Cen distrusts Xu Wang's shortcuts; Xu Wang trusts her evidence discipline.",
      candidate_payload_json: {
        lineage_key: "REL_CHAR_LINCEN_CHAR_XUWANG",
        left_character_id: "CHAR_LINCEN",
        right_character_id: "CHAR_XUWANG",
        text: "They argue about proof versus speed. Trust grows only when each protects the other's evidence chain.",
      },
    },
    {
      review_id: `review_full_cloud_style_${suffix}`,
      item_type: "style_rule_set",
      candidate_text: "Original style: clue first, explanation later; every scene changes one visible piece of evidence.",
      candidate_payload_json: {
        lineage_key: "STYLE_FULL_CLOUD_ORIGINAL",
        text: "Start with a tactile clue, postpone explanation, and let one visible consequence move the scene.",
        scope: "global",
        scope_ref_id: "global",
        rule_tier: "project",
      },
    },
    {
      review_id: `review_full_cloud_calibration_${suffix}`,
      item_type: "calibration_candidate",
      candidate_text: "Calibration: compact pressure beats, sensory evidence, no protected source names or recognizable bridges.",
      candidate_payload_json: {
        lineage_key: "CAL_FULL_CLOUD_ORIGINAL",
        text: "Use compact pressure beats, sensory evidence, delayed explanation, and explicit source-name avoidance.",
        scope: "global",
        scope_ref_id: "global",
      },
    },
  ];
  const published = [];
  for (const spec of specs) {
    published.push(await createKnowledgeReview(spec));
  }
  await screenshot(page, "knowledge-console-published");
  return { published };
  const reviewId = `review_full_cloud_style_${Date.now()}`;
  await apiPost("/api/v1/review-items", {
    review_id: reviewId,
    item_type: "style_rule_set",
    chapter_id: "CHOR01",
    scene_id: "CHOR01_SC01",
    status: "pending",
    candidate_text: "原创风格：物证先亮相，解释后置；每场用一件可触摸物推进因果；禁止源书专名、体系和同构桥段。",
    active_on_approve: 1,
    candidate_payload_json: {
      lineage_key: "STYLE_FULL_CLOUD_ORIGINAL",
      text: "物证先亮相，解释后置；情绪只经由行动、声音和证据变化外显。",
      scope: "chapter",
      scope_ref_id: "CHOR01",
      rule_tier: "project",
      chapter_id: "CHOR01",
      scene_id: "CHOR01_SC01",
    },
  });
  await apiPost(`/api/v1/review-items/${encodeURIComponent(reviewId)}/approve`, {});
  await apiPost(`/api/v1/review-items/${encodeURIComponent(reviewId)}/release`, {}).catch((error) =>
    result.warnings.push(`style release deferred: ${error.message}`),
  );
  await screenshot(page, "knowledge-console-published");
  return { published: [reviewId] };
}

async function exerciseIndexConsole(page) {
  await visit(page, "index", "index-console-view", "index-console");
  await apiPost("/api/v1/runtime/promotions/run-due", {}).catch((error) => result.warnings.push(`run-due blocked: ${error.message}`));
  await apiPost("/api/v1/runtime/recovery/sweep", {}).catch((error) => result.warnings.push(`recovery sweep blocked: ${error.message}`));
  const jobs = await apiGet("/api/v1/index/jobs?limit=20").catch(() => ({ items: [] }));
  const ledger = await apiGet("/api/v1/index/runtime-ledger?limit=10").catch(() => ({ items: [] }));
  const targetGroups = await apiGet("/api/v1/target-activity-groups?limit=10").catch(() => ({ items: [] }));
  return { jobCount: jobs.items?.length || 0, ledgerCount: ledger.items?.length || 0, targetGroupCount: targetGroups.items?.length || 0 };
}

async function pollSceneRunJob(jobId, sceneId, maxPolls = 720) {
  if (!jobId) {
    throw new Error(`scene run for ${sceneId} did not return a job id`);
  }
  let latest = null;
  for (let index = 0; index < maxPolls; index += 1) {
    latest = await apiGet(`/api/v1/run-jobs/${encodeURIComponent(jobId)}`, 30000);
    if (terminalJobStatuses.has(latest.status) || latest.finished_at) {
      return latest;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`scene run job ${jobId} for ${sceneId} did not finish; latest status ${latest?.status || "unknown"}`);
}

async function exerciseSceneWorkbench(page) {
  await visit(page, "workbench", "scene-workbench-view", "scene-workbench");
  // Wave 0：不再首败即抛错——逐场记录真实结果并继续，让结果门禁对全部计划场景判定。
  for (const chapter of chapters) {
    for (const scene of chapter.scenes) {
      const sceneId = scene.scene_id;
      const sceneStartedAt = Date.now();
      const start = await apiPost(`/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs`, {}, 30000);
      await page.getByTestId("scene-id-input").fill(sceneId).catch(() => null);
      await page.getByTestId("scene-load-button").click().catch(() => null);
      const job = await pollSceneRunJob(start.job_id, sceneId);
      const output = await collectSceneOutput(sceneId);
      const archived = job.status !== "failed" && output.sceneStatus === "archived" && Boolean(output.finalRowId);
      const blockReason = archived
        ? null
        : `job=${job.status || "unknown"} scene=${output.sceneStatus || "unknown"} ${job.error_code || ""} ${job.error_text || ""}`.trim();
      finalScenes[sceneId] = {
        runJob: job,
        attemptNo: 1,
        durationMs: Date.now() - sceneStartedAt,
        tokens: outcomeGateLib.tokensFromOutput(job, output),
        blockReason,
        ...output,
      };
      writeJson("final-scenes.json", finalScenes);
      await screenshot(page, `scene-workbench-${sceneId.toLowerCase()}`);
      if (!archived) {
        result.warnings.push(`${sceneId} did not archive; ${blockReason}`);
        appendLog({ type: "scene-job-blocker", sceneId, blockReason });
      }
    }
  }
  recordPhase(
    "scene_execution",
    "api",
    "场景运行经 /api/v1/scenes/{id}/run/jobs 深链触发；工作台 UI 仅填表与截图证据。",
  );
  recordPhase(
    "candidate_selection",
    "missing",
    "候选终选 UI 到 Wave 3 才交付；style-candidates 接口当前无前端消费者。",
  );
  recordPhase(
    "archive",
    "api",
    "归档由后端管线自动完成，无作者 UI 采纳动作。",
  );
  return finalScenes;
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
    source_safety_scan: payload.source_safety_scan || null,
    generationSummary: payload.generation_summary || null,
  };
}

async function exerciseChapterManuscripts(page) {
  await visit(page, "manuscripts", "chapter-manuscript-view", "chapter-manuscripts");
  const aggregates = {};
  for (const chapter of chapters) {
    aggregates[chapter.chapter_id] = await apiPost(
      `/api/v1/chapters/${encodeURIComponent(chapter.chapter_id)}/runtime/aggregate/final`,
      {},
      120000,
    ).catch((error) => ({ blocked: error.message }));
  }
  recordPhase(
    "chapter_aggregation",
    "api",
    "章节聚合经 /api/v1/chapters/{id}/runtime/aggregate/final 深链触发；UI 仅走查证据。",
  );
  await screenshot(page, "chapter-manuscripts-aggregate");
  return aggregates;
}

async function exerciseInteropCenter(page) {
  await visit(page, "interop", "interop-center-view", "interop-center");
  const sourceScene = finalScenes[chapters[0]?.scenes[0]?.scene_id] || {};
  const worksheetBundleId = `bundle_interop_full_cloud_${Date.now()}`;
  const worksheet = `
bundle_id: ${worksheetBundleId}
scene_id: CHOR01_SC01
chapter_id: CHOR01
hash_contract_version: BSHASH_v1
hash_alg: sha256
execution_mode: P1_scripted
created_by_action: bundle_worksheet_import
snapshot:
  contract_version: BSHASH_v1
  stage_allowlist_name: bundle_build_allowlist_v1
  scene_id: CHOR01_SC01
  chapter_id: CHOR01
  source_version_refs:
    chapter_goal: CHOR01
    scene_card: CHOR01_SC01
    style_rule_set_id: STYLE_FULL_CLOUD_ORIGINAL
  resolved_ref_ids:
    relation_ids: []
    world_rule_ids: []
    open_foreshadow_ids: []
  ordered_injections:
    - slot: chapter_goal
      ref_id: CHOR01
      digest_key: chapter_goal
    - slot: scene_card
      ref_id: CHOR01_SC01
      digest_key: scene_card
    - slot: style_rules
      ref_id: STYLE_FULL_CLOUD_ORIGINAL
      digest_key: style_rule
  inline_digests:
    chapter_goal: archive restorer receives a salt bell shard and finds altered tide records
    scene_card: CHOR01_SC01 uses a tactile clue to trigger an original investigation
    style_rule: clue first, explanation later, protected terms blocked
`.trim();
  const previewData = await apiPost("/api/v1/interop/preview/bundle-worksheet", { worksheet_yaml: worksheet }, 30000);
  const importData = await apiPost("/api/v1/interop/import/bundle-worksheet", { worksheet_yaml: worksheet }, 30000);
  const exportBundleId = sourceScene.bundleId || worksheetBundleId;
  const exportData = await apiGet(`/api/v1/interop/export/bundle-worksheet/${encodeURIComponent(exportBundleId)}`, 30000);
  const replayData = sourceScene.finalRowId
    ? await apiGet(`/api/v1/replay/final-scene/${encodeURIComponent(sourceScene.finalRowId)}`, 30000).catch((error) => ({
        blocked: error.message,
      }))
    : null;
  await screenshot(page, "interop-center-roundtrip");
  return {
    worksheetBundleId,
    previewStatus: previewData.hash_validation?.status || null,
    importedBundleId: importData.bundle?.bundle_id || null,
    exportedBundleId: exportData.bundle_id || exportBundleId,
    replayFinalRowId: sourceScene.finalRowId || null,
    replayEnvelopeBundleId: replayData?.bundle_id || null,
  };
}

async function exerciseAuthorTrash(page) {
  const suffix = String(Date.now()).slice(-8);
  const chapterId = `CHOR_TRASH_${suffix}`;
  const sceneId = `${chapterId}_SC01`;
  await apiPost("/api/v1/chapters", {
    chapter_id: chapterId,
    planned_scene_count: 1,
    mid_aggregate_enabled: 0,
    chapter_goal: "隔离测试章节：用于作者回收站移入、恢复和永久清除。",
    main_plot_push: "仅测试生命周期，不影响原创三章。",
    emotional_target: "无",
    ending_effect: "无",
    must_not: "不得被三章生成引用。",
    notes: "QA trash lifecycle.",
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
  await apiPost("/api/v1/scenes/trash", { scene_ids: [sceneId], reason: "QA trash scene lifecycle" });
  await visit(page, "trash", "author-trash-view", "author-trash");
  await apiPost("/api/v1/scenes/restore", { scene_ids: [sceneId] });
  await apiPost("/api/v1/chapters/trash", { chapter_ids: [chapterId], reason: "QA trash chapter lifecycle" });
  await apiPost("/api/v1/chapters/purge", { chapter_ids: [chapterId] });
  await screenshot(page, "author-trash-purged");
  return { chapterId, sceneId, purgedChapterId: chapterId };
}

function evaluateExperienceScores() {
  result.experienceScores = buildExperienceScores();
}

function evaluateChapterScores() {
  result.chapterScores = buildChapterScores({ chapters, finalScenes, protectedTerms });
}

function fillRootCauseFindings() {
  result.rootCauseFindings = [
    {
      issue: "one-off QA scripts can silently bind to a stale backend",
      rootCause: "hard-coded ports and one-time artifacts drift from the current .codex-run runtime",
      evidence: ".codex-run/backend.url and .codex-run/frontend.url are read before fallback defaults",
    },
    {
      issue: "reference-learning observability is hard during long LLM analysis",
      rootCause: "authors need run/round/finding/profile/application state, not raw source excerpts",
      evidence: "the runner calls /api/v1/reference-books/{book_id}/learning-tree and records the summary",
    },
    {
      issue: "source safety can regress after scene generation",
      rootCause: "final text must be scanned after bundle/final-scene materialization, not only during reference import",
      evidence: "collectSceneOutput persists source_safety_scan for every CHOR scene",
    },
  ];
  result.systemFixes = [
    {
      fix: "portable QA runner URL discovery",
      status: "implemented in this script",
      verification: "script contains .codex-run URL reads and avoids a fixed backend URL",
    },
    {
      fix: "stable artifact schema for live and final results",
      status: "implemented in this script",
      verification: "qa-live-results.json writes meta, steps, experienceScores, chapterScores, rootCauseFindings, systemFixes, screenshots, warnings, console, requestFailures",
    },
    {
      fix: "sanitized full-cloud reference workflow",
      status: "implemented in this script",
      verification: "import uses cloud_policy allow_full_cloud while reports store abstract decisions and generated output excerpts only",
    },
  ];
}

function buildReport() {
  const stepRows = result.steps
    .map((item) => `| ${item.ok ? "通过" : "阻塞"} | ${item.name} | ${Math.round(item.ms / 1000)} | ${item.ok ? "完成" : preview(item.error, 140)} |`)
    .join("\n");
  const experienceRows = Object.entries(result.experienceScores)
    .map(([name, item]) => `| ${name} | ${item.score}/10 | ${item.note} |`)
    .join("\n");
  const chapterSections = chapters
    .map((chapter) => {
      const score = result.chapterScores[chapter.chapter_id] || {};
      const sceneLines = chapter.scenes
        .map((scene) => {
          const output = finalScenes[scene.scene_id] || {};
          return `- ${scene.scene_id}：状态 ${output.sceneStatus || "not_started"}，最终行 ${output.finalRowId || "未生成"}，字数 ${(output.finalText || "").length}，tokens ${output.tokens ?? "-"}，耗时 ${output.durationMs != null ? Math.round(output.durationMs / 1000) + "s" : "-"}${output.blockReason ? `，阻断 ${preview(output.blockReason, 120)}` : ""}`;
        })
        .join("\n");
      const firstOutput = finalScenes[chapter.scenes[0]?.scene_id] || {};
      const scoreLines = score.no_draft
        ? `- 评分：无稿——不生成文学评分与来源安全结论（${score.note || "no draft"}）`
        : `- 评分：原创性 ${score.originality || 0}/10，冲突推进 ${score.conflictProgression || 0}/10，人物张力 ${score.characterTension || 0}/10，场景因果 ${score.sceneCausality || 0}/10，连续性 ${score.continuity || 0}/10，源书泄漏风险控制 ${score.sourceLeakRisk || 0}/10
- source_safety_scan：${JSON.stringify(score.source_safety_scan || null)}
- 语言质感：${score.languageTexture || 0}/10
- 人工审美备注：${score.manualRemark || "none"}
- 摘录：${preview(firstOutput.finalText || "", 360)}`;
      return `### ${chapter.chapter_id}（${chapter.scenes.length} 场）
${sceneLines}
- 章字数：${score.characters || 0}
${scoreLines}
`;
    })
    .join("\n");
  const rootCauseRows = result.rootCauseFindings
    .map((item) => `| ${item.issue} | ${item.rootCause} | ${item.evidence} |`)
    .join("\n");
  const fixRows = result.systemFixes.map((item) => `| ${item.fix} | ${item.status} | ${item.verification} |`).join("\n");
  const screenshots = result.screenshots.map((item) => `- ${item}`).join("\n") || "- 无截图";
  const gate = result.outcomeGate;
  const gateBlock = gate
    ? `## 结果门禁（唯一权威判定）

- 判定：**${gate.passed ? "通过" : "失败"}**${gate.error ? `（${gate.error}）` : ""}
- 详情：outcome-gate-verdict.md
- 语义：${expectedChapterCount} 章 × ${expectedScenesPerChapter} 场全部存在非空后端归档正文才算成稿成功；步骤表只是诊断证据。`
    : `## 结果门禁（唯一权威判定）

- 判定：**失败**（门禁未执行——运行提前中止或判定器不可用；门禁未执行不得视为通过）`;
  return `# Longzu Full-Cloud 三章闭环 QA 报告（参考安全 lane，${expectedChapterCount} 章 × ${expectedScenesPerChapter} 场）

生成时间：${new Date().toISOString()}

${gateBlock}

## 环境
- 前端：${frontendUrl}
- 后端：${apiBase}
- 操作者：${operatorRef}
- 参考书：${referencePath}
- 参考策略：allow_full_cloud
- 输出目录：${outDir}

## 步骤证据（仅诊断，不构成成稿判定）
| 结果 | 步骤 | 耗时秒 | 备注 |
| --- | --- | ---: | --- |
${stepRows}

## 资深创作者体验审查
| 功能页/链路 | 评分 | 观察 |
| --- | ---: | --- |
${experienceRows}

## 三章创作结果
${chapterSections}

## 原创性与安全扫描
- 保护词扫描：${Object.values(result.chapterScores).flatMap((item) => item.leakTerms || []).join(", ") || "未命中源书专名或受保护标记"}
- 学习树摘要：${JSON.stringify(result.steps.find((item) => item.name.includes("reference learning"))?.data?.learningTreeSummary || null)}
- 报告不保存参考书原文或长摘录，只保存抽象决策、学习树摘要、生成结果摘录与 source_safety_scan。

## 开发根因与修复
| 问题 | 根因 | 证据 |
| --- | --- | --- |
${rootCauseRows}

| 修复 | 状态 | 验证 |
| --- | --- | --- |
${fixRows}

## 截图与日志
${screenshots}
- ${path.relative(repoRoot, logPath).replace(/\\/g, "/")}

## 残余风险
- 真实云端模型质量和耗时受当前 provider 状态影响；本脚本记录真实结果，不替换为假结果。
- PowerShell 终端可能把 UTF-8 中文显示为乱码，脚本和报告均按 UTF-8 写入。
`;
}

async function main() {
  ensureOutDir();
  writeJson("qa-live-results.json", result);
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  try {
    await prepareBrowser(page);
    await step("system config preflight", preflight, { fatal: true });
    await step("system config probes", () => exerciseSystemConfig(page));
    const reference = await step("reference learning full-cloud import, learning-tree, review and apply", () => exerciseReferenceLearning(page), { fatal: true });
    await step("review inbox approve/release applied cards", () => exerciseReviewInbox(page, reference?.applyReviewIds || []));
    await step("author workspace create CHOR01..03 SC01 plans", () => createAuthorWorkspace(page), { fatal: true });
    await step("knowledge console publish original style candidate", () => exerciseKnowledgeConsole(page), { fatal: true });
    await step("index console promotions recovery ledger target activity", () => exerciseIndexConsole(page));
    await step("scene workbench run CHOR01..03 SC01 and collect source_safety_scan", () => exerciseSceneWorkbench(page), { fatal: true });
    await step("chapter manuscripts final aggregate and reading panes", () => exerciseChapterManuscripts(page));
    await step("interop center worksheet preview import export replay", () => exerciseInteropCenter(page));
    await step("author trash isolated lifecycle", () => exerciseAuthorTrash(page));
  } finally {
    await context.close().catch(() => null);
    await browser.close().catch(() => null);
    evaluateExperienceScores();
    evaluateChapterScores();
    fillRootCauseFindings();
    result.meta.finishedAt = new Date().toISOString();
    writeJson("final-scenes.json", finalScenes);
    // Wave 0：结果门禁是唯一权威判定——任一计划场景无非空归档正文即退出码非零。
    const gatePassed = runOutcomeGate();
    writeJson("qa-live-results.json", result);
    fs.writeFileSync(path.join(outDir, "report.md"), buildReport(), "utf8");
    if (!gatePassed) {
      process.exitCode = 1;
      console.error(
        `outcome gate FAIL: 要求 ${expectedChapterCount} 章 × ${expectedScenesPerChapter} 场全部存在非空后端归档正文；详见 ${path.join(outDir, "outcome-gate-verdict.md")}`,
      );
    }
  }
}

main().catch((error) => {
  ensureOutDir();
  result.meta.finishedAt = new Date().toISOString();
  result.meta.fatalError = String(error && error.stack ? error.stack : error);
  evaluateExperienceScores();
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
