// @vitest-environment jsdom

import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import { createApp, nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";
import { useShellRouter } from "../src/router";
import { useReferenceLearningStore } from "../src/stores/referenceLearning";
import ReferenceLearningView from "../src/views/ReferenceLearningView.vue";

const REFERENCE_VIEW_PATH = resolve(process.cwd(), "src/views/ReferenceLearningView.vue");
const REFERENCE_STORE_PATH = resolve(process.cwd(), "src/stores/referenceLearning.js");
const ROUTER_PATH = resolve(process.cwd(), "src/router.js");
const API_PATH = resolve(process.cwd(), "src/lib/api.js");
const APP_PATH = resolve(process.cwd(), "src/App.vue");
const STYLE_PATH = resolve(process.cwd(), "src/styles/app.css");

function ok(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

function fail(code, message, status = 409) {
  return {
    ok: false,
    status,
    json: async () => ({ ok: false, data: null, error: { code, message } }),
  };
}

function referenceDetail(status = "waiting_review") {
  return {
    book: {
      book_id: "refbook_alpha",
      title: "Reference Alpha",
      cloud_policy: "allow_full_cloud",
      analysis_focus: "style_structure",
      status,
      total_segments: 8,
    },
    coverage: {
      approved_findings: status === "completed" ? 5 : 0,
      pending_findings: status === "waiting_review" ? 2 : 0,
      coverage_score: status === "completed" ? 1 : 0.25,
      dimension_coverage_score: status === "completed" ? 1 : 0.25,
      sample_coverage_score: status === "completed" ? 0.63 : 0.25,
      sampled_segments: status === "completed" ? 5 : 2,
      eligible_segments: 8,
      remaining_segments: status === "completed" ? 3 : 6,
      learning_complete: false,
      profile_ready: status === "completed",
      next_round_available: true,
      ready: status === "completed",
    },
    latest_run: {
      run_id: "refrun_alpha",
      status,
      round_count: 1,
      coverage: { coverage_score: 0.25 },
    },
    profiles:
      status === "completed"
        ? [
            {
              profile_id: "refprofile_alpha",
              title: "Reference Alpha profile",
              status: "ready",
              coverage: {
                approved_findings: 5,
                ready: true,
                profile_stale: false,
                sampled_segments: 5,
                eligible_segments: 8,
                remaining_segments: 3,
                sample_coverage_score: 0.63,
                learning_complete: false,
                next_round_available: true,
              },
              application_status: {
                total: 0,
                pending: 0,
                approved: 0,
                rejected: 0,
                review_ids: [],
                scope: null,
                scope_ref_id: null,
              },
              model_trace: {
                provider: "local",
                model: "local-heuristic",
                node_id: "reference_profile_synthesize",
                success_count: 0,
                failure_count: 0,
                quality_score: 0.82,
                mode: "local_heuristic",
              },
              safety_summary: { safe: true, stripped_count: 2, blocked_markers: [] },
              profile_json: {
                style_profile: {
                  contract_version: "STYLE_FEATURE_CONTRACT_v1",
                  features: {
                    rhythm: { guidance: ["Use compact pressure beats."] },
                  },
                  banned_moves: ["Do not copy protected expression."],
                },
                narrative_patterns: ["Use chapter hook escalation and delayed explanation."],
              },
            },
          ]
        : [],
  };
}

function staleReferenceDetail() {
  const detail = referenceDetail("completed");
  detail.coverage = {
    ...detail.coverage,
    profile_stale: true,
  };
  detail.latest_run.coverage = {
    ...detail.latest_run.coverage,
    profile_stale: true,
  };
  detail.profiles = [
    {
      ...detail.profiles[0],
      status: "stale",
      coverage: { ...detail.profiles[0].coverage, profile_stale: true },
    },
  ];
  return detail;
}

function roundPayload() {
  return {
    run: {
      run_id: "refrun_alpha",
      book_id: "refbook_alpha",
      status: "waiting_review",
      round_count: 1,
      coverage: { coverage_score: 0.25, pending_findings: 2 },
    },
    round: {
      round_id: "refround_alpha_1",
      status: "waiting_review",
      findings: [
        {
          finding_id: "reffind_1",
          finding_type: "style_rule_set",
          dimension: "rhythm",
          summary: "Use short pressure beats before release.",
          status: "pending",
          model_trace: {
            provider: "fake",
            model: "qwen3-local",
            node_id: "reference_style_structure_extract",
            success_count: 1,
            failure_count: 0,
            quality_score: 0.91,
          },
          source_segment: {
            segment_id: "refseg_alpha_0001",
            preview: null,
            chapter_hint: "第一章 雨夜来信",
            display_label: "opening segment",
            segment_kind: "opening",
          },
          review: { review_id: "review_reffind_1", item_type: "style_rule_set", status: "pending" },
        },
        {
          finding_id: "reffind_2",
          finding_type: "narrative_pattern",
          dimension: "chapter hook",
          summary: "Use chapter hook escalation.",
          status: "pending",
          model_trace: {
            provider: "local",
            model: "local-heuristic",
            node_id: "reference_style_structure_extract",
            success_count: 0,
            failure_count: 0,
            quality_score: 0.72,
            mode: "local_heuristic",
          },
          source_segment: {
            segment_id: "refseg_alpha_0002",
            preview: null,
            chapter_hint: "第二章 卡塞尔访客",
            display_label: "structure segment",
            segment_kind: "structure",
          },
          review: { review_id: "review_reffind_2", item_type: "narrative_pattern", status: "pending" },
        },
      ],
    },
  };
}

async function flushUi() {
  await nextTick();
  await new Promise((resolve) => {
    setTimeout(resolve, 0);
  });
}

async function mountReferenceLearningViewWithRound(payload = roundPayload()) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useShellRouter().reset();
  globalThis.fetch = vi.fn(async () => ok({ items: [] }));

  const store = useReferenceLearningStore();
  store.books = [{ book_id: "refbook_alpha", title: "Reference Alpha", status: "waiting_review" }];
  store.selectedBookId = "refbook_alpha";
  store.detail = referenceDetail("waiting_review");
  store.currentRun = payload.run;
  store.currentRound = payload.round;
  store.loaded = true;

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp(ReferenceLearningView);
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

async function mountReferenceLearningViewWithDetail(detail) {
  const pinia = createPinia();
  setActivePinia(pinia);
  useShellRouter().reset();
  globalThis.fetch = vi.fn(async () => ok({ items: [] }));

  const store = useReferenceLearningStore();
  store.books = [{ book_id: detail.book.book_id, title: detail.book.title, status: detail.book.status }];
  store.selectedBookId = detail.book.book_id;
  store.detail = detail;
  store.currentRun = detail.latest_run;
  store.currentRound = null;
  store.loaded = true;

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp(ReferenceLearningView);
  app.use(pinia);
  app.mount(container);
  await flushUi();

  return {
    container,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

describe("reference learning shell registration", () => {
  it("adds the reference learning view to the shell navigation", () => {
    const appSource = readFileSync(APP_PATH, "utf8");
    const routerSource = readFileSync(ROUTER_PATH, "utf8");

    expect(existsSync(REFERENCE_VIEW_PATH)).toBe(true);
    expect(existsSync(REFERENCE_STORE_PATH)).toBe(true);
    expect(appSource).toContain("ReferenceLearningView");
    expect(routerSource).toContain('id: "reference"');
    expect(routerSource).toContain('label: "9 学习参考"');
    expect(routerSource).toContain('legacyLabel: "参考书学习"');
  });
});

describe("reference learning api helpers", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn(async () => ok({}));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls the reference learning endpoints", async () => {
    await api.fetchReferenceBooks();
    await api.importReferenceBookPath({
      file_path: "E:/books/reference.md",
      title: "Reference",
      cloud_policy: "allow_full_cloud",
      analysis_focus: "style_structure",
    });
    await api.fetchReferenceBook("refbook_alpha");
    await api.fetchReferenceLearningTree("refbook_alpha");
    await api.fetchReferenceSegmentExcerpt("refbook_alpha", "refseg_alpha_0001");
    await api.startReferenceLearningRun("refbook_alpha", { batch_size: 8 });
    await api.advanceReferenceLearningRun("refbook_alpha", "refrun_alpha");
    await api.applyReferenceProfile("refbook_alpha", "refprofile_alpha", {
      scope: "chapter",
      scope_ref_id: "CH001",
    });
    await api.rejectReview("review_reffind_1", { reason: "重复样本" });

    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/reference-books");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/reference-books/import-path",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/reference-books/refbook_alpha");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/reference-books/refbook_alpha/learning-tree",
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/reference-books/refbook_alpha/segments/refseg_alpha_0001/excerpt",
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/reference-books/refbook_alpha/runs",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/reference-books/refbook_alpha/runs/refrun_alpha/advance",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/reference-books/refbook_alpha/profiles/refprofile_alpha/apply",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/review-items/review_reffind_1/reject",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("reference learning store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/reference-books")) {
        return ok({ items: [{ book_id: "refbook_alpha", title: "Reference Alpha", status: "imported" }] });
      }
      if (url.endsWith("/api/v1/reference-books/import-path")) {
        return ok({ book_id: "refbook_alpha", book: { book_id: "refbook_alpha", title: "Reference Alpha" } });
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha/runs")) {
        return ok({ run: { run_id: "refrun_alpha", status: "running", round_count: 0 } });
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha/runs/refrun_alpha/advance")) {
        return ok(roundPayload());
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha/segments/refseg_alpha_0001/excerpt")) {
        return ok({
          segment_id: "refseg_alpha_0001",
          display_label: "开篇片段",
          excerpt: "雨敲在窗台上，房间里只剩屏幕的蓝光。",
          max_chars: 800,
          source_visibility: "review_only",
          safety_note: "仅供审核，不进入生成链路。",
        });
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha/learning-tree")) {
        return ok({
          book: { book_id: "refbook_alpha", title: "Reference Alpha" },
          summary: {
            run_count: 1,
            round_count: 1,
            finding_count: 2,
            profile_count: 1,
            apply_review_count: 1,
          },
          runs: [
            {
              run_id: "refrun_alpha",
              status: "completed",
              rounds: [
                {
                  round_id: "refround_alpha_1",
                  round_index: 1,
                  findings: roundPayload().round.findings,
                },
              ],
            },
          ],
          profiles: [{ profile_id: "refprofile_alpha", application_status: { total: 1, pending: 1 } }],
          active_knowledge_refs: [],
        });
      }
      if (url.endsWith("/api/v1/review-items/review_reffind_1/approve")) {
        return ok({ review_id: "review_reffind_1", materialize_status: "succeeded" });
      }
      if (url.endsWith("/api/v1/review-items/review_reffind_2/reject")) {
        return ok({ review_id: "review_reffind_2", status: "rejected" });
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha/profiles/refprofile_alpha/apply")) {
        return ok({
          applied: false,
          reviews: [{ review_id: "review_apply_ref", item_type: "narrative_pattern", status: "pending" }],
          application_status: {
            total: 1,
            pending: 1,
            approved: 0,
            rejected: 0,
            review_ids: ["review_apply_ref"],
            scope: "chapter",
            scope_ref_id: "CH001",
          },
        });
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha")) {
        return ok(referenceDetail(options.method === "POST" ? "waiting_review" : "completed"));
      }
      return ok({});
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("imports a path, advances a run, makes review decisions, and applies a profile", async () => {
    const { useReferenceLearningStore } = await import("../src/stores/referenceLearning.js");
    const store = useReferenceLearningStore();

    await store.initialize();
    expect(store.books).toHaveLength(1);

    await store.importPath({
      file_path: "E:/books/reference.md",
      title: "Reference Alpha",
      cloud_policy: "allow_full_cloud",
      analysis_focus: "style_structure",
    });
    expect(store.selectedBookId).toBe("refbook_alpha");

    await store.startRun();
    expect(store.lastActionMessage).toContain("学习任务已启动");
    await store.advanceRun();
    expect(store.currentRound.findings).toHaveLength(2);
    expect(store.pendingDecisionCount).toBe(2);
    expect(store.lastActionMessage).toContain("第 1 轮候选卡");

    await store.approveFinding("review_reffind_1");
    await store.rejectFinding("review_reffind_2", "重复样本");
    expect(store.approvedDecisionCount).toBe(1);
    expect(store.rejectedDecisionCount).toBe(1);
    expect(store.pendingDecisionCount).toBe(0);
    expect(store.lastActionMessage).toContain("已拒绝 1 张候选卡");

    store.detail = referenceDetail("completed");
    await store.applyProfile("refprofile_alpha", { scope: "chapter", scope_ref_id: "CH001" });
    expect(store.lastActionMessage).toContain("已创建 1 个应用审核项");
    expect(store.detail.profiles[0].application_status.pending).toBe(1);
    expect(store.detail.profiles[0].application_status.review_ids).toEqual(["review_apply_ref"]);

    const excerpt = await store.fetchSegmentExcerpt("refseg_alpha_0001");
    expect(excerpt.excerpt).toContain("雨敲在窗台上");
    expect(store.segmentExcerpts.refseg_alpha_0001.source_visibility).toBe("review_only");

    const tree = await store.loadLearningTree();
    expect(tree.summary.run_count).toBe(1);
    expect(store.learningTree.runs[0].rounds[0].findings).toHaveLength(2);
  });

  it("refreshes detail and explains stale profile apply failures", async () => {
    const { useReferenceLearningStore } = await import("../src/stores/referenceLearning.js");
    const store = useReferenceLearningStore();
    let detailReads = 0;
    globalThis.fetch = vi.fn(async (url) => {
      if (url.endsWith("/api/v1/reference-books")) {
        return ok({ items: [{ book_id: "refbook_alpha", title: "Reference Alpha", status: "completed" }] });
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha/profiles/refprofile_alpha/apply")) {
        return fail("REFERENCE_PROFILE_STALE", "reference profile is stale or unsafe; regenerate it before applying");
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha")) {
        detailReads += 1;
        return ok(staleReferenceDetail());
      }
      return ok({});
    });

    await store.initialize();
    await expect(store.applyProfile("refprofile_alpha", { scope: "chapter", scope_ref_id: "CH001" })).rejects.toThrow(
      "参考画像已过期，请继续分析重新生成画像。",
    );

    expect(detailReads).toBeGreaterThanOrEqual(2);
    expect(store.error).toBe("参考画像已过期，请继续分析重新生成画像。");
    expect(store.detail.profiles[0].status).toBe("stale");
  });

  it("keeps reference decisions reversible and metrics local to the current round", () => {
    const source = readFileSync(REFERENCE_VIEW_PATH, "utf8");

    expect(source).toContain("referenceLearning.approvedDecisionCount");
    expect(source).toContain("referenceLearning.rejectedDecisionCount");
    expect(source).toContain("canRejectFinding");
    expect(source).toContain("rejectLabel");
    expect(source).toContain("reference-flow");
    expect(source).toContain("reference-secondary");
  });

  it("renders reference finding source labels and safety status in Chinese", async () => {
    const mounted = await mountReferenceLearningViewWithRound();

    try {
      const text = mounted.container.textContent || "";
      expect(text).toContain("开篇片段");
      expect(text).toContain("结构片段");
      expect(text).toContain("源文片段已隐藏");
      expect(text).toContain("已抽象化");
      expect(text).not.toContain("opening segment");
      expect(text).not.toContain("source excerpt hidden");
      expect(text).not.toContain("abstract summary only");
      expect(text).not.toContain("Use short pressure beats");
      expect(text).not.toContain("Use chapter hook escalation");
      expect(text).not.toContain("Reference Learning");
      expect(text).not.toContain("Import");
      expect(text).not.toContain("Library");
      expect(text).not.toContain("Learning Run");
      expect(text).not.toContain("Decision Cards");
      expect(text).not.toContain("Profiles");
    } finally {
      mounted.unmount();
    }
  });

  it("renders legacy English profile previews through Chinese reference-learning labels", async () => {
    const detail = referenceDetail("completed");
    detail.coverage.covered_dimensions = ["rhythm", "chapter hook", "dialogue ratio"];
    detail.profiles[0].title = "抽象参考：龙族 reference profile";
    detail.profiles[0].display_profile_json = detail.profiles[0].profile_json;
    detail.profiles[0].preview_items = [
      "dialogue_ratio: Use of layered syntax to juxtapose mundane dialogue with emotionally charged internal monologues.",
      "narrative: Begin with a specific phenomenon, delay explanation, and drive scene transitions through visible consequences.",
    ];
    const mounted = await mountReferenceLearningViewWithDetail(detail);

    try {
      const text = mounted.container.textContent || "";
      expect(text).toContain("节奏");
      expect(text).toContain("章节钩子");
      expect(text).toContain("对话比例");
      expect(text).toContain("抽象参考：龙族 · 参考画像");
      expect(text).toContain("对话比例：用分层句法承载对话与内心张力");
      expect(text).toContain("叙事模式：先给具体现象，延后解释");
      expect(text).not.toContain("reference profile");
      expect(text).not.toContain("Use of layered syntax");
      expect(text).not.toContain("Begin with a specific phenomenon");
      expect(text).not.toContain("dialogue_ratio:");
    } finally {
      mounted.unmount();
    }
  });

  it("shows sampled book progress, model source, application status, and expandable source evidence", async () => {
    const detail = referenceDetail("completed");
    detail.profiles[0].application_status = {
      total: 2,
      pending: 2,
      approved: 0,
      rejected: 0,
      review_ids: ["review_apply_style", "review_apply_narrative"],
      scope: "chapter",
      scope_ref_id: "CH001",
    };
    const mounted = await mountReferenceLearningViewWithDetail(detail);

    try {
      const text = mounted.container.textContent || "";
      expect(text).toContain("已抽样 5/8");
      expect(text).toContain("剩余 3");
      expect(text).toContain("继续学习更多片段");
      expect(text).toContain("模型来源");
      expect(text).toContain("本地启发式提取");
      expect(text).toContain("已创建 2 个应用审核项，等待审核收件箱批准");
      expect(text).not.toContain("100%覆盖度");
    } finally {
      mounted.unmount();
    }

    const roundMounted = await mountReferenceLearningViewWithRound();
    globalThis.fetch = vi.fn(async (url) => {
      if (url.endsWith("/api/v1/reference-books/refbook_alpha/segments/refseg_alpha_0001/excerpt")) {
        return ok({
          segment_id: "refseg_alpha_0001",
          display_label: "开篇片段",
          excerpt: "雨敲在窗台上，房间里只剩屏幕的蓝光。",
          max_chars: 800,
          source_visibility: "review_only",
          safety_note: "仅供审核，不进入生成链路。",
        });
      }
      return ok({});
    });
    try {
      const toggle = roundMounted.container.querySelector('[data-testid="reference-toggle-excerpt-refseg_alpha_0001"]');
      expect(toggle).toBeTruthy();
      toggle.click();
      await flushUi();

      const text = roundMounted.container.textContent || "";
      expect(text).toContain("雨敲在窗台上");
      expect(text).toContain("仅供审核，不进入生成链路");
      expect(globalThis.fetch).toHaveBeenCalledWith(
        "http://127.0.0.1:8000/api/v1/reference-books/refbook_alpha/segments/refseg_alpha_0001/excerpt",
      );
    } finally {
      roundMounted.unmount();
    }
  });

  it("surfaces the current blocker, guarded run controls, and collapsible import", () => {
    const source = readFileSync(REFERENCE_VIEW_PATH, "utf8");

    expect(source).toContain("currentTask");
    expect(source).toContain("nextAction");
    expect(source).toContain("startRunLabel");
    expect(source).toContain("startRunDisabledReason");
    expect(source).toContain("advanceRunLabel");
    expect(source).toContain("advanceRunDisabledReason");
    expect(source).toContain("reference-import-toggle");
    expect(source).toContain("shouldShowImportForm");
    expect(source).toContain("reference-next-action");
    expect(source).toContain("还有");
    expect(source).toContain("张候选卡待决策");
    expect(source).toContain("继续生成画像");
    expect(source).toContain("useFlowActionFeedback");
    expect(source).toContain("FlowActionReceipt");
    expect(source).toContain("referenceProfileReceipt");
    expect(source).toContain("去审核收件箱");
    expect(source).toContain("referenceLearning.initialize()");
  });

  it("shows safe profile summaries and gates stale profile application in the view source", () => {
    const source = readFileSync(REFERENCE_VIEW_PATH, "utf8");

    expect(source).toContain("readyProfiles");
    expect(source).toContain("staleProfiles");
    expect(source).toContain("profileVisibilityFilter");
    expect(source).toContain("visibleProfiles");
    expect(source).toContain('data-testid="reference-profile-filter"');
    expect(source).toContain('data-testid="reference-profile-filter-ready"');
    expect(source).toContain('data-testid="reference-profile-filter-all"');
    expect(source).toContain("canApplyProfile");
    expect(source).toContain("profileSummary");
    expect(source).toContain("profilePreviewItems");
    expect(source).toContain("bookProgressLabel");
    expect(source).toContain("reference-profile-summary");
    expect(source).toContain("reference-profile-json");
    expect(source).toContain('v-if="false"');
  });

  it("does not render the retired sample demo workspace in the reference learning view", () => {
    const source = readFileSync(REFERENCE_VIEW_PATH, "utf8");
    const apiSource = readFileSync(API_PATH, "utf8");
    const retiredTitle = ["Demo", "Studio"].join(" ");
    const retiredChineseTitle = ["\u4e09\u7ae0", "\u4fee\u4ed9 Demo"].join("");
    const retiredStateRef = ["dragon", "Demo", "Status"].join("");
    const retiredScopeRef = ["DRAGON", "DEMO", "SCOPE"].join("_");
    const retiredTestId = `data-testid="${["dragon", "demo", "workspace"].join("-")}"`;
    const retiredSlug = ["dragon", "xianxia"].join("-");
    const retiredEndpoint = ["/api/v1", "demo", retiredSlug].join("/");
    const retiredStatusHelper = ["fetch", "Dragon", "Xianxia", "Demo", "Status"].join("");
    const retiredRunHelper = ["run", "Dragon", "Xianxia", "Demo"].join("");
    const retiredStatusLoader = ["load", "Dragon", "Demo", "Status"].join("");

    expect(source).not.toContain(retiredTitle);
    expect(source).not.toContain(retiredChineseTitle);
    expect(source).not.toContain(retiredStateRef);
    expect(source).not.toContain(retiredScopeRef);
    expect(source).not.toContain(retiredTestId);
    expect(apiSource).not.toContain(retiredEndpoint);
    expect(apiSource).not.toContain(retiredStatusHelper);
    expect(apiSource).not.toContain(retiredRunHelper);
    expect(source).not.toContain(retiredStatusLoader);
    expect(source).toContain("source_excerpt_hidden");
    expect(source).toContain("findingSourceLabel");
    expect(source).toContain("findingSafetyLabel");
    expect(source).toContain("source_segment?.display_label");
    expect(source).toContain("源文片段已隐藏");
    expect(source).toContain("仅显示抽象摘要");
    expect(source).not.toContain("source excerpt hidden");
    expect(source).not.toContain("abstract summary only");
    expect(source).toContain("已抽象化");
    expect(source).toContain("已移除源书专名");
    expect(source).toContain("profile.preview_items");
    expect(source).not.toContain("finding.source_segment?.preview");
    expect(source).not.toContain("source_segment?.chapter_hint");
    expect(source).not.toContain("const profileJson = profile?.profile_json || {}");
  });

  it("keeps shell notices compact and human readable", () => {
    const appSource = readFileSync(APP_PATH, "utf8");
    const styleSource = readFileSync(STYLE_PATH, "utf8");

    expect(appSource).toContain("formatNotice");
    expect(styleSource).toContain("max-width: 34rem");
    expect(styleSource).toContain("overflow-wrap: anywhere");
    expect(styleSource).not.toContain("grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));");
  });

  it("surfaces long-running reference analysis progress for real LLM waits", () => {
    const source = readFileSync(REFERENCE_VIEW_PATH, "utf8");

    expect(source).toContain("referenceLongTaskSeconds");
    expect(source).toContain("reference-long-task");
    expect(source).toContain("真实模型分析可能需要数分钟");
    expect(source).toContain("已等待");
    expect(source).toContain("referenceLearningPhaseSteps");
    expect(source).toContain("导入");
    expect(source).toContain("分段");
    expect(source).toContain("全文分析");
    expect(source).toContain("画像合成");
  });

  it("renders a read-only learning tree so authors can see the reference workflow without raw payloads", () => {
    const source = readFileSync(REFERENCE_VIEW_PATH, "utf8");
    const storeSource = readFileSync(REFERENCE_STORE_PATH, "utf8");

    expect(storeSource).toContain("learningTree");
    expect(storeSource).toContain("loadLearningTree");
    expect(source).toContain("reference-learning-tree");
    expect(source).toContain("学习树");
    expect(source).toContain("运行");
    expect(source).toContain("轮次");
    expect(source).toContain("结论");
    expect(source).not.toContain("Evidence:");
  });

  it("keeps completed safe profiles replayable from the advance control instead of forcing API fallback", () => {
    const source = readFileSync(REFERENCE_VIEW_PATH, "utf8");

    expect(source).toContain("canReplayProfileAdvance");
    expect(source).toContain('return "刷新画像状态"');
    expect(source).toContain('return "画像已生成，可点击刷新状态或直接应用。"');
  });
});
