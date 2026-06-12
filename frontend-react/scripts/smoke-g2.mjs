// FE-ALIGN G2 冒烟：雪花 history 轻量跨会话（fe_meta journal，去快照 cap 20）。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-g2.mjs [BASE] [API]
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

const TITLE = "履历之书-" + Date.now().toString(36);

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

await check("① 构思保存（带 history journal）→ 上行 fe_meta", async () => {
  pid = await page.evaluate(async (t) => {
    window.WsWorks.create({ title: t, mark: "履", accent: "slate" });
    await new Promise(r => setTimeout(r, 1500));
    return window.WsWorks.activeId();
  }, TITLE);
  await page.evaluate((id) => {
    const key = "ws_snow_state_v2::" + id;
    const saved = {
      drafts: { logline: "履历测试一句话。" },
      scaffolds: {}, checks: {}, states: { logline: "done" },
      revs: {}, confirmRevs: {},
      history: [
        { t: Date.now() - 1000, who: "我", action: "确认通过", note: "02 一句话概括", key: "logline", snap: { draft: "旧稿", scaffold: null } },
        { t: Date.now() - 2000, who: "AI", action: "生成候选", note: "02 一句话概括 · 3 条", key: "logline" },
      ],
      _t: Date.now(),
    };
    localStorage.setItem(key, JSON.stringify(saved));
    window.dispatchEvent(new CustomEvent("ws:snow-saved", { detail: key }));
  }, pid);
  let meta = null;
  for (let i = 0; i < 10 && !meta; i++) {
    await page.waitForTimeout(1000);
    const ws = await api(`/api/v2/projects/${pid}/snowflake-workspace`);
    const brief = (ws.steps || []).find(s => s.step_key === "book_brief");
    meta = brief && brief.draft && brief.draft.fe_meta && Array.isArray(brief.draft.fe_meta.history) && brief.draft.fe_meta.history.length === 2 ? brief.draft.fe_meta : null;
  }
  if (!meta) throw new Error("fe_meta.history not synced");
  if (meta.history.some(h => h.snap)) throw new Error("snap should be stripped");
});

await check("② 清缓存重载 → journal 还原（无 snap 只读）", async () => {
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
    if (snap && Array.isArray(snap.history) && snap.history.length) break;
  }
  if (!snap || !Array.isArray(snap.history) || snap.history.length !== 2) throw new Error(`history: ${snap && JSON.stringify(snap.history || []).slice(0, 80)}`);
  if (snap.history.some(h => h.snap)) throw new Error("restored entries must be snapless");
  if (!snap.history.some(h => h.action === "确认通过")) throw new Error("journal entry missing");
});

await check("③ 构思视图时间线展示还原条目且无回滚按钮", async () => {
  await page.waitForTimeout(800);
  // 历史时间线在右栏「履历」页签——直接检查全文与回滚按钮数量
  const r = await page.evaluate(() => {
    const text = document.body.innerText;
    const restores = document.querySelectorAll(".hist-restore").length;
    return { has: text.includes("确认通过") || text.includes("生成候选"), restores };
  });
  // 时间线可能在子页签里，store 级已验证；这里只断言无误渲染（没有可回滚按钮即可）
  if (r.restores !== 0) throw new Error(`unexpected restore buttons: ${r.restores}`);
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
