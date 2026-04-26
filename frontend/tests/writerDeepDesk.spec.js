// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";

const SOURCE_ROOT = process.cwd();

function readSource(relativePath) {
  return readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
}

function okEnvelope(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

function chapterListPayload() {
  return {
    items: [
      {
        chapter_id: "DESKFE100",
        chapter_goal: "林岑必须决定是否公开证据。",
        completion_status: "partial",
        comparison_status: "aggregate_missing",
      },
    ],
  };
}

function chapterDetailPayload() {
  return {
    chapter_id: "DESKFE100",
    aggregate: { row_id: "chapter_memory_final_DESKFE100_v1", content: "最终聚合稿。" },
    assembled: { content: "实时拼接稿。" },
    scenes: [
      {
        scene_id: "DESKFE100_SC01",
        chapter_id: "DESKFE100",
        scene_goal: "她先关门再公开录音。",
        final_scene: { row_id: "final_scene_DESKFE100_SC01_v1" },
      },
    ],
  };
}

function authorDraftPayload() {
  return {
    draft: {
      draft_id: "author_draft_scene_DESKFE100_SC01",
      object_type: "scene",
      object_id: "DESKFE100_SC01",
      source_text_ref: "final_scene:final_scene_DESKFE100_SC01_v1",
      content: "作者稿正文。",
      revision_no: 2,
      status: "current",
    },
    draft_mode: "scene",
    desk_mode: "write_first",
    source_layer: "author_draft",
    open_structure_candidates: [],
    open_patch_candidates: [],
    author_preference_summary: {},
  };
}

function deskSnapshotPayload() {
  return {
    target: {
      object_type: "scene",
      object_id: "DESKFE100_SC01",
      chapter_id: "DESKFE100",
      scene_id: "DESKFE100_SC01",
    },
    author_draft: authorDraftPayload().draft,
    runtime_text: {
      source_ref: "final_scene:final_scene_DESKFE100_SC01_v1",
      content: "运行终稿。",
      text_layer: "runtime_final_scene",
    },
    aggregate_text: {
      source_ref: "chapter_memory:chapter_memory_final_DESKFE100_v1",
      content: "最终聚合稿。",
      text_layer: "chapter_memory_final",
    },
    deep_review_summary: {
      overall_score: 0.62,
      top_findings: [{ dimension: "choice_pressure", issue: "代价不够具体。" }],
    },
    open_candidates: [
      {
        candidate_type: "passage_patch",
        patch_id: "patch_DESKFE100",
        candidate_category: "dialogue_rewrite",
        revision_strategy: "反问替代解释",
        preference_tags: ["少解释", "对白更短"],
        inserted_into_author_draft: true,
        replacement_options: [{ option_id: "subtle", label: "更含蓄", replacement_text: "她没有回答。" }],
      },
    ],
    longform_pressure: [
      {
        card_id: "lf_DESKFE100_arc",
        card_type: "character_arc_gap",
        severity: "critical",
        recommendation: { summary: "让人物付出可见代价。" },
      },
    ],
    author_preference_summary: { preferred_moves: ["更含蓄"] },
  };
}

describe("writer deep revision desk", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

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

    expect(apiSource).toContain("fetchAuthorDeskSnapshot");
    expect(apiSource).toContain("/api/v1/author-desk");
    expect(apiSource).toContain("fetchAuthorDraftEvents");
    expect(apiSource).toContain("/events");
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

  it("calls author desk snapshot and draft events API helpers", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.fetchAuthorDeskSnapshot("scene", "DESKFE100_SC01");
    await api.fetchAuthorDraftEvents("author_draft_scene_DESKFE100_SC01");

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-desk/scene/DESKFE100_SC01/snapshot");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/author-drafts/author_draft_scene_DESKFE100_SC01/events");
  });

  it("hydrates the writer desk snapshot, timeline, and longform pressure in the store", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      const path = String(url);
      if (path.includes("/chapter-manuscripts/DESKFE100")) {
        return okEnvelope(chapterDetailPayload());
      }
      if (path.includes("/chapter-manuscripts")) {
        return okEnvelope(chapterListPayload());
      }
      if (path.includes("/ensure-blank")) {
        return okEnvelope(authorDraftPayload());
      }
      if (path.includes("/deep-review")) {
        return okEnvelope({ latest_evaluation: null, lens_evaluations: [], patch_candidates: [] });
      }
      if (path.includes("/author-preference-profile")) {
        return okEnvelope({ profile: { summary: { preferred_moves: ["更含蓄"] } } });
      }
      if (path.includes("/author-desk/scene/DESKFE100_SC01/snapshot")) {
        return okEnvelope(deskSnapshotPayload());
      }
      if (path.includes("/author-drafts/author_draft_scene_DESKFE100_SC01/events")) {
        return okEnvelope({
          draft_id: "author_draft_scene_DESKFE100_SC01",
          events: [{ event_type: "created" }, { event_type: "edited" }],
        });
      }
      return okEnvelope({});
    });

    const { useWriterDeepDeskStore } = await import("../src/stores/writerDeepDesk.js");
    const store = useWriterDeepDeskStore();

    await store.initialize({ force: true });
    await store.setDraftMode("scene");

    expect(store.authorDeskSnapshot.target.object_id).toBe("DESKFE100_SC01");
    expect(store.longformPressure[0].card_type).toBe("character_arc_gap");
    expect(store.snapshotOpenCandidates[0].candidate_category).toBe("dialogue_rewrite");
    expect(store.snapshotOpenCandidates[0].preference_tags).toEqual(["少解释", "对白更短"]);
    expect(store.draftEvents.map((event) => event.event_type)).toEqual(["created", "edited"]);
    expect(store.deskStage).toBe("write");
    store.setDeskStage("longform");
    expect(store.deskStage).toBe("longform");
  });

  it("adds a focused store without deep watchers for long chapter text", () => {
    const storePath = path.join(SOURCE_ROOT, "src/stores/writerDeepDesk.js");
    expect(existsSync(storePath)).toBe(true);
    const source = readSource("src/stores/writerDeepDesk.js");

    expect(source).toContain('defineStore("writerDeepDesk"');
    expect(source).toContain('draftMode: "chapter"');
    expect(source).toContain("authorDraft");
    expect(source).toContain("authorDeskSnapshot");
    expect(source).toContain("draftEvents");
    expect(source).toContain("longformPressure");
    expect(source).toContain('deskStage: "write"');
    expect(source).toContain("loadAuthorDeskSnapshot");
    expect(source).toContain("loadDraftEvents");
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
    expect(source).toContain('data-testid="desk-stage-write"');
    expect(source).toContain('data-testid="desk-stage-ai"');
    expect(source).toContain('data-testid="desk-stage-review"');
    expect(source).toContain('data-testid="desk-stage-longform"');
    expect(source).toContain('data-testid="desk-longform-pressure"');
    expect(source).toContain('data-testid="author-draft-events"');
    expect(source).toContain("candidateCategoryLabel");
    expect(source).toContain("candidateMetaLine");
    expect(source).toContain("已放入稿件");
    expect(source).toContain("偏好标签");
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
    expect(source).toContain("深改诊断");
    expect(source).toContain("长篇压力");
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
