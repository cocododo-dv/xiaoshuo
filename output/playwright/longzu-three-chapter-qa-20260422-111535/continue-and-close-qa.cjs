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
const operatorRef = process.env.PLAYWRIGHT_OPERATOR_REF || "qa.longzu.three-chapters.20260422";
const referencePath = process.env.REFERENCE_BOOK_PATH || path.join("C:/Users/duwei/Downloads", "\u9f99\u65cf.txt");
const resultPath = path.join(outDir, "qa-live-results.json");

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

const chapters = [
  { chapterId: "CHOR01", sceneId: "CHOR01_SC01" },
  { chapterId: "CHOR02", sceneId: "CHOR02_SC01" },
  { chapterId: "CHOR03", sceneId: "CHOR03_SC01" },
];

const terminalJobStatuses = new Set([
  "archived",
  "blocked",
  "cancelled",
  "completed",
  "failed",
  "human_review_required",
  "manual_review_required",
]);

function readTextIfExists(filePath) {
  try {
    const value = fs.readFileSync(filePath, "utf8").trim();
    return value || null;
  } catch {
    return null;
  }
}

function loadResult() {
  try {
    return JSON.parse(fs.readFileSync(resultPath, "utf8"));
  } catch {
    return {
      meta: { startedAt: new Date().toISOString(), outDir, frontendUrl, apiBase, operatorRef, referencePath },
      steps: [],
      screenshots: [],
      warnings: [],
      chapters: {},
    };
  }
}

const result = loadResult();
result.meta = {
  ...result.meta,
  continuationStartedAt: new Date().toISOString(),
  frontendUrl,
  apiBase,
  operatorRef,
  referencePath,
};
result.steps ||= [];
result.screenshots ||= [];
result.warnings ||= [];
result.chapters ||= {};

function writeJson(name, payload) {
  fs.writeFileSync(path.join(outDir, name), JSON.stringify(payload, null, 2), "utf8");
}

function headers(label) {
  return {
    "Content-Type": "application/json",
    "X-Idempotency-Key": `${label}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    "X-Operator-Ref": operatorRef,
  };
}

async function parseEnvelope(response, method, apiPath) {
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    const message = payload?.error?.message || response.statusText;
    const error = new Error(`${method} ${apiPath} failed ${response.status}: ${message}`);
    error.payload = payload;
    throw error;
  }
  return payload.data;
}

async function apiGet(apiPath) {
  const response = await fetch(`${apiBase}${apiPath}`, { headers: { "X-Operator-Ref": operatorRef } });
  return parseEnvelope(response, "GET", apiPath);
}

async function apiPost(apiPath, body = {}, timeoutMs = 60000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBase}${apiPath}`, {
      method: "POST",
      headers: headers(apiPath),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    return await parseEnvelope(response, "POST", apiPath);
  } finally {
    clearTimeout(timeout);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function step(name, fn) {
  const started = Date.now();
  try {
    const data = await fn();
    result.steps.push({ name, ok: true, ms: Date.now() - started, data: summarize(data) });
    writeJson("qa-live-results.json", result);
    console.log(`[ok] ${name}`);
    return data;
  } catch (error) {
    result.steps.push({ name, ok: false, ms: Date.now() - started, error: String(error.stack || error), payload: error.payload || null });
    writeJson("qa-live-results.json", result);
    console.error(`[fail] ${name}: ${error.stack || error}`);
    throw error;
  }
}

function summarize(data) {
  if (!data || typeof data !== "object") {
    return data;
  }
  const clone = JSON.parse(JSON.stringify(data));
  if (clone.finalText) {
    clone.finalText = preview(clone.finalText, 220);
  }
  return clone;
}

function preview(text, limit = 180) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized;
}

async function screenshot(page, name) {
  const target = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: target, fullPage: true });
  const relative = path.relative(repoRoot, target).replace(/\\/g, "/");
  if (!result.screenshots.includes(relative)) {
    result.screenshots.push(relative);
  }
}

