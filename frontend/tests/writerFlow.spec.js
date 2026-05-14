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
    expect(source).toContain('data-testid="snowflake-structure-handoff"');
    expect(source).toContain('testId: "snowflake-handoff-writer-flow"');
    expect(source).toContain(':data-testid="structureHandoff.testId"');
  });

  it("offline chapter runs expose a system config exit while keeping generation disabled", () => {
    const source = readSource("src/views/WriterFlowView.vue");

    expect(source).toContain('data-testid="writer-flow-offline-banner"');
    expect(source).toContain('data-testid="writer-flow-config-action"');
    expect(source).toContain("离线 fallback");
    expect(source).toContain("router.navigate('config'");
    expect(source).toContain("disabled: offlineBanner.value");
  });

  it("translates writer-flow machine states into author-facing copy", async () => {
    const {
      backtrackScopeLabel,
      bodyEmptyReasonLabel,
      bodySourceLabel,
      chapterListLabel,
      completionStatusLabel,
      latestErrorLabel,
      nextActionLabel,
      runStatusLabel,
      sceneDisplayLabel,
    } = await import("../src/lib/writerFlowDisplay");

    expect(sceneDisplayLabel({
      chapter_id: "PRJ_FLOW_CH01",
      scenes: [
        { scene_id: "PRJ_FLOW_CH01_SC01", scene_seq: 1, scene_goal: "Open with the map." },
        { scene_id: "PRJ_FLOW_CH01_SC02", scene_seq: 2, title: "Witness bargain" },
      ],
    }, "PRJ_FLOW_CH01_SC02")).toBe("第 2 场：Witness bargain");
    expect(chapterListLabel({ chapter_id: "PRJ_FLOW_CH02" }, 1)).toBe("第 2 章");
    expect(bodyEmptyReasonLabel("no_generated_scenes")).toBe("还没有场景完成生成");
    expect(bodyEmptyReasonLabel("manuscript_body_empty")).toBe("正文汇总为空，请检查运行状态");
    expect(bodySourceLabel("llm")).toBe("");
    expect(bodySourceLabel("fallback")).toBe("离线演示正文");
    expect(completionStatusLabel("partial")).toBe("部分场景已完成");
    expect(nextActionLabel("resolve_backtrack_items")).toContain("返工");
    expect(runStatusLabel("failed", "approve_chapter_final")).toBe("起草失败，需要查看原因");
    expect(latestErrorLabel({ message: "chapter run is blocked by pending replanning work" })).toContain("返工");
    expect(backtrackScopeLabel({ scope: "scene", chapter_id: "CH01", scene_id: "SC02" })).toBe("场景 SC02");
  });

  it("renders writer-facing review coverage, scene list, and backtrack controls without raw ids as primary copy", () => {
    const source = readSource("src/views/WriterFlowView.vue");

    expect(source).toContain("writerFlowDisplay");
    expect(source).toContain('data-testid="writer-flow-scene-reviews"');
    expect(source).toContain('data-testid="writer-flow-backtrack-banner"');
    expect(source).toContain("missingSceneLabels");
    expect(source).toContain("targetWordCountLabel");
    expect(source).toContain("openBacktrackItem");
    expect(source).toContain("openWriterRoomForScene");
    expect(source).toContain("sceneDisplayLabel");
    expect(source).toContain("pollIntervalMs");
    expect(source).not.toContain("runStatus?.current_scene_id || currentChapter?.chapter_id");
    expect(source).not.toContain("reviewPacket?.body_empty_reason ||");
  });

  it("keeps final review, polling, note count, and writer-room return context visible", () => {
    const viewSource = readSource("src/views/WriterFlowView.vue");
    const roomSource = readSource("src/views/WriterRoomView.vue");
    const apiSource = readSource("src/lib/api/projects.js");

    expect(apiSource).toContain("reviewProjectChapterFinal");
    expect(apiSource).toContain("/final-review");
    expect(viewSource).toContain("isPolling");
    expect(viewSource).toContain('data-testid="writer-flow-polling-status"');
    expect(viewSource).toContain("approvalNotesCount");
    expect(viewSource).toContain("approvalNotesTooLong");
    expect(viewSource).toContain("returnTo: 'writer-flow'");
    expect(viewSource).toContain("returnLabel: '返回批准'");
    expect(roomSource).toContain('data-testid="writer-room-return-to-flow"');
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
      if (url.endsWith("/api/v1/projects/PRJ_FLOW/chapters/PRJ_FLOW_CH01/final-review") && method === "POST") {
        expect(JSON.parse(options.body)).toEqual({
          decision: "approve",
          revision_notes: "Keep the second scene tense.",
        });
        return okEnvelope({
          project: { ...project, status: "completed", current_chapter_id: null, approved_chapter_ids: ["PRJ_FLOW_CH01"] },
          next_chapter_id: null,
          approved_chapter_id: "PRJ_FLOW_CH01",
          approval_note: { revision_notes: "Keep the second scene tense." },
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
    await store.approveCurrentChapterFinal({ revision_notes: "Keep the second scene tense." });

    expect(store.selectedProjectId).toBe("PRJ_FLOW");
    expect(run.job_id).toBe("chapter_run_PRJ_FLOW_CH01");
    expect(status.progress_pct).toBe(100);
    expect(store.project.status).toBe("completed");
    expect(store.lastApprovalNote.revision_notes).toBe("Keep the second scene tense.");
  });
});
