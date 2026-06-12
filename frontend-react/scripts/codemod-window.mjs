// FE-ALIGN F7：window.* 跨模块读访问 → 显式 ESM import（一次性 codemod）。
// 安全规则：
//  - 只处理 main.jsx 装配清单内的模块（+ ws-app.jsx 殿后）；
//  - 只转换「定义模块加载序更早」的符号（防环）且该符号已 ESM 导出；
//  - window.X = …（注册面）、浏览器原生、__ 运行时信箱、未知符号一律保留；
//  - lib/ 与清单外模块（wr-doc-store 等运行时探测是刻意设计）不动。
// 运行：node scripts/codemod-window.mjs [--write]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(HERE, "../src");
const WRITE = process.argv.includes("--write");

const main = fs.readFileSync(path.join(SRC, "main.jsx"), "utf8");
const order = [...main.matchAll(/import "\.\/(.+?\.jsx)";/g)].map((m) => m[1]);
order.push("ws-app.jsx");
const orderIdx = Object.fromEntries(order.map((f, i) => [f, i]));

const registry = {};
const exportsBy = {};
for (const f of order) {
  const code = fs.readFileSync(path.join(SRC, f), "utf8");
  const ex = new Set();
  for (const m of code.matchAll(/export \{([^}]+)\}/g)) {
    m[1].split(",").map((s) => s.trim().split(/\s+as\s+/).pop()).filter(Boolean).forEach((n) => ex.add(n));
  }
  exportsBy[f] = ex;
  for (const m of code.matchAll(/Object\.assign\(window,\s*\{([\s\S]*?)\}\s*\)/g)) {
    m[1].split(",").map((s) => s.trim().split(":")[0].trim()).filter((s) => /^[A-Za-z_$][\w$]*$/.test(s)).forEach((sym) => {
      if (!registry[sym]) registry[sym] = f;
    });
  }
  for (const m of code.matchAll(/window\.([A-Za-z_$][\w$]*)\s*=[^=]/g)) {
    if (!registry[m[1]]) registry[m[1]] = f;
  }
}

const SKIP = new Set([
  "addEventListener", "removeEventListener", "dispatchEvent", "alert", "confirm", "prompt",
  "getSelection", "matchMedia", "innerWidth", "innerHeight", "location", "localStorage",
  "setTimeout", "clearTimeout", "scrollTo", "open", "claude", "requestAnimationFrame",
  "navigator", "print", "performance", "getComputedStyle", "CustomEvent", "Event",
]);

const report = { converted: 0, files: 0, skips: {} };
const skip = (why, f, sym) => { (report.skips[why] = report.skips[why] || []).push(`${f}:${sym}`); };

for (const f of order) {
  const p = path.join(SRC, f);
  let code = fs.readFileSync(p, "utf8");
  const used = new Map();
  let count = 0;
  code = code.replace(/window\.([A-Za-z_$][\w$]*)(\s*=(?!=))?/g, (whole, sym, assign) => {
    if (assign) return whole;
    if (SKIP.has(sym) || sym.startsWith("__")) return whole;
    const src = registry[sym];
    if (!src || src === f) return whole;
    if (!(exportsBy[src] && exportsBy[src].has(sym))) { skip("no-export", f, sym); return whole; }
    if (orderIdx[src] >= orderIdx[f]) { skip("load-order", f, sym + "←" + src); return whole; }
    if (!used.has(src)) used.set(src, new Set());
    used.get(src).add(sym);
    count++;
    return sym;
  });
  if (!used.size) continue;
  for (const [src, syms] of used) {
    const impRe = new RegExp(`import \\{([^}]+)\\} from "\\./${src.replace(/\./g, "\\.")}";`);
    const m = code.match(impRe);
    const have = m ? m[1].split(",").map((s) => s.trim()).filter(Boolean) : [];
    const need = [...syms].filter((s2) => !have.includes(s2));
    if (m) {
      if (need.length) code = code.replace(impRe, `import { ${[...have, ...need].join(", ")} } from "./${src}";`);
    } else {
      const lines = code.split("\n");
      let lastImp = -1;
      lines.forEach((ln, i) => { if (/^import /.test(ln)) lastImp = i; });
      lines.splice(lastImp + 1, 0, `import { ${need.join(", ")} } from "./${src}";`);
      code = lines.join("\n");
    }
  }
  report.converted += count;
  report.files++;
  if (WRITE) fs.writeFileSync(p, code);
  console.log(`${WRITE ? "write" : "dry "} ${f}: ${count} refs ← ${[...used.keys()].join(", ")}`);
}
console.log(`\n${report.converted} refs in ${report.files} files${WRITE ? " (written)" : " (dry-run)"}`);
for (const [why, list] of Object.entries(report.skips)) {
  const uniq = [...new Set(list)];
  console.log(`skip[${why}] ${uniq.length}:`, uniq.slice(0, 12).join(" "), uniq.length > 12 ? "…" : "");
}