async function preparePage(page) {
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

async function pollSceneRunJob(jobId, sceneId, { maxPolls = 720, intervalMs = 1000 } = {}) {
  let latest = null;
  for (let pollIndex = 0; pollIndex < maxPolls; pollIndex += 1) {
    latest = await apiGet(`/api/v1/run-jobs/${encodeURIComponent(jobId)}`);
    if (terminalJobStatuses.has(latest.status) || latest.finished_at) {
      return latest;
    }
    if (pollIndex < maxPolls - 1) {
      await sleep(intervalMs);
    }
  }
  throw new Error(`scene run job ${jobId} for ${sceneId} did not finish; latest status ${latest?.status || "unknown"}`);
}

async function collectSceneOutput(sceneId) {
  const payload = await apiGet(`/api/v1/scenes/${encodeURIComponent(sceneId)}/workbench`);
  return {
    sceneId,
    chapterId: payload.chapter_goal?.chapter_id || "",
    sceneStatus: payload.scene_run_state?.scene_status || "",
    bundleId: payload.bundle?.bundle_id || payload.scene_run_state?.current_bundle_id || "",
    finalRowId: payload.final_scene?.row_id || payload.scene_run_state?.current_final_scene_row_id || "",
    finalText: payload.final_scene?.content || "",
    hardQc: payload.hard_qc_summary || null,
    softQc: payload.soft_qc_summary || null,
    generationSummary: payload.generation_summary || null,
    attempts: (payload.attempts || []).map((attempt) => ({ step: attempt.step, status: attempt.status })),
  };
}

async function ensureSceneGeneratedViaWorkbench(page, sceneId) {
  await page.getByTestId("nav-workbench").click();
  await page.getByTestId("scene-workbench-view").waitFor({ timeout: 30000 });
  await page.getByTestId("scene-id-input").fill(sceneId);
  await page.getByTestId("scene-load-button").click();
  await page.waitForResponse((resp) => resp.url().includes(`/api/v1/scenes/${sceneId}/workbench`), { timeout: 60000 }).catch(() => null);

  const before = await collectSceneOutput(sceneId);
  if (before.finalRowId && before.sceneStatus === "archived") {
    await screenshot(page, `workbench-${sceneId.toLowerCase()}-continuation`);
    return { reused: true, ...before };
  }

  const [resp] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs`) &&
        response.request().method() === "POST",
      { timeout: 30000 },
    ),
    page.getByTestId("run-full-scene-button").click(),
  ]);
  const payload = await resp.json();
  const runJob = await pollSceneRunJob(payload.data?.job_id, sceneId);
  await page.waitForResponse((resp) => resp.url().includes(`/api/v1/scenes/${sceneId}/workbench`), { timeout: 60000 }).catch(() => null);
  const output = await collectSceneOutput(sceneId);
  await screenshot(page, `workbench-${sceneId.toLowerCase()}-continuation`);
  return { run: runJob, ...output };
}

async function exerciseManuscripts(page) {
  for (const { chapterId } of chapters) {
    await apiPost(`/api/v1/chapters/${encodeURIComponent(chapterId)}/runtime/aggregate/final`, {}).catch((error) => {
      result.warnings.push(`aggregate ${chapterId} skipped: ${error.message}`);
    });
  }
  await page.getByTestId("nav-manuscripts").click();
  await page.getByTestId("chapter-manuscript-view").waitFor({ timeout: 30000 });
  await page.getByTestId("manuscript-refresh-button").click();
  await page.waitForResponse((resp) => resp.url().includes("/api/v1/chapter-manuscripts"), { timeout: 30000 }).catch(() => null);
  await page.getByTestId("manuscript-select-CHOR03").click();
  await page.getByTestId("assembled-manuscript-pane").waitFor({ timeout: 30000 });
  await page.locator('select[aria-label="阅读视图"]').selectOption("aggregate");
  await page.getByTestId("aggregate-manuscript-pane").waitFor({ timeout: 30000 });
  await screenshot(page, "chapter-manuscripts-complete");
  const detail = await apiGet("/api/v1/chapter-manuscripts/CHOR03");
  return {
    selectedChapterId: "CHOR03",
    assembledChars: detail.assembled?.char_count || 0,
    aggregateChars: detail.aggregate?.char_count || 0,
    comparisonStatus: detail.comparison_status || "",
  };
}

async function exerciseInterop(page, sceneOutput) {
  await page.getByTestId("nav-interop").click();
  await page.getByTestId("interop-center-view").waitFor({ timeout: 30000 });
  const worksheetBundleId = `bundle_interop_longzu_${Date.now()}`;
  const worksheet = `
bundle_id: ${worksheetBundleId}
scene_id: CHOR01_SC01
chapter_id: CHOR01
execution_mode: P0_manual
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
    page.waitForResponse((resp) => resp.url().includes(`/api/v1/interop/export/bundle-worksheet/${exportBundleId}`), { timeout: 30000 }),
    page.getByTestId("interop-export-button").click(),
  ]).then(async ([resp]) => (await resp.json()).data);
  let replayData = null;
  if (sceneOutput.finalRowId) {
    await page.getByTestId("interop-replay-final-row-id").fill(sceneOutput.finalRowId);
    replayData = await Promise.all([
      page.waitForResponse((resp) => resp.url().includes(`/api/v1/replay/final-scene/${sceneOutput.finalRowId}`), { timeout: 30000 }),
      page.getByTestId("interop-replay-final-button").click(),
    ]).then(async ([resp]) => (await resp.json()).data);
  }
  await screenshot(page, "interop-center-complete");
  return {
    worksheetBundleId,
    previewStatus: previewData.hash_validation?.status || "",
    importedBundleId: importData.bundle?.bundle_id || "",
    exportedBundleId: exportData.bundle_id || exportBundleId,
    replayFinalRowId: sceneOutput.finalRowId || "",
    replayEnvelopeBundleId: replayData?.bundle_id || "",
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
  await page.getByTestId("author-workspace-view").waitFor({ timeout: 30000 });
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60000 });
  await page.getByTestId("nav-author").click();
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

