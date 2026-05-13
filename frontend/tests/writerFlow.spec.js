// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

describe("writer flow command center", () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
    vi.restoreAllMocks();
    useShellRouter().reset();
  });

  it("registers writer-flow as the second writer primary step", () => {
    const router = useShellRouter();
    const routerSource = readSource("src/router.js");
    const appSource = readSource("src/App.vue");
    const progressSource = readSource("src/composables/useWriterPathProgress.js");

    const writerPrimaryIds = router.views
      .filter((view) => view.writerPrimary)
      .sort((left, right) => (left.writerOrder || 99) - (right.writerOrder || 99))
      .map((view) => view.id);

    expect(writerPrimaryIds).toEqual([
      "snowflake-workbench",
      "writer-flow",
      "writer-room",
      "reference",
      "review",
    ]);
    expect(router.viewMeta("writer-flow")).toEqual(expect.objectContaining({
      writerPrimary: true,
      writerOrder: 2,
      writerLabel: "写作总控",
    }));
    expect(routerSource).toContain('id: "writer-flow"');
    expect(appSource).toContain('"writer-flow": defineAsyncComponent');
    expect(progressSource).toContain('"writer-flow"');
  });

  it("snowflake outline approval offers a writer-flow handoff target", () => {
    const source = readSource("src/components/SnowflakeMaterializationPanel.vue");

    expect(source).toContain('view: "writer-flow"');
    expect(source).toContain('label: "进入写作总控"');
    expect(source).toContain(":on-navigate");
  });

  it("store drives dashboard, run-job polling, and final approval from next_action", async () => {
    const { useWriterFlowStore } = await import("../src/stores/writerFlow");
    const project = {
      project_id: "PRJ_FLOW",
      title: "Project Flow",
      status: "chapter_ready",
      current_chapter_id: "PRJ_FLOW_CH01",
      approved_chapter_ids: [],
      reference_profile_ids: [],
    };
    const currentChapter = {
      chapter_id: "PRJ_FLOW_CH01",
      chapter_goal: "Open the case.",
      scenes: [{ scene_id: "PRJ_FLOW_CH01_SC01", scene_goal: "Find the clue." }],
    };
    const reviewPacket = {
      chapter_id: "PRJ_FLOW_CH01",
      body: "final chapter body",
      body_source: "assembled",
      char_count: 18,
      body_empty_reason: null,
      completion_status: "complete",
      missing_scene_ids: [],
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      const method = options.method || "GET";
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/dashboard")) {
        return okEnvelope({
          project,
          latest_plan: null,
          chapters: [currentChapter],
          current_chapter: currentChapter,
          reference_profiles: [],
          backtrack_items: [],
          review_packet: null,
          next_action: "run_current_chapter",
          runtime: { llm_enabled: true, generation_mode: "live" },
        });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/chapters/PRJ_FLOW_CH01/run-job") && method === "POST") {
        return okEnvelope({
          project: { ...project, status: "chapter_running" },
          run: {
            job_id: "chapter_run_PRJ_FLOW_CH01",
            status: "running",
            scene_count: 1,
            completed_count: 0,
            progress_pct: 0,
          },
          next_action: "view_chapter_progress",
        });
      }
      if (url.endsWith("/api/v1/chapters/PRJ_FLOW_CH01/run-status")) {
        return okEnvelope({
          job_id: "chapter_run_PRJ_FLOW_CH01",
          status: "completed",
          scene_count: 1,
          completed_count: 1,
          progress_pct: 100,
        });
      }
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/chapters/PRJ_FLOW_CH01/approve-final") && method === "POST") {
        return okEnvelope({
          project: { ...project, status: "completed", current_chapter_id: null, approved_chapter_ids: ["PRJ_FLOW_CH01"] },
          next_chapter_id: null,
          approved_chapter_id: "PRJ_FLOW_CH01",
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWriterFlowStore();
    await store.loadProject("PRJ_FLOW");
    const run = await store.startCurrentChapterJob();
    const status = await store.refreshRunStatus();
    store.applyDashboard({
      project: { ...project, status: "chapter_final_review" },
      chapters: [currentChapter],
      current_chapter: currentChapter,
      review_packet: reviewPacket,
      next_action: "approve_chapter_final",
    });
    expect(store.reviewPacket.body).toBe("final chapter body");
    await store.approveCurrentChapterFinal();

    expect(store.selectedProjectId).toBe("PRJ_FLOW");
    expect(run.job_id).toBe("chapter_run_PRJ_FLOW_CH01");
    expect(status.progress_pct).toBe(100);
    expect(store.project.status).toBe("completed");
  });
});
