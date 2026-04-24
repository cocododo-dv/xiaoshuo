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
          finalRowId: "final_scene_CHOR01_SC01_v1",
          finalText: "林岑发现证据，于是决定保护许望。盐钟、潮汛、档案、监听、船坞和指腹共同形成追踪风险。",
          source_safety_scan: { safe: true, blocked_terms: [] },
        },
      },
      protectedTerms: ["龙族"],
      manualRemarks: { CHOR01: "人工复核：保留克制感。" },
    });

    expect(chapterScores.CHOR01.finalRowId).toBe("final_scene_CHOR01_SC01_v1");
    expect(chapterScores.CHOR01.sourceLeakRisk).toBe(10);
    expect(chapterScores.CHOR01.languageTexture).toBeGreaterThanOrEqual(8);
    expect(chapterScores.CHOR01.manualRemark).toBe("人工复核：保留克制感。");
    expect(scoring.buildExperienceScores()["review inbox"].note).toContain("校验");
  });
});
