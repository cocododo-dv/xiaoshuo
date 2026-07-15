const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const test = require("node:test");

const repoRoot = path.resolve(__dirname, "..", "..");
const profilePath = path.join(repoRoot, "config", "qa", "public-domain-source-safety-five-chapter.json");
const wrapperPath = path.join(repoRoot, "scripts", "run-public-domain-source-safety-five-chapter-qa.cjs");
const harnessPath = path.join(repoRoot, "scripts", "run-currentdb-three-chapter-qa.cjs");
const { loadReferenceQaProfile } = require("../lib/reference-qa-profile.cjs");

test("公开来源安全 lane 固定为仓库内公有领域五章十五场配置", () => {
  const profile = loadReferenceQaProfile({ repoRoot, env: {}, profilePath });
  assert.equal(profile.laneId, "public-domain-source-safety-five-chapter");
  assert.equal(profile.sourceBasis, "public_domain");
  assert.equal(profile.cloudPolicy, "segments_only");
  assert.equal(profile.rightsDeclaration.declared, true);
  assert.equal(profile.rightsDeclaration.send_rights, true);
  assert.equal(profile.expectedChapterCount, 5);
  assert.equal(profile.expectedScenesPerChapter, 3);
  assert.ok(profile.referencePath.startsWith(repoRoot));
  assert.ok(fs.statSync(profile.referencePath).size > 100_000);
  assert.ok(profile.protectedTerms.length >= 8);
});

test("自定义语料不得继承公有领域 lane 的云端发送权", () => {
  assert.throws(
    () => loadReferenceQaProfile({
      repoRoot,
      profilePath,
      env: { REFERENCE_BOOK_PATH: "backend/tests/golden/style_reference/corpus/zhuziqing_essays.txt" },
    }),
    /不会继承公有领域配置的权属声明/,
  );
});

test("固定 lane 预检输出可复算的来源、权属和规模", () => {
  const output = execFileSync(process.execPath, [wrapperPath, "--preflight-only"], {
    cwd: repoRoot,
    encoding: "utf8",
  });
  const report = JSON.parse(output);
  assert.equal(report.ok, true);
  assert.equal(report.reference_path, "backend/tests/golden/style_reference/corpus/luxun_short_stories.txt");
  assert.equal(report.rights_declared, true);
  assert.equal(report.send_rights, true);
  assert.equal(report.expected_chapter_count, 5);
  assert.equal(report.expected_scenes_per_chapter, 3);
  assert.equal(report.planned_scene_count, 15);
});

test("UI 主 harness 将权属声明传给后端并记录来源 lane", () => {
  const source = fs.readFileSync(harnessPath, "utf8");
  assert.match(source, /rights_declaration:\s*referenceRightsDeclaration/);
  assert.match(source, /referenceLaneId:\s*referenceProfile\.laneId/);
  assert.match(source, /protectedTerms = referenceProfile\.protectedTerms/);
  assert.match(source, /learn and bind the audited public-domain reference profile/);
  assert.match(source, /\/api\/v2\/style-reference\/books\/import-path/);
  assert.doesNotMatch(source, /\/api\/v1\/reference-books/);
  assert.match(source, /sourceSafetyGate/);
});
