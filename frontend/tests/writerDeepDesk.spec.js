// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

describe("writer deep revision desk", () => {
  it("registers a dedicated deep revision desk route and lazy view", () => {
    const routerSource = readSource("src/router.js");
    const appSource = readSource("src/App.vue");

    expect(routerSource).toContain('id: "deepdesk"');
    expect(routerSource).toContain("作家深改台");
    expect(routerSource).toContain("深改文本");
    expect(routerSource).toContain('nextViews: ["manuscripts", "author", "workbench"]');
    expect(appSource).toContain("deepdesk: defineAsyncComponent");
    expect(appSource).toContain("./views/WriterDeepDeskView.vue");
  });

  it("exposes deep review, passage patch, and author preference API helpers", () => {
    const apiSource = readSource("src/lib/api.js");

    expect(apiSource).toContain("fetchSceneDeepReview");
    expect(apiSource).toContain("runSceneDeepReview");
    expect(apiSource).toContain("fetchChapterDeepReview");
    expect(apiSource).toContain("runChapterDeepReview");
    expect(apiSource).toContain("createPassagePatchCandidate");
    expect(apiSource).toContain("acceptPassagePatchCandidate");
    expect(apiSource).toContain("rejectPassagePatchCandidate");
    expect(apiSource).toContain("fetchAuthorPreferenceProfile");
    expect(apiSource).toContain("/deep-review");
    expect(apiSource).toContain("/passages/patch-candidates");
    expect(apiSource).toContain("/author-preference-profile");
  });

  it("adds a focused store without deep watchers for long chapter text", () => {
    const storePath = path.join(SOURCE_ROOT, "src/stores/writerDeepDesk.js");
    expect(existsSync(storePath)).toBe(true);
    const source = readSource("src/stores/writerDeepDesk.js");

    expect(source).toContain('defineStore("writerDeepDesk"');
    expect(source).toContain("runChapterDeepReview");
    expect(source).toContain("createPassagePatchCandidate");
    expect(source).toContain("acceptPassagePatchCandidate");
    expect(source).toContain("rejectPassagePatchCandidate");
    expect(source).not.toContain("deep: true");
  });

  it("renders a quiet reader, diagnosis rail, patch candidates, and preference draft", () => {
    const viewPath = path.join(SOURCE_ROOT, "src/views/WriterDeepDeskView.vue");
    expect(existsSync(viewPath)).toBe(true);
    const source = readSource("src/views/WriterDeepDeskView.vue");

    expect(source).toContain('data-testid="writer-deep-desk"');
    expect(source).toContain('data-testid="deep-desk-reader"');
    expect(source).toContain('data-testid="deep-review-run"');
    expect(source).toContain('data-testid="patch-candidate-create"');
    expect(source).toContain('data-testid="deep-review-findings"');
    expect(source).toContain('data-testid="passage-patch-candidates"');
    expect(source).toContain('data-testid="author-preference-profile"');
    expect(source).toContain("candidate.status !== 'candidate'");
  });
});
