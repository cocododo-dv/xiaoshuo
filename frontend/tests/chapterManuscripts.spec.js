// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { createApp, nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";
import { useShellRouter } from "../src/router";

const SOURCE_ROOT = process.cwd();
const VIEW_PATH = path.join(SOURCE_ROOT, "src/views/ChapterManuscriptView.vue");
const STORE_PATH = path.join(SOURCE_ROOT, "src/stores/chapterManuscripts.js");

function okEnvelope(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

function manuscriptListItem(overrides = {}) {
  return {
    chapter_id: "CHM900",
    planned_scene_count: 2,
    chapter_goal: "完整查看生成章节",
    main_plot_push: "推进调查",
    emotional_target: "稳定信任",
    ending_effect: "留下钩子",
    must_not: "",
    notes: "",
    current_phase: "drafting",
    chapter_passed_scene_count: 1,
    chapter_backfill_pending_count: 0,
    active_scene_count: 2,
    trashed_scene_count: 0,
    trash_allowed: 1,
    trash_block_reason: null,
    scene_count: 2,
    generated_scene_count: 1,
    missing_scene_ids: ["CHM900_SC02"],
    completion_status: "partial",
    comparison_status: "aggregate_differs_current",
    aggregate_row_id: "chapter_memory_final_CHM900_v1",
    ...overrides,
  };
}

function manuscriptDetail(overrides = {}) {
  return {
    chapter: {
      chapter_id: "CHM900",
      planned_scene_count: 2,
      mid_aggregate_enabled: 0,
      chapter_goal: "完整查看生成章节",
      main_plot_push: "推进调查",
      emotional_target: "稳定信任",
      ending_effect: "留下钩子",
      must_not: "",
      notes: "",
    },
    chapter_state: {
      chapter_id: "CHM900",
      current_phase: "drafting",
      chapter_passed_scene_count: 1,
      chapter_backfill_pending_count: 0,
    },
    completion_status: "partial",
    comparison_status: "aggregate_differs_current",
    assembled: {
      content: "第一场正文",
      char_count: 5,
      scene_count: 2,
      generated_scene_count: 1,
      missing_scene_ids: ["CHM900_SC02"],
    },
    aggregate: {
      row_id: "chapter_memory_final_CHM900_v1",
      content: "旧版聚合正文",
      char_count: 6,
      created_at: "2026-04-22T01:00:00+00:00",
    },
    scenes: [
      {
        scene_id: "CHM900_SC01",
        chapter_id: "CHM900",
        scene_seq: 1,
        scene_goal: "找到线索",
        beats_json: ["进入", "发现"],
        must_include_text: "",
        forbidden_text: "",
        exit_change: "",
        hook: "",
        target_length_band: "medium",
        scene_type: "reunion",
        is_chapter_last: 0,
        scene_status: "archived",
        current_bundle_id: "bundle_CHM900_SC01",
        current_final_scene_row_id: "final_scene_CHM900_SC01_v1",
        final_scene: {
          row_id: "final_scene_CHM900_SC01_v1",
          char_count: 5,
          created_at: "2026-04-22T00:55:00+00:00",
        },
      },
      {
        scene_id: "CHM900_SC02",
        chapter_id: "CHM900",
        scene_seq: 2,
        scene_goal: "制造悬念",
        beats_json: [],
        must_include_text: "",
        forbidden_text: "",
        exit_change: "",
        hook: "",
        target_length_band: "medium",
        scene_type: "bridge",
        is_chapter_last: 1,
        scene_status: "ready",
        current_bundle_id: null,
        current_final_scene_row_id: null,
        final_scene: null,
      },
    ],
    source_safety_scan: {
      safe: true,
      blocked_terms: [],
      source_profile_ids: [],
      checked_at: "2026-04-23T00:00:00+00:00",
    },
    editorial_workspace: {
      reading_source: "assembled",
      chapter_review: {
        status: "reviewed",
        object_type: "chapter",
        object_id: "CHM900",
        latest_score: 0.61,
        candidate_count: 1,
        latest_evaluation: {
          evaluation_id: "writer_eval_CHM900",
          overall_score: 0.61,
          scores: { ending_drive: 0.52 },
          findings: [
            {
              dimension: "ending_drive",
              severity: "major",
              issue: "chapter ending stalls",
              recommendation: "end on a sharper choice",
              evidence_excerpt: "aggregate evidence excerpt",
              evidence_location: "chapter close",
              why_it_matters: "keeps the next chapter urgent",
            },
          ],
          revision_brief: [{ dimension: "ending_drive", action: "sharpen the final beat", priority: "high" }],
          requires_human_review: false,
        },
        candidates: [
          {
            revision_id: "revision_CHM900",
            object_type: "chapter",
            object_id: "CHM900",
            revision_type: "chapter_revision",
            proposed_text: "chapter revision plan preview",
            status: "candidate",
            diff_summary: {
              summary: "reshape the closing beat",
              changed_dimensions: ["ending_drive"],
              candidate_kind: "revision_plan",
              rewrite_strategy: "revision_plan",
            },
          },
        ],
      },
      scene_reviews: [
        {
          scene_id: "CHM900_SC01",
          scene_seq: 1,
          scene_goal: "鎵惧埌绾跨储",
          review: {
            status: "reviewed",
            latest_evaluation: {
              evaluation_id: "writer_eval_CHM900_SC01",
              overall_score: 0.57,
              scores: { dialogue_edge: 0.49 },
              findings: [
                {
                  dimension: "dialogue_edge",
                  severity: "major",
                  issue: "scene reply is too soft",
                  recommendation: "cut polite filler",
                  evidence_excerpt: "scene evidence excerpt",
                  evidence_location: "scene 1",
                  why_it_matters: "power shift needs to be visible",
                },
              ],
              revision_brief: [{ dimension: "dialogue_edge", action: "make the reply cost something", priority: "high" }],
              requires_human_review: true,
            },
            candidates: [],
          },
        },
      ],
      revision_candidates: [
        {
          revision_id: "revision_CHM900",
          object_type: "chapter",
          object_id: "CHM900",
          status: "candidate",
          proposed_text: "chapter revision plan preview",
          diff_summary: { summary: "reshape the closing beat", candidate_kind: "revision_plan" },
        },
      ],
      open_issue_counts: {
        open_candidates: 1,
        findings: 2,
        requires_human_review: 1,
        reviewed_objects: 2,
      },
    },
    ...overrides,
  };
}

async function flushUi() {
  for (let index = 0; index < 4; index += 1) {
    await Promise.resolve();
    await nextTick();
    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  }
}

describe("chapter manuscript shell registration", () => {
  it("registers a dedicated chapter manuscript view and store", () => {
    const appSource = readFileSync(path.join(SOURCE_ROOT, "src/App.vue"), "utf8");
    const routerSource = readFileSync(path.join(SOURCE_ROOT, "src/router.js"), "utf8");

    expect(existsSync(VIEW_PATH)).toBe(true);
    expect(existsSync(STORE_PATH)).toBe(true);
    expect(appSource).toContain("ChapterManuscriptView");
    expect(routerSource).toContain('id: "manuscripts"');
    expect(routerSource).toContain("章节成稿中心");
    expect(routerSource).toContain('targetType === "chapter_manuscript"');
    expect(routerSource).toContain('return "manuscripts"');
  });
});

describe("chapter manuscript api helpers", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn(async (url, options = {}) =>
      okEnvelope({
        url,
        method: options.method || "GET",
        body: options.body ? JSON.parse(options.body) : null,
      }),
    );
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls the dedicated manuscript endpoints and reused management endpoints", async () => {
    expect(typeof api.fetchChapterManuscripts).toBe("function");
    expect(typeof api.fetchChapterManuscriptDetail).toBe("function");

    await api.fetchChapterManuscripts();
    await api.fetchChapterManuscriptDetail("CHM900");
    await api.runChapterFull("CHM900");
    await api.runChapterFinalAggregate("CHM900");

    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/chapter-manuscripts");
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/chapter-manuscripts/CHM900");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chapters/CHM900/run/full",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chapters/CHM900/runtime/aggregate/final",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("chapter manuscript store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads list and detail, then refreshes after chapter actions", async () => {
    const state = {
      items: [manuscriptListItem()],
      detail: manuscriptDetail(),
      runCount: 0,
      aggregateCount: 0,
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const requestUrl = String(url);
      if (requestUrl.endsWith("/api/v1/chapter-manuscripts")) {
        return okEnvelope({ items: state.items });
      }
      if (requestUrl.endsWith("/api/v1/chapter-manuscripts/CHM900")) {
        return okEnvelope(state.detail);
      }
      if (requestUrl.endsWith("/api/v1/chapters/CHM900/run/full") && options.method === "POST") {
        state.runCount += 1;
        state.detail = manuscriptDetail({
          completion_status: "complete",
          assembled: {
            content: "第一场正文\n第二场正文",
            char_count: 11,
            scene_count: 2,
            generated_scene_count: 2,
            missing_scene_ids: [],
          },
          scenes: manuscriptDetail().scenes.map((scene) =>
            scene.scene_id === "CHM900_SC02"
              ? {
                  ...scene,
                  scene_status: "archived",
                  current_final_scene_row_id: "final_scene_CHM900_SC02_v1",
                  final_scene: { row_id: "final_scene_CHM900_SC02_v1", char_count: 5, created_at: "2026-04-22T01:30:00+00:00" },
                }
              : scene,
          ),
        });
        state.items = [manuscriptListItem({ completion_status: "complete", generated_scene_count: 2, missing_scene_ids: [] })];
        return okEnvelope({ status: "completed", chapter_id: "CHM900" });
      }
      if (requestUrl.endsWith("/api/v1/chapters/CHM900/runtime/aggregate/final") && options.method === "POST") {
        state.aggregateCount += 1;
        state.detail = {
          ...state.detail,
          comparison_status: "aggregate_matches_current",
          aggregate: {
            row_id: "chapter_memory_final_CHM900_v2",
            content: state.detail.assembled.content,
            char_count: state.detail.assembled.char_count,
            created_at: "2026-04-22T02:00:00+00:00",
          },
        };
        state.items = [manuscriptListItem({ comparison_status: "aggregate_matches_current", aggregate_row_id: "chapter_memory_final_CHM900_v2" })];
        return okEnvelope({ status: "created", chapter_memory_row_id: "chapter_memory_final_CHM900_v2" });
      }
      throw new Error(`Unexpected fetch: ${requestUrl}`);
    });

    const { useChapterManuscriptsStore } = await import("../src/stores/chapterManuscripts.js");
    const store = useChapterManuscriptsStore();

    await store.initialize();

    expect(store.items).toHaveLength(1);
    expect(store.selectedChapterId).toBe("CHM900");
    expect(store.detail.assembled.content).toBe("第一场正文");
    expect(store.detail.comparison_status).toBe("aggregate_differs_current");
    expect(store.canUseAggregate).toBe(true);
    expect(store.exportMarkdown("assembled")).toContain("# CHM900");
    expect(store.exportText("aggregate")).toBe("旧版聚合正文");

    const runMessage = await store.runSelectedChapter();
    expect(runMessage).toContain("CHM900");
    expect(state.runCount).toBe(1);
    expect(store.detail.completion_status).toBe("complete");
    expect(store.detail.assembled.missing_scene_ids).toEqual([]);

    const aggregateMessage = await store.runFinalAggregate();
    expect(aggregateMessage).toContain("chapter_memory_final_CHM900_v2");
    expect(state.aggregateCount).toBe(1);
    expect(store.detail.comparison_status).toBe("aggregate_matches_current");
  });
});

