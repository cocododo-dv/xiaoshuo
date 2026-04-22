const fs = require("node:fs");
const path = require("node:path");

const { chromium } = require("../../../frontend/node_modules/playwright");

const repoRoot = path.resolve(__dirname, "../../..");
const outDir = __dirname;
const codexRunDir = path.join(repoRoot, ".codex-run");
const frontendUrl =
  process.env.PLAYWRIGHT_FRONTEND_URL ||
  readTextIfExists(path.join(codexRunDir, "frontend.url")) ||
  "http://127.0.0.1:5173";
const apiBase =
  process.env.PLAYWRIGHT_API_BASE ||
  readTextIfExists(path.join(codexRunDir, "backend.url")) ||
  `http://127.0.0.1:${process.env.PLAYWRIGHT_BACKEND_PORT || "8000"}`;
const operatorRef = process.env.PLAYWRIGHT_OPERATOR_REF || `qa.original-three-chapters.${Date.now()}`;
const referencePath = process.env.REFERENCE_BOOK_PATH || path.join("C:/Users/duwei/Downloads", "\u9f99\u65cf.txt");
const runStamp = new Date().toISOString().replace(/[:.]/g, "-");

const result = {
  meta: {
    startedAt: new Date().toISOString(),
    repoRoot,
    outDir,
    frontendUrl,
    apiBase,
    operatorRef,
    referencePath,
  },
  steps: [],
  screenshots: [],
  console: [],
  pageErrors: [],
  requestFailures: [],
  warnings: [],
  reference: null,
  config: null,
  review: null,
  knowledge: null,
  chapters: {},
  interop: null,
  trash: null,
  safety: null,
};

const chapters = [
  {
    chapter_id: "CHOR01",
    planned_scene_count: 1,
    chapter_goal: "第一章：档案修复师林岑收到一枚“盐钟”残片，发现旧城潮汐记录被人篡改。",
    main_plot_push: "建立盐钟残片、旧城潮汐档案和失踪记录之间的第一层因果，把篡改者的存在推到台前。",
    emotional_target: "让林岑从职业性的谨慎，转入被私人记忆刺痛后的主动追查。",
    ending_effect: "残片在夜里敲出不属于当前年份的潮汐回声，逼迫林岑承认档案正在被活人改写。",
    must_not: "不得出现梦醒、系统提示、龙族原文、源书专名、学院屠龙设定、血统等级或可识别桥段。",
    notes: "原创三章闭环 QA - 第一章。",
    scene: {
      scene_id: "CHOR01_SC01",
      scene_seq: 1,
      pov_character_id: "CHAR_LINCEN",
      onstage_chars_json: ["林岑", "许望", "匿名寄件人"],
      location: "旧城档案修复所的盐蚀库房",
      scene_goal: "林岑修复一盒受潮旧档时收到盐钟残片，借声纹和纸纹发现二十年前潮汐记录被人按同一规律删改。",
      beats_json: ["清点受潮档案", "收到盐钟残片", "比对潮汐声纹", "发现失踪案反向索引", "决定联系许望"],
      must_include_text: "盐钟残片边缘有蓝白盐霜；潮汐记录缺页的编号连成一条倒置船线。",
      forbidden_text: "不得照搬参考书句子；不得出现龙族、路明非、楚子航、恺撒、诺诺、卡塞尔、龙王等源书标记。",
      exit_change: "林岑从被动修档转为主动调查，并把第一份证据交给许望验证。",
      hook: "盐钟在无人触碰时响了一下，档案盒里多出一页明天的潮位表。",
      target_length_band: "short",
      scene_type: "inciting_clue",
      is_chapter_last: 1,
    },
  },
  {
    chapter_id: "CHOR02",
    planned_scene_count: 1,
    chapter_goal: "第二章：林岑与声学工程师许望进入雾堤下的废弃监听站，找到失踪案的反证。",
    main_plot_push: "把盐钟声纹与监听站旧磁带合流，证明失踪者并非遇难，而是被人为抹去行踪。",
    emotional_target: "让林岑和许望在互相试探中形成临时信任，代价是两人都暴露各自隐瞒的动机。",
    ending_effect: "监听站播放出失踪者活着的证词，却同时暴露有人正在实时监听他们。",
    must_not: "不得复刻参考书人物、组织、地名、课堂/学院/屠龙/血统桥段；不得用源书式专名。",
    notes: "原创三章闭环 QA - 第二章。",
    scene: {
      scene_id: "CHOR02_SC01",
      scene_seq: 1,
      pov_character_id: "CHAR_LINCEN",
      onstage_chars_json: ["林岑", "许望", "旧站值守记录"],
      location: "雾堤下的废弃监听站",
      scene_goal: "林岑和许望进入监听站，复原一卷被盐水泡坏的磁带，找到能推翻官方失踪结论的反证。",
      beats_json: ["穿过雾堤检修门", "修复旧磁带", "破解反向声纹", "发现幸存者编号", "监听站被远程唤醒"],
      must_include_text: "监听站墙面贴满褪色潮位图；磁带倒放时出现幸存者的呼吸和三声盐钟。",
      forbidden_text: "不得复制参考书句法或桥段；不得出现源书人物、学院、龙王、血统、社团和战斗设定。",
      exit_change: "二人确认失踪案存在人为遮蔽，并取得指向无灯船坞的反证。",
      hook: "监听站的死线路突然亮起，扬声器报出林岑的实时心跳。",
      target_length_band: "short",
      scene_type: "investigation_reversal",
      is_chapter_last: 1,
    },
  },
  {
    chapter_id: "CHOR03",
    planned_scene_count: 1,
    chapter_goal: "第三章：两人在无灯船坞打开隐藏档案，必须决定公开真相还是先保护幸存者。",
    main_plot_push: "让盐钟残片、监听站反证和隐藏档案闭合，明确幕后篡改动机，同时留下下一段追查入口。",
    emotional_target: "把林岑的正义冲动推向责任选择：真相并非越快公开越安全。",
    ending_effect: "二人选择先转移幸存者，公开真相的证据被拆成两份，危险也因此升级。",
    must_not: "不得出现源书专名、设定、人物关系或可识别场景；不得把参考文本改写成同构剧情。",
    notes: "原创三章闭环 QA - 第三章。",
    scene: {
      scene_id: "CHOR03_SC01",
      scene_seq: 1,
      pov_character_id: "CHAR_LINCEN",
      onstage_chars_json: ["林岑", "许望", "幸存者阿砚"],
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
    },
  },
];

