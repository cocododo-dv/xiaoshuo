// FE-ALIGN F6 冒烟：起草引擎接 scenes run 管线。
// 本环境 LLM 不可用 → 验证「投递真实管线 + 结构化引导」而非假输出；
// 后端守卫（无运行态行不 500）由 pytest test_fe_scene_run_guards 覆盖。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-f6.mjs [BASE] [API]
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
page.setDefaultTimeout(25_000);
page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));
page.on("dialog", (d) => d.accept());

async function check(label, fn) {
  try { await fn(); console.log("ok:", label); }
  catch (e) { failed++; console.log("FAIL:", label, "—", e.message.split("\n")[0]); }
}

const TITLE = "起草之书-" + Date.now().toString(36);

await page.goto(BASE);
await page.evaluate((apiBase) => {
  localStorage.clear();
  localStorage.setItem("novel-system-api-base", apiBase);
  localStorage.setItem("novel-system-api-base-default", "http://127.0.0.1:8000");
}, API);
await page.reload();
await page.waitForSelector(".ws-app");
await page.waitForTimeout(2000);

let sid = null;

await check("① 建书建场（最小场景卡）", async () => {
  sid = await page.evaluate(async (t) => {
    window.WsWorks.create({ title: t, mark: "草", accent: "slate" });
    await new Promise(r => setTimeout(r, 1500));
    const chs = window.WsCatalog.get();
    window.WsCatalog.set([...chs, { id: "tmp1", n: "01", title: "起草章", state: "writing", scenes: [
      { title: "起草场", kind: "主动", state: "writing", goal: "拿到证物", obstacle: "保安巡逻", turn: "证物已被调包" },
    ] }]);
    await new Promise(r => setTimeout(r, 2500));
    return window.WsCatalog.get()[0].scenes[0].sid;
  }, TITLE);
  if (!sid) throw new Error("no sid");
});

await check("② scnRun 投递真实管线 → 结构化引导（无假输出）", async () => {
  const r = await page.evaluate(async (s) => {
    try {
      const res = await window.scnRun({ sid: s, title: "起草场", kind: "主动" }, "", "");
      return { ok: true, words: res && res.words };
    } catch (e) { return { ok: false, msg: e.message || String(e) }; }
  }, sid);
  // LLM 不可用环境：必须拒绝并给引导；若环境配好了 LLM 则应产出真实正文
  if (r.ok) {
    if (!r.words || r.words < 100) throw new Error(`unexpected tiny draft: ${r.words}`);
    console.log("   (LLM 可用：产出真实正文", r.words, "字)");
  } else if (!/执行契约|补全|LLM|起草失败|前置/.test(r.msg)) {
    throw new Error(`message not actionable: ${r.msg}`);
  }
});

await check("③ UI：起草台点「开始起草」→ 明确报错而非假进度", async () => {
  await page.evaluate((s) => { window.scnQueueSave([s]); location.hash = "#scene"; }, sid);
  await page.waitForTimeout(1500);
  await page.click('button:has-text("开始起草")');
  // 轮询等待错误文案或真实完成（不接受一直停留在假进度）
  let text = "";
  for (let i = 0; i < 30; i++) {
    await page.waitForTimeout(1000);
    text = await page.evaluate(() => document.body.innerText);
    if (/执行契约|起草失败|补全|LLM/.test(text) || /待裁决/.test(text)) break;
  }
  if (!(/执行契约|起草失败|补全|LLM/.test(text) || /待裁决/.test(text))) throw new Error("no actionable outcome rendered");
});

// 清理：软删 + 彻底清除
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
