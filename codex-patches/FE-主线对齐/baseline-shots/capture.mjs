// Phase 0 基线截图：静态服务 design/index.html，两部种子作品各打开一遍后，
// 对 15 个视图各截一张。运行：cd frontend && node ../codex-patches/FE-主线对齐/baseline-shots/capture.mjs
// 依赖 frontend/node_modules 里的 playwright；服务器需先在 8077 端口起好（python -m http.server）。
import { fileURLToPath } from "node:url";
import path from "node:path";
import { createRequire } from "node:module";

// 从运行目录（frontend/）解析 playwright，脚本本身在 node_modules 树外
const require = createRequire(path.join(process.cwd(), "package.json"));
const { chromium } = require("playwright");

const BASE = process.env.DESIGN_BASE || "http://127.0.0.1:8077/index.html";
const OUT = path.dirname(fileURLToPath(import.meta.url));
const VIEWS = [
  "home", "flowmap", "snowflake", "writer", "styleref", "review", "library",
  "author", "scene", "manuscripts", "longform", "index", "interop", "settings", "trash",
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.setDefaultTimeout(90_000);

async function waitApp() {
  await page.waitForSelector(".ws-app", { state: "attached" });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(800);
}

await page.goto(BASE);
await waitApp();

// 让两部种子作品的派生数据各生成一遍
for (const id of ["salt", "tide"]) {
  await page.evaluate((wid) => localStorage.setItem("ws_active_work_v1", wid), id);
  await page.reload();
  await waitApp();
}

for (let i = 0; i < VIEWS.length; i++) {
  const v = VIEWS[i];
  await page.evaluate((hash) => { location.hash = hash; }, "#" + v);
  await page.waitForTimeout(900);
  const file = path.join(OUT, `${String(i + 1).padStart(2, "0")}-${v}.png`);
  await page.screenshot({ path: file, fullPage: false });
  console.log("shot", file);
}

await browser.close();
console.log("done");
