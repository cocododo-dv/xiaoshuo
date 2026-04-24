// @vitest-environment jsdom

import { createApp, nextTick } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useShellRouter } from "../src/router";
import { useWorkbenchStore } from "../src/stores/workbench";
import SceneWorkbenchView from "../src/views/SceneWorkbenchView.vue";

function createWorkbenchPayload({
  sceneId,
  chapterId,
  sceneStatus = "ready",
  generationSummary = null,
  hardQcSummary = null,
  softQcSummary = null,
  rewriteCounters = {
    hard_partial_rewrite_count: 0,
    hard_full_rewrite_count: 0,
    soft_patch_count: 0,
    repeat_issue_key: null,
    repeat_issue_count: 0,
  },
  humanReviewSummary = null,
  source_safety_scan = null,
} = {}) {
  return {
    chapter_goal: {
      chapter_id: chapterId,
      chapter_goal: "Keep the workbench evidence compact",
      main_plot_push: "Show generation evidence beside the run receipt",
      emotional_target: "Reduce operator uncertainty",
      ending_effect: "Keep the view stable for historical scenes",
    },
    scene_card: {
      scene_id: sceneId,
      scene_goal: "Confirm evidence cards render after a run",
      must_include_text: "Old letter clue",
      location: "Old city gate",
    },
    scene_run_state: {
      scene_status: sceneStatus,
      current_bundle_id: sceneStatus === "archived" ? `bundle_${sceneId}` : null,
      current_bundle_hash: sceneStatus === "archived" ? `hash_${sceneId}` : null,
      current_final_scene_row_id: sceneStatus === "archived" ? `final_scene_${sceneId}` : null,
    },
    chapter_state: {
      chapter_id: chapterId,
      chapter_backfill_pending_count: 0,
      aggregate_block_reason: "none",
      manual_hold_reason: null,
      mid_aggregate_enabled_effective: 0,
      last_interim_memory_row_id: null,
      last_final_memory_row_id: null,
      staged_backfill_items: [],
    },
    run_preflight: {
      can_run: true,
      overall_status: "ready",
      blocking_items: [],
      warning_items: [],
      context_items: [],
    },
    bundle: {
      bundle_id: sceneStatus === "archived" ? `bundle_${sceneId}` : null,
      bundle_snapshot_hash: sceneStatus === "archived" ? `hash_${sceneId}` : null,
      snapshot: { scene_id: sceneId },
    },
    generation_summary: generationSummary,
    hard_qc_summary: hardQcSummary,
    soft_qc_summary: softQcSummary,
    rewrite_counters: rewriteCounters,
    human_review_summary: humanReviewSummary,
    neutral_draft: { row_id: `draft_neutral_${sceneId}`, content: "Neutral draft" },
    style_draft: { row_id: `draft_style_${sceneId}`, content: "Style draft" },
    final_scene: sceneStatus === "archived" ? { row_id: `final_scene_${sceneId}`, content: "Final scene" } : null,
    scene_memory: sceneStatus === "archived" ? { row_id: `scene_memory_${sceneId}`, content: "Scene memory" } : null,
    attempts: [],
    source_safety_scan: source_safety_scan || {
      safe: true,
      blocked_terms: [],
      source_profile_ids: [],
      checked_at: "2026-04-23T00:00:00+00:00",
    },
  };
}

function createSceneFetchMock({
  sceneId,
  initialPayload,
  refreshedPayload = initialPayload,
  runResult = {
    scene_status: refreshedPayload.scene_run_state.scene_status,
    current_bundle_id: refreshedPayload.scene_run_state.current_bundle_id,
    current_bundle_hash: refreshedPayload.scene_run_state.current_bundle_hash,
    current_final_scene_row_id: refreshedPayload.scene_run_state.current_final_scene_row_id,
  },
  humanReviewItems = [],
}) {
  let hasRun = false;

  return vi.fn(async (url) => {
    const requestUrl = String(url);

    if (requestUrl.includes(`/scenes/${sceneId}/run/jobs`)) {
      hasRun = true;
      return {
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            job_id: `scene_run_job_${sceneId}`,
            scene_id: sceneId,
            status: "queued",
            current_step: "bundle_built",
          },
        }),
      };
    }

    if (requestUrl.includes(`/run-jobs/scene_run_job_${sceneId}`)) {
      return {
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            job_id: `scene_run_job_${sceneId}`,
            scene_id: sceneId,
            status: "completed",
            current_step: "archived",
            result_summary: runResult,
          },
        }),
      };
    }

    if (requestUrl.includes(`/scenes/${sceneId}/workbench`)) {
      return {
        ok: true,
        json: async () => ({
          ok: true,
          data: hasRun ? refreshedPayload : initialPayload,
        }),
      };
    }

    if (requestUrl.includes(`/human-review-events?scene_id=${sceneId}`)) {
      return {
        ok: true,
        json: async () => ({
          ok: true,
          data: { items: humanReviewItems },
        }),
      };
    }

    if (requestUrl.includes(`/scenes/${sceneId}/attempts`)) {
      return {
        ok: true,
        json: async () => ({
          ok: true,
          data: {
            items: [],
            pagination: {
              mode: "cursor",
              limit: 25,
              page: null,
              page_size: null,
              returned: 0,
              total: 0,
              has_next: false,
              next_cursor: null,
            },
          },
        }),
      };
    }

    throw new Error(`Unexpected fetch: ${requestUrl}`);
  });
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

