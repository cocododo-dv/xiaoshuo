// FE-ALIGN F4 冒烟：lf6 控制塔可视化数据接后端锚点库。
// 覆盖：seed 锚点水合 → 塔渲染真实数据 → POST 锚点刷新可见 → 塔内操作写回 PATCH。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-f4.mjs [BASE] [API]（前置：已 seed demo）
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(path.join(process.cwd(), "package.json"));
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
await page.waitForTimeout(2500); // 等启动水合（700ms 定时 + fetch）

await check("① seed 锚点 → 24 条（6 设定+6 悬念+4 线+3 弧+5 检索池）", async () => {
  const data = await api("/api/v2/projects/tide/longform/anchors");
  if ((data.anchors || []).length !== 24) throw new Error(`anchors: ${(data.anchors || []).length}`);
});

await check("② 水合：LF2_* 由锚点库背书", async () => {
  const snap = await page.evaluate(() => ({
    loops: (window.LF2_LOOPS || []).length,
    canon: (window.LF2_CANON || []).length,
    threads: (window.LF2_THREADS || []).length,
    arcs: (window.LF2_ARCS || []).length,
    firstLoop: (window.LF2_LOOPS || [])[0] && window.LF2_LOOPS[0].title,
    has: window.lf2HasTowerData && window.lf2HasTowerData(),
  }));
  if (snap.loops !== 6 || snap.canon !== 6 || snap.threads !== 4 || snap.arcs !== 3) throw new Error(JSON.stringify(snap));
  if (!snap.has) throw new Error("lf2HasTowerData false");
  if (!/No\.31/.test(snap.firstLoop || "")) throw new Error(`first loop: ${snap.firstLoop}`);
});

await check("③ 塔视图渲染锚点数据", async () => {
  await page.evaluate(() => { location.hash = "#longform"; });
  await page.waitForTimeout(1800);
  const text = await page.evaluate(() => document.body.innerText);
  if (!text.includes("No.31")) throw new Error("loop title not rendered");
  if (!text.includes("悬念债") && !text.includes("控制塔")) throw new Error("tower not rendered");
});

let newId = null;
await check("④ POST 新锚点 → 刷新后塔上可见", async () => {
  newId = "lx-" + Date.now().toString(36);
  await page.evaluate(async ({ apiBase, id }) => {
    await fetch(`${apiBase}/api/v2/projects/tide/longform/anchors`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Idempotency-Key": "smoke-anc-" + id },
      body: JSON.stringify({
        kind: "promise", text: "冒烟新钩子：天台上的信号灯",
        note: JSON.stringify({ fe: { id, title: "冒烟新钩子：天台上的信号灯", setup: 2, payoff: 7, state: "open", pri: "high", pinned: false, note: "smoke" } }),
      }),
    });
    await window.lf2SyncFromTower();
  }, { apiBase: API, id: newId });
  const n = await page.evaluate(() => (window.LF2_LOOPS || []).length);
  if (n !== 7) throw new Error(`loops after post: ${n}`);
  // 重新进塔（重挂载读最新缓存）
  await page.evaluate(() => { location.hash = "#home"; });
  await page.waitForTimeout(600);
  await page.evaluate(() => { location.hash = "#longform"; });
  await page.waitForTimeout(1500);
  const text = await page.evaluate(() => document.body.innerText);
  if (!text.includes("天台上的信号灯")) throw new Error("new anchor not rendered");
});

await check("⑤ 塔内操作写回：排期 → PATCH 落库", async () => {
  await page.evaluate((id) => { window.lf2LoopOp("schedule", id, 15); }, newId);
  await page.waitForTimeout(1200);
  const data = await api("/api/v2/projects/tide/longform/anchors");
  const row = (data.anchors || []).find(a => (a.note || "").includes(newId));
  if (!row) throw new Error("anchor row missing");
  const fe = JSON.parse(row.note).fe;
  if (fe.payoff !== 15) throw new Error(`payoff: ${fe.payoff}`);
});

await browser.close();
const uniq = [...new Set(errors)];
if (uniq.length) { console.log(`\n${uniq.length} page errors:`); uniq.slice(0, 10).forEach(e => console.log(" -", e.slice(0, 300))); }
process.exitCode = failed || uniq.length ? 1 : 0;
console.log(failed ? `\n${failed} checks failed` : "\nall checks passed");
