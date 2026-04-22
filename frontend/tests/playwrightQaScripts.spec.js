import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const QA_ROOTS = [
  path.resolve(process.cwd(), "../output/playwright/three-chapter-qa"),
  path.resolve(process.cwd(), "../output/playwright/original-three-chapter-qa"),
];

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
    };
    const offenders = Object.entries(filesByRoot).flatMap(([root, files]) =>
      files
        .filter((file) => readFileSync(path.join(root, file), "utf8").includes("http://127.0.0.1:8000"))
        .map((file) => path.relative(process.cwd(), path.join(root, file))),
    );

    expect(offenders).toEqual([]);
  });

  it("waits for scene run jobs instead of the legacy blocking scene run response", () => {
    const script = readFileSync(path.join(QA_ROOTS[1], "run-original-three-chapter-qa.cjs"), "utf8");

    expect(script).toContain("/api/v1/scenes/${encodeURIComponent(sceneId)}/run/jobs");
    expect(script).not.toContain("/api/v1/scenes/${sceneId}/run/full");
  });

  it("uses the current root-level bundle worksheet envelope shape", () => {
    const script = readFileSync(path.join(QA_ROOTS[1], "run-original-three-chapter-qa.cjs"), "utf8");

    expect(script).toContain("bundle_id: ${worksheetBundleId}");
    expect(script).toContain("scene_id: CHOR01_SC01");
    expect(script).toContain("chapter_id: CHOR01");
    expect(script).not.toContain("bundle:\n  bundle_id:");
  });
});
