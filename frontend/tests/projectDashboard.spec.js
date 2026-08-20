// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";
import { useShellRouter } from "../src/router";

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

describe("outline-driven project dashboard", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it("keeps the home cockpit as the default writer-mode landing while advanced mode keeps every backend tool", () => {
    const router = useShellRouter();
    const routerSource = readSource("src/router.js");
    const appSource = readSource("src/App.vue");

    router.reset();

    expect(router.activeView.value).toBe("home");
    expect(router.visitedViews.value).toEqual(["home"]);
    expect(router.views[0]).toEqual(expect.objectContaining({
      id: "home",
      label: "主页",
      writerPrimary: true,
      writerOrder: 0.5,
    }));
    expect(router.views
      .filter((view) => view.writerPrimary)
      .sort((left, right) => (left.writerOrder || 99) - (right.writerOrder || 99))
      .map((view) => view.id)).toEqual([
      "home",
      "flowmap",
      "snowflake-workbench",
      "writer-flow",
      "writer-room",
      "reference",
      "review",
      "library",
    ]);
    expect(routerSource).toContain('id: "snowflake-workbench"');
    expect(routerSource).toContain('id: "writer-flow"');
    expect(appSource).toContain('"snowflake-workbench": defineAsyncComponent');
    expect(appSource).toContain('"writer-flow": defineAsyncComponent');
    expect(appSource).toContain("./views/SnowflakeWorkbenchView.vue");
    expect(appSource).toContain("./views/WriterFlowView.vue");
  });

  it("exposes project orchestration API helpers", async () => {
    globalThis.fetch = vi.fn(async () => okEnvelope({}));

    await api.fetchProjects();
    await api.createProject({ outline_text: "大纲" });
    await api.fetchProjectDashboard("PRJ_FLOW");
    await api.fetchProjectBacktrackItems("PRJ_FLOW");
    await api.generateProjectOutlinePlan("PRJ_FLOW");
    await api.approveProjectOutlinePlan("PRJ_FLOW", "PLAN_1");
    await api.runProjectChapter("PRJ_FLOW", "PRJ_FLOW_CH01");
    await api.runProjectChapterJob("PRJ_FLOW", "PRJ_FLOW_CH01");
    await api.approveProjectChapterFinal("PRJ_FLOW", "PRJ_FLOW_CH01");
    await api.attachProjectReferenceProfile("PRJ_FLOW", "PROFILE_READY");
    await api.resolveProjectBacktrackItem("PRJ_FLOW", "BT_1", { resolution_note: "fixed" });

    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/dashboard");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/backtrack-items");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/backtrack-items/BT_1/resolve");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/outline-plan");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/outline-plan/PLAN_1/approve");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/chapters/PRJ_FLOW_CH01/run");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/chapters/PRJ_FLOW_CH01/run-job");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/chapters/PRJ_FLOW_CH01/approve-final");
    expect(urls).toContain("http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/reference-profiles");
  });

  it("store drives the outline-to-chapter-review happy path", async () => {
    const { useProjectDashboardStore } = await import("../src/stores/projectDashboard");
    const project = {
      project_id: "PRJ_FLOW",
      title: "雨城残响",
      status: "outline_draft",
      outline_text: "第一章发现旧信",
      current_chapter_id: null,
      reference_profile_ids: [],
      approved_chapter_ids: [],
    };
    const plan = {
      plan_id: "PLAN_1",
      status: "pending_review",
      plan_json: {
        reference_safety: ["禁复刻原文表达"],
        chapters: [
          {
            chapter_id: "PRJ_FLOW_CH01",
            chapter_goal: "发现旧信",
            scenes: [{ scene_id: "PRJ_FLOW_CH01_SC01", scene_goal: "打开旧信", beats_json: ["旧信出现"] }],
          },
        ],
      },
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v1/projects") && method === "GET") {
        return okEnvelope({ items: [project] });
      }
      if (url.endsWith("/api/v1/projects") && method === "POST") {
        return okEnvelope({ project });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/dashboard")) {
        return okEnvelope({ project, latest_plan: null, chapters: [], reference_profiles: [], next_action: "generate_outline_plan" });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/outline-plan")) {
        return okEnvelope({ project: { ...project, status: "outline_review" }, plan });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/outline-plan/PLAN_1/approve")) {
        return okEnvelope({
          project: { ...project, status: "chapter_ready", current_chapter_id: "PRJ_FLOW_CH01" },
          plan: { ...plan, status: "approved" },
          created_chapter_count: 1,
          created_scene_count: 1,
        });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/chapters/PRJ_FLOW_CH01/run")) {
        return okEnvelope({
          project: { ...project, status: "chapter_final_review", current_chapter_id: "PRJ_FLOW_CH01" },
          run: { status: "completed" },
          review_packet: { chapter_id: "PRJ_FLOW_CH01", issues_summary: [], reference_safety: ["禁复刻原文表达"] },
        });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/chapters/PRJ_FLOW_CH01/approve-final")) {
        return okEnvelope({
          project: { ...project, status: "chapter_ready", current_chapter_id: "PRJ_FLOW_CH02", approved_chapter_ids: ["PRJ_FLOW_CH01"] },
          next_chapter_id: "PRJ_FLOW_CH02",
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useProjectDashboardStore();
    await store.initialize();
    const created = await store.createFromDraft({
      title: "雨城残响",
      outline_text: "第一章发现旧信",
      target_chapter_count: 2,
    });
    const generated = await store.generateOutlinePlan();
    await store.approveOutlinePlan("PLAN_1");
    await store.runCurrentChapter();
    await store.approveCurrentChapterFinal();

    expect(created.project_id).toBe("PRJ_FLOW");
    expect(generated.plan_id).toBe("PLAN_1");
    expect(store.selectedProjectId).toBe("PRJ_FLOW");
    expect(store.project.status).toBe("chapter_ready");
    expect(store.project.current_chapter_id).toBe("PRJ_FLOW_CH02");
    expect(store.planChapters[0].scenes[0].scene_id).toBe("PRJ_FLOW_CH01_SC01");
    expect(store.lastReviewPacket.chapter_id).toBe("PRJ_FLOW_CH01");
  });

  it("store resolves pending backtrack items and refreshes the dashboard", async () => {
    const { useProjectDashboardStore } = await import("../src/stores/projectDashboard");
    const project = {
      project_id: "PRJ_FLOW",
      title: "雨城残响",
      status: "chapter_blocked",
      outline_text: "第一章发现旧信",
      current_chapter_id: "PRJ_FLOW_CH01",
      reference_profile_ids: [],
      approved_chapter_ids: [],
    };
    const pendingItem = {
      item_id: "BT_1",
      scope: "scene_detail",
      status: "pending",
      problem_summary: "Scene needs replanning.",
      recommended_fix: "Return to scene_details.",
      reason_codes: ["soft_patch_limit_reached"],
      scene_id: "PRJ_FLOW_CH01_SC01",
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v1/projects") && method === "GET") {
        return okEnvelope({ items: [project] });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/dashboard")) {
        return okEnvelope({
          project,
          latest_plan: null,
          chapters: [],
          reference_profiles: [],
          backtrack_items: method === "GET" && globalThis.fetch.mock.calls.length > 2 ? [] : [pendingItem],
          next_action: method === "GET" && globalThis.fetch.mock.calls.length > 2 ? "run_current_chapter" : "resolve_backtrack_items",
        });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/backtrack-items/BT_1/resolve")) {
        return okEnvelope({ item: { ...pendingItem, status: "resolved", resolution_note: "fixed" } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useProjectDashboardStore();
    await store.initialize();
    expect(store.pendingBacktrackItems).toHaveLength(1);

    const resolved = await store.resolveBacktrackItem("BT_1", "fixed");

    expect(resolved.status).toBe("resolved");
    expect(store.pendingBacktrackItems).toHaveLength(0);
    expect(store.lastActionMessage).toBe("返工项已关闭，可以继续推进项目主流程。");
  });

  it("store binds project reference profiles through style_reference apply and reloads dashboard", async () => {
    const { useProjectDashboardStore } = await import("../src/stores/projectDashboard");
    const project = {
      project_id: "PRJ_FLOW",
      title: "雨城残响",
      status: "chapter_ready",
      outline_text: "第一章发现旧信。",
      current_chapter_id: "PRJ_FLOW_CH01",
      reference_profile_ids: [],
      approved_chapter_ids: [],
    };
    const boundProfile = {
      profile_id: "PROFILE_READY",
      title: "抽象风格画像",
      status: "active",
      profile_json: { style_features: ["短句推进"] },
      safe_summary: {
        abstract_tags: [{ label: "节奏", summary: "短句推进" }],
        safety_note: "仅使用抽象节奏、结构和安全规则；不展示或复制参考书原文。",
      },
      binding_id: "sr_bind_123",
      scope: "project",
      scope_ref_id: "PRJ_FLOW",
      task_type: "scene_generation",
      strategy: "mixed",
    };
    let dashboardCalls = 0;

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v1/projects") && method === "GET") {
        return okEnvelope({ items: [project] });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/dashboard") && method === "GET") {
        dashboardCalls += 1;
        if (dashboardCalls === 1) {
          return okEnvelope({
            project,
            latest_plan: null,
            chapters: [],
            reference_profiles: [],
            next_action: "generate_outline_plan",
          });
        }
        return okEnvelope({
          project: { ...project, reference_profile_ids: ["PROFILE_READY"] },
          latest_plan: null,
          chapters: [],
          reference_profiles: [boundProfile],
          next_action: "generate_outline_plan",
        });
      }
      if (url.endsWith("/api/v2/style-reference/profiles/PROFILE_READY/apply") && method === "POST") {
        return okEnvelope({
          profile_id: "PROFILE_READY",
          binding_id: "sr_bind_123",
          review_ids: [],
          item_type_counts: {},
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useProjectDashboardStore();
    await store.initialize();
    const result = await store.bindReferenceProfile("PROFILE_READY");

    expect(result.binding_id).toBe("sr_bind_123");
    expect(store.project.reference_profile_ids).toEqual(["PROFILE_READY"]);
    expect(store.referenceProfiles).toEqual([boundProfile]);
    expect(store.profileBindDraft).toBe("");
    expect(store.lastActionMessage).toBe("参考画像已绑定到当前项目。");
    const urls = globalThis.fetch.mock.calls.map(([url]) => url);
    expect(urls).toContain("http://127.0.0.1:8000/api/v2/style-reference/profiles/PROFILE_READY/apply");
    expect(
      urls.filter((url) => url === "http://127.0.0.1:8000/api/v1/projects/PRJ_FLOW/dashboard"),
    ).toHaveLength(2);
  });

  it("project dashboard source exposes the backtrack panel and resolve controls", () => {
    const source = readSource("src/views/ProjectDashboardView.vue");

    expect(source).toContain('data-testid="project-backtrack-panel"');
    expect(source).toContain("返工项");
    expect(source).toContain("关闭返工项");
    expect(source).toContain("openBacktrackTarget");
    expect(source).toContain("resolveBacktrack");
  });
});
