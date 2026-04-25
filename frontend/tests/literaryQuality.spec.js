// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

describe("literary quality engine console", () => {
  it("registers the quality route and lazy view in the runtime group", () => {
    const routerSource = readSource("src/router.js");
    const appSource = readSource("src/App.vue");

    expect(routerSource).toContain('id: "quality"');
    expect(routerSource).toContain('groupId: "runtime"');
    expect(routerSource).toContain('nextViews: ["deepdesk", "review", "workbench"]');
    expect(appSource).toContain("quality: defineAsyncComponent");
    expect(appSource).toContain("./views/LiteraryQualityView.vue");
  });

  it("exposes overview and literary eval API helpers", () => {
    const apiSource = readSource("src/lib/api.js");

    expect(apiSource).toContain("fetchLiteraryQualityOverview");
    expect(apiSource).toContain("/api/v1/literary-quality/overview");
    expect(apiSource).toContain("fetchLiteraryEvalLatest");
    expect(apiSource).toContain("runLiteraryEval");
  });

  it("adds a Pinia store for overview and benchmark reports", () => {
    const storePath = path.join(SOURCE_ROOT, "src/stores/literaryQuality.js");
    expect(existsSync(storePath)).toBe(true);
    const source = readSource("src/stores/literaryQuality.js");

    expect(source).toContain('defineStore("literaryQuality"');
    expect(source).toContain("fetchLiteraryQualityOverview");
    expect(source).toContain("fetchLiteraryEvalLatest");
    expect(source).toContain("runLiteraryEval");
    expect(source).toContain("overviewItems");
    expect(source).toContain("runBaselineEval");
    expect(source).toContain("runLiveEval");
  });

  it("renders manuscript patrol and benchmark tabs with deepdesk navigation", () => {
    const viewPath = path.join(SOURCE_ROOT, "src/views/LiteraryQualityView.vue");
    expect(existsSync(viewPath)).toBe(true);
    const source = readSource("src/views/LiteraryQualityView.vue");

    expect(source).toContain('data-testid="literary-quality-view"');
    expect(source).toContain('data-testid="quality-tab-overview"');
    expect(source).toContain('data-testid="quality-tab-benchmark"');
    expect(source).toContain('data-testid="quality-overview-items"');
    expect(source).toContain('data-testid="quality-eval-report"');
    expect(source).toContain("model_voice");
    expect(source).toContain("image_homogeneity");
    expect(source).toContain("repetitive_action");
    expect(source).toContain("expository_dialogue");
    expect(source).toContain('navigate("deepdesk")');
    expect(source).toContain("runBaselineEval");
    expect(source).toContain("runLiveEval");
  });
});