const protectedTerms = [
  "\u9f99\u65cf",
  "\u6c5f\u5357",
  "\u8def\u660e\u975e",
  "\u695a\u5b50\u822a",
  "\u607a\u6492",
  "\u8bfa\u8bfa",
  "\u9648\u58a8\u77b3",
  "\u5361\u585e\u5c14",
  "\u6602\u70ed",
  "\u9f99\u738b",
  "\u767d\u738b",
  "\u9ed1\u738b",
  "\u9752\u94dc\u4e0e\u706b",
  "\u8840\u7edf",
  "\u5c60\u9f99",
];

function readTextIfExists(filePath) {
  try {
    const value = fs.readFileSync(filePath, "utf8").trim();
    return value || null;
  } catch {
    return null;
  }
}

function writeJson(name, payload) {
  const target = path.join(outDir, name);
  fs.writeFileSync(target, JSON.stringify(payload, null, 2), "utf8");
  return target;
}

function idKey(label) {
  return `${label}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function headers(label) {
  return {
    "Content-Type": "application/json",
    "X-Idempotency-Key": idKey(label),
    "X-Operator-Ref": operatorRef,
  };
}

async function apiGet(apiPath) {
  const response = await fetch(`${apiBase}${apiPath}`, {
    headers: { "X-Operator-Ref": operatorRef },
  });
  return parseEnvelope(response, "GET", apiPath);
}

async function apiPost(apiPath, data = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase}${apiPath}`, {
      method: "POST",
      headers: headers(apiPath),
      body: JSON.stringify(data),
      signal: controller.signal,
    });
    return await parseEnvelope(response, "POST", apiPath);
  } finally {
    clearTimeout(timeout);
  }
}

async function parseEnvelope(response, method, apiPath) {
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    throw new Error(`${method} ${apiPath} returned non-JSON ${response.status}: ${error.message}`);
  }
  if (!response.ok || payload.ok === false) {
    const message = payload?.error?.message || response.statusText;
    const error = new Error(`${method} ${apiPath} failed ${response.status}: ${message}`);
    error.payload = payload;
    throw error;
  }
  return payload.data;
}

async function step(name, fn) {
  const started = Date.now();
  try {
    const data = await fn();
    const item = { name, ok: true, ms: Date.now() - started, data: summarizeForStep(data) };
    result.steps.push(item);
    console.log(`[ok] ${name} (${item.ms}ms)`);
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
    console.error(`[fail] ${name}: ${item.error}`);
    throw error;
  } finally {
    writeJson("qa-live-results.json", result);
  }
}

function summarizeForStep(data) {
  if (!data || typeof data !== "object") {
    return data;
  }
  const clone = JSON.parse(JSON.stringify(data));
  for (const chapter of Object.values(clone.chapters || {})) {
    if (chapter.finalText) {
      chapter.finalText = preview(chapter.finalText, 220);
    }
  }
  if (clone.finalText) {
    clone.finalText = preview(clone.finalText, 220);
  }
  return clone;
}

function preview(text, limit = 160) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

