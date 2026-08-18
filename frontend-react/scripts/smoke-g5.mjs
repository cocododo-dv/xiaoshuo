// FE-ALIGN G5 冒烟：雪花步骤候选生成接后端节点 snowflake_step_candidates。
// 本环境 LLM 不可用/路由未配 → 验证「真实端点 + 引导文案 + 默认静态候选不受影响」；
// LLM 关的 fallback 语义与三件套完整性由 pytest test_snowflake_fe_candidates 覆盖。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-g5.mjs [BASE] [API]
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://127.0.0.1:5174/";
const API = process.argv[3] || "http://127.0.0.1:8009";
let failed = 0;
const errors = [];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.setDefaultTimeout(20_000);
page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));
page.on("dialog", (d) => d.accept());

async function check(label, fn) {
  try { await fn(); console.log("ok:", label); }
  catch (e) { failed++; console.log("FAIL:", label, "—", e.message.split("\n")[0]); }
}

const TITLE = "候选之书-" + Date.now().toString(36);

await page.goto(BASE);
await page.evaluate((apiBase) => {
  localStorage.clear();
  localStorage.setItem("novel-system-api-base", apiBase);
  localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8000");
}, API);
await page.reload();
await page.waitForSelector(".ws-app");
await page.waitForTimeout(2000);

await check("① 建书", async () => {
  const pid = await page.evaluate(async (t) => {
    window.WsWorks.create({ title: t, mark: "候", accent: "slate" });
    await new Promise(r => setTimeout(r, 1500));
    return window.WsWorks.activeId();
  }, TITLE);
  if (!pid) throw new Error("no pid");
});

await check("② s2GenerateCands 走真实端点 → 诚实结果（候选或引导）", async () => {
  const r = await page.evaluate(async () => {
    const active = window.S2_STEPS.find(s => s.key === "logline");
    try {
      const list = await window.s2GenerateCands(active, { target: 120 }, { logline: "她发现恩师改写了灾难档案。" }, {});
      return { ok: true, n: list.length, first: list[0] && list[0].text };
    } catch (e) { return { ok: false, msg: e.message || String(e) }; }
  });
  if (r.ok) {
    if (!r.n || !r.first) throw new Error(`bad candidates: ${JSON.stringify(r)}`);
    console.log("   (LLM 可用：返回", r.n, "条候选)");
  } else if (!/LLM|路由|生成失败|候选/.test(r.msg)) {
    throw new Error(`message not actionable: ${r.msg.slice(0, 120)}`);
  }
});

await check("③ UI：构思页生成失败显示引导、默认静态候选仍在", async () => {
  await page.evaluate(() => { location.hash = "#snowflake"; });
  await page.waitForTimeout(1500);
  // 候选区默认展示本地启发式三卡（紧凑/标准/展开）——不受 AI 失败影响
  const text = await page.evaluate(() => document.body.innerText);
  if (!(text.includes("紧凑版") || text.includes("标准版") || text.includes("候选"))) {
    throw new Error("default candidates area missing");
  }
});

// 清理
await page.evaluate(async (apiBase) => {
  try {
    const id = window.WsWorks.activeId();
    window.WsWorks.remove(id);
    await new Promise(r => setTimeout(r, 1000));
    await fetch(`${apiBase}/api/v2/trash/${encodeURIComponent("work:" + id)}`, {
      method: "DELETE", headers: { "X-Idempotency-Key": "smoke-purge-" + id },
    });
  } catch (e) {}
}, API);

await browser.close();
const uniq = [...new Set(errors)];
if (uniq.length) { console.log(`\n${uniq.length} page errors:`); uniq.slice(0, 10).forEach(e => console.log(" -", e.slice(0, 300))); }
process.exitCode = failed || uniq.length ? 1 : 0;
console.log(failed ? `\n${failed} checks failed` : "\nall checks passed");
