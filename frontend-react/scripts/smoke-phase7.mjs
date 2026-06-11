// Phase 7 验收冒烟：控制塔桥（裁决同源 / onceTask dedupe / 归档写回）。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-phase7.mjs
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
  localStorage.setItem("ws_active_work_v1", "tide");
}, API);
await page.reload();
await page.waitForSelector(".ws-app");
await page.waitForTimeout(2500);

await check("塔与待办同源：seed 冲突 c1/c2/c3 双侧可见", async () => {
  const audit = await api("/api/v2/projects/tide/longform/audit");
  const open = audit.findings.filter(f => f.status === "open").map(f => f.finding_id);
  if (!["c1", "c2", "c3"].every(id => open.includes(id))) throw new Error(`open: ${open}`);
  const items = (await api("/api/v1/review-items?state=open&project_id=tide")).items;
  if (!items.some(i => i.dedupe_key === "canon:c1")) throw new Error("canon:c1 card missing");
  const pending = await page.evaluate(() => window.lf7PendingCanon().map(c => c.id));
  if (!pending.includes("c1")) throw new Error(`bridge pending: ${pending}`);
});

await check("待办侧裁决 c2 → 塔侧消失（finding adjudicated）", async () => {
  await page.evaluate(() => { location.hash = "#review"; });
  await page.waitForTimeout(1500);
  await page.click('.rv-item:has-text("盐钟 · 材质")');
  await page.waitForTimeout(400);
  await page.click('button:has-text("统一为「铜」并锁定")');
  await page.waitForTimeout(2000);
  const audit = await api("/api/v2/projects/tide/longform/audit");
  const c2 = audit.findings.find(f => f.finding_id === "c2");
  if (c2.status !== "adjudicated") throw new Error(`c2: ${c2.status}`);
  const ruled = await page.evaluate(async () => { await window.Lf7Bridge.__refresh(); return window.Lf7Bridge.isRuled("c2"); });
  if (!ruled) throw new Error("bridge isRuled false");
});

await check("塔侧裁决 c3（adjudicate 端点）→ 待办同条消失", async () => {
  await page.evaluate(async (apiBase) => {
    await fetch(`${apiBase}/api/v2/projects/tide/longform/audit/c3/adjudicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Idempotency-Key": "p7-adj-" + Date.now() },
      body: JSON.stringify({ decision: "accept_fix", note: "案发后第三天" }),
    });
  }, API);
  const items = (await api("/api/v1/review-items?state=open&project_id=tide")).items;
  if (items.some(i => i.dedupe_key === "canon:c3")) throw new Error("card still open");
});

await check("onceTask：同一事项重复触发只有一张卡", async () => {
  await page.evaluate(() => {
    window.Lf7Bridge.onceTask("task:backfill:ch09:脚印", { kind: "qc", priority: 2, title: "补铺垫：第二组脚印", source: "长篇控制塔", where: "第 9 章" });
    window.Lf7Bridge.onceTask("task:backfill:ch09:脚印", { kind: "qc", priority: 2, title: "补铺垫：第二组脚印", source: "长篇控制塔", where: "第 9 章" });
  });
  await page.waitForTimeout(2000);
  const items = (await api("/api/v1/review-items?state=open&project_id=tide")).items;
  if (items.filter(i => i.dedupe_key === "task:backfill:ch09:脚印").length !== 1) throw new Error("duplicate task cards");
});

await check("归档写回：契约 archived → 章状态 draft + 派生静默跳过", async () => {
  const tree = await api("/api/v2/projects/tide/catalog");
  const ch10 = tree.chapters[9];
  const base = `/api/v2/projects/tide/longform/chapters/${ch10.chapter_id}/contract`;
  await page.evaluate(async (args) => {
    const H = { "Content-Type": "application/json" };
    await fetch(args.api + args.base, { method: "PUT", headers: H, body: JSON.stringify({ constraints: [{ text: "守住盐钟材质=铜" }] }) });
    for (const s of ["ready", "dispatched"]) {
      await fetch(`${args.api}${args.base}/transition`, { method: "POST", headers: { ...H, "X-Idempotency-Key": "p7-t-" + s + Date.now() }, body: JSON.stringify({ status: s }) });
    }
    await fetch(`${args.api}${args.base}/transition`, { method: "POST", headers: { ...H, "X-Idempotency-Key": "p7-t-arch" + Date.now() }, body: JSON.stringify({ status: "archived", force: true }) });
  }, { api: API, base });
  const after = await api("/api/v2/projects/tide/catalog");
  if (after.chapters[9].state !== "draft") throw new Error(`state: ${after.chapters[9].state}`);
  const archived = await page.evaluate(async () => {
    await window.WsCatalog.__refresh();
    await new Promise(r => setTimeout(r, 800));
    return window.Lf7Bridge.isArchived(10);
  });
  if (!archived) throw new Error("bridge isArchived false");
});

await browser.close();
const uniq = [...new Set(errors)];
if (uniq.length) { console.log(`\n${uniq.length} page errors:`); uniq.slice(0, 10).forEach(e => console.log(" -", e.slice(0, 300))); }
process.exitCode = failed || uniq.length ? 1 : 0;
console.log(failed ? `\n${failed} checks failed` : "\nall checks passed");
