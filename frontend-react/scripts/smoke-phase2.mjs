// Phase 2 验收冒烟：WsWorks 接真（列表/创建/profile/统计 来自后端）。
// 前置：React dev 5174 + 后端（参数2，默认 8009，已 seed demo）。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-phase2.mjs
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

async function check(label, fn) {
  try { await fn(); console.log("ok:", label); }
  catch (e) { failed++; console.log("FAIL:", label, "—", e.message.split("\n")[0]); }
}

// 干净起步：清掉缓存影子，注入 API 地址
await page.goto(BASE);
await page.evaluate((api) => {
  localStorage.clear();
  localStorage.setItem("novel-system-api-base", api);
  localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8000");
}, API);
await page.reload();
await page.waitForSelector(".ws-app");
await page.waitForTimeout(1500); // 等首轮 API 拉取

await check("书架来自后端（两部 demo 种子）", async () => {
  await page.click(".ws-brand");
  await page.waitForSelector(".ws-wsw");
  const list = await page.textContent(".ws-wsw-list");
  if (!list.includes("潮汐档案") || !list.includes("盐镇来信")) throw new Error(`switcher: ${list.slice(0, 120)}`);
  await page.keyboard.press("Escape");
});

await check("切换器进度数字来自 writing-stats（3.8 万字）", async () => {
  await page.click(".ws-brand");
  await page.waitForSelector(".ws-wsw");
  const row = await page.textContent('.ws-wsw-row:has-text("潮汐档案")');
  if (!row.includes("3.8 万字")) throw new Error(`row: ${row}`);
  await page.keyboard.press("Escape");
});

await check("新建作品落库（换会话仍在）", async () => {
  await page.click(".ws-brand");
  await page.waitForSelector(".ws-wsw");
  await page.click(".ws-wsw-new");
  await page.waitForSelector(".ws-nw");
  await page.fill(".ws-nw-input", "P2冒烟之书");
  await page.click(".ws-nw-foot .btn-accent");
  await page.waitForTimeout(1200); // 等 POST 回写正式 id
  // 模拟"换浏览器"：清空本地缓存影子，仅保留 api base，重载后从后端取
  await page.evaluate((api) => {
    localStorage.clear();
    localStorage.setItem("novel-system-api-base", api);
    localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8000");
  }, API);
  await page.reload();
  await page.waitForSelector(".ws-app");
  await page.waitForTimeout(1500);
  await page.click(".ws-brand");
  await page.waitForSelector(".ws-wsw");
  const list = await page.textContent(".ws-wsw-list");
  if (!list.includes("P2冒烟之书")) throw new Error("created work missing after cache reset");
  await page.keyboard.press("Escape");
});

await check("demo 作品主页正常渲染（本地目录种子 + 服务端统计）", async () => {
  await page.click(".ws-brand");
  await page.waitForSelector(".ws-wsw");
  await page.click('.ws-wsw-row:has-text("潮汐档案")');
  await page.waitForTimeout(1200);
  const body = await page.textContent(".hm-title");
  if (!body.includes("潮汐档案")) throw new Error(`title: ${body}`);
});

await check("档案更新走 PATCH profile（改简介后端可读回）", async () => {
  const result = await page.evaluate(async () => {
    window.WsWorks.update("salt", { sub: "P2 冒烟改写的简介" });
    await new Promise(r => setTimeout(r, 1000));
    const res = await fetch(localStorage.getItem("novel-system-api-base") + "/api/v2/projects").then(r => r.json());
    const salt = res.data.items.find(i => i.project_id === "salt");
    return salt && salt.synopsis_line;
  });
  if (result !== "P2 冒烟改写的简介") throw new Error(`synopsis_line: ${result}`);
  // 还原，避免污染 demo（seed 重跑也会复位）
  await page.evaluate(() => window.WsWorks.update("salt", { sub: "八十年代末，盐场子弟苏怀梅离乡前写下最后一封没寄出的信，牵出三代人围绕一片废弃盐田的隐忍与亏欠——一部缓慢生长的家族长篇。" }));
  await page.waitForTimeout(600);
});

await browser.close();
const uniq = [...new Set(errors)];
if (uniq.length) { console.log(`\n${uniq.length} page errors:`); uniq.slice(0, 10).forEach(e => console.log(" -", e.slice(0, 300))); }
process.exitCode = failed || uniq.length ? 1 : 0;
console.log(failed ? `\n${failed} checks failed` : "\nall checks passed");
