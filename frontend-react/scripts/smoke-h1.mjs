// FE-ALIGN H1 冒烟：记忆预算可检索池接锚点库（faded 池 → LF3_RETRIEVE）。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-h1.mjs [BASE] [API]（前置：已 seed demo）
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

await page.goto(BASE);
await page.evaluate((apiBase) => {
  localStorage.clear();
  localStorage.setItem("novel-system-api-base", apiBase);
  localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8000");
}, API);
await page.reload();
await page.waitForSelector(".ws-app");
await page.waitForTimeout(2500); // 等启动水合

await check("① seed：24 锚点（19 + 5 条 faded 检索池）", async () => {
  const data = await api("/api/v2/projects/tide/longform/anchors");
  const rows = data.anchors || [];
  if (rows.length !== 24) throw new Error(`anchors: ${rows.length}`);
  if (rows.filter(a => a.status === "faded").length !== 5) throw new Error("faded count wrong");
});

await check("② 投影：LF3_RETRIEVE 由锚点库背书、不混入 LF2_CANON", async () => {
  const snap = await page.evaluate(() => ({
    rv: (window.LF3_RETRIEVE || []).length,
    first: (window.LF3_RETRIEVE || [])[0] && window.LF3_RETRIEVE[0].text,
    canon: (window.LF2_CANON || []).length,
  }));
  if (snap.rv !== 5) throw new Error(`retrieve: ${snap.rv}`);
  if (!/钟摆声/.test(snap.first || "")) throw new Error(`first: ${snap.first}`);
  if (snap.canon !== 6) throw new Error(`canon polluted: ${snap.canon}`);
});

await check("③ 塔记忆面板渲染真实检索池", async () => {
  await page.evaluate(() => { location.hash = "#longform"; });
  await page.waitForTimeout(1800);
  const text = await page.evaluate(() => document.body.innerText);
  if (!text.includes("钟摆声")) throw new Error("pool item not rendered");
});

await check("④ POST 新 faded 锚点 → 刷新池可见", async () => {
  const id = "rvx-" + Date.now().toString(36);
  await page.evaluate(async ({ apiBase, id }) => {
    const created = await (await fetch(`${apiBase}/api/v2/projects/tide/longform/anchors`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Idempotency-Key": "smoke-rv-" + id },
      body: JSON.stringify({
        kind: "setting", text: "冒烟池条目：顶楼信号灯的频率",
        note: JSON.stringify({ fe: { id, text: "冒烟池条目：顶楼信号灯的频率", ch: 8, tone: "slate", reason: "smoke", pool: "retrieve" } }),
      }),
    })).json();
    // create 默认 pinned → 补一刀 PATCH 成 faded（池语义）
    await fetch(`${apiBase}/api/v2/projects/tide/longform/anchors/${created.data.anchor_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-Idempotency-Key": "smoke-rv-p-" + id },
      body: JSON.stringify({ status: "faded" }),
    });
    await window.lf2SyncFromTower();
  }, { apiBase: API, id });
  const n = await page.evaluate(() => (window.LF3_RETRIEVE || []).length);
  if (n !== 6) throw new Error(`pool after post: ${n}`);
});

await browser.close();
const uniq = [...new Set(errors)];
if (uniq.length) { console.log(`\n${uniq.length} page errors:`); uniq.slice(0, 10).forEach(e => console.log(" -", e.slice(0, 300))); }
process.exitCode = failed || uniq.length ? 1 : 0;
console.log(failed ? `\n${failed} checks failed` : "\nall checks passed");
