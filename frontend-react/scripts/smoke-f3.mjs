// FE-ALIGN F3 冒烟：雪花构思 ↔ snowflake-workspace v2 同步。
// 覆盖：保存上行（PATCH steps + 规范字段）→ 确认 approve → 清缓存跨会话水合。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-f3.mjs [BASE] [API]
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
const api = async (p) => (await page.evaluate(async (u) => (await fetch(u)).json(), API + p)).data;

const TITLE = "雪花之书-" + Date.now().toString(36);
const LOGLINE = "一个档案修复师发现恩师二十年来系统性改写灾难记录。";

await page.goto(BASE);
await page.evaluate((apiBase) => {
  localStorage.clear();
  localStorage.setItem("novel-system-api-base", apiBase);
  localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8000");
}, API);
await page.reload();
await page.waitForSelector(".ws-app");
await page.waitForTimeout(2000);

let pid = null;

await check("① 建书 + 构思保存上行 PATCH steps", async () => {
  pid = await page.evaluate(async (t) => {
    window.WsWorks.create({ title: t, mark: "雪", accent: "slate" });
    await new Promise(r => setTimeout(r, 1500));
    return window.WsWorks.activeId();
  }, TITLE);
  if (!pid) throw new Error("no pid");
  await page.evaluate(({ id, logline }) => {
    const key = "ws_snow_state_v2::" + id;
    const saved = {
      drafts: { logline },
      scaffolds: {
        audience: { genre: "文学悬疑", reader: "25–35 岁文学向读者", pleasure: "真相揭开时的胸口发紧", source: "克制叙述", exclude: "不靠反转密度" },
        paragraph: { premiseF: "", premiseT: "对得起死者的是活人", setup: "句一", d1: "句二", d2: "句三", d3: "句四", resolution: "句五" },
      },
      checks: {}, states: { audience: "done", logline: "done" },
      revs: { audience: 1 }, confirmRevs: {}, history: [], _t: Date.now(),
    };
    localStorage.setItem(key, JSON.stringify(saved));
    window.dispatchEvent(new CustomEvent("ws:snow-saved", { detail: key }));
  }, { id: pid, logline: LOGLINE });
  // 轮询后端直到步骤草稿带上内容
  let ok = false;
  for (let i = 0; i < 12 && !ok; i++) {
    await page.waitForTimeout(1000);
    const ws = await api(`/api/v2/projects/${pid}/snowflake-workspace`);
    const step = (ws.steps || []).find(s => s.step_key === "one_sentence_summary");
    ok = !!step && step.draft && step.draft.summary === LOGLINE && step.draft.fe_text === LOGLINE;
  }
  if (!ok) throw new Error("one_sentence_summary not synced");
});

await check("② 确认（fe_state done）→ 后端 approve", async () => {
  let ok = false;
  for (let i = 0; i < 8 && !ok; i++) {
    await page.waitForTimeout(1000);
    const ws = await api(`/api/v2/projects/${pid}/snowflake-workspace`);
    const brief = (ws.steps || []).find(s => s.step_key === "book_brief");
    const line = (ws.steps || []).find(s => s.step_key === "one_sentence_summary");
    ok = brief && brief.status === "approved" && line && line.status === "approved";
  }
  if (!ok) throw new Error("steps not approved");
});

await check("③ 跨会话：清缓存重载 → 构思从后端水合", async () => {
  await page.evaluate((args) => {
    localStorage.clear();
    localStorage.setItem("novel-system-api-base", args.api);
    localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8000");
    localStorage.setItem("ws_active_work_v1", args.pid);
  }, { api: API, pid });
  await page.reload();
  await page.waitForSelector(".ws-app");
  await page.waitForTimeout(1000);
  await page.evaluate(() => { location.hash = "#snowflake"; });
  let snap = null;
  for (let i = 0; i < 10; i++) {
    await page.waitForTimeout(1000);
    snap = await page.evaluate((id) => {
      try { return JSON.parse(localStorage.getItem("ws_snow_state_v2::" + id)); } catch (e) { return null; }
    }, pid);
    if (snap && snap.drafts && snap.drafts.logline) break;
  }
  if (!snap || !snap.drafts || snap.drafts.logline !== LOGLINE) throw new Error("logline not hydrated");
  if (!snap.scaffolds || !snap.scaffolds.audience || snap.scaffolds.audience.genre !== "文学悬疑") throw new Error("scaffold not hydrated");
  if ((snap.states || {}).audience !== "done") throw new Error(`state: ${(snap.states || {}).audience}`);
  // 主页速览读同一份缓存
  const sum = await page.evaluate(() => window.s2StepSummary && window.s2StepSummary());
  if (!sum || !sum.steps.some(s => s.s === "done")) throw new Error("step summary not reflecting");
});

await check("④ 构思视图展示水合内容", async () => {
  // 进入构思页（已在 #construct），检查一句话概括步骤的草稿出现在 DOM
  await page.evaluate(() => { window.dispatchEvent(new CustomEvent("ws:snow-step", { detail: "logline" })); });
  await page.waitForTimeout(800);
  const hasText = await page.evaluate((t) => document.body.innerText.includes(t.slice(0, 12)) ||
    Array.from(document.querySelectorAll("textarea")).some(el => (el.value || "").includes(t.slice(0, 12))), LOGLINE);
  if (!hasText) throw new Error("logline text not visible in construct view");
});

// 清理：软删 + 回收站彻底清除（残留会污染 run-smokes 批跑的回收站用例）
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
