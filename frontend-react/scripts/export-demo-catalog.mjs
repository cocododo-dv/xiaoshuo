// Phase 3 一次性工具：把前端 demo 目录种子（tide 的 ARR_CHAPTERS + salt 的
// CAT_SALT_CHAPTERS）导出为 JSON，供后端 seed（seed_fe_demo_works）经
// CatalogService.import_catalog 写入 —— 保证 demo 作品在目录真相切到后端后
// 仍保有完整的戏剧卡/线索/张力数据。
// 运行：node frontend-react/scripts/export-demo-catalog.mjs
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../src");
const OUT = path.resolve(HERE, "../../backend/src/novel_system/tools/fe_demo_catalog.json");

// tide：ws-author-data.jsx 是纯数据模块（无 JSX）——剥掉 import/export 后整体求值
let authorData = fs.readFileSync(path.join(SRC, "ws-author-data.jsx"), "utf8");
authorData = authorData
  .replace(/^import .*$/gm, "")
  .replace(/^\/\* ESM 导出.*$/gm, "")
  .replace(/^export .*$/gm, "");
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(authorData + "\nthis.__tide = ARR_CHAPTERS;", sandbox);
const tide = sandbox.__tide;

// salt：ws-catalog.jsx 含 React 组件，只取 CAT_SALT_CHAPTERS 字面量段求值
const catalogSrc = fs.readFileSync(path.join(SRC, "ws-catalog.jsx"), "utf8");
const saltMatch = catalogSrc.match(/const CAT_SALT_CHAPTERS = (\[[\s\S]*?\n\]);/);
if (!saltMatch) throw new Error("CAT_SALT_CHAPTERS literal not found");
const salt = vm.runInNewContext("(" + saltMatch[1] + ")");

if (!Array.isArray(tide) || !tide.length) throw new Error("ARR_CHAPTERS eval failed");
if (!Array.isArray(salt) || !salt.length) throw new Error("CAT_SALT_CHAPTERS eval failed");

fs.writeFileSync(OUT, JSON.stringify({ tide, salt }, null, 1), "utf8");
console.log(`tide chapters: ${tide.length}, salt chapters: ${salt.length}`);
console.log("written:", OUT);
