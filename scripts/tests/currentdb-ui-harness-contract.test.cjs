const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const harnessPath = path.resolve(__dirname, "..", "run-currentdb-three-chapter-qa.cjs");

function functionBody(source, name) {
  const start = source.indexOf(`async function ${name}(`);
  assert.notEqual(start, -1, `${name} must exist`);
  const open = source.indexOf("{", start);
  let depth = 0;
  for (let index = open; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") depth -= 1;
    if (depth === 0) return source.slice(open + 1, index);
  }
  throw new Error(`cannot parse ${name}`);
}

test("六阶段不得写死 api/missing lane", () => {
  const source = fs.readFileSync(harnessPath, "utf8");
  assert.doesNotMatch(source, /recordPhase\(\s*["'](?:snowflake_planning|materialization|scene_execution|candidate_selection|archive|chapter_aggregation)["']\s*,\s*["'](?:api|missing)["']/s);
});

test("关键阶段实现不得通过 Node apiPost 深链完成动作", () => {
  const source = fs.readFileSync(harnessPath, "utf8");
  for (const name of ["createOriginalWorkspace", "exerciseSceneWorkbench", "exerciseChapterManuscripts"]) {
    assert.doesNotMatch(functionBody(source, name), /\bapiPost\s*\(/, `${name} must use browser UI interactions`);
  }
});

test("场景预算耗尽只能经作者界面追加并续跑", () => {
  const source = fs.readFileSync(harnessPath, "utf8");
  const body = functionBody(source, "exerciseSceneWorkbench");
  assert.match(body, /scene-budget-topup/);
  assert.match(body, /scene-hard-rewrite/);
  assert.match(body, /scene-start/);
  assert.match(body, /\/budget\/topup/);
  assert.match(
    body,
    /\["scene-budget-topup", "scene-create-cards", "scene-candidate-select", "scene-hard-rewrite", "scene-start", "scene-archive"\]/,
  );
  assert.doesNotMatch(body, /apiPost\s*\(/);
});

test("诊断规模按计划场景数收缩候选选择门槛", () => {
  const source = fs.readFileSync(harnessPath, "utf8");
  const body = functionBody(source, "exerciseSceneWorkbench");
  assert.match(body, /Math\.min\(3, plannedSceneList\.length\)/);
  assert.match(body, /"candidate-select": requiredCandidateSelections/);
  assert.match(body, /"selection-resume": requiredCandidateSelections/);
  assert.doesNotMatch(body, /candidateSelections < 3/);
});

test("发布 QA 优先连接 React 主前端而非 legacy Vue", () => {
  const source = fs.readFileSync(harnessPath, "utf8");
  const start = source.indexOf("function resolveFrontendUrl(");
  const end = source.indexOf("function resolveApiBase(", start);
  const body = source.slice(start, end);
  assert.ok(body.indexOf('readRunFile("frontend-react.url")') < body.indexOf('readRunFile("frontend.url")'));
  assert.match(body, /PLAYWRIGHT_FRONTEND_PORT \|\| "5174"/);
});