describe("chapter manuscript view", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    setActivePinia(createPinia());
    useShellRouter().reset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("renders chapter management, side-by-side manuscript panes, and export actions", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      const requestUrl = String(url);
      if (requestUrl.endsWith("/api/v1/chapter-manuscripts")) {
        return okEnvelope({ items: [manuscriptListItem()] });
      }
      if (requestUrl.endsWith("/api/v1/chapter-manuscripts/CHM900")) {
        return okEnvelope(manuscriptDetail());
      }
      throw new Error(`Unexpected fetch: ${requestUrl}`);
    });

    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn(async () => undefined),
      },
    });

    const { default: ChapterManuscriptView } = await import("../src/views/ChapterManuscriptView.vue");
    const pinia = createPinia();
    setActivePinia(pinia);
    const container = document.createElement("div");
    document.body.appendChild(container);
    const app = createApp(ChapterManuscriptView);
    app.use(pinia);
    app.mount(container);

    try {
      await flushUi();

      expect(container.querySelector('[data-testid="chapter-manuscript-view"]')).not.toBeNull();
      const chapterList = container.querySelector('[data-testid="manuscript-chapter-list"]');
      expect(chapterList).not.toBeNull();
      expect(chapterList.className).toContain("readable-list");
      const chapterRow = chapterList.querySelector(".manuscript-list-row");
      expect(chapterRow.className).toContain("readable-selector-row");
      expect(chapterRow.querySelector(".readable-row-title").textContent).toContain("完整查看生成章节");
      expect(chapterRow.querySelector(".readable-tech-ref").textContent).toContain("CHM900");
      expect(container.querySelector('[data-testid="manuscript-management-panel"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="assembled-manuscript-pane"]').textContent).toContain("第一场正文");
      expect(container.querySelector('[data-testid="aggregate-manuscript-pane"]').textContent).toContain("旧版聚合正文");
      expect(container.textContent).toContain("聚合不同步");
      expect(container.textContent).toContain("CHM900_SC02");
      expect(container.querySelector('[data-testid="copy-assembled-button"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="download-aggregate-button"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="run-final-aggregate-button"]')).not.toBeNull();
      expect(container.querySelector('[data-testid="manuscript-source-safety-card"]')).not.toBeNull();
      expect(container.textContent).toContain("源书安全扫描");

      expect(container.querySelector('[data-testid="manuscript-editorial-workspace"]')).not.toBeNull();
      expect(container.textContent).toContain("aggregate evidence excerpt");
      expect(container.textContent).toContain("scene evidence excerpt");
      expect(container.textContent).toContain("chapter revision plan preview");

      container.querySelector('[data-testid="copy-assembled-button"]').click();
      await flushUi();
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining("第一场正文"));
    } finally {
      app.unmount();
      container.remove();
    }
  });

  it("keeps expected source anchors for management and exports", () => {
    const source = readFileSync(VIEW_PATH, "utf8");

    expect(source).toContain("downloadManuscript");
    expect(source).toContain("copyManuscript");
    expect(source).toContain("runSelectedChapter");
    expect(source).toContain("runFinalAggregate");
    expect(source).toContain("openSceneWorkbench");
    expect(source).toContain("saveChapter");
    expect(source).toContain("saveScene");
    expect(source).toContain("reorderScenes");
    expect(source).toContain("trashScenes");
    expect(source).toContain("manuscript-source-safety-card");
    expect(source).toContain("sourceSafetyScan");
    expect(source).toContain("editorialWorkspace");
    expect(source).toContain("manuscript-editorial-workspace");
  });
});