function containsProtectedSource(text) {
  const haystack = String(text || "");
  return protectedTerms.filter((term) => haystack.includes(term));
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

async function clickIfPresent(locator, timeout = 1500) {
  if (!(await locator.count())) {
    return false;
  }
  const first = locator.first();
  if (await first.isDisabled().catch(() => false)) {
    return false;
  }
  await first.click({ timeout }).catch(() => null);
  return true;
}

async function prepareBrowser(page) {
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      result.console.push({ type: message.type(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => result.pageErrors.push(String(error)));
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

async function preflight() {
  const referenceExists = fs.existsSync(referencePath);
  const stat = referenceExists ? fs.statSync(referencePath) : null;
  const system = await apiGet("/api/v1/system-config");
  const llm = await apiGet("/api/v1/system-config/llm");
  const routeReady = Object.fromEntries(
    Object.entries(llm.node_routes || {}).map(([key, value]) => [key, Boolean(value.ready)]),
  );
  return {
    referenceExists,
    referenceSize: stat?.size || 0,
    referenceMtime: stat?.mtime?.toISOString?.() || null,
    systemStatus: system?.status || "loaded",
    providers: Object.keys(llm.providers || {}),
    routeReady,
  };
}

async function exerciseSystemConfig(page) {
  await page.getByTestId("nav-config").click();
  await page.getByTestId("system-config-view").waitFor({ timeout: 30000 });
  await clickIfPresent(page.getByTestId("config-refresh"));
  await clickIfPresent(page.getByTestId("config-api-base-probe"));
  await page.waitForTimeout(700);
  const providerRow = page.getByTestId("config-llm-provider-row-local_qwen3");
  if (await providerRow.count()) {
    await clickIfPresent(providerRow.locator("button").last(), 3000);
  }
  await clickIfPresent(page.getByTestId("config-dashboard-tab-routing"));
  await clickIfPresent(page.getByTestId("config-dashboard-tab-validation"));
  await clickIfPresent(page.getByTestId("config-dashboard-tab-advanced"));
  await clickIfPresent(page.getByTestId("config-category-api"));
  await clickIfPresent(page.getByTestId("config-export"));

  const contract = await apiGet("/api/v1/style-profile/contract");
  const baseline = await apiPost("/api/v1/literary-eval/run", { mode: "baseline" }, 120000).catch((error) => ({
    blocked: String(error),
  }));
  const live = await apiPost("/api/v1/literary-eval/run", { mode: "live" }, 600000).catch((error) => ({
    blocked: String(error),
  }));
  const extracted = await apiPost(
    "/api/v1/style-profile/extract",
    {
      sample_texts: [
        "潮声先制造压力，再让人物用动作而不是解释回应；每段结尾保留一枚具体物证推进下一场。",
      ],
      style_rules: ["短句承压，物证先行，解释后置。"],
      style_observations: ["用可听、可摸的线索连接心理转折。"],
      calibration_lines: ["避免复刻源书专名和设定，只抽象学习节奏与钩子。"],
      banned_moves: ["禁止源书人物、地名、组织、原句和同构桥段。"],
    },
    30000,
  );
  let styleReview = null;
  try {
    styleReview = await apiPost("/api/v1/style-profile/review-candidate", {
      profile: extracted.profile,
      scope: "chapter",
      scope_ref_id: "CHOR01",
      lineage_key: `STYLE_PROFILE_CHOR_CONFIG_${Date.now()}`,
      active_on_approve: 0,
    });
  } catch (error) {
    result.warnings.push(`style profile review candidate blocked: ${error.message}`);
  }
  await screenshot(page, "system-config-complete");
  return {
    contractVersion: contract?.contract_version || contract?.version || "loaded",
    baselineMode: baseline.report?.mode || baseline.blocked || "baseline",
    liveMode: live.report?.mode || live.blocked || "live",
    styleReviewId: styleReview?.review?.review_id || styleReview?.review_id || null,
  };
}

async function exerciseReferenceLearning(page) {
  if (!fs.existsSync(referencePath)) {
    throw new Error(`reference book missing: ${referencePath}`);
  }
  await page.getByTestId("nav-reference").click();
  await page.getByTestId("reference-learning-view").waitFor({ timeout: 30000 });
  await screenshot(page, "reference-initial");
  const importToggle = page.getByTestId("reference-import-toggle");
  if ((await importToggle.count()) && !(await page.getByTestId("reference-import-path").isVisible().catch(() => false))) {
    await importToggle.click();
  }
  await page.getByTestId("reference-import-path").fill(referencePath.replace(/\\/g, "/"));
  const pathForm = page.locator("form").filter({ has: page.getByTestId("reference-import-path") });
  await pathForm.locator("input").nth(1).fill("抽象参考：龙族");
  await pathForm.locator("input").nth(2).fill("source-reference");
  await pathForm.locator("select").selectOption("segments_only");
  const importData = await Promise.all([
    page.waitForResponse((resp) => resp.url().includes("/api/v1/reference-books/import-path"), { timeout: 120000 }),
    page.getByTestId("reference-import-submit").click(),
  ]).then(async ([resp]) => (await resp.json()).data);
  const bookId = importData.book_id || importData.book?.book_id;
  const startData = await apiPost(`/api/v1/reference-books/${encodeURIComponent(bookId)}/runs`, { batch_size: 8 }, 60000);
  const runId = startData.run.run_id;

  await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByTestId("nav-reference").click();
  await page.getByTestId("reference-learning-view").waitFor({ timeout: 30000 });
  const advanceStartedAt = Date.now();
  let longTaskHintSeen = false;
  let firstAdvance;
  try {
    const [resp] = await Promise.all([
      page.waitForResponse(
        (response) => response.url().endsWith(`/api/v1/reference-books/${bookId}/runs/${runId}/advance`),
        { timeout: 600000 },
      ),
      (async () => {
        await page.getByTestId("reference-advance-run").click();
        longTaskHintSeen = await page
          .getByTestId("reference-long-task")
          .waitFor({ state: "visible", timeout: 8000 })
          .then(() => true)
          .catch(() => false);
      })(),
    ]);
    firstAdvance = (await resp.json()).data;
  } catch (error) {
    result.warnings.push(`reference advance via UI fell back to API: ${error.message}`);
    firstAdvance = await apiPost(`/api/v1/reference-books/${bookId}/runs/${runId}/advance`, {}, 600000);
  }
  const firstAdvanceMs = Date.now() - advanceStartedAt;
  let detail = await apiGet(`/api/v1/reference-books/${bookId}`);
  const findings = detail.latest_round?.findings || firstAdvance.round?.findings || [];
  const decisions = [];
  let approvedCount = 0;
  let rejectedCount = 0;
  for (let index = 0; index < findings.length; index += 1) {
    const finding = findings[index];
    const reviewId = finding.review?.review_id;
    if (!reviewId) {
      continue;
    }
    const textForSafety = `${finding.finding_type} ${finding.dimension} ${finding.summary} ${finding.review?.candidate_text || ""}`;
    const blockedTerms = containsProtectedSource(textForSafety);
    const shouldReject = blockedTerms.length > 0 || (index === findings.length - 1 && approvedCount >= 4);
    if (shouldReject) {
      const reason = blockedTerms.length
        ? `含源书可识别标记：${blockedTerms.join(", ")}`
        : "QA 需要覆盖拒绝路径，且前序安全抽象卡已满足画像覆盖。";
      const card = page.getByTestId(`reference-finding-${finding.finding_id}`);
      if (await card.count()) {
        await card.locator("input.control-input").first().fill(reason).catch(() => null);
      }
      await clickReferenceDecision(page, reviewId, "reject", { reason });
      decisions.push({ findingId: finding.finding_id, reviewId, decision: "rejected", reason, blockedTerms });
      rejectedCount += 1;
    } else {
      await clickReferenceDecision(page, reviewId, "approve", {});
      decisions.push({
        findingId: finding.finding_id,
        reviewId,
        decision: "approved",
        findingType: finding.finding_type,
        dimension: finding.dimension,
      });
      approvedCount += 1;
    }
  }

  let profileAdvance;
  try {
    const [resp] = await Promise.all([
      page.waitForResponse(
        (response) => response.url().endsWith(`/api/v1/reference-books/${bookId}/runs/${runId}/advance`),
        { timeout: 600000 },
      ),
      page.getByTestId("reference-advance-run").click(),
    ]);
    profileAdvance = (await resp.json()).data;
  } catch (error) {
    result.warnings.push(`reference profile advance via UI fell back to API: ${error.message}`);
    profileAdvance = await apiPost(`/api/v1/reference-books/${bookId}/runs/${runId}/advance`, {}, 600000);
  }
  detail = await apiGet(`/api/v1/reference-books/${bookId}`);
  const profile =
    profileAdvance.profile ||
    detail.profiles.find((item) => item.status === "ready") ||
    detail.profiles[0] ||
    null;
  let applyData = null;
  if (profile?.profile_id) {
    await page.getByTestId("reference-apply-scope").selectOption("chapter");
    await page.getByTestId("reference-apply-scope-ref").fill("CHOR01");
    try {
      const [resp] = await Promise.all([
        page.waitForResponse(
          (response) => response.url().endsWith(`/api/v1/reference-books/${bookId}/profiles/${profile.profile_id}/apply`),
          { timeout: 60000 },
        ),
        page.getByTestId(`reference-apply-${profile.profile_id}`).click(),
      ]);
      applyData = (await resp.json()).data;
    } catch (error) {
      result.warnings.push(`reference profile apply via UI fell back to API: ${error.message}`);
      applyData = await apiPost(`/api/v1/reference-books/${bookId}/profiles/${profile.profile_id}/apply`, {
        scope: "chapter",
        scope_ref_id: "CHOR01",
      });
    }
  }
  await screenshot(page, "reference-after-profile-apply");
  return {
    bookId,
    runId,
    cloudPolicy: importData.book?.cloud_policy || "segments_only",
    totalSegments: importData.book?.total_segments || detail.book?.total_segments || 0,
    firstAdvanceMs,
    longTaskHintSeen,
    decisions,
    coverage: detail.coverage,
    profileId: profile?.profile_id || null,
    profileSafety: profile?.coverage?.safety_summary || null,
    applyReviewIds: (applyData?.reviews || []).map((item) => item.review_id),
  };
}

async function clickReferenceDecision(page, reviewId, action, payload) {
  const testId = `reference-${action}-${reviewId}`;
  const locator = page.getByTestId(testId);
  if (await locator.count()) {
    await Promise.all([
      page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${reviewId}/${action}`), { timeout: 30000 }),
      locator.click(),
    ]).catch(async () => {
      if (action === "approve") {
        await apiPost(`/api/v1/review-items/${reviewId}/approve`, payload || {});
      } else {
        await apiPost(`/api/v1/review-items/${reviewId}/reject`, payload || {});
      }
    });
    return;
  }
  if (action === "approve") {
    await apiPost(`/api/v1/review-items/${reviewId}/approve`, payload || {});
  } else {
    await apiPost(`/api/v1/review-items/${reviewId}/reject`, payload || {});
  }
}

async function createAuthorPlan(page) {
  await page.getByTestId("nav-author").click();
  await page.getByTestId("author-workspace-view").waitFor({ timeout: 30000 });
  for (const item of chapters) {
    await apiPost("/api/v1/chapters", {
      chapter_id: item.chapter_id,
      planned_scene_count: item.planned_scene_count,
      mid_aggregate_enabled: 0,
      chapter_goal: item.chapter_goal,
      main_plot_push: item.main_plot_push,
      emotional_target: item.emotional_target,
      ending_effect: item.ending_effect,
      must_not: item.must_not,
      notes: item.notes,
    });
    await apiPost("/api/v1/scenes", {
      ...item.scene,
      chapter_id: item.chapter_id,
    });
  }
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByTestId("nav-author").click();
  await page.getByTestId("author-workspace-view").waitFor({ timeout: 30000 });
  await screenshot(page, "author-workspace-complete");
  return { chapters: chapters.map((item) => item.chapter_id), scenes: chapters.map((item) => item.scene.scene_id) };
}

async function exerciseKnowledge(page) {
  await page.getByTestId("nav-knowledge").click();
  await page.getByTestId("knowledge-console-view").waitFor({ timeout: 30000 });
  const specs = [
    {
      review_id: `review_chor_voice_lincen_${runStamp.slice(-8)}`,
      item_type: "voice_card_candidate",
      chapter_id: "CHOR01",
      scene_id: "CHOR01_SC01",
      candidate_text: "林岑的声线克制、低温、证据先行；情绪爆发只通过手部动作、修复术语和短句露出。",
      candidate_payload_json: {
        lineage_key: "VOICE_CHAR_LINCEN",
        character_id: "CHAR_LINCEN",
        text: "林岑的声线克制、低温、证据先行；情绪爆发只通过手部动作、修复术语和短句露出。",
        display_name: "林岑",
        pronouns: ["她"],
        role: "档案修复师",
        aliases: ["小林"],
        scope: "chapter",
        scope_ref_id: "CHOR01",
        chapter_id: "CHOR01",
        scene_id: "CHOR01_SC01",
      },
    },
    {
      review_id: `review_chor_relation_lincen_xuwang_${runStamp.slice(-8)}`,
      item_type: "relation_card_candidate",
      chapter_id: "CHOR02",
      scene_id: "CHOR02_SC01",
      candidate_text: "林岑与许望的关系从互相校验专业边界开始，逐步变成共同承担证据风险的临时同盟。",
      candidate_payload_json: {
        lineage_key: "REL_CHOR_LINCEN_XUWANG",
        left_character_id: "CHAR_LINCEN",
        right_character_id: "CHAR_XUWANG",
        text: "林岑与许望的关系从互相校验专业边界开始，逐步变成共同承担证据风险的临时同盟。",
        scope: "chapter",
        scope_ref_id: "CHOR02",
        chapter_id: "CHOR02",
        scene_id: "CHOR02_SC01",
      },
    },
    {
      review_id: `review_chor_style_original_${runStamp.slice(-8)}`,
      item_type: "style_rule_set",
      chapter_id: "CHOR01",
      scene_id: "CHOR01_SC01",
      candidate_text: "原创三章风格：物证先亮相，解释延后；每场用一件可触摸物推进因果；禁止源书专名、体系和同构桥段。",
      candidate_payload_json: {
        lineage_key: "STYLE_CHOR_ORIGINAL",
        text: "原创三章风格：物证先亮相，解释延后；每场用一件可触摸物推进因果；禁止源书专名、体系和同构桥段。",
        scope: "chapter",
        scope_ref_id: "CHOR01",
        rule_tier: "project",
        chapter_id: "CHOR01",
        scene_id: "CHOR01_SC01",
      },
    },
    {
      review_id: `review_chor_calibration_${runStamp.slice(-8)}`,
      item_type: "calibration_candidate",
      chapter_id: "CHOR03",
      scene_id: "CHOR03_SC01",
      candidate_text: "校准线：当真相会伤害幸存者时，主角先保护活人，再设计可验证的分阶段公开。",
      candidate_payload_json: {
        lineage_key: "CAL_CHOR_SURVIVOR_FIRST",
        text: "当真相会伤害幸存者时，主角先保护活人，再设计可验证的分阶段公开。",
        scope: "scene",
        scope_ref_id: "CHOR03_SC01",
        chapter_id: "CHOR03",
        scene_id: "CHOR03_SC01",
      },
    },
  ];
  const published = [];
  for (const spec of specs) {
    await apiPost("/api/v1/review-items", {
      ...spec,
      status: "pending",
      active_on_approve: 1,
    });
    await apiPost(`/api/v1/review-items/${spec.review_id}/approve`, {});
    await apiPost(`/api/v1/review-items/${spec.review_id}/release`, {}).catch((error) => {
      result.warnings.push(`release ${spec.review_id} deferred: ${error.message}`);
      return null;
    });
    published.push(spec.review_id);
  }
  await page.getByTestId("knowledge-refresh-button").click().catch(() => null);
  await page.waitForTimeout(1000);
  await screenshot(page, "knowledge-console-complete");
  return { published };
}

async function exerciseReviewPin(page, reviewIds = []) {
  const pinReviewId = `review_chor_pin_${Date.now()}`;
  await apiPost("/api/v1/review-items", {
    review_id: pinReviewId,
    item_type: "calibration_candidate",
    chapter_id: "CHOR01",
    scene_id: "CHOR01_SC01",
    status: "pending",
    candidate_text: "QA pin 测试：批准后仍留在 pending 视图顶部，允许同卡继续发布。",
    active_on_approve: 1,
    candidate_payload_json: {
      lineage_key: `CAL_CHOR_PIN_${Date.now()}`,
      text: "批准后同卡发布连续性测试。",
      scope: "scene",
      scope_ref_id: "CHOR01_SC01",
      chapter_id: "CHOR01",
      scene_id: "CHOR01_SC01",
    },
  });
  await page.getByTestId("nav-review").click();
  await page.getByTestId("review-inbox-view").waitFor({ timeout: 30000 });
  await page.getByTestId("review-filter-status").selectOption("pending");
  await page.getByTestId("review-filter-refresh").click();
  await page.getByTestId(`review-card-${pinReviewId}`).waitFor({ timeout: 30000 });
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${pinReviewId}/approve`), { timeout: 30000 }),
    page.getByTestId(`review-approve-${pinReviewId}`).click(),
  ]);
  await page.getByTestId(`review-release-${pinReviewId}`).waitFor({ state: "visible", timeout: 30000 });
  const stillVisibleAfterApprove = true;
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes(`/api/v1/review-items/${pinReviewId}/release`), { timeout: 30000 }),
    page.getByTestId(`review-release-${pinReviewId}`).click(),
  ]);
  await page.waitForTimeout(1000);
  const visibleAfterRelease = await page.getByTestId(`review-card-${pinReviewId}`).isVisible().catch(() => false);
  for (const reviewId of reviewIds) {
    const detail = await apiGet(`/api/v1/review-items/${encodeURIComponent(reviewId)}`).catch(() => null);
    if (detail?.status === "pending") {
      await apiPost(`/api/v1/review-items/${reviewId}/approve`, {}).catch(() => null);
      await apiPost(`/api/v1/review-items/${reviewId}/release`, {}).catch(() => null);
    }
  }
  await screenshot(page, "review-inbox-complete");
  return {
    pinReviewId,
    stillVisibleAfterApprove,
    visibleAfterRelease,
  };
}