async function mountWorkbenchView(sceneId, fetchMock) {
  const pinia = createPinia();
  setActivePinia(pinia);

  const router = useShellRouter();
  router.reset();

  const store = useWorkbenchStore();
  store.sceneId = sceneId;
  globalThis.fetch = fetchMock;

  const container = document.createElement("div");
  document.body.appendChild(container);

  const app = createApp(SceneWorkbenchView);
  app.use(pinia);
  app.mount(container);

  await store.ensureLoaded({ sceneId, force: true });
  await flushUi();

  return {
    app,
    container,
    store,
    unmount() {
      app.unmount();
      container.remove();
    },
  };
}

describe("scene workbench generation evidence", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useShellRouter().reset();
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("preserves generation and qc summary payloads after a mocked run refresh", async () => {
    const sceneId = "CH001_SC01";
    const refreshedPayload = createWorkbenchPayload({
      sceneId,
      chapterId: "CH001",
      sceneStatus: "archived",
      generationSummary: {
        step: "style_patch",
        raw_step: "soft_patch",
        provider: "openai",
        model: "gpt-4.1-mini",
        prompt_hash: "prompt_hash_abc123",
        prompt_tokens: 117,
        completion_tokens: 231,
        total_tokens: 348,
        latency_ms: 812,
        finish_reason: "stop",
        error_code: null,
        style_score_summary: {
          style_score: 0.84,
          style_dimensions: [{ name: "rhythm", score: 0.9, evidence: "Pressure lands at paragraph ends." }],
          style_deviations: [{ dimension: "paragraph_density", severity: "low", patch_brief: "Break the longest paragraph." }],
        },
      },
      hardQcSummary: {
        qc_type: "hard_qc",
        pass_flag: true,
        resolution_code: "hard_pass",
        issue_keys: [],
        next_action: "pass",
        rewrite_brief: [],
      },
      softQcSummary: {
        qc_type: "soft_qc",
        pass_flag: false,
        resolution_code: "soft_patch_requested",
        issue_keys: ["style_tension_flat"],
        next_action: "patch",
        rewrite_brief: ["Raise tension in the closing beat"],
        style_score: 0.84,
        style_dimensions: [{ name: "rhythm", score: 0.9, evidence: "Pressure lands at paragraph ends." }],
        style_deviations: [{ dimension: "paragraph_density", severity: "low", patch_brief: "Break the longest paragraph." }],
      },
      rewriteCounters: {
        hard_partial_rewrite_count: 0,
        hard_full_rewrite_count: 0,
        soft_patch_count: 1,
        repeat_issue_key: null,
        repeat_issue_count: 0,
      },
      humanReviewSummary: {
        event_id: "human_review_generation_CH001_SC01_20260415010101",
        status: "needs_followup",
        event_source: "scene_generation",
        priority: "high",
        trigger_reason: "soft_qc_patch_cycle_limit",
        failure_reason: "soft_qc requested another patch",
        recommended_action: "human_review_required",
        linked_target_ref: "scene_draft:draft_style_patch_CH001_SC01",
      },
    });

    globalThis.fetch = createSceneFetchMock({
      sceneId,
      initialPayload: createWorkbenchPayload({ sceneId, chapterId: "CH001" }),
      refreshedPayload,
    });

    const store = useWorkbenchStore();
    await store.runScene(sceneId);

    expect(store.lastRunResult).toEqual(expect.objectContaining({ scene_status: "archived" }));
    expect(store.data.generation_summary.step).toBe("style_patch");
    expect(store.data.generation_summary.raw_step).toBe("soft_patch");
    expect(store.data.hard_qc_summary.resolution_code).toBe("hard_pass");
    expect(store.data.soft_qc_summary.resolution_code).toBe("soft_patch_requested");
    expect(store.data.generation_summary.style_score_summary.style_score).toBe(0.84);
    expect(store.data.soft_qc_summary.style_dimensions[0].name).toBe("rhythm");
    expect(store.data.rewrite_counters.soft_patch_count).toBe(1);
    expect(store.data.human_review_summary.trigger_reason).toBe("soft_qc_patch_cycle_limit");
  });

  it("keeps null summary payloads intact after a mocked run refresh", async () => {
    const sceneId = "CH002_SC01";
    const emptySummaryPayload = createWorkbenchPayload({
      sceneId,
      chapterId: "CH002",
      generationSummary: null,
      hardQcSummary: null,
      softQcSummary: null,
      humanReviewSummary: null,
    });

    globalThis.fetch = createSceneFetchMock({
      sceneId,
      initialPayload: emptySummaryPayload,
      refreshedPayload: emptySummaryPayload,
      runResult: {
        scene_status: "ready",
        current_bundle_id: null,
        current_bundle_hash: null,
        current_final_scene_row_id: null,
      },
    });

    const store = useWorkbenchStore();
    await store.runScene(sceneId);

    expect(store.data.generation_summary).toBeNull();
    expect(store.data.hard_qc_summary).toBeNull();
    expect(store.data.soft_qc_summary).toBeNull();
    expect(store.data.human_review_summary).toBeNull();
    expect(store.data.rewrite_counters).toEqual(
      expect.objectContaining({
        soft_patch_count: 0,
        repeat_issue_key: null,
      }),
    );
  });

  it("renders deterministic source safety scan status for archived scene text", async () => {
    const sceneId = "CH003_SC01";
    const unsafeScan = {
      safe: false,
      blocked_terms: ["龙族", "路明非"],
      source_profile_ids: ["refprofile_longzu_safe"],
      checked_at: "2026-04-23T00:00:00+00:00",
    };
    const mounted = await mountWorkbenchView(
      sceneId,
      createSceneFetchMock({
        sceneId,
        initialPayload: createWorkbenchPayload({
          sceneId,
          chapterId: "CH003",
          sceneStatus: "archived",
          source_safety_scan: unsafeScan,
        }),
        refreshedPayload: createWorkbenchPayload({
          sceneId,
          chapterId: "CH003",
          sceneStatus: "archived",
          source_safety_scan: unsafeScan,
        }),
      }),
    );
    const _unusedSafetyScan = {
      safe: false,
      blocked_terms: ["龙族", "路明非"],
      source_profile_ids: ["refprofile_longzu_safe"],
      checked_at: "2026-04-23T00:00:00+00:00",
    };
    await flushUi();

    try {
      expect(mounted.container.querySelector('[data-testid="scene-source-safety-card"]')).not.toBeNull();
      expect(mounted.container.textContent).toContain("源书安全扫描");
      expect(mounted.container.textContent).toContain("命中 2 个保护标记");
      expect(mounted.container.textContent).toContain("refprofile_longzu_safe");
    } finally {
      mounted.unmount();
    }
  });
});

