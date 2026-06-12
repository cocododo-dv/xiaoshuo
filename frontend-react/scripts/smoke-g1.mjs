// FE-ALIGN G1 冒烟：LF3 空降/断链/认知态接后端审计层。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-g1.mjs [BASE] [API]（前置：已 seed demo）
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
await page.waitForTimeout(2500); // 等启动水合

await check("① seed：tide findings = 3 canon + 9 LF3", async () => {
  const data = await api("/api/v2/projects/tide/longform/audit");
  const kinds = (data.findings || []).map(f => f.kind);
  if (kinds.length !== 12) throw new Error(`findings: ${kinds.length}`);
  if (kinds.filter(k => k === "unplanted_reveal").length !== 2) throw new Error("orphans wrong");
  if (kinds.filter(k => k === "causal_break").length !== 3) throw new Error("causal wrong");
  if (kinds.filter(k => k === "unfair_clue").length !== 4) throw new Error("clues wrong");
});

await check("② 水合：LF3_* 由审计层背书", async () => {
  const snap = await page.evaluate(() => ({
    orphans: (window.LF3_ORPHANS || []).length,
    causal: (window.LF3_CAUSAL || []).length,
    clues: (window.LF3_CLUES || []).length,
    o1: (window.LF3_ORPHANS || [])[0] && window.LF3_ORPHANS[0].reveal,
  }));
  if (snap.orphans !== 2 || snap.causal !== 3 || snap.clues !== 4) throw new Error(JSON.stringify(snap));
  if (!/周岚早就认识/.test(snap.o1 || "")) throw new Error(`o1: ${snap.o1}`);
});

await check("③ 塔渲染空降/断链 + canon 页不被 LF3 污染", async () => {
  await page.evaluate(() => { location.hash = "#longform"; });
  await page.waitForTimeout(1800);
  const text = await page.evaluate(() => document.body.innerText);
  if (!text.includes("空降")) throw new Error("orphan chip/board missing");
  // extraCanon 只认 drift：锚点页待统一数不应包含 9 条 LF3 findings
  const pollution = await page.evaluate(() => {
    const extras = window.Lf7Bridge ? window.Lf7Bridge.extraCanon() : [];
    return extras.filter(x => /^AUD_TIDE_(O|K|Q)/.test(x.id)).length;
  });
  if (pollution !== 0) throw new Error(`canon polluted by ${pollution} LF3 findings`);
});

await check("④ POST 新空降 → 刷新可见", async () => {
  const id = "ox-" + Date.now().toString(36);
  const tree = await api("/api/v2/projects/tide/catalog");
  const cid = tree.chapters[0].chapter_id;
  await page.evaluate(async ({ apiBase, id, cid }) => {
    await fetch(`${apiBase}/api/v2/projects/tide/longform/chapters/${cid}/audit`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Idempotency-Key": "smoke-orphan-" + id },
      body: JSON.stringify({
        finding_id: "AUD_TIDE_SMOKE_" + id,
        kind: "unplanted_reveal", severity: "warn", text: "冒烟空降：顶楼的旧无线电",
        evidence: JSON.stringify({ fe: { id, reveal: "冒烟空降：顶楼的旧无线电", revealCh: 8, sev: "medium", why: "smoke", fix: "smoke" } }),
      }),
    });
    await window.lf3SyncFromAudit();
  }, { apiBase: API, id, cid });
  const n = await page.evaluate(() => (window.LF3_ORPHANS || []).length);
  if (n !== 3) throw new Error(`orphans after post: ${n}`);
});

await browser.close();
const uniq = [...new Set(errors)];
if (uniq.length) { console.log(`\n${uniq.length} page errors:`); uniq.slice(0, 10).forEach(e => console.log(" -", e.slice(0, 300))); }
process.exitCode = failed || uniq.length ? 1 : 0;
console.log(failed ? `\n${failed} checks failed` : "\nall checks passed");