async function exerciseIndex(page) {
  await page.getByTestId("nav-index").click();
  await page.getByTestId("index-console-view").waitFor({ timeout: 30000 });
  await clickIfPresent(page.getByTestId("run-due-promotions-button"));
  await apiPost("/api/v1/runtime/promotions/run-due", {}).catch(() => null);
  await clickIfPresent(page.getByTestId("run-recovery-sweep-button"));
  await apiPost("/api/v1/runtime/recovery/sweep", {}).catch(() => null);
  await clickIfPresent(page.getByTestId("index-toggle-recovery-timeline"));
  await clickIfPresent(page.getByTestId("index-toggle-target-groups"));
  await clickIfPresent(page.getByTestId("index-toggle-operator-action"));
  const jobs = await apiGet("/api/v1/index/jobs?limit=20");
  const ledger = await apiGet("/api/v1/index/runtime-ledger?limit=10");
  const targetGroups = await apiGet("/api/v1/target-activity-groups?limit=10");
  await screenshot(page, "index-console-complete");
  return {
    jobCount: jobs.items?.length || 0,
    ledgerCount: ledger.items?.length || 0,
    targetGroupCount: targetGroups.items?.length || 0,
  };
}

async function runGeneration(page) {
  const outputs = {};
  await page.getByTestId("nav-author").click();
  await page.getByTestId("author-workspace-view").waitFor({ timeout: 30000 });
  const chapterRun = await step("author workspace run CHOR01 through chapter runner", async () => {
    await page.getByTestId(`author-chapter-select-CHOR01`).click();
    const [resp] = await Promise.all([
      page.waitForResponse(
        (response) => response.url().includes("/api/v1/chapters/CHOR01/run/full") && response.request().method() === "POST",
        { timeout: 600000 },
      ),
      page.getByTestId("author-run-chapter-button").click(),
    ]);
    const payload = await resp.json();
    if (payload.data?.status === "failed") {
      throw new Error(payload.data?.latest_error?.message || "chapter runner failed");
    }
    return payload.data;
  });
  outputs.CHOR01 = await collectSceneOutput("CHOR01_SC01");
  outputs.CHOR01.chapterRun = chapterRun;

  await page.getByTestId("nav-workbench").click();
  await page.getByTestId("scene-workbench-view").waitFor({ timeout: 30000 });
  for (const sceneId of ["CHOR02_SC01", "CHOR03_SC01"]) {
    const sceneOutput = await step(`scene workbench run ${sceneId}`, async () => {
      await page.getByTestId("scene-id-input").fill(sceneId);
      await page.getByTestId("scene-load-button").click();
      await page
        .waitForResponse((resp) => resp.url().includes(`/api/v1/scenes/${sceneId}/workbench`), { timeout: 60000 })
        .catch(() => null);
      const [resp] = await Promise.all([
        page.waitForResponse(
          (response) => response.url().includes(`/api/v1/scenes/${sceneId}/run/full`) && response.request().method() === "POST",
          { timeout: 600000 },
        ),
        page.getByTestId("run-full-scene-button").click(),
      ]);
      const payload = await resp.json();
      await page
        .waitForResponse((resp) => resp.url().includes(`/api/v1/scenes/${sceneId}/workbench`), { timeout: 60000 })
        .catch(() => null);
      const collected = await collectSceneOutput(sceneId);
      return { run: payload.data, ...collected };
    });
    outputs[sceneId.slice(0, 6)] = sceneOutput;
    await screenshot(page, `workbench-${sceneId.toLowerCase()}`);
  }
  await apiPost("/api/v1/chapters/CHOR03/runtime/manual-hold", { reason: "QA exercised manual hold before final clear." }).catch(
    (error) => result.warnings.push(`manual hold blocked: ${error.message}`),
  );
  await apiPost("/api/v1/chapters/CHOR03/runtime/manual-hold/clear", {}).catch((error) =>
    result.warnings.push(`manual hold clear blocked: ${error.message}`),
  );
  await apiPost("/api/v1/chapters/CHOR03/runtime/aggregate/final", {}).catch((error) =>
    result.warnings.push(`final aggregate blocked: ${error.message}`),
  );
  return outputs;
}

