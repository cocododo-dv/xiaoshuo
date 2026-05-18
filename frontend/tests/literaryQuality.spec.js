// @vitest-environment jsdom

import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

function readApiLayerSource() {
  const dir = path.join(SOURCE_ROOT, "src/lib/api");
  return readdirSync(dir).filter(f => f.endsWith(".js")).map(f => readFileSync(path.join(dir, f), "utf8")).join("\n");
}

describe("literary quality engine console", () => {
  it("registers the quality route and lazy view in the runtime group", () => {
    const routerSource = readSource("src/router.js");
    const appSource = readSource("src/App.vue");

    expect(routerSource).toContain('id: "quality"');
    expect(routerSource).toContain('stage: "toolbox"');
    expect(routerSource).toContain('nextViews: ["deepdesk", "review", "workbench"]');
    expect(appSource).toContain("quality: defineAsyncComponent");
    expect(appSource).toContain("./views/LiteraryQualityView.vue");
  });

  it("exposes overview and literary eval API helpers", () => {
    const apiSource = readApiLayerSource();

    expect(apiSource).toContain("fetchLiteraryQualityOverview");
    expect(apiSource).toContain("/api/v1/literary-quality/overview");
    expect(apiSource).toContain('chapterId: "chapter_id"');
    expect(apiSource).toContain('riskType: "risk_type"');
    expect(apiSource).toContain('minSeverity: "min_severity"');
    expect(apiSource).toContain("analyzeLiteraryQualityText");
    expect(apiSource).toContain("/api/v1/literary-quality/analyze-text");
    expect(apiSource).toContain("runLiteraryQualityChapterSetReview");
    expect(apiSource).toContain("/api/v1/literary-quality/chapter-set-review");
    expect(apiSource).toContain("fetchLiteraryEvalLatest");
    expect(apiSource).toContain("runLiteraryEval");
  });

  it("adds a Pinia store for overview and benchmark reports", () => {
    const storePath = path.join(SOURCE_ROOT, "src/stores/literaryQuality.js");
    expect(existsSync(storePath)).toBe(true);
    const source = readSource("src/stores/literaryQuality.js");

    expect(source).toContain('defineStore("literaryQuality"');
    expect(source).toContain("fetchLiteraryQualityOverview");
    expect(source).toContain("analyzeLiteraryQualityText");
    expect(source).toContain("runLiteraryQualityChapterSetReview");
    expect(source).toContain("chapterSetReview");
    expect(source).toContain("runChapterSetReview");
    expect(source).toContain("fetchLiteraryEvalLatest");
    expect(source).toContain("runLiteraryEval");
    expect(source).toContain("overviewItems");
    expect(source).toContain("riskClusters");
    expect(source).toContain("fingerprints");
    expect(source).toContain("crossSceneReuse");
    expect(source).toContain("recommendedNextAction");
    expect(source).toContain("analyzeText");
    expect(source).toContain("runBaselineEval");
    expect(source).toContain("runLiveEval");
  });

  it("renders manuscript patrol and benchmark tabs with deepdesk navigation", () => {
    const viewPath = path.join(SOURCE_ROOT, "src/views/LiteraryQualityView.vue");
    expect(existsSync(viewPath)).toBe(true);
    const source = readSource("src/views/LiteraryQualityView.vue");

    expect(source).toContain('data-testid="literary-quality-view"');
    expect(source).toContain('data-testid="quality-tab-overview"');
    expect(source).toContain('data-testid="quality-tab-chapter-set"');
    expect(source).toContain('data-testid="quality-tab-benchmark"');
    expect(source).toContain('data-testid="quality-filters"');
    expect(source).toContain('data-testid="quality-filter-risk-type"');
    expect(source).toContain('data-testid="quality-filter-min-severity"');
    expect(source).toContain('data-testid="quality-ad-hoc-scan"');
    expect(source).toContain('data-testid="quality-span-findings"');
    expect(source).toContain('data-testid="quality-risk-clusters"');
    expect(source).toContain('data-testid="quality-cross-scene-reuse"');
    expect(source).toContain('data-testid="quality-fingerprint-summary"');
    expect(source).toContain('data-testid="quality-overview-items"');
    expect(source).toContain('data-testid="quality-eval-report"');
    expect(source).toContain('data-testid="quality-chapter-set-review"');
    expect(source).toContain('data-testid="quality-chapter-set-input"');
    expect(source).toContain('data-testid="quality-chapter-set-run"');
    expect(source).toContain('data-testid="quality-chapter-set-scores"');
    expect(source).toContain('data-testid="quality-chapter-set-patterns"');
    expect(source).toContain('data-testid="quality-chapter-set-safety"');
    expect(source).toContain("model_voice");
    expect(source).toContain("image_homogeneity");
    expect(source).toContain("repetitive_action");
    expect(source).toContain("expository_dialogue");
    expect(source).toContain("template_action_reuse");
    expect(source).toContain("image_field_reuse");
    expect(source).toContain("syntax_monotony");
    expect(source).toContain("false_clarity");
    expect(source).toContain("valid_ambiguity");
    expect(source).toContain("choice_pressure");
    expect(source).toContain("painless_scene");
    expect(source).toContain("decorative_imagery");
    expect(source).toContain("dialogue_as_report");
    expect(source).toContain("over_explained_motive");
    expect(source).toContain("false_poetic_closure");
    expect(source).toContain("人物无痛");
    expect(source).toContain("装饰性意象");
    expect(source).toContain("汇报式对白");
    expect(source).toContain("quality_signal_id");
    expect(source).toContain("span_findings");
    expect(source).toContain("spanFindings");
    expect(source).toContain("recommended_next_action");
    expect(source).toContain('navigate("deepdesk")');
    expect(source).toContain("runBaselineEval");
    expect(source).toContain("runLiveEval");
  });
});
