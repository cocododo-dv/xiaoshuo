import { existsSync, readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";

const REFERENCE_VIEW_PATH = new URL("../src/views/ReferenceLearningView.vue", import.meta.url);
const REFERENCE_STORE_PATH = new URL("../src/stores/referenceLearning.js", import.meta.url);
const API_PATH = new URL("../src/lib/api.js", import.meta.url);
const APP_PATH = new URL("../src/App.vue", import.meta.url);
const STYLE_PATH = new URL("../src/styles/app.css", import.meta.url);

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
              coverage: { approved_findings: 5, ready: true, profile_stale: false },
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
          source_segment: {
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
          source_segment: {
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

describe("reference learning shell registration", () => {
  it("adds the reference learning view to the shell navigation", () => {
    const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(existsSync(REFERENCE_VIEW_PATH)).toBe(true);
    expect(existsSync(REFERENCE_STORE_PATH)).toBe(true);
    expect(appSource).toContain("ReferenceLearningView");
    expect(routerSource).toContain('id: "reference"');
    expect(routerSource).toContain('label: "参考书学习"');
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
      if (url.endsWith("/api/v1/review-items/review_reffind_1/approve")) {
        return ok({ review_id: "review_reffind_1", materialize_status: "succeeded" });
      }
      if (url.endsWith("/api/v1/review-items/review_reffind_2/reject")) {
        return ok({ review_id: "review_reffind_2", status: "rejected" });
      }
      if (url.endsWith("/api/v1/reference-books/refbook_alpha/profiles/refprofile_alpha/apply")) {
        return ok({ applied: false, reviews: [{ review_id: "review_apply_ref", item_type: "narrative_pattern" }] });
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
});