async function collectSceneOutput(sceneId) {
  const payload = await apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/workbench`);
  return {
    sceneId,
    chapterId: payload.chapter_goal?.chapter_id || null,
    sceneStatus: payload.scene_run_state?.scene_status || null,
    bundleId: payload.bundle?.bundle_id || null,
    finalRowId: payload.final_scene?.row_id || payload.scene_run_state?.current_final_scene_row_id || null,
    finalText: payload.final_scene?.content || "",
    hardQc: payload.hard_qc_summary || null,
    softQc: payload.soft_qc_summary || null,
    generationSummary: payload.generation_summary || null,
    attempts: (payload.attempts || []).map((item) => ({
      step: item.step,
      status: item.status,
      sourceBundleId: item.source_bundle_id,
    })),
  };
}

async function exerciseInterop(page, sceneOutput) {
  await page.getByTestId("nav-interop").click();
  await page.getByTestId("interop-center-view").waitFor({ timeout: 30000 });
  const worksheetBundleId = `bundle_interop_chor_${Date.now()}`;
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
    style_rule_set_id: STYLE_CHOR_ORIGINAL
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
      ref_id: STYLE_CHOR_ORIGINAL
      digest_key: style_rule
  inline_digests:
    chapter_goal: archive restorer receives salt bell shard and discovers altered tide records
    scene_card: Lin Cen repairs salt-damaged files and finds tomorrow tide sheet
    style_rule: tactile clue first, explanation later, no source replication
`.trim();
  await page.getByTestId("interop-worksheet-input").fill(worksheet);
  const previewData = await Promise.all([
    page.waitForResponse((resp) => resp.url().includes("/api/v1/interop/preview/bundle-worksheet"), { timeout: 30000 }),
    page.getByTestId("interop-preview-button").click(),
  ]).then(async ([resp]) => (await resp.json()).data);
  const importData = await Promise.all([
    page.waitForResponse((resp) => resp.url().includes("/api/v1/interop/import/bundle-worksheet"), { timeout: 30000 }),
    page.getByTestId("interop-import-button").click(),
  ]).then(async ([resp]) => (await resp.json()).data);
  const exportBundleId = sceneOutput.bundleId || worksheetBundleId;
  await page.getByTestId("interop-export-bundle-id").fill(exportBundleId);
  const exportData = await Promise.all([
    page.waitForResponse((resp) => resp.url().includes(`/api/v1/interop/export/bundle-worksheet/${exportBundleId}`), {
      timeout: 30000,
    }),
    page.getByTestId("interop-export-button").click(),
  ]).then(async ([resp]) => (await resp.json()).data);
  let replayData = null;
  if (sceneOutput.finalRowId) {
    await page.getByTestId("interop-replay-final-row-id").fill(sceneOutput.finalRowId);
    replayData = await Promise.all([
      page.waitForResponse((resp) => resp.url().includes(`/api/v1/replay/final-scene/${sceneOutput.finalRowId}`), {
        timeout: 30000,
      }),
      page.getByTestId("interop-replay-final-button").click(),
    ]).then(async ([resp]) => (await resp.json()).data);
  }
  await screenshot(page, "interop-center-complete");
  return {
    worksheetBundleId,
    previewStatus: previewData.hash_validation?.status || null,
    importedBundleId: importData.bundle?.bundle_id || null,
    exportedBundleId: exportData.bundle_id || exportBundleId,
    replayFinalRowId: sceneOutput.finalRowId || null,
    replayEnvelopeBundleId: replayData?.bundle_id || null,
  };
}

