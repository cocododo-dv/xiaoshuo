import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const main = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const router = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

assert.ok(html.includes("小说系统"));
assert.ok(html.includes("/src/main.js"));
assert.ok(main.includes("createPinia"));
assert.ok(app.includes("SceneWorkbenchView"));
assert.ok(app.includes("ReviewInboxView"));
assert.ok(app.includes("IndexConsoleView"));
assert.ok(app.includes("LongformControlView"));
assert.ok(app.includes("InteropCenterView"));
assert.ok(app.includes("stage-notices"));
assert.ok(!app.includes("stage-chrome"));
assert.ok(!app.includes("api-base-input"));
assert.ok(router.includes('id: "knowledge"'));
assert.ok(router.includes('id: "longform"'));
assert.ok(router.includes('label: "长篇控制"'));
assert.ok(router.includes('label: "沉淀知识"'));
assert.ok(router.includes('legacyLabel: "知识控制台"'));
assert.ok(router.includes('id: "interop"'));
assert.ok(router.includes('label: "导入导出"'));
assert.ok(router.includes('legacyLabel: "互操作中心"'));
assert.ok(router.includes('cacheMode: "light"'));
assert.ok(!router.includes("chromeTitle"));
assert.ok(!router.includes("formatViewLabel"));
assert.ok(!router.includes("uiText"));

console.log("frontend smoke ok");
