const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { loadReferenceQaProfile } = require("./lib/reference-qa-profile.cjs");

const repoRoot = path.resolve(__dirname, "..");
const profilePath = path.join(repoRoot, "config", "qa", "public-domain-source-safety-five-chapter.json");
const laneEnv = {
  ...process.env,
  QA_REFERENCE_PROFILE_PATH: profilePath,
  QA_CHAPTER_COUNT: "5",
  QA_SCENES_PER_CHAPTER: "3",
  QA_MANAGE_DEV_SERVICES: "1",
  QA_FIXED_RELEASE_GATE: "1",
  PLAYWRIGHT_OPERATOR_REF: process.env.PLAYWRIGHT_OPERATOR_REF || "qa.public-domain-source-safety-five-chapter",
};

// 固定发布 lane 不接受调用进程残留的自定义语料/权属覆盖，避免证据串线。
for (const key of [
  "REFERENCE_BOOK_PATH",
  "REFERENCE_CLOUD_POLICY",
  "REFERENCE_RIGHTS_DECLARATION_JSON",
  "REFERENCE_PROTECTED_TERMS_JSON",
  "REFERENCE_SOURCE_BASIS",
]) {
  delete laneEnv[key];
}

const profile = loadReferenceQaProfile({ repoRoot, env: laneEnv, profilePath });
if (process.argv.includes("--preflight-only")) {
  process.stdout.write(`${JSON.stringify({
    ok: true,
    lane_id: profile.laneId,
    profile_path: path.relative(repoRoot, profile.profilePath).replaceAll("\\", "/"),
    reference_path: path.relative(repoRoot, profile.referencePath).replaceAll("\\", "/"),
    source_basis: profile.sourceBasis,
    cloud_policy: profile.cloudPolicy,
    rights_declared: profile.rightsDeclaration?.declared === true,
    send_rights: profile.rightsDeclaration?.send_rights === true,
    protected_term_count: profile.protectedTerms.length,
    expected_chapter_count: profile.expectedChapterCount,
    expected_scenes_per_chapter: profile.expectedScenesPerChapter,
    planned_scene_count: profile.expectedChapterCount * profile.expectedScenesPerChapter,
  }, null, 2)}\n`);
  process.exit(0);
}

const harnessPath = path.join(repoRoot, "scripts", "run-currentdb-three-chapter-qa.cjs");
const child = spawnSync(process.execPath, [harnessPath], {
  cwd: repoRoot,
  env: laneEnv,
  stdio: "inherit",
});
if (child.error) {
  throw child.error;
}
process.exitCode = child.status ?? 1;
