// FE-ALIGN P8：React 端契约级 E2E 跑批器。
// 依次执行 smoke-phase2..7 + ai-settings（与后端契约相关的用例——对应 Vue 端 E2E 的平移面，
// 覆盖：作品域/目录/正文/回收站/待办 effect/资料库/控制塔桥），末尾追加 qa2-ui（批次2 浏览器 UI
// 回归守卫：SNOW-12 不发 409 / Q3-UI 物化态 / AUTHOR-04 单章 SVG / 全视图 console 巡检）。
// 前置：React dev（参数1，默认 5174）+ 已 seed demo 的后端（参数2，默认 8009）。
// 运行：cd frontend && node ../frontend-react/scripts/run-smokes.mjs [BASE] [API]
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.argv[2] || "http://127.0.0.1:5174/";
const API = process.argv[3] || "http://127.0.0.1:8009";

const SMOKES = ["smoke-phase2.mjs", "smoke-phase3.mjs", "smoke-phase4.mjs", "smoke-phase5.mjs", "smoke-phase6.mjs", "smoke-phase7.mjs", "smoke-ai-settings.mjs", "qa2-ui.mjs"];
const BACKEND_DIR = path.resolve(HERE, "../../backend");

// 各套用例都会改动夹具数据（裁决/插场/改题），套间 reseed 保独立性
function reseed() {
  const r = spawnSync("python", ["tests/fixture_runtime.py"], {
    cwd: BACKEND_DIR,
    env: { ...process.env, PYTHONPATH: "src" },
    stdio: "pipe",
  });
  if (r.status !== 0) console.log("WARN: reseed failed —", String(r.stderr).slice(0, 200));
}

let failed = 0;
for (const smoke of SMOKES) {
  console.log(`\n===== ${smoke} =====`);
  reseed();
  const r = spawnSync(process.execPath, [path.join(HERE, smoke), BASE, API], { stdio: "inherit" });
  if (r.status !== 0) failed++;
}
console.log(failed ? `\n${failed} smoke suites failed` : "\nall smoke suites passed");
process.exitCode = failed ? 1 : 0;