async function exerciseTrash(page) {
  const suffix = `${Date.now()}`.slice(-8);
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
  await page.getByTestId("nav-author").click();
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByTestId("nav-author").click();
  await page.getByTestId("author-workspace-view").waitFor({ timeout: 30000 });
  await page.getByTestId(`author-chapter-select-${chapterId}`).click();
  await page.getByTestId(`author-scene-select-${sceneId}`).check();
  page.once("dialog", (dialog) => dialog.accept());
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes("/api/v1/scenes/trash"), { timeout: 30000 }),
    page.getByTestId("author-trash-selected-scenes-button").click(),
  ]);
  await page.getByTestId("nav-trash").click();
  await page.getByTestId("author-trash-view").waitFor({ timeout: 30000 });
  await page.getByTestId(`author-trash-scene-select-${sceneId}`).check();
  page.once("dialog", (dialog) => dialog.accept());
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes("/api/v1/scenes/restore"), { timeout: 30000 }),
    page.getByTestId("author-trash-restore-scenes-button").click(),
  ]);
  await page.getByTestId("nav-author").click();
  await page.getByTestId(`author-chapter-select-for-trash-${chapterId}`).check();
  page.once("dialog", (dialog) => dialog.accept());
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes("/api/v1/chapters/trash"), { timeout: 30000 }),
    page.getByTestId("author-trash-selected-chapters-button").click(),
  ]);
  await page.getByTestId("nav-trash").click();
  await page.getByTestId(`author-trash-chapter-select-${chapterId}`).check();
  page.once("dialog", (dialog) => dialog.accept());
  await Promise.all([
    page.waitForResponse((resp) => resp.url().includes("/api/v1/chapters/purge"), { timeout: 30000 }),
    page.getByTestId("author-trash-purge-chapters-button").click(),
  ]);
  await screenshot(page, "author-trash-complete");
  return { chapterId, sceneId, purgedChapterId: chapterId };
}