describe("scene workbench generation view", () => {
  beforeEach(() => {
    useShellRouter().reset();
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("renders evidence cards in the DOM after a mocked llm-backed scene run", async () => {
    const sceneId = "CH001_SC01";
    const fetchMock = createSceneFetchMock({
      sceneId,
      initialPayload: createWorkbenchPayload({
        sceneId,
        chapterId: "CH001",
        generationSummary: null,
        hardQcSummary: null,
        softQcSummary: null,
        humanReviewSummary: null,
      }),
      refreshedPayload: createWorkbenchPayload({
        sceneId,
        chapterId: "CH001",
        sceneStatus: "archived",
        generationSummary: {
          step: "style_patch",
          raw_step: "soft_patch",
          provider: "openai",
          model: "gpt-4.1-mini",
          prompt_hash: "prompt_hash_abc123",
          prompt_tokens: 117,
          completion_tokens: 231,
          total_tokens: 348,
          latency_ms: 812,
          finish_reason: "stop",
          error_code: null,
          style_score_summary: {
            style_score: 0.84,
            style_dimensions: [{ name: "rhythm", score: 0.9, evidence: "Pressure lands at paragraph ends." }],
            style_deviations: [{ dimension: "paragraph_density", severity: "low", patch_brief: "Break the longest paragraph." }],
          },
        },
        hardQcSummary: {
          qc_type: "hard_qc",
          pass_flag: true,
          resolution_code: "hard_pass",
          issue_keys: [],
          next_action: "pass",
          rewrite_brief: [],
        },
        softQcSummary: {
          qc_type: "soft_qc",
          pass_flag: false,
          resolution_code: "soft_patch_requested",
          issue_keys: ["style_tension_flat"],
          next_action: "patch",
          rewrite_brief: ["Raise tension in the closing beat"],
          style_score: 0.84,
          style_dimensions: [{ name: "rhythm", score: 0.9, evidence: "Pressure lands at paragraph ends." }],
          style_deviations: [{ dimension: "paragraph_density", severity: "low", patch_brief: "Break the longest paragraph." }],
        },
        rewriteCounters: {
          hard_partial_rewrite_count: 0,
          hard_full_rewrite_count: 0,
          soft_patch_count: 1,
          repeat_issue_key: "style_tension_flat",
          repeat_issue_count: 1,
        },
        humanReviewSummary: {
          event_id: "human_review_generation_CH001_SC01_20260415010101",
          status: "needs_followup",
          event_source: "scene_generation",
          priority: "high",
          trigger_reason: "soft_qc_patch_cycle_limit",
          failure_reason: "soft_qc requested another patch",
          recommended_action: "human_review_required",
          linked_target_ref: "scene_draft:draft_style_patch_CH001_SC01",
        },
      }),
    });
    const mounted = await mountWorkbenchView(sceneId, fetchMock);

    try {
      const generationCard = mounted.container.querySelector('[data-testid="scene-generation-summary-card"]');
      const qcCard = mounted.container.querySelector('[data-testid="scene-qc-report-card"]');
      const runButton = mounted.container.querySelector('[data-testid="run-full-scene-button"]');

      expect(generationCard).not.toBeNull();
      expect(qcCard).not.toBeNull();
      expect(runButton).not.toBeNull();
      expect(generationCard.textContent).toContain("暂无生成证据");
      expect(qcCard.textContent).toContain("暂无硬 QC 结果");
      expect(qcCard.textContent).toContain("暂无软 QC 结果");

      runButton.click();
      await flushUi();

      const refreshedGenerationCard = mounted.container.querySelector('[data-testid="scene-generation-summary-card"]');
      const refreshedQcCard = mounted.container.querySelector('[data-testid="scene-qc-report-card"]');
      const runReceipt = mounted.container.querySelector('[data-testid="scene-run-receipt"]');

      expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/scenes/CH001_SC01/run/jobs", expect.any(Object));
      expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/run-jobs/scene_run_job_CH001_SC01");
      expect(runReceipt).not.toBeNull();
      expect(runReceipt.textContent).toContain("bundle_CH001_SC01");
      expect(refreshedGenerationCard.textContent).not.toContain("暂无生成证据");
      expect(refreshedGenerationCard.textContent).toContain("openai");
      expect(refreshedGenerationCard.textContent).toContain("gpt-4.1-mini");
      expect(refreshedGenerationCard.textContent).toContain("prompt_hash_abc123");
      expect(refreshedGenerationCard.textContent).toContain("stop");
      expect(refreshedGenerationCard.textContent).toContain("风格命中");
      expect(refreshedGenerationCard.textContent).toContain("84%");
      expect(refreshedQcCard.textContent).toContain("hard_pass");
      expect(refreshedQcCard.textContent).toContain("soft_patch_requested");
      expect(refreshedQcCard.textContent).toContain("style_tension_flat");
      expect(refreshedQcCard.textContent).toContain("Raise tension in the closing beat");
      expect(refreshedQcCard.textContent).toContain("rhythm");
      expect(refreshedQcCard.textContent).toContain("paragraph_density");
      expect(refreshedQcCard.textContent).toContain("Break the longest paragraph");
      expect(refreshedQcCard.textContent).toContain("human_review_required");
    } finally {
      mounted.unmount();
    }
  });

  it("preserves empty evidence states for historical deterministic scenes", async () => {
    const sceneId = "CH002_SC01";
    const mounted = await mountWorkbenchView(
      sceneId,
      createSceneFetchMock({
        sceneId,
        initialPayload: createWorkbenchPayload({
          sceneId,
          chapterId: "CH002",
          generationSummary: null,
          hardQcSummary: null,
          softQcSummary: null,
          humanReviewSummary: null,
        }),
      }),
    );

    try {
      const generationCard = mounted.container.querySelector('[data-testid="scene-generation-summary-card"]');
      const qcCard = mounted.container.querySelector('[data-testid="scene-qc-report-card"]');

      expect(generationCard).not.toBeNull();
      expect(qcCard).not.toBeNull();
      expect(generationCard.textContent).toContain("暂无生成证据");
      expect(qcCard.textContent).toContain("暂无硬 QC 结果");
      expect(qcCard.textContent).toContain("暂无软 QC 结果");
      expect(qcCard.textContent).toContain("当前没有人工复核摘要");
      expect(mounted.store.data.generation_summary).toBeNull();
      expect(mounted.store.data.soft_qc_summary).toBeNull();
    } finally {
      mounted.unmount();
    }
  });

  it("labels clean, waived, and deterministic blocked archive states", async () => {
    const cleanSceneId = "CH003_SC01";
    const cleanMounted = await mountWorkbenchView(
      cleanSceneId,
      createSceneFetchMock({
        sceneId: cleanSceneId,
        initialPayload: createWorkbenchPayload({
          sceneId: cleanSceneId,
          chapterId: "CH003",
          sceneStatus: "archived",
          hardQcSummary: {
            qc_type: "hard_qc",
            pass_flag: true,
            resolution_code: "hard_pass",
            issue_keys: [],
            next_action: "pass",
            rewrite_brief: [],
          },
          softQcSummary: {
            qc_type: "soft_qc",
            pass_flag: true,
            resolution_code: "soft_pass",
            issue_keys: [],
            next_action: "pass",
            rewrite_brief: [],
          },
        }),
      }),
    );

    try {
      expect(cleanMounted.container.textContent).toContain("Clean archived");
    } finally {
      cleanMounted.unmount();
    }

    const waivedSceneId = "CH004_SC01";
    const waivedMounted = await mountWorkbenchView(
      waivedSceneId,
      createSceneFetchMock({
        sceneId: waivedSceneId,
        initialPayload: createWorkbenchPayload({
          sceneId: waivedSceneId,
          chapterId: "CH004",
          sceneStatus: "archived",
          hardQcSummary: {
            qc_type: "hard_qc",
            pass_flag: true,
            resolution_code: "hard_pass",
            issue_keys: [],
            next_action: "pass",
            rewrite_brief: [],
          },
          softQcSummary: {
            qc_type: "soft_qc",
            pass_flag: true,
            resolution_code: "soft_waive",
            issue_keys: ["style_profile_drift"],
            next_action: "pass_with_notes",
            rewrite_brief: ["Carry this note into scene memory."],
          },
        }),
      }),
    );

    try {
      expect(waivedMounted.container.textContent).toContain("Archived with waived notes");
    } finally {
      waivedMounted.unmount();
    }

    const blockedSceneId = "CH005_SC01";
    const blockedMounted = await mountWorkbenchView(
      blockedSceneId,
      createSceneFetchMock({
        sceneId: blockedSceneId,
        initialPayload: createWorkbenchPayload({
          sceneId: blockedSceneId,
          chapterId: "CH005",
          sceneStatus: "human_review_required",
          hardQcSummary: {
            qc_type: "hard_qc",
            pass_flag: false,
            resolution_code: "hard_fail_partial",
            issue_keys: ["character_pronoun_drift"],
            next_action: "partial_rewrite",
            rewrite_brief: ["修正林岑的代词。"],
          },
          humanReviewSummary: {
            event_id: "human_review_generation_CH005_SC01",
            status: "needs_followup",
            trigger_reason: "blocking_soft_qc_issue",
            failure_reason: "character_pronoun_drift blocked finalization",
            recommended_action: "human_review_required",
            linked_target_ref: "scene_draft:draft_style_CH005_SC01",
          },
        }),
      }),
    );

    try {
      expect(blockedMounted.container.textContent).toContain("Blocked by deterministic QC");
    } finally {
      blockedMounted.unmount();
    }
  });
});
