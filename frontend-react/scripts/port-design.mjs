// Phase 1 一次性 codemod：把 design/ 原型（Babel standalone 全局脚本）机械转换为
// frontend-react/src/ 的 ES modules。逻辑零改动：只加 import / export，
// 过渡期保留全部 window.* 赋值（部分文件做运行时探测，Phase 8 统一清除）。
//
// 规则：
// - 加载清单与顺序以 design/index.html 的 <script>/<link> 实际引用为准（剥掉 ?v=N 缓存串）。
// - 注册表 = 各文件的 Object.assign(window, {...}) 与 `window.NAME = NAME;` 导出。
// - 每个文件的 import 需求 = /* global */ 头注释 ∪ 源码中按词边界出现的注册表名
//   （头注释有遗漏，如 ws-app.jsx 用了 WsConstruct 但未声明）。
// - 只允许从加载顺序更早的文件 import（保持原 script 执行顺序，防环）；
//   引用更晚文件的名字只能是运行时 window 探测，列入报告人工复核。
// - ws-app.jsx 特殊：剥掉末行 createRoot，改为 export { App }；main.jsx 负责挂载。
//
// 运行：node frontend-react/scripts/port-design.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESIGN = path.resolve(HERE, "../../codex-patches/FE-主线对齐/design");
const OUT = path.resolve(HERE, "../src");

const html = fs.readFileSync(path.join(DESIGN, "index.html"), "utf8");
const cssFiles = [...html.matchAll(/<link rel="stylesheet" href="([^"?]+)(?:\?v=\d+)?"/g)].map(m => m[1]);
const jsxFiles = [...html.matchAll(/<script type="text\/babel" src="([^"?]+)(?:\?v=\d+)?"><\/script>/g)].map(m => m[1]);

console.log("css order:", cssFiles.join(", "));
console.log("jsx order:", jsxFiles.join(", "));

// ---------- pass 1: export registry ----------
// name -> { file, renamed?: expr }
const registry = new Map();
const fileExports = new Map(); // file -> { plain: [], renamed: [{name, expr}] }

