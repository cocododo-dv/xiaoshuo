import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const main = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const router = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

assert.ok(html.includes("Novel System P2 Console"));
assert.ok(html.includes("/src/main.js"));
assert.ok(main.includes("createPinia"));
assert.ok(app.includes("Scene Workbench"));
assert.ok(app.includes("Review Inbox"));
assert.ok(app.includes("Index Console"));
assert.ok(app.includes("Interop Center"));
assert.ok(router.includes('label: "Knowledge Console"'));
assert.ok(router.includes('label: "Interop Center"'));

console.log("frontend smoke ok");
