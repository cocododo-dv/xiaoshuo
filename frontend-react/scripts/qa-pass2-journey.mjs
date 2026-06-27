// pass2 真实用户旅程探针（林默视角）——读 5 章成稿 + 验 #quality 跨项目污染(DEF-D) + #longform 空治理(DEF-C)。
// 非破坏：只导航/读取/切 tab，不生成/物化/送审/删除。
// 运行：cd frontend && node ../frontend-react/scripts/qa-pass2-journey.mjs [BASE] [API] [WORK]
import path from "node:path";
import fs from "node:fs";
import { createRequire } from "node:module";
const require = createRequire(path.join(process.cwd(), "package.json"));
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://127.0.0.1:5174/";
const API = process.argv[3] || "http://127.0.0.1:8000";
const WORK = process.argv[4] || "PRJ_F9EFC3DF5F";
const OUT = path.resolve("../.codex-run/qa-session-20260627-pass2");
fs.mkdirSync(path.join(OUT, "shots"), { recursive: true });

const out = { work: WORK, errors: [], net4xx5xx: [], steps: {} };
let ctx = "";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
page.setDefaultTimeout(20000);
page.on("console", (m) => { if (m.type() === "error") out.errors.push({ ctx, t: m.text().slice(0, 200) }); });
page.on("pageerror", (e) => out.errors.push({ ctx, t: "PAGEERROR " + e.message.slice(0, 200) }));
page.on("response", (r) => { const u = r.url(); if (u.includes("/api/") && r.status() >= 400) out.net4xx5xx.push({ ctx, s: r.status(), u: u.replace(API, "") }); });

await page.addInitScript((api) => {
  localStorage.setItem("novel-system-api-base", api);
  localStorage.setItem("ws_tweaks_v1", JSON.stringify({ mode: "advanced" }));
}, API);
async function waitApp() { await page.waitForSelector(".ws-app", { state: "attached" }); try { await page.evaluate(() => document.fonts.ready); } catch {} await page.waitForTimeout(500); }
async function go(view) {
  await page.evaluate((w) => localStorage.setItem("ws_active_work_v1", w), WORK);
  await page.evaluate((v) => { location.hash = "#" + v; }, view);
  await page.reload(); await waitApp(); await page.waitForTimeout(1100);
}
async function shot(n) { try { await page.screenshot({ path: path.join(OUT, "shots", n + ".png"), fullPage: false }); } catch {} }
const txt = () => page.evaluate(() => (document.querySelector(".ws-content") || document.body).innerText || "");

await page.goto(BASE); await waitApp();

// ---- 1) #manuscripts: 林默读自己的 5 章 ----
ctx = "manuscripts"; await go("manuscripts"); await shot("p2-01-manuscripts");
{
  const t = await txt();
  const chapterTitles = [...t.matchAll(/第\s*\d+\s*章[^\n]{0,30}/g)].map(m => m[0].trim());
  out.steps.manuscripts = {
    contentLen: t.length,
    chapterTitlesSeen: [...new Set(chapterTitles)].slice(0, 12),
    mentions玻璃雨: t.includes("玻璃雨"),
    wordCountHits: [...t.matchAll(/(\d[\d,]{2,})\s*字/g)].map(m => m[1]).slice(0, 10),
  };
}

// ---- 2) #quality 稿件巡检: DEF-D 跨项目污染 ----
ctx = "quality"; await go("quality"); await page.waitForTimeout(1200); await shot("p2-02-quality-overview");
{
  const t = await txt();
  // 统计页面文本里出现的项目前缀（跨项目污染证据）
  const prefixes = {};
  for (const p of ["PRJ_F9EFC3DF5F", "tide_CH", "salt_CH", "CDBQA_", "GLASS5", "DH_"]) {
    const re = new RegExp(p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
    prefixes[p] = (t.match(re) || []).length;
  }
  // 读 store 真相：overview.items 的 chapter_id 项目归属
  const ovTruth = await page.evaluate(() => {
    try {
      const st = (window.WsQuality && window.WsQuality.get && window.WsQuality.get()) || null;
      return st && st.overview ? { count: st.overview.items ? st.overview.items.length : 0 } : "no-WsQuality-store";
    } catch (e) { return "err:" + e.message; }
  });
  out.steps.quality = { contentLen: t.length, projectPrefixHitsOnPage: prefixes, storeOverview: ovTruth };
  // 切到「章组复审」tab 看选择器是否含跨项目章
  const clicked = await page.locator("text=章组复审").first().count().then(c => c ? page.locator("text=章组复审").first().click().then(()=>true).catch(()=>false) : false);
  await page.waitForTimeout(900); await shot("p2-03-quality-chapterset");
  if (clicked) {
    const t2 = await txt();
    const cross = {};
    for (const p of ["PRJ_F9EFC3DF5F", "tide_CH", "salt_CH", "CDBQA_", "GLASS5"]) cross[p] = (t2.match(new RegExp(p, "g")) || []).length;
    out.steps.quality.chapterSetPickerPrefixHits = cross;
  }
}

// ---- 3) #longform 控制塔: DEF-C 对本书空治理 ----
ctx = "longform"; await go("longform"); await page.waitForTimeout(1200); await shot("p2-04-longform");
{
  const t = await txt();
  out.steps.longform = {
    contentLen: t.length,
    mentionsEmptyish: /暂无|空|没有|0\s*条|未/.test(t),
    sample: t.slice(0, 300),
  };
}

fs.writeFileSync(path.join(OUT, "probes", "journey-findings.json"), JSON.stringify(out, null, 2));
console.log("=== pass2 journey done ===");
console.log("errors:", out.errors.length, "| net4xx5xx:", out.net4xx5xx.length);
console.log(JSON.stringify(out.steps, null, 2).slice(0, 2000));
await browser.close();
