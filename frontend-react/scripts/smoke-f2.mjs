// FE-ALIGN F2 冒烟：正文修订历史 + 成稿中心版本对比接真。
// 前置同 run-smokes：React dev/preview（参数1）+ 已迁移到 head 的后端（参数2）。
// 运行：cd frontend && node ../frontend-react/scripts/smoke-f2.mjs [BASE] [API]
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
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

const TITLE = "对比之书-" + Date.now().toString(36);

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

await check("① 建书建章建场 + 两次保存正文", async () => {
  await page.evaluate(async (t) => {
    window.WsWorks.create({ title: t, mark: "比", accent: "slate" });
    await new Promise(r => setTimeout(r, 1500));
    const chs = window.WsCatalog.get();
    window.WsCatalog.set([...chs, { id: "tmp1", n: "01", title: "对比章", state: "writing", scenes: [
      { title: "对比场", kind: "主动", state: "writing", goal: "目标", obstacle: "阻碍", turn: "挫折" },
    ] }]);
    await new Promise(r => setTimeout(r, 2500));
  }, TITLE);
  sid = await page.evaluate(async () => {
    const s = window.WsCatalog.get()[0].scenes[0].sid;
    await window.WrDocs.save(s, "<p>第一版：潮水在夜里退去。机器声变得很轻。</p>");
    await new Promise(r => setTimeout(r, 600));
    await window.WrDocs.save(s, "<p>第一版：潮水在夜里退去。机器声变得安静。多了一句完全新增的话。</p>");
    await new Promise(r => setTimeout(r, 800));
    return s;
  });
  if (!sid) throw new Error("no sid");
});

await check("② store：版本列表 ≥3 且旧版正文可取回", async () => {
  const r = await page.evaluate(async (s) => {
    const items = await window.WrDocVersions.list(s);
    const old = items[1]; // 倒序第二项 = 第一次保存
    const paras = old ? await window.WrDocVersions.paras(s, old.revisionNo) : [];
    return { count: items.length, sample: paras.join("|") };
  }, sid);
  if (r.count < 3) throw new Error(`versions: ${r.count}`); // ensure 初版 + 两次保存
  if (!r.sample.includes("机器声变得很轻")) throw new Error(`old content wrong: ${r.sample.slice(0, 80)}`);
});

await check("③ store：句级 diff 标记新增/删除", async () => {
  const d = await page.evaluate(() => window.WrDocVersions.diff(
    ["潮水在夜里退去。机器声变得很轻。"],
    ["潮水在夜里退去。机器声变得安静。多了一句新话。"],
  ));
  if (d.adds !== 2 || d.dels !== 1) throw new Error(`adds=${d.adds} dels=${d.dels}`);
});

await check("④ UI：成稿中心「对比」渲染真实 diff", async () => {
  await page.evaluate(async () => {
    // 章送审后「对比」标签才出现
    window.WsCatalog.set(window.WsCatalog.get().map(c => ({ ...c, state: "review" })));
    await new Promise(r => setTimeout(r, 800));
    location.hash = "#manuscripts";
  });
  await page.waitForTimeout(1500);
  await page.click('button.seg-btn:has-text("对比")');
  await page.waitForSelector(".ms-diff-body .d-add", { timeout: 15_000 });
  const stat = await page.textContent(".ms-diff-head");
  if (!/\+\d+ 句/.test(stat)) throw new Error(`stat missing: ${stat}`);
});

// 清理：软删 + 回收站彻底清除（残留会污染 run-smokes 批跑的回收站用例）
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
