const assert = require("node:assert/strict");
const test = require("node:test");

const { buildChapters, buildSnowflakeImportPlan } = require("../run-currentdb-three-chapter-qa.cjs");

test("五章导入计划包含十步、五章与十五场稳定身份", () => {
  const chapters = buildChapters("contract").slice(0, 5);
  const plan = buildSnowflakeImportPlan(chapters);
  const expectedSteps = [
    "book_brief", "one_sentence_summary", "one_paragraph_summary", "character_sheets", "short_synopsis",
    "character_synopses", "long_synopsis", "character_bibles", "scene_list", "scene_details",
  ];
  assert.deepEqual(Object.keys(plan.steps), expectedSteps);
  assert.equal(plan.steps.scene_list.scenes.length, 15);
  assert.equal(plan.steps.scene_details.scenes.length, 15);
  assert.equal(new Set(plan.steps.scene_details.scenes.map((scene) => scene.row_uid)).size, 15);
  assert.equal(new Set(plan.steps.scene_details.scenes.map((scene) => scene.chapter_id)).size, 5);
});

test("十五场规划均具备可物化的主动场三拍、坩埚和明确代价", () => {
  const plan = buildSnowflakeImportPlan(buildChapters("pressure").slice(0, 5));
  for (const scene of plan.steps.scene_details.scenes) {
    assert.equal(scene.primary_form, "proactive");
    for (const field of ["title", "summary", "scene_crucible", "goal", "conflict", "setback", "cost_requirement", "exit_change", "hook"]) {
      assert.ok(String(scene[field] || "").trim(), `${scene.row_uid}.${field} must be non-empty`);
    }
    assert.ok(scene.conflict.length >= 60, `${scene.row_uid} conflict must express escalation`);
    assert.match(scene.setback, /代价|失去|风险/);
  }
});
