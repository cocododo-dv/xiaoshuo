// Phase 7 验收冒烟：长篇审计与当前产品界面的真实链路
// （审计发现 → 待办收件箱 / 服务端 dedupe / 契约归档写回）。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-phase7.mjs
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
  localStorage.setItem("ws_active_work_v1", "work-a");
}, API);
await page.reload();
await page.waitForSelector(".ws-app");
await page.waitForTimeout(2500);

await check("塔与待办同源：seed 冲突 c1/c2/c3 双侧可见", async () => {
  const audit = await api("/api/v2/projects/work-a/longform/audit");
  const open = audit.findings.filter(f => f.status === "open").map(f => f.finding_id);
  if (!["c1", "c2", "c3"].every(id => open.includes(id))) throw new Error(`open: ${open}`);
  const items = (await api("/api/v1/review-items?state=open&project_id=work-a")).items;
  if (!items.some(i => i.dedupe_key === "canon:c1")) throw new Error("canon:c1 card missing");
  await page.evaluate(() => { location.hash = "#review"; });
  const card = page.locator('.rv-item:has-text("角色甲 · 年龄")');
  await card.waitFor({ state: "visible" });
});

await check("待办侧裁决 c2 → 塔侧消失（finding adjudicated）", async () => {
  await page.evaluate(() => { location.hash = "#review"; });
  await page.waitForTimeout(1500);
  await page.click('.rv-item:has-text("道具甲 · 材质")');
  await page.waitForTimeout(400);
  await page.click('button:has-text("统一为「铜」并锁定")');
  await page.waitForTimeout(2000);
  const audit = await api("/api/v2/projects/work-a/longform/audit");
  const c2 = audit.findings.find(f => f.finding_id === "c2");
  if (c2.status !== "adjudicated") throw new Error(`c2: ${c2.status}`);
  const items = (await api("/api/v1/review-items?state=open&project_id=work-a")).items;
  if (items.some(i => i.dedupe_key === "canon:c2")) throw new Error("canon:c2 card still open");
  await page.locator('.rv-item:has-text("道具甲 · 材质")').waitFor({ state: "detached" });
});

await check("塔侧裁决 c3（adjudicate 端点）→ 待办同条消失", async () => {
  await page.evaluate(async (apiBase) => {
    await fetch(`${apiBase}/api/v2/projects/work-a/longform/audit/c3/adjudicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Idempotency-Key": "p7-adj-" + Date.now() },
      body: JSON.stringify({ decision: "accept_fix", note: "案发后第三天" }),
    });
  }, API);
  const items = (await api("/api/v1/review-items?state=open&project_id=work-a")).items;
  if (items.some(i => i.dedupe_key === "canon:c3")) throw new Error("card still open");
});

await check("onceTask：同一事项重复触发只有一张卡", async () => {
  const create = () => page.evaluate(async (apiBase) => {
    const response = await fetch(`${apiBase}/api/v1/review-items`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Idempotency-Key": `p7-task-${crypto.randomUUID()}`,
      },
      body: JSON.stringify({
        project_id: "work-a",
        kind: "qc",
        priority: 2,
        title: "补铺垫：第二组脚印",
        source: "章节编排",
        where: "第 9 章",
        dedupe_key: "task:backfill:ch09:脚印",
      }),
    });
    return { status: response.status, body: await response.json() };
  }, API);
  const first = await create();
  const second = await create();
  if (first.status !== 200 || second.status !== 200) throw new Error(`create status: ${first.status}/${second.status}`);
  if (first.body.data.deduped !== false || second.body.data.deduped !== true) {
    throw new Error(`dedupe flags: ${first.body.data.deduped}/${second.body.data.deduped}`);
  }
  const items = (await api("/api/v1/review-items?state=open&project_id=work-a")).items;
  if (items.filter(i => i.dedupe_key === "task:backfill:ch09:脚印").length !== 1) throw new Error("duplicate task cards");
});

await check("归档写回：契约 archived → 章状态 draft + 派生静默跳过", async () => {
  const tree = await api("/api/v2/projects/work-a/catalog");
  const ch10 = tree.chapters[9];
  const base = `/api/v2/projects/work-a/longform/chapters/${ch10.chapter_id}/contract`;
  await page.evaluate(async (args) => {
    const request = async (url, init) => {
      const response = await fetch(url, init);
      if (!response.ok) throw new Error(`${init.method} ${url}: ${response.status} ${await response.text()}`);
    };
    const H = { "Content-Type": "application/json", "X-Idempotency-Key": `p7-contract-${crypto.randomUUID()}` };
    await request(args.api + args.base, { method: "PUT", headers: H, body: JSON.stringify({ constraints: [{ text: "守住道具甲材质=铜" }] }) });
    for (const s of ["ready", "dispatched"]) {
      await request(`${args.api}${args.base}/transition`, { method: "POST", headers: { ...H, "X-Idempotency-Key": `p7-t-${s}-${crypto.randomUUID()}` }, body: JSON.stringify({ status: s }) });
    }
    await request(`${args.api}${args.base}/transition`, { method: "POST", headers: { ...H, "X-Idempotency-Key": `p7-t-arch-${crypto.randomUUID()}` }, body: JSON.stringify({ status: "archived", force: true }) });
  }, { api: API, base });
  const after = await api("/api/v2/projects/work-a/catalog");
  if (after.chapters[9].state !== "draft") throw new Error(`state: ${after.chapters[9].state}`);
  const contract = await api(base);
  if (contract.status !== "archived" || !contract.archived_at) throw new Error(`contract: ${contract.status}`);
});

await browser.close();
const uniq = [...new Set(errors)];
if (uniq.length) { console.log(`\n${uniq.length} page errors:`); uniq.slice(0, 10).forEach(e => console.log(" -", e.slice(0, 300))); }
process.exitCode = failed || uniq.length ? 1 : 0;
console.log(failed ? `\n${failed} checks failed` : "\nall checks passed");
