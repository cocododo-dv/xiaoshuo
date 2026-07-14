const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");

const { observeUiPhase } = require("../lib/ui-phase-evidence.cjs");

class FakePage extends EventEmitter {
  off(name, handler) { this.removeListener(name, handler); }
}

function response(method, url, status = 200) {
  return {
    status: () => status,
    url: () => url,
    request: () => ({ method: () => method, resourceType: () => "fetch" }),
  };
}

function locator(page, emitted) {
  return {
    async click() {
      for (const item of emitted) page.emit("response", item);
    },
    async fill() {},
  };
}

test("没有 locator 交互时不得记录 UI 阶段", async () => {
  const page = new FakePage();
  await assert.rejects(
    observeUiPhase(page, "scene_execution", async () => {}),
    { code: "UI_PHASE_INTERACTION_REQUIRED" },
  );
});

test("只有点击、没有浏览器成功响应时不得记录 UI 阶段", async () => {
  const page = new FakePage();
  await assert.rejects(
    observeUiPhase(page, "scene_execution", async ({ click }) => {
      await click(locator(page, []));
    }),
    { code: "UI_PHASE_REQUEST_MISSING" },
  );
});
test("失败响应不得满足 UI 阶段请求契约", async () => {
  const page = new FakePage();
  await assert.rejects(
    observeUiPhase(page, "archive", async ({ click }) => {
      await click(locator(page, [response("POST", "http://api/api/v1/scenes/S1/adopt-current", 409)]));
    }),
    { code: "UI_PHASE_REQUEST_FAILED" },
  );
});

test("浏览器点击触发成功请求后生成可审计 UI 回执", async () => {
  const page = new FakePage();
  const receipt = await observeUiPhase(page, "materialization", async ({ click }) => {
    await click(locator(page, [
      response("POST", "http://api/api/v2/projects/P1/snowflake-workspace/materialize"),
      response("POST", "http://api/api/v2/projects/P1/snowflake-workspace/outline/approve"),
    ]));
  });
  assert.equal(receipt.lane, "ui");
  assert.equal(receipt.interaction_count, 1);
  assert.equal(receipt.requests.length, 2);
  assert.deepEqual(receipt.requirements.map((item) => item.matched), [1, 1]);
});

test("候选终选必须同时观察选择与续跑请求", async () => {
  const page = new FakePage();
  await assert.rejects(
    observeUiPhase(page, "candidate_selection", async ({ click }) => {
      await click(locator(page, [
        response("POST", "http://api/api/v1/scenes/S1/style-candidates/C1/select"),
      ]));
    }),
    { code: "UI_PHASE_REQUEST_MISSING" },
  );
});
