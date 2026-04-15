import { readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkbenchStore } from "../src/stores/workbench";

describe("scene workbench generation evidence", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("preserves generation and qc summary payloads after a mocked run refresh", async () => {
    const basePayload = {
      chapter_goal: {
        chapter_id: "CH001",
        chapter_goal: "Keep the workbench evidence compact",
        main_plot_push: "Show generation evidence beside the run receipt",
        emotional_target: "Reduce operator uncertainty",
        ending_effect: "Keep the view stable for historical scenes",
      },
      scene_card: {
        scene_id: "CH001_SC01",
        scene_goal: "Confirm evidence cards render after a run",
        must_include_text: "Old letter clue",
        location: "Old city gate",
      },
      scene_run_state: {
        scene_status: "archived",
        current_bundle_id: "bundle_CH001_SC01",
        current_bundle_hash: "hash_CH001_SC01",
        current_final_scene_row_id: "final_scene_CH001_SC01",
      },
      chapter_state: {
        chapter_id: "CH001",
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
        bundle_id: "bundle_CH001_SC01",
        bundle_snapshot_hash: "hash_CH001_SC01",
        snapshot: { scene_id: "CH001_SC01" },
      },
      generation_summary: {
        step: "soft_patch",
        raw_step: "style_patch",
        provider: "offline_deterministic",
        model: "gpt-4.1-mini",
        prompt_hash: "prompt_hash_abc123",
        prompt_tokens: 0,
        completion_tokens: 0,
        total_tokens: 0,
        latency_ms: 12,
        finish_reason: "offline_fallback",
        error_code: null,
      },
      hard_qc_summary: {
        qc_type: "hard_qc",
        pass_flag: true,
        resolution_code: "hard_pass",
        issue_keys: [],
        next_action: "pass",
        rewrite_brief: [],
      },
      soft_qc_summary: {
        qc_type: "soft_qc",
        pass_flag: true,
        resolution_code: "soft_pass",
        issue_keys: [],
        next_action: "pass",
        rewrite_brief: [],
      },
      rewrite_counters: {
        hard_partial_rewrite_count: 0,
        hard_full_rewrite_count: 0,
        soft_patch_count: 1,
        repeat_issue_key: null,
        repeat_issue_count: 0,
      },
      human_review_summary: {
        event_id: "human_review_generation_CH001_SC01_20260415010101",
        status: "needs_followup",
        event_source: "scene_generation",
        priority: "high",
        trigger_reason: "soft_qc_patch_cycle_limit",
        failure_reason: "soft_qc requested another patch",
        recommended_action: "human_review_required",
        linked_target_ref: "scene_draft:draft_style_patch_CH001_SC01",
      },
      neutral_draft: { row_id: "draft_neutral_CH001_SC01", content: "Neutral draft" },
      style_draft: { row_id: "draft_style_CH001_SC01", content: "Style draft" },
      final_scene: { row_id: "final_scene_CH001_SC01", content: "Final scene" },
      scene_memory: { row_id: "scene_memory_CH001_SC01", content: "Scene memory" },
      attempts: [],
    };

    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/scenes/CH001_SC01/run/full")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_status: "archived",
              current_bundle_id: "bundle_CH001_SC01",
              current_bundle_hash: "hash_CH001_SC01",
              current_final_scene_row_id: "final_scene_CH001_SC01",
              current_qc_report_id: "qc_report_CH001_SC01",
              current_human_review_event_id: "human_review_generation_CH001_SC01",
              hard_qc: {
                branch: "continue",
                qc_report_id: "qc_report_CH001_SC01",
                human_review_event_id: null,
                resolution_code: "hard_pass",
                next_action: "pass",
                stop_reason: null,
              },
              soft_qc: {
                branch: "continue",
                qc_report_id: "qc_report_CH001_SC01_soft",
                human_review_event_id: null,
                resolution_code: "soft_pass",
                next_action: "pass",
                stop_reason: null,
              },
            },
          }),
        };
      }

      if (url.includes("/scenes/CH001_SC01/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: basePayload,
          }),
        };
      }

      if (url.includes("/human-review-events?scene_id=CH001_SC01")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }

      if (url.includes("/scenes/CH001_SC01/attempts")) {
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

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    await store.runScene("CH001_SC01");

    expect(store.lastRunResult).toEqual(expect.objectContaining({ scene_status: "archived" }));
    expect(store.data.generation_summary.step).toBe("soft_patch");
    expect(store.data.hard_qc_summary.resolution_code).toBe("hard_pass");
    expect(store.data.soft_qc_summary.resolution_code).toBe("soft_pass");
    expect(store.data.rewrite_counters.soft_patch_count).toBe(1);
    expect(store.data.human_review_summary.trigger_reason).toBe("soft_qc_patch_cycle_limit");
  });
});

describe("scene workbench generation view wiring", () => {
  it("renders dedicated evidence cards beside the run receipt", () => {
    const viewSource = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");
    const generationCardSource = readFileSync(
      new URL("../src/components/GenerationSummaryCard.vue", import.meta.url),
      "utf8",
    );
    const qcCardSource = readFileSync(new URL("../src/components/QcReportCard.vue", import.meta.url), "utf8");

    expect(viewSource).toContain("GenerationSummaryCard");
    expect(viewSource).toContain("QcReportCard");
    expect(viewSource).toContain('data-testid="scene-generation-summary-card"');
    expect(viewSource).toContain('data-testid="scene-qc-report-card"');
    expect(viewSource).toContain("scene-run-receipt");
    expect(viewSource).toContain("workbench-columns");
    expect(viewSource).toContain("generation_summary");
    expect(viewSource).toContain("hard_qc_summary");
    expect(viewSource).toContain("soft_qc_summary");
    expect(viewSource).toContain("rewrite_counters");
    expect(viewSource).toContain("human_review_summary");

    expect(generationCardSource).toContain("provider");
    expect(generationCardSource).toContain("prompt_hash");
    expect(generationCardSource).toContain("finish_reason");
    expect(qcCardSource).toContain("pass_flag");
    expect(qcCardSource).toContain("resolution_code");
    expect(qcCardSource).toContain("rewrite_brief");
    expect(qcCardSource).toContain("next_action");
  });
});
