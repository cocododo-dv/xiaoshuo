import { readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkbenchStore } from "../src/stores/workbench";

function buildWorkbenchPayload(runPreflight) {
  return {
    chapter_goal: {
      chapter_id: "CH910",
      chapter_goal: "Keep the scene pipeline honest",
      main_plot_push: "Show preflight before scene execution",
      emotional_target: "Reduce operator guesswork",
      ending_effect: "Run only when the inputs are truly ready",
    },
    scene_card: {
      scene_id: "CH910_SC01",
      scene_goal: "Verify the workbench preflight card",
      must_include_text: "Old letter clue",
      location: "Old city gate",
    },
    scene_run_state: {
      scene_status: "ready",
      current_bundle_id: null,
      current_bundle_hash: null,
      current_final_scene_row_id: null,
    },
    chapter_state: {
      chapter_id: "CH910",
      chapter_backfill_pending_count: 0,
      aggregate_block_reason: "none",
      manual_hold_reason: null,
      mid_aggregate_enabled_effective: 0,
      last_interim_memory_row_id: null,
      last_final_memory_row_id: null,
      staged_backfill_items: [],
    },
    run_preflight: runPreflight,
    bundle: {
      bundle_id: null,
      bundle_snapshot_hash: null,
      snapshot: null,
    },
    neutral_draft: null,
    style_draft: null,
    final_scene: null,
    scene_memory: null,
    attempts: [],
  };
}

function buildAttemptsPayload() {
  return {
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
  };
}

describe("scene workbench preflight store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps run_preflight on the loaded workbench payload", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/scenes/CH910_SC01/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: buildWorkbenchPayload({
              can_run: false,
              overall_status: "blocked",
              blocking_items: [
                {
                  code: "VOICE_PROFILE_MISSING",
                  title: "缺少 POV 声线档案，当前不宜运行场景",
                  detail: "请先补齐当前 POV 角色的可用声线档案，再执行完整场景运行。",
                  technical_hint: "expected active voice profile: VOICE_CHAR_A",
                },
              ],
              warning_items: [],
              context_items: [],
              missing_dependencies: [
                {
                  dependency_type: "voice_card",
                  lineage_key: "VOICE_CHAR_A",
                  detail: "POV voice card is required before generation",
                },
              ],
              create_actions: [
                {
                  action: "create_minimal_voice_card",
                  lineage_key: "VOICE_CHAR_A",
                  label: "Create minimal voice card",
                },
              ],
              constraint_conflicts: [
                {
                  term: "死亡证明",
                  severity: "blocking",
                  human_readable_reason: "Hook requires a term that another constraint forbids",
                },
              ],
            }),
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    await store.load("CH910_SC01");

    expect(store.data.run_preflight).toEqual(
      expect.objectContaining({
        can_run: false,
        overall_status: "blocked",
        blocking_items: [
          expect.objectContaining({
            code: "VOICE_PROFILE_MISSING",
            technical_hint: "expected active voice profile: VOICE_CHAR_A",
          }),
        ],
        missing_dependencies: [
          expect.objectContaining({
            dependency_type: "voice_card",
            lineage_key: "VOICE_CHAR_A",
          }),
        ],
        create_actions: [
          expect.objectContaining({
            action: "create_minimal_voice_card",
            lineage_key: "VOICE_CHAR_A",
          }),
        ],
        constraint_conflicts: [
          expect.objectContaining({
            term: "死亡证明",
            severity: "blocking",
          }),
        ],
      }),
    );
  });
});

describe("scene workbench preflight view wiring", () => {
  it("ships the preflight card, grouped sections, and run-button gating", () => {
    const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(source).toContain('data-testid="scene-run-preflight-card"');
    expect(source).toContain('data-testid="scene-run-preflight-blocking"');
    expect(source).toContain('data-testid="scene-run-preflight-warning"');
    expect(source).toContain('data-testid="scene-run-preflight-context"');
    expect(source).toContain('data-testid="scene-run-preflight-missing-dependencies"');
    expect(source).toContain('data-testid="scene-run-preflight-create-actions"');
    expect(source).toContain('data-testid="scene-run-preflight-constraint-conflicts"');
    expect(source).toContain('data-testid="scene-run-preflight-status"');
    expect(source).toContain("runPreflight");
    expect(source).toContain("missingDependencies");
    expect(source).toContain("constraintConflicts");
    expect(source).toContain("item.detail");
    expect(source).toContain("item.technical_hint");
    expect(source).toContain("!runPreflight.can_run");
  });
});