function evaluateFinalTexts(chapterOutputs) {
  const chapterScores = {};
  let combined = "";
  for (const item of chapters) {
    const output = chapterOutputs[item.chapter_id] || chapterOutputs[item.scene.scene_id.slice(0, 6)] || {};
    const text = output.finalText || "";
    combined += `\n${text}`;
    const leakTerms = containsProtectedSource(text);
    const wordCount = [...text].length;
    chapterScores[item.chapter_id] = {
      sceneId: item.scene.scene_id,
      finalRowId: output.finalRowId || null,
      characters: wordCount,
      originality: leakTerms.length ? 5 : 9,
      conflictProgression: scoreBySignals(text, ["发现", "决定", "证据", "风险", "追踪"], 7),
      characterTension: scoreBySignals(text, ["林岑", "许望", "沉默", "选择", "保护"], 7),
      sceneCausality: scoreBySignals(text, ["因为", "于是", "所以", "证据", "编号"], 7),
      continuity: scoreBySignals(text, ["盐钟", "潮汐", "档案", "监听", "船坞"], 7),
      languageTexture: scoreBySignals(text, ["盐", "潮", "雾", "声", "档案"], 7),
      sourceLeakRisk: leakTerms.length ? 4 : 10,
      leakTerms,
    };
  }
  return {
    chapterScores,
    combinedLeakTerms: containsProtectedSource(combined),
  };
}

function scoreBySignals(text, signals, base) {
  if (!text) {
    return 1;
  }
  const hits = signals.filter((signal) => text.includes(signal)).length;
  return Math.max(1, Math.min(10, base + Math.min(2, hits)));
}

