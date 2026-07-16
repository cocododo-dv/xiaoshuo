import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

import { describe, expect, it } from "vitest";

const QA_ROOTS = [
  path.resolve(process.cwd(), "../output/playwright/three-chapter-qa"),
  path.resolve(process.cwd(), "../output/playwright/original-three-chapter-qa"),
  path.resolve(process.cwd(), "../output/playwright/longzu-three-chapter-qa-20260422-111535"),
];
const FULL_CLOUD_RUNNER = path.resolve(process.cwd(), "../scripts/run-longzu-full-cloud-qa.cjs");
const CURRENT_DB_RUNNER = path.resolve(process.cwd(), "../scripts/run-currentdb-three-chapter-qa.cjs");
const PUBLIC_DOMAIN_REFERENCE_PROFILE = path.resolve(
  process.cwd(),
  "../config/qa/public-domain-source-safety-five-chapter.json",
);
const require = createRequire(import.meta.url);

describe("three-chapter QA script portability", () => {
  it("keeps one-off Playwright QA scripts off a hard-coded backend port", () => {
    const filesByRoot = {
      [QA_ROOTS[0]]: [
        "exercise-remaining-pages.js",
        "exercise-remaining-pages-continue.js",
        "chqa03-final-aggregate.js",
        "run-chapters-wait-response.js",
        "run-scenes-workbench.js",
      ],
      [QA_ROOTS[1]]: ["run-original-three-chapter-qa.cjs"],
      [QA_ROOTS[2]]: ["run-longzu-three-chapter-qa.cjs", "continue-and-close-qa.cjs"],
    };
    const offenders = Object.entries(filesByRoot).flatMap(([root, files]) =>
      files
        .filter((file) => readFileSync(path.join(root, file), "utf8").includes("http://127.0.0.1:8000"))
        .map((file) => path.relative(process.cwd(), path.join(root, file))),
    );

    expect(offenders).toEqual([]);
  });

  it("waits for scene run jobs instead of the legacy blocking scene run response", () => {
    const scripts = [
      path.join(QA_ROOTS[1], "run-original-three-chapter-qa.cjs"),
      path.join(QA_ROOTS[2], "run-longzu-three-chapter-qa.cjs"),
    ];

    const offenders = scripts
      .filter((scriptPath) => readFileSync(scriptPath, "utf8").includes("/api/v1/scenes/${sceneId}/run/full"))
      .map((scriptPath) => path.relative(process.cwd(), scriptPath));

    expect(offenders).toEqual([]);
    for (const scriptPath of scripts) {
      expect(readFileSync(scriptPath, "utf8")).toContain("/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs");
    }
  });

  it("uses the current root-level bundle worksheet envelope shape", () => {
    const script = readFileSync(path.join(QA_ROOTS[1], "run-original-three-chapter-qa.cjs"), "utf8");

    expect(script).toContain("bundle_id: ${worksheetBundleId}");
    expect(script).toContain("scene_id: CHOR01_SC01");
    expect(script).toContain("chapter_id: CHOR01");
    expect(script).not.toContain("bundle:\n  bundle_id:");
  });

  it("defines the full-cloud Longzu QA runner with stable artifact schema and sanitized reporting", () => {
    const script = readFileSync(FULL_CLOUD_RUNNER, "utf8");

    expect(script).toContain('cloud_policy: "allow_full_cloud"');
    expect(script).toContain("qa.longzu.full-cloud");
    expect(script).toContain("longzu-full-cloud-qa-20260423");
    expect(script).toContain(".codex-run");
    expect(script).toContain("learning-tree");
    expect(script).toContain("source_safety_scan");
    expect(script).toContain("approveAndPublishReview(pinReviewId)");
    expect(script).toContain("/api/v1/index/verify/");
    expect(script).toContain("pinReleased");
    expect(script).toContain("longzu-literary-scoring.cjs");
    expect(script).not.toContain("review release deferred:");
    for (const key of [
      "meta",
      "steps",
      "experienceScores",
      "chapterScores",
      "rootCauseFindings",
      "systemFixes",
      "screenshots",
      "warnings",
      "console",
      "requestFailures",
    ]) {
      expect(script).toContain(`${key}:`);
    }
    expect(script).toContain("资深创作者体验审查");
    expect(script).toContain("开发根因与修复");
    expect(script).not.toContain("http://127.0.0.1:8000");
  });

  it("keeps full-cloud literary scoring reusable with manual remark slots", () => {
    const scoring = require(path.resolve(process.cwd(), "../scripts/lib/longzu-literary-scoring.cjs"));
    const chapters = [{ chapter_id: "CHOR01", scene: { scene_id: "CHOR01_SC01" } }];
    const chapterScores = scoring.buildChapterScores({
      chapters,
      finalScenes: {
        CHOR01: {
          sceneStatus: "archived",
          finalRowId: "final_scene_CHOR01_SC01_v1",
          finalText: "林岑发现证据，于是决定保护许望。盐钟、潮汛、档案、监听、船坞和指腹共同形成追踪风险。",
          source_safety_scan: { safe: true, blocked_terms: [] },
        },
      },
      protectedTerms: ["龙族"],
      manualRemarks: { CHOR01: "人工复核：保留克制感。" },
    });

    expect(chapterScores.CHOR01.finalRowIds).toEqual(["final_scene_CHOR01_SC01_v1"]);
    expect(chapterScores.CHOR01.sourceLeakRisk).toBe(10);
    expect(chapterScores.CHOR01.languageTexture).toBeGreaterThanOrEqual(8);
    expect(chapterScores.CHOR01.manualRemark).toBe("人工复核：保留克制感。");
    expect(scoring.buildExperienceScores()["review inbox"].note).toContain("校验");
  });

  it("defines the current-DB three-chapter QA runner with unique artifacts and safety scans", () => {
    const script = readFileSync(CURRENT_DB_RUNNER, "utf8");
    const referenceProfile = JSON.parse(readFileSync(PUBLIC_DOMAIN_REFERENCE_PROFILE, "utf8"));

    expect(script).toContain("currentdb-three-chapter-qa-");
    expect(script).toContain("玻璃雨停在零点");
    expect(script).toContain("loadReferenceQaProfile({ repoRoot })");
    expect(script).toContain("referenceProfile.sourceBasis");
    expect(referenceProfile.source_basis).toBe("public_domain");
    expect(referenceProfile.cloud_policy).toBe("segments_only");
    expect(script).not.toContain("C:\\\\Users\\\\duwei\\\\Downloads\\\\龙族.txt");
    expect(script).toContain("protectedTerms");
    expect(script).toContain("/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs");
    expect(script).toContain("/api/v1/literary-quality/chapter-set-review");
    expect(script).toContain("qa-live-results.json");
    expect(script).toContain("final-scenes.json");
    expect(script).toContain("report.md");
    expect(script).toContain("layoutFindings");
    expect(script).toContain("collectLayoutFindings");
    expect(script).toContain("资深创作者体验审查");
    expect(script).toContain("开发根因与修复");
    expect(script).not.toContain("http://127.0.0.1:8000");
  });

  it("lets the current-DB QA runner reset author state before a from-zero run", () => {
    const script = readFileSync(CURRENT_DB_RUNNER, "utf8");

    expect(script).toContain("QA_RESET_AUTHOR_STATE");
    expect(script).toContain("QA_MANAGE_DEV_SERVICES");
    expect(script).toContain("python -m alembic upgrade head");
    expect(script).toContain("novel_system.tools.reset_author_state");
    expect(script).toContain("--execute");
    expect(script).toContain("start-dev.cmd");
    expect(script).toContain("isWindowsCommandScript");
    expect(script).toContain("cmd.exe");
    expect(script).toContain("stdioMode");
    expect(script).toContain("作者态重置");
    expect(script).toContain("resetAuthorState");
    expect(script).toContain("QA_ASSUME_SERVICES_STOPPED");
  });

  it("treats missing reference profiles and current-run blockers as first-class QA evidence", () => {
    const script = readFileSync(CURRENT_DB_RUNNER, "utf8");

    expect(script).toContain("reference learning did not produce a ready profile");
    expect(script).toContain("throwReferenceLearningBlocker");
    expect(script).toContain("deriveCurrentRunBlockerFindings");
    expect(script).toContain("currentRunBlockers");
    expect(script).toContain("run-log.ndjson");
    expect(script).not.toContain("latest QA stopped after four scene attempts");
  });
});