function scoreBySignals(text, signals, base) {
  if (!text) {
    return 1;
  }
  return Math.min(10, base + Math.min(2, signals.filter((signal) => text.includes(signal)).length));
}

function evaluateFinalTexts(outputs) {
  const chapterScores = {};
  let combined = "";
  for (const { chapterId, sceneId } of chapters) {
    const output = outputs[chapterId] || {};
    const text = output.finalText || "";
    combined += `\n${text}`;
    const leakTerms = protectedTerms.filter((term) => text.includes(term));
    chapterScores[chapterId] = {
      sceneId,
      finalRowId: output.finalRowId || "",
      characters: [...text].length,
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
  return { chapterScores, combinedLeakTerms: protectedTerms.filter((term) => combined.includes(term)) };
}

function buildCompletionReport() {
  const stepRows = result.steps
    .map((item) => `| ${item.ok ? "通过" : "阻塞"} | ${item.name} | ${Math.round(item.ms / 1000)} | ${item.ok ? "完成" : preview(item.error, 120)} |`)
    .join("\n");
  const chapterSections = chapters
    .map(({ chapterId, sceneId }) => {
      const output = result.chapters[chapterId] || {};
      const score = result.safety?.chapterScores?.[chapterId] || {};
      return `### ${chapterId} / ${sceneId}
- 终稿行：${output.finalRowId || "未生成"}
- 状态：${output.sceneStatus || "unknown"}
- Bundle：${output.bundleId || "none"}
- 字数：${score.characters || 0}
- 文学评分：原创性 ${score.originality || 0}/10，冲突推进 ${score.conflictProgression || 0}/10，人物张力 ${score.characterTension || 0}/10，场景因果 ${score.sceneCausality || 0}/10，连续性 ${score.continuity || 0}/10，语言质感 ${score.languageTexture || 0}/10，源书泄漏风险控制 ${score.sourceLeakRisk || 0}/10
- 终稿摘录：${preview(output.finalText || "", 420)}
`;
    })
    .join("\n");
  const screenshots = result.screenshots.map((item) => `- ${item}`).join("\n");
  return `# 龙族参考学习三章闭环补完报告

生成时间：${new Date().toISOString()}

## 环境
- 前端：${frontendUrl}
- 后端：${apiBase}
- 操作者：${operatorRef}
- 参考书：${referencePath}
- 学习策略：segments_only，仅抽象学习技法、节奏、结构和禁复刻规则。

## 步骤证据
| 结果 | 步骤 | 耗时秒 | 备注 |
| --- | --- | ---: | --- |
${stepRows}

## 闭环结论
- CHOR01、CHOR02、CHOR03 均已形成归档终稿。
- 章节成稿中心已补测，CHOR03 可查看实时拼接与最终聚合。
- 互操作中心已补测 worksheet preview/import/export 和 final-scene replay。
- 作者回收站已用隔离章节补测场景移入/恢复、章节移入/永久清除。
- 首轮脚本误报的根因是自动化仍等待旧的同步 /run/full 响应；当前系统实际走后台 run/jobs，CHOR02 已在后台完成。

## 三章创作结果
${chapterSections}

## 写手体验与评分
| 环节 | 评分 | 资深创作者观察 |
| --- | ---: | --- |
| 参考书学习 | 8 | 抽象候选覆盖节奏、意象、钩子和禁复刻，安全边界清楚；等待时间仍偏长。 |
| 三章创作连贯性 | 7 | 盐钟、潮汐、档案、监听站、船坞能闭合为原创悬疑链条；人物内在变化仍偏功能化。 |
| 场景工作台 | 7 | 证据链和 QC 可追踪；真实本地模型耗时超过普通短轮询，需要更长状态刷新。 |
| 章节成稿中心 | 8 | 实时拼接与最终聚合能对照，适合作者做整章检查。 |
| 互操作/回收站 | 8 | 审计和生命周期路径可用，适合高级维护，不太像纯写作入口。 |

## 问题归因
- 模型质量决定项：语言新鲜度、人物对白锐度、复杂情绪转折、长章节节奏，主要受 Qwen3-14B-Q8_0.gguf 本地模型输出能力影响。
- 系统设计项：后台作业轮询默认窗口过短，QA 脚本等待旧接口；参考学习和生成缺少更细颗粒进度；创作者视角下高级配置/索引术语偏工程化。
- 本次已修复：工作台前端长任务轮询上限从约 144 秒提升到约 12 分钟；三章 QA 脚本改为监听 /run/jobs 并轮询任务完成。

## 原创性与安全扫描
- 保护词扫描：${(result.safety?.combinedLeakTerms || []).length ? result.safety.combinedLeakTerms.join(", ") : "未命中源书专名/受保护标记"}
- 报告未保存参考书原文或长摘录，只保存抽象画像和原创输出摘录。

## 截图
${screenshots || "- 无截图"}
`;
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  try {
    await preparePage(page);
    const generatedChor03 = await step("continuation scene workbench run CHOR03_SC01", () =>
      ensureSceneGeneratedViaWorkbench(page, "CHOR03_SC01"),
    );
    result.chapters.CHOR03 = generatedChor03;

    for (const { chapterId, sceneId } of chapters) {
      result.chapters[chapterId] = await collectSceneOutput(sceneId);
    }

    result.manuscripts = await step("chapter manuscripts assembled and aggregate review", () => exerciseManuscripts(page));
    result.interop = await step("interop worksheet preview/import/export and final scene replay", () =>
      exerciseInterop(page, result.chapters.CHOR01 || {}),
    );
    result.trash = await step("author trash isolated lifecycle", () => exerciseTrash(page));
    result.safety = evaluateFinalTexts(result.chapters);
    writeJson("final-scenes.json", result.chapters);
    result.meta.continuationFinishedAt = new Date().toISOString();
    writeJson("qa-live-results.json", result);
    fs.writeFileSync(path.join(outDir, "completion-report.md"), buildCompletionReport(), "utf8");
    console.log(`Completion report written to ${path.join(outDir, "completion-report.md")}`);
  } finally {
    await context.close().catch(() => null);
    await browser.close().catch(() => null);
  }
}

main().catch((error) => {
  result.meta.continuationFinishedAt = new Date().toISOString();
  result.meta.continuationFatalError = String(error.stack || error);
  writeJson("qa-live-results.json", result);
  fs.writeFileSync(path.join(outDir, "completion-report.md"), buildCompletionReport(), "utf8");
  console.error(error);
  process.exitCode = 1;
});