function parseAssignBlocks(src) {
  const names = [];
  const renamed = [];
  const re = /Object\.assign\(window,\s*\{/g;
  let m;
  while ((m = re.exec(src))) {
    // find matching close brace from m.index
    let depth = 0, i = src.indexOf("{", m.index);
    let start = i;
    for (; i < src.length; i++) {
      if (src[i] === "{") depth++;
      else if (src[i] === "}") { depth--; if (depth === 0) break; }
    }
    const body = src.slice(start + 1, i);
    // 按顶层逗号切分（嵌套 {}/[]/() 内的逗号不算 — 如 ws-snow 的 s2Materialize: {...}）
    const entries = [];
    let depth2 = 0, cur = "";
    for (const ch of body) {
      if ("{[(".includes(ch)) depth2++;
      else if ("}])".includes(ch)) depth2--;
      if (ch === "," && depth2 === 0) { entries.push(cur); cur = ""; }
      else cur += ch;
    }
    entries.push(cur);
    for (const rawEntry of entries) {
      const entry = rawEntry.trim();
      if (!entry) continue;
      const plain = entry.match(/^([A-Za-z_$][\w$]*)$/);
      const named = entry.match(/^([A-Za-z_$][\w$]*)\s*:\s*([\s\S]+?)\s*$/);
      if (plain) names.push(plain[1]);
      else if (named) renamed.push({ name: named[1], expr: named[2].trim() });
      else console.log("  !! unparsed assign entry:", JSON.stringify(entry.slice(0, 60)));
    }
  }
  // window.NAME = NAME; （icons.jsx 等）
  for (const mm of src.matchAll(/^\s*window\.([A-Za-z_$][\w$]*)\s*=\s*([A-Za-z_$][\w$]*)\s*;\s*$/gm)) {
    if (mm[1] === mm[2]) names.push(mm[1]);
  }
  return { names: [...new Set(names)], renamed };
}

for (const f of jsxFiles) {
  const src = fs.readFileSync(path.join(DESIGN, f), "utf8");
  const { names, renamed } = parseAssignBlocks(src);
  fileExports.set(f, { plain: names, renamed });
  for (const n of names) {
    if (registry.has(n) && registry.get(n).file !== f) console.log(`  !! duplicate export ${n}: ${registry.get(n).file} vs ${f}`);
    registry.set(n, { file: f });
  }
  for (const r of renamed) {
    if (registry.has(r.name)) console.log(`  !! duplicate renamed export ${r.name}`);
    registry.set(r.name, { file: f, renamed: r.expr });
  }
}
console.log(`registry: ${registry.size} names across ${jsxFiles.length} files`);

// ---------- pass 2: convert each file ----------
const order = new Map(jsxFiles.map((f, i) => [f, i]));
const report = [];

function headerGlobals(src) {
  const m = src.match(/\/\*\s*global\s+([\s\S]*?)\*\//);
  if (!m) return [];
  return m[1].split(/[,\s]+/).map(s => s.trim()).filter(s => /^[A-Za-z_$][\w$]*$/.test(s));
}

function localDecls(src) {
  const set = new Set();
  for (const m of src.matchAll(/(?:^|[\s;{}()])(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)/g)) set.add(m[1]);
  return set;
}

fs.mkdirSync(OUT, { recursive: true });

for (const f of jsxFiles) {
  let src = fs.readFileSync(path.join(DESIGN, f), "utf8");
  const myExports = fileExports.get(f);
  const myNames = new Set([...myExports.plain, ...myExports.renamed.map(r => r.name)]);
  const decls = localDecls(src);
  const need = new Set(headerGlobals(src));
  // 个别文件（tweaks-panel.jsx）无 /* global */ 头注释，按实际用法补 React/ReactDOM
  if (/\bReact\b/.test(src)) need.add("React");
  if (/\bReactDOM\b/.test(src)) need.add("ReactDOM");
  // registry-wide usage scan（补头注释遗漏）
  for (const name of registry.keys()) {
    if (myNames.has(name) || decls.has(name) || need.has(name)) continue;
    if (new RegExp(`(?<![.\\w$])${name}\\b`).test(src)) need.add(name);
  }
  need.delete("window");

  const importLines = [];
  if (need.delete("React")) importLines.push(`import React from "react";`);
  if (need.delete("ReactDOM")) importLines.push(`import ReactDOM from "react-dom";`);

  const bySource = new Map();
  for (const name of [...need].sort()) {
    if (myNames.has(name) || decls.has(name)) continue;
    const hit = registry.get(name);
    if (!hit) { report.push(`${f}: unresolved global '${name}' (window-only or missing)`); continue; }
    if (hit.file === f) continue;
    if (order.get(hit.file) >= order.get(f)) {
      report.push(`${f}: needs '${name}' from LATER file ${hit.file} — left as window/runtime`);
      continue;
    }
    if (!bySource.has(hit.file)) bySource.set(hit.file, []);
    bySource.get(hit.file).push(name);
  }
  for (const [srcFile, names] of [...bySource.entries()].sort((a, b) => order.get(a[0]) - order.get(b[0]))) {
    importLines.push(`import { ${names.join(", ")} } from "./${srcFile}";`);
  }

  // ws-app.jsx：摘掉 createRoot 挂载行（移入 main.jsx）
  if (f === "ws-app.jsx") {
    src = src.replace(/^ReactDOM\.createRoot\(document\.getElementById\("root"\)\)\.render\(<App \/>\);\s*$/m,
      "/* createRoot 挂载已移至 main.jsx（Phase 1 工程化） */");
    myExports.plain.push("App");
  }

  const exportLines = [];
  if (myExports.plain.length) exportLines.push(`export { ${[...new Set(myExports.plain)].join(", ")} };`);
  for (const r of myExports.renamed) exportLines.push(`export const ${r.name} = ${r.expr};`);

  const out = (importLines.length ? importLines.join("\n") + "\n\n" : "") + src +
    (exportLines.length ? `\n/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */\n${exportLines.join("\n")}\n` : "");
  fs.writeFileSync(path.join(OUT, f), out, "utf8");
}

for (const f of cssFiles) fs.copyFileSync(path.join(DESIGN, f), path.join(OUT, f));

// ---------- main.jsx ----------
const mainLines = [
  "// 入口装配（Phase 1）。CSS 与模块均按 design/index.html 的原始引用顺序导入 —",
  "// 两者的顺序都有语义（CSS 层叠 / window 注册先后），禁止重排。",
  ...cssFiles.map(f => `import "./${f}";`),
  "",
  ...jsxFiles.filter(f => f !== "ws-app.jsx").map(f => `import "./${f}";`),
  `import { App } from "./ws-app.jsx";`,
  `import ReactDOMClient from "react-dom/client";`,
  "",
  "// 原型的 store 是模块级单例 + 副作用订阅，StrictMode 双挂载会暴露非幂等订阅；",
  "// 保真优先不包 StrictMode（陷阱 T4），治理留到 Phase 8。",
  `ReactDOMClient.createRoot(document.getElementById("root")).render(React.createElement(App));`,
];
fs.writeFileSync(path.join(OUT, "main.jsx"),
  `import React from "react";\n` + mainLines.join("\n") + "\n", "utf8");

console.log("\n==== manual review report ====");
for (const r of report) console.log(" -", r);
console.log("done.");
