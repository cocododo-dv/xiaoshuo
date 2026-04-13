import { readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkbenchStore } from "../src/stores/workbench";

const STAGE_ID = "staged_backfill_CH200_SC01_F200_abc";

function buildWorkbenchPayload({
  pendingCount = 1,
  aggregateBlockReason = "blocked_waiting_backfill",
  manualHoldReason = null,
  stagedStatus = "pending",
  lastFinalMemoryRowId = null,
} = {}) {
  return {
    chapter_goal: {
      chapter_id: "CH200",
      chapter_goal: "补齐章节运行治理闭环",
      main_plot_push: "让旧信线索进入 backfill runtime",
      emotional_target: "从停滞推进到可执行",
      ending_effect: "形成新的章节 final aggregate",
    },
    scene_card: {
      scene_id: "CH200_SC01",
      scene_goal: "把模板 marker 治理成可操作 staged backfill",
      must_include_text: "旧信寄件人线索",
      location: "旧城门洞",
    },
    scene_run_state: {
      scene_status: "archived",
      current_bundle_id: "bundle_CH200_SC01",
      current_bundle_hash: "hash_CH200_SC01",
      current_final_scene_row_id: "final_scene_CH200_SC01_seed",
    },
    chapter_state: {
      chapter_id: "CH200",
      chapter_backfill_pending_count: pendingCount,
      aggregate_block_reason: aggregateBlockReason,
      manual_hold_reason: manualHoldReason,
      mid_aggregate_enabled_effective: 0,
      last_interim_memory_row_id: null,
      last_final_memory_row_id: lastFinalMemoryRowId,
      staged_backfill_items: [
        {
          stage_id: STAGE_ID,
          chapter_id: "CH200",
          scene_id: "CH200_SC01",
          marker_id: "F200",
          marker_text: "旧信寄件人线索",
          marker_token: '{{backfill id=F200 text="旧信寄件人线索"}}',
          status: stagedStatus,
          linked_tracker_row_id: stagedStatus === "pending" ? null : "foreshadow_F200_v1",
          last_strategy: stagedStatus === "pending" ? null : "create_tracker_now",
        },
      ],
    },
    bundle: {
      bundle_id: "bundle_CH200_SC01",
      bundle_snapshot_hash: "hash_CH200_SC01",
      snapshot: { scene_id: "CH200_SC01" },
    },
    final_scene: {
      row_id: "final_scene_CH200_SC01_seed",
      content: "归档里仍然保留 旧信寄件人线索",
    },
    scene_memory: {
      row_id: "scene_memory_CH200_SC01_seed",
      content: "场景记忆仍然写着 旧信寄件人线索",
    },
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

describe("workbench chapter runtime store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("runs staged backfill and refreshes the chapter receipt", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes(`/runtime/backfill/${STAGE_ID}`)) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              chapter_state: {
                chapter_backfill_pending_count: 0,
              },
              receipt: {
                action: "run_backfill",
                chapter_id: "CH200",
                stage_id: STAGE_ID,
                strategy: "create_tracker_now",
                status: "completed",
              },
            },
          }),
        };
      }

      if (url.includes("/scenes/CH200_SC01/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: buildWorkbenchPayload({
              pendingCount: 0,
              aggregateBlockReason: "none",
              stagedStatus: "completed",
            }),
          }),
        };
      }

      if (url.includes("/human-review-events?scene_id=CH200_SC01")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }

      if (url.includes("/scenes/CH200_SC01/attempts")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: buildAttemptsPayload(),
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    const message = await store.runChapterBackfill("CH200", STAGE_ID, "create_tracker_now", "CH200_SC01");

    expect(message).toContain("create_tracker_now");
    expect(store.lastChapterActionResult).toEqual(
      expect.objectContaining({
        action: "run_backfill",
        chapter_id: "CH200",
        stage_id: STAGE_ID,
        status: "completed",
      }),
    );
    expect(store.data.chapter_state.chapter_backfill_pending_count).toBe(0);
    expect(store.data.chapter_state.aggregate_block_reason).toBe("none");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      `http://127.0.0.1:8000/api/v1/chapters/CH200/runtime/backfill/${STAGE_ID}`,
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("runs final aggregate and persists the latest chapter action receipt", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/runtime/aggregate/final")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              chapter_state: {
                chapter_backfill_pending_count: 0,
                last_final_memory_row_id: "chapter_memory_final_CH200_v2",
              },
              receipt: {
                action: "run_final_aggregate",
                chapter_id: "CH200",
                chapter_memory_row_id: "chapter_memory_final_CH200_v2",
              },
            },
          }),
        };
      }

      if (url.includes("/scenes/CH200_SC01/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: buildWorkbenchPayload({
              pendingCount: 0,
              aggregateBlockReason: "none",
              stagedStatus: "completed",
              lastFinalMemoryRowId: "chapter_memory_final_CH200_v2",
            }),
          }),
        };
      }

      if (url.includes("/human-review-events?scene_id=CH200_SC01")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }

      if (url.includes("/scenes/CH200_SC01/attempts")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: buildAttemptsPayload(),
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    const message = await store.runChapterFinalAggregate("CH200", "CH200_SC01");

    expect(message).toContain("CH200");
    expect(store.lastChapterActionResult).toEqual(
      expect.objectContaining({
        action: "run_final_aggregate",
        chapter_memory_row_id: "chapter_memory_final_CH200_v2",
      }),
    );
    expect(store.data.chapter_state.last_final_memory_row_id).toBe("chapter_memory_final_CH200_v2");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/chapters/CH200/runtime/aggregate/final",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("sets and clears manual hold through chapter runtime endpoints", async () => {
    let holdActive = true;
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/runtime/manual-hold/clear")) {
        holdActive = false;
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              chapter_state: {
                aggregate_block_reason: "none",
                manual_hold_reason: null,
              },
              receipt: {
                action: "clear_manual_hold",
                chapter_id: "CH200",
              },
            },
          }),
        };
      }

      if (url.includes("/runtime/manual-hold")) {
        holdActive = true;
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              chapter_state: {
                aggregate_block_reason: "manual_hold",
                manual_hold_reason: "等待作者确认 backfill 处理策略",
              },
              receipt: {
                action: "set_manual_hold",
                chapter_id: "CH200",
                reason: "等待作者确认 backfill 处理策略",
              },
            },
          }),
        };
      }

      if (url.includes("/scenes/CH200_SC01/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: buildWorkbenchPayload({
              pendingCount: 0,
              aggregateBlockReason: holdActive ? "manual_hold" : "none",
              manualHoldReason: holdActive ? "等待作者确认 backfill 处理策略" : null,
              stagedStatus: "completed",
            }),
          }),
        };
      }

      if (url.includes("/human-review-events?scene_id=CH200_SC01")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }

      if (url.includes("/scenes/CH200_SC01/attempts")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: buildAttemptsPayload(),
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    const setMessage = await store.setChapterManualHold("CH200", "等待作者确认 backfill 处理策略", "CH200_SC01");
    expect(setMessage).toContain("设置人工挂起");
    expect(store.data.chapter_state.aggregate_block_reason).toBe("manual_hold");
    expect(store.data.chapter_state.manual_hold_reason).toBe("等待作者确认 backfill 处理策略");

    const clearMessage = await store.clearChapterManualHold("CH200", "CH200_SC01");
    expect(clearMessage).toContain("清除");
    expect(store.lastChapterActionResult).toEqual(
      expect.objectContaining({
        action: "clear_manual_hold",
        chapter_id: "CH200",
      }),
    );
    expect(store.data.chapter_state.aggregate_block_reason).toBe("none");
    expect(store.data.chapter_state.manual_hold_reason).toBeNull();
  });
});

describe("scene workbench chapter runtime source", () => {
  it("renders staged backfill controls, aggregate action, and chapter receipt", () => {
    const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(source).toContain("chapter-backfill-strategy-");
    expect(source).toContain("chapter-backfill-run-");
    expect(source).toContain("chapter-final-aggregate-button");
    expect(source).toContain("chapter-manual-hold-reason-input");
    expect(source).toContain("chapter-action-receipt");
  });
});
