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
    expect(routerSource).toContain("写作与深改台");
    expect(routerSource).toContain("写作深改");
    expect(routerSource).toContain("反向提取戏剧卡");
    expect(routerSource).toContain('nextViews: ["author", "manuscripts", "longform", "workbench"]');
    expect(appSource).toContain("deepdesk: defineAsyncComponent");
    expect(appSource).toContain("./views/WriterDeepDeskView.vue");
  });

  it("exposes blank draft, structure extraction, deep review, passage patch, and author preference API helpers", () => {
    const apiSource = readSource("src/lib/api.js");

    expect(apiSource).toContain("fetchCurrentAuthorDraft");
    expect(apiSource).toContain("ensureAuthorDraft");
    expect(apiSource).toContain("ensureBlankAuthorDraft");
    expect(apiSource).toContain("deriveAuthorDraftFromGeneration");
    expect(apiSource).toContain("saveAuthorDraft");
    expect(apiSource).toContain("recordAuthorDraftCandidateEvent");
    expect(apiSource).toContain("applyAuthorDraftPatchOption");
    expect(apiSource).toContain("extractAuthorDraftStructure");
    expect(apiSource).toContain("applyAuthorStructureCandidate");
    expect(apiSource).toContain("rejectAuthorStructureCandidate");
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
    expect(apiSource).toContain("/author-drafts");
    expect(apiSource).toContain("/ensure-blank");
    expect(apiSource).toContain("/derive-from-generation");
    expect(apiSource).toContain("/apply-patch-option");
    expect(apiSource).toContain("/structure-extract");
    expect(apiSource).toContain("/author-structure-candidates");
    expect(apiSource).toContain("/author-preference-profile");
  });

  it("adds a focused store without deep watchers for long chapter text", () => {
    const storePath = path.join(SOURCE_ROOT, "src/stores/writerDeepDesk.js");
    expect(existsSync(storePath)).toBe(true);
    const source = readSource("src/stores/writerDeepDesk.js");

    expect(source).toContain('defineStore("writerDeepDesk"');
    expect(source).toContain('draftMode: "chapter"');
    expect(source).toContain("authorDraft");
    expect(source).toContain("draftContent");
    expect(source).toContain("draftDirty");
    expect(source).toContain("ensureAuthorDraft");
    expect(source).toContain("ensureBlankAuthorDraft as ensureBlankAuthorDraftApi");
    expect(source).toContain("deriveAuthorDraftFromGeneration");
    expect(source).toContain("applyAuthorDraftPatchOption");
    expect(source).toContain("runFullScene");
    expect(source).toContain('deskMode: "write_first"');
    expect(source).toContain("setDeskMode");
    expect(source).toContain("runAiDraftToAuthorDraft");
    expect(source).toContain("saveAuthorDraft");
    expect(source).toContain("recordAuthorDraftCandidateEvent");
    expect(source).toContain("structureCandidates");
    expect(source).toContain("structureCandidateRows");
    expect(source).toContain("extractAuthorStructure");
    expect(source).toContain("applyStructureCandidate");
    expect(source).toContain("rejectStructureCandidate");
    expect(source).toContain("insertCandidateOption");
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
    expect(source).toContain('data-testid="draft-mode-chapter"');
    expect(source).toContain('data-testid="draft-mode-scene"');
    expect(source).toContain('data-testid="desk-mode-write-first"');
    expect(source).toContain('data-testid="desk-mode-ai-draft"');
    expect(source).toContain('data-testid="ai-draft-to-author-draft"');
    expect(source).toContain('data-testid="author-draft-editor"');
    expect(source).toContain('data-testid="author-draft-ensure-blank"');
    expect(source).toContain('data-testid="author-draft-save"');
    expect(source).toContain('data-testid="structure-extract-run"');
    expect(source).toContain('data-testid="author-structure-candidates"');
    expect(source).toContain('data-testid="author-structure-apply"');
    expect(source).toContain('data-testid="author-structure-reject"');
    expect(source).toContain('data-testid="deep-review-run"');
    expect(source).toContain('data-testid="patch-candidate-create"');
    expect(source).toContain('data-testid="deep-review-findings"');
    expect(source).toContain('data-testid="passage-patch-candidates"');
    expect(source).toContain('data-testid="author-preference-profile"');
    expect(source).toContain("写作与深改台");
    expect(source).toContain("我先写");
    expect(source).toContain("AI 起草");
    expect(source).toContain("运行并转为作者稿");
    expect(source).toContain("创建空白作者稿");
    expect(source).toContain("反向提取戏剧卡");
    expect(source).toContain("结构候选");
    expect(source).toContain("作者稿");
    expect(source).toContain("运行终稿");
    expect(source).toContain("最终聚合稿");
    expect(source).toContain("放入稿件");
    expect(source).toContain("candidate.status !== 'candidate'");
  });

  it("uses the writer desk as the default first screen", () => {
    const routerSource = readSource("src/router.js");

    expect(routerSource).toContain('const activeView = ref("deepdesk")');
    expect(routerSource).toContain('const visitedViews = ref(["deepdesk"])');
  });
});