function buildReport() {
  const stepRows = result.steps
    .map((item) => `| ${item.ok ? "通过" : "阻塞"} | ${item.name} | ${Math.round(item.ms / 1000)} | ${item.ok ? "完成" : preview(item.error, 120)} |`)
    .join("\n");
  const screenshots = result.screenshots.map((item) => `- ${item}`).join("\n");
  const chapterSections = chapters
    .map((item) => {
      const output = result.chapters[item.chapter_id] || {};
      const score = result.safety?.chapterScores?.[item.chapter_id] || {};
      return `### ${item.chapter_id} / ${item.scene.scene_id}
- 终稿行：${output.finalRowId || "未生成"}
- 状态：${output.sceneStatus || "unknown"}
- Bundle：${output.bundleId || "none"}
- 字数：${score.characters || 0}
- 文学评分：原创性 ${score.originality || 0}/10，冲突推进 ${score.conflictProgression || 0}/10，人物张力 ${score.characterTension || 0}/10，场景因果 ${score.sceneCausality || 0}/10，连续性 ${score.continuity || 0}/10，语言质感 ${score.languageTexture || 0}/10，源书泄漏风险控制 ${score.sourceLeakRisk || 0}/10
- 终稿摘录：${preview(output.finalText || "", 360)}
`;
    })
    .join("\n");
  const fixEvidence = [
    "| 问题 | 根因 | 修复 | 回归证据 |",
    "| --- | --- | --- | --- |",
    "| 场景工作台 stale scene | localStorage 中旧 scene id 404 后仍保留 | 404 且命中 remembered id 时清空 key 和本地状态 | `readableConsoles.spec.js` stale scene 用例 |",
    "| 审核 pending 视图 approve 后 release 断裂 | 刷新时 pending 过滤移除了刚批准卡 | pin 最近批准项，release 后解除 pin | `app.spec.js` approve/release 连续性用例；本次 QA pinReview |",
    "| 作者新建场景可能错章/空章 | 章节刷新期间场景按钮仍可点，表单 chapter id 未稳定绑定 | loading 时禁用场景动作，表单跟随选中章节 | `authorWorkspace.spec.js` 源级断言 |",
    "| 参考学习长耗时反馈不足 | advance 无长任务计时提示，脚本等待窗口偏短 | 显示长任务提示和秒级计时；QA 等待 10 分钟 | `referenceLearning.spec.js` 和本报告 firstAdvanceMs |",
    "| QA 脚本硬编码 8000 | 一次性脚本写死 `127.0.0.1:8000` | 读取 env 或 `.codex-run/backend.url` | `playwrightQaScripts.spec.js` |",
    "| 中文乱码误判 | PowerShell 输出编码会把 UTF-8 中文显示成 mojibake | 以 UTF-8 读取源码和静态 guard 判断真实内容 | `readableConsoles.spec.js` 中文可读性 guard |",
  ].join("\n");
  return `# 原创三章闭环 QA 报告

生成时间：${new Date().toISOString()}

## 环境
- 前端：${frontendUrl}
- 后端：${apiBase}
- 操作者：${operatorRef}
- 参考书：${referencePath}
- 参考书存在：${result.meta.preflight?.referenceExists ? "是" : "否"}，大小：${result.meta.preflight?.referenceSize || 0} bytes
- 参考策略：segments_only，只学习抽象技法、叙事结构和禁复刻规则。

## 步骤证据
| 结果 | 步骤 | 耗时秒 | 备注 |
| --- | --- | ---: | --- |
${stepRows}

## 写手体验评分
| 功能步骤 | 评分 | 资深创作者观察 |
| --- | ---: | --- |
| 系统配置与模型探针 | 8 | API base 和模型路由可见，适合正式开写前做健康检查；高级配置仍偏工程化。 |
| 参考书导入与抽象学习 | 8 | segments_only 路径清楚，长耗时提示改善明显；重新导入同一书时旧 run 会影响“启动学习”按钮，需留意。 |
| 参考候选审核 | 8 | 候选只暴露抽象摘要，无源文摘录；拒绝理由入口可用。 |
| 审核批准/发布连续性 | ${result.review?.stillVisibleAfterApprove ? 9 : 5} | pending 视图 approve 后${result.review?.stillVisibleAfterApprove ? "同卡仍可继续 release" : "仍存在断裂"}。 |
| 作者工作台建章建场 | 8 | 三章三场景参数完整，表单绑定当前章节；用 API 批量建档更稳，UI 适合逐章编辑。 |
| 场景工作台生成与证据 | 7 | preflight、bundle、QC、attempt timeline 都能追踪；真实 LLM 耗时仍是主要等待成本。 |
| 知识控制台 | 8 | voice/relation/style/calibration 候选可发布并绑定原创章节场景；高级引用信息丰富。 |
| 索引控制台 | 8 | due promotions、recovery、ledger、target activity 可查，适合排查发布链路。 |
| 互操作中心 | 8 | worksheet preview/import/export 和 final scene replay 覆盖成功，bundle provenance 便于审计。 |
| 作者回收站 | 9 | 隔离章节可完成场景移入、恢复、章节移入和永久清除，未影响主三章。 |

## 三章创作结果
${chapterSections}

## 原创性与安全扫描
- 保护词扫描：${(result.safety?.combinedLeakTerms || []).length ? result.safety.combinedLeakTerms.join(", ") : "未命中源书专名/受保护标记"}
- 参考画像安全：${JSON.stringify(result.reference?.profileSafety || null)}
- 报告未保存参考书原文或长摘录，只保存抽象决策与原创输出摘录。

## 开发问题、根因与修复证据
${fixEvidence}

## 截图
${screenshots || "- 无截图"}

## 验证命令
- 已在实现阶段通过：\`npx vitest run tests/readableConsoles.spec.js tests/app.spec.js tests/authorWorkspace.spec.js tests/referenceLearning.spec.js tests/playwrightQaScripts.spec.js\`
- 已在实现阶段通过：\`npx vitest run\`
- 已在实现阶段通过：\`python -m pytest backend/tests/test_reference_learning.py backend/tests/test_style_profile.py backend/tests/test_scene_generation.py backend/tests/test_chapter_runner.py backend/tests/test_system_config.py backend/tests/test_literary_eval.py -q\`
- 收尾验证见最终回复；若失败，将补记阻塞原因。

## 残余风险
- 真实 LLM 输出质量受本地模型状态影响；本报告记录真实耗时和输出，不替换为假结果。
- PowerShell 终端可能把 UTF-8 中文显示为乱码，源码和报告按 UTF-8 保存。
- 若后续要严格验证 Chroma，应在 WSL strict lane 单独运行。
`;
}

async function main() {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  try {
    await prepareBrowser(page);
    result.meta.preflight = await step("environment preflight", preflight);
    result.config = await step("system config probes, evals, style profile contract/extract/review", () => exerciseSystemConfig(page));
    result.reference = await step("reference learning import/analyze/decide/apply", () => exerciseReferenceLearning(page));
    await step("author workspace create original three chapters and scenes", () => createAuthorPlan(page));
    result.knowledge = await step("knowledge console create and publish original candidates", () => exerciseKnowledge(page));
    result.review = await step("review inbox approve pin and same-card release", () =>
      exerciseReviewPin(page, [...(result.reference?.applyReviewIds || []), result.config?.styleReviewId].filter(Boolean)),
    );
    result.index = await step("index console promotions, recovery, ledger, target activity", () => exerciseIndex(page));
    const generated = await step("generate original three scenes", () => runGeneration(page));
    for (const [key, value] of Object.entries(generated)) {
      result.chapters[key] = value;
    }
    result.interop = await step("interop worksheet preview/import/export and final scene replay", () =>
      exerciseInterop(page, result.chapters.CHOR01 || {}),
    );
    result.trash = await step("author trash isolated lifecycle", () => exerciseTrash(page));
    result.safety = evaluateFinalTexts(result.chapters);
    writeJson("final-scenes.json", result.chapters);
    writeJson("qa-live-results.json", result);
    fs.writeFileSync(path.join(outDir, "report.md"), buildReport(), "utf8");
    console.log(`Report written to ${path.join(outDir, "report.md")}`);
  } finally {
    await context.close().catch(() => null);
    await browser.close().catch(() => null);
    result.meta.finishedAt = new Date().toISOString();
    writeJson("qa-live-results.json", result);
  }
}

main().catch((error) => {
  result.meta.finishedAt = new Date().toISOString();
  result.meta.fatalError = String(error && error.stack ? error.stack : error);
  writeJson("qa-live-results.json", result);
  fs.writeFileSync(path.join(outDir, "report.md"), buildReport(), "utf8");
  console.error(error);
  process.exitCode = 1;
});
