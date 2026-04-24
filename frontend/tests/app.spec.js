import { existsSync, readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { actOnHumanReviewEvent, setOperatorRef } from "../src/lib/api";
import { useShellRouter } from "../src/router";
import { useIndexConsoleStore } from "../src/stores/indexConsole";
import { useKnowledgeConsoleStore } from "../src/stores/knowledgeConsole";
import { useReviewInboxStore } from "../src/stores/reviewInbox";
import { useWorkbenchStore } from "../src/stores/workbench";

function ok(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

describe("workbench store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          scene_card: { scene_id: "CH001_SC01" },
          scene_run_state: { scene_status: "ready" },
          bundle: { bundle_id: "bundle_CH001_SC01" },
          attempts: [],
        },
      }),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads a scene workbench payload from the API envelope", async () => {
    const store = useWorkbenchStore();

    await store.load("CH001_SC01");

    expect(store.sceneId).toBe("CH001_SC01");
    expect(store.data.scene_card.scene_id).toBe("CH001_SC01");
  });

  it("loads scene-scoped human review items for the requested scene", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_card: { scene_id: "CH001_SC01" },
              scene_run_state: { scene_status: "ready" },
              bundle: { bundle_id: "bundle_CH001_SC01" },
              attempts: [],
            },
          }),
        };
      }

      if (url.includes("/human-review-events?scene_id=CH001_SC01")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  event_id: "human_review_scene_1",
                  scene_id: "CH001_SC01",
                },
              ],
            },
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
    await store.refreshAll("CH001_SC01");

    expect(store.humanReviewItems).toEqual([
      expect.objectContaining({
        event_id: "human_review_scene_1",
        scene_id: "CH001_SC01",
      }),
    ]);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/human-review-events?scene_id=CH001_SC01",
    );
  });

  it("replaces human review items when the workbench scene changes", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/scenes/CH001_SC01/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_card: { scene_id: "CH001_SC01" },
              scene_run_state: { scene_status: "ready" },
              bundle: { bundle_id: "bundle_CH001_SC01" },
              attempts: [],
            },
          }),
        };
      }

      if (url.includes("/scenes/CH001_SC02/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_card: { scene_id: "CH001_SC02" },
              scene_run_state: { scene_status: "ready" },
              bundle: { bundle_id: "bundle_CH001_SC02" },
              attempts: [],
            },
          }),
        };
      }

      if (url.includes("/human-review-events?scene_id=CH001_SC01")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  event_id: "human_review_scene_1",
                  scene_id: "CH001_SC01",
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/human-review-events?scene_id=CH001_SC02")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  event_id: "human_review_scene_2",
                  scene_id: "CH001_SC02",
                },
              ],
            },
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

      if (url.includes("/scenes/CH001_SC02/attempts")) {
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

    await store.refreshAll("CH001_SC01");
    await store.refreshAll("CH001_SC02");

    expect(store.sceneId).toBe("CH001_SC02");
    expect(store.humanReviewItems).toEqual([
      expect.objectContaining({
        event_id: "human_review_scene_2",
        scene_id: "CH001_SC02",
      }),
    ]);
    expect(store.humanReviewItems).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ event_id: "human_review_scene_1" })]),
    );
  });

  it("runs a full scene and refreshes the workbench state", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/run/jobs")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              job_id: "scene_run_job_CH001_SC01",
              scene_id: "CH001_SC01",
              status: "queued",
              current_step: "bundle_built",
            },
          }),
        };
      }

      if (url.includes("/run-jobs/scene_run_job_CH001_SC01")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              job_id: "scene_run_job_CH001_SC01",
              scene_id: "CH001_SC01",
              status: "completed",
              current_step: "archived",
              result_summary: {
                scene_status: "archived",
                current_bundle_id: "bundle_CH001_SC01",
                current_bundle_hash: "hash_123",
                current_final_scene_row_id: "final_scene_CH001_SC01",
              },
            },
          }),
        };
      }

      if (url.includes("/workbench")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_card: { scene_id: "CH001_SC01" },
              scene_run_state: { scene_status: "archived" },
              bundle: { bundle_id: "bundle_CH001_SC01" },
              attempts: [],
            },
          }),
        };
      }

      if (url.includes("/human-review-events")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  event_id: "human_review_scene_1",
                  scene_id: "CH001_SC01",
                },
              ],
            },
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
    const message = await store.runScene("CH001_SC01");

    expect(message).toContain("CH001_SC01");
    expect(store.lastRunResult.current_final_scene_row_id).toBe("final_scene_CH001_SC01");
    expect(store.data.scene_run_state.scene_status).toBe("archived");
    expect(store.humanReviewItems).toEqual([
      expect.objectContaining({
        event_id: "human_review_scene_1",
        scene_id: "CH001_SC01",
      }),
    ]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(5);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/scenes/CH001_SC01/run/jobs",
      expect.objectContaining({ method: "POST" }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/run-jobs/scene_run_job_CH001_SC01");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/human-review-events?scene_id=CH001_SC01",
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/scenes/CH001_SC01/attempts?limit=25",
    );
  });

  it("keeps polling long-running local model scene jobs until they complete", async () => {
    let pollCount = 0;
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/run-jobs/long_qwen_scene_job")) {
        pollCount += 1;
        return ok({
          job_id: "long_qwen_scene_job",
          scene_id: "CHQWEN_SC01",
          status: pollCount > 180 ? "completed" : "running",
          current_step: pollCount > 180 ? "archived" : "style_draft",
          result_summary: pollCount > 180
            ? {
                scene_status: "archived",
                current_bundle_id: "bundle_CHQWEN_SC01",
                current_bundle_hash: "hash_qwen",
                current_final_scene_row_id: "final_scene_CHQWEN_SC01",
              }
            : {},
        });
      }

      if (url.includes("/scenes/CHQWEN_SC01/workbench")) {
        return ok({
          scene_card: { scene_id: "CHQWEN_SC01" },
          scene_run_state: { scene_status: "archived" },
          bundle: { bundle_id: "bundle_CHQWEN_SC01" },
          attempts: [],
        });
      }

      if (url.includes("/human-review-events?scene_id=CHQWEN_SC01")) {
        return ok({ items: [] });
      }

      if (url.includes("/scenes/CHQWEN_SC01/attempts")) {
        return ok({
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
        });
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useWorkbenchStore();
    const job = await store.pollRunJob("long_qwen_scene_job", "CHQWEN_SC01", { intervalMs: 0 });

    expect(job.status).toBe("completed");
    expect(pollCount).toBe(181);
    expect(store.lastRunResult.current_final_scene_row_id).toBe("final_scene_CHQWEN_SC01");
    expect(store.data.scene_run_state.scene_status).toBe("archived");
  });

  it("keeps the current scene context when a run request fails", async () => {
    const store = useWorkbenchStore();
    store.sceneId = "CH001_SC01";
    store.data = {
      scene_card: { scene_id: "CH001_SC01" },
      scene_run_state: { scene_status: "ready" },
      bundle: { bundle_id: "bundle_CH001_SC01" },
      attempts: [],
    };

    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/run/jobs")) {
        return {
          ok: false,
          json: async () => ({
            ok: false,
            error: { message: "Scene pipeline failed" },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    await expect(store.runScene("CH001_SC02")).rejects.toThrow("Scene pipeline failed");

    expect(store.sceneId).toBe("CH001_SC01");
    expect(store.data.scene_card.scene_id).toBe("CH001_SC01");
    expect(store.error).toBe("Scene pipeline failed");
    expect(store.actionId).toBe("");
    expect(store.lastRunResult).toBeNull();
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });
});

describe("vue shell", () => {
  it("renders the three required views from the Vue shell", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(source).toContain("SceneWorkbenchView");
    expect(source).toContain("ReviewInboxView");
    expect(source).toContain("IndexConsoleView");
    expect(source).toContain("KnowledgeConsoleView");
    expect(source).toContain("WorkflowNav");
    expect(source).toContain("UiModeSwitch");
    expect(routerSource).toContain('id: "workbench"');
    expect(routerSource).toContain('label: "3 运行场景"');
    expect(routerSource).toContain('legacyLabel: "场景工作台"');
    expect(routerSource).toContain('id: "review"');
    expect(routerSource).toContain('label: "4 处理审核"');
    expect(routerSource).toContain('legacyLabel: "审核收件箱"');
    expect(routerSource).toContain('id: "index"');
    expect(routerSource).toContain('label: "7 发布索引"');
    expect(routerSource).toContain('legacyLabel: "索引控制台"');
    expect(routerSource).toContain('id: "knowledge"');
    expect(routerSource).toContain('label: "8 沉淀知识"');
    expect(routerSource).toContain('legacyLabel: "知识控制台"');
    expect(routerSource).toContain('cacheMode: "light"');
    expect(routerSource).not.toContain("chromeTitle");
    expect(routerSource).not.toContain("formatViewLabel");
    expect(routerSource).not.toContain("uiText");
  });

  it("ships an explicit favicon asset so browser QA starts clean", () => {
    const indexSource = readFileSync(new URL("../index.html", import.meta.url), "utf8");

    expect(indexSource).toContain('rel="icon"');
    expect(indexSource).toContain('/favicon.svg');
    expect(existsSync(new URL("../public/favicon.svg", import.meta.url))).toBe(true);
  });

  it("adds an interop center entry point to the shell", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(source).toContain("InteropCenterView");
    expect(source).toContain("activeView === 'interop'");
    expect(routerSource).toContain('id: "interop"');
    expect(routerSource).toContain('label: "10 导入导出"');
    expect(routerSource).toContain('legacyLabel: "互操作中心"');
  });
});

describe("shell router", () => {
  it("opens a runtime target in the matching view and keeps focus", () => {
    const router = useShellRouter();

    router.reset();
    router.openTarget({
      target_type: "review_item",
      target_id: "review_style_pending",
      target_ref: "review_item:review_style_pending",
    });

    expect(router.activeView.value).toBe("review");
    expect(router.focusTarget.value).toEqual({
      target_type: "review_item",
      target_id: "review_style_pending",
      target_ref: "review_item:review_style_pending",
      source_type: null,
      source_id: null,
    });

    router.openTarget({
      target_type: "verify_job",
      target_id: "verify_review_style_pending",
      target_ref: "verify_job:verify_review_style_pending",
    });

    expect(router.activeView.value).toBe("index");
    expect(router.focusTarget.value).toEqual({
      target_type: "verify_job",
      target_id: "verify_review_style_pending",
      target_ref: "verify_job:verify_review_style_pending",
      source_type: null,
      source_id: null,
    });

    router.openTarget({
      target_type: "scene_card",
      target_id: "CH001_SC02",
      target_ref: "scene_card:CH001_SC02",
    });

    expect(router.activeView.value).toBe("workbench");
    expect(router.focusTarget.value).toEqual({
      target_type: "scene_card",
      target_id: "CH001_SC02",
      target_ref: "scene_card:CH001_SC02",
      source_type: null,
      source_id: null,
    });
  });

  it("keeps source context when a jump should stay inside the index console", () => {
    const router = useShellRouter();

    router.reset();
    router.openTarget(
      {
        target_type: "review_item",
        target_id: "review_style_released",
        target_ref: "review_item:review_style_released",
      },
      {
        view_id: "index",
        source_type: "system_activity",
        source_id: 12,
      },
    );

    expect(router.activeView.value).toBe("index");
    expect(router.focusTarget.value).toEqual({
      target_type: "review_item",
      target_id: "review_style_released",
      target_ref: "review_item:review_style_released",
      source_type: "system_activity",
      source_id: 12,
    });
  });

  it("tracks pending focus view only for cross-view target opens", () => {
    const router = useShellRouter();

    router.reset();
    router.openTarget({
      target_type: "review_item",
      target_id: "review_style_pending",
      target_ref: "review_item:review_style_pending",
    });

    expect(router.pendingFocusView.value).toBe("review");

    router.settleFocusView("review");
    expect(router.pendingFocusView.value).toBeNull();

    router.openTarget({
      target_type: "review_item",
      target_id: "review_style_released",
      target_ref: "review_item:review_style_released",
    });

    expect(router.pendingFocusView.value).toBeNull();
  });

  it("ships interop and knowledge-specific target routing", () => {
    const source = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(source).toContain('id: "interop"');
    expect(source).toContain('label: "10 导入导出"');
    expect(source).toContain('legacyLabel: "互操作中心"');
    expect(source).toContain('if (targetType === "knowledge_entry")');
    expect(source).toContain('return "knowledge"');
  });
});

describe("api helpers", () => {
  const originalWindow = globalThis.window;

  afterEach(() => {
    vi.restoreAllMocks();
    if (originalWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = originalWindow;
    }
  });

  it("includes the persisted operator ref in human review action requests", async () => {
    const storage = new Map();
    globalThis.window = {
      localStorage: {
        getItem: (key) => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
      },
    };
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          event_id: "human_review_idempotency_recovery_approve-review-stale",
          action: "retry_request",
          status: "resolved",
        },
      }),
    });

    setOperatorRef("ops.duwei");
    await actOnHumanReviewEvent("human_review_idempotency_recovery_approve-review-stale", "retry_request");

    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/human-review-events/human_review_idempotency_recovery_approve-review-stale/actions",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-Operator-Ref": "ops.duwei",
        }),
      }),
    );
  });

  it("ships dedicated interop API helpers", () => {
    const source = readFileSync(new URL("../src/lib/api.js", import.meta.url), "utf8");

    expect(source).toContain("previewBundleWorksheet");
    expect(source).toContain("/api/v1/interop/preview/bundle-worksheet");
    expect(source).toContain("importBundleWorksheet");
    expect(source).toContain("/api/v1/interop/import/bundle-worksheet");
    expect(source).toContain("fetchBundleWorksheetExport");
    expect(source).toContain("fetchReplayFinalScene");
    expect(source).toContain("fetchReplayDraft");
  });

  it("preserves structured database-busy API errors", async () => {
    const { fetchRunJob } = await import("../src/lib/api.js");
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => ({
        ok: false,
        error: {
          code: "DATABASE_BUSY",
          message: "DATABASE_BUSY: writer lock is held",
          details: { retry_after_ms: 1000 },
        },
      }),
    });

    await expect(fetchRunJob("job_busy")).rejects.toMatchObject({
      code: "DATABASE_BUSY",
      message: "DATABASE_BUSY: writer lock is held",
      status: 503,
      details: { retry_after_ms: 1000 },
    });
  });
});

describe("interop center source", () => {
  it("ships dedicated interop store and view files", () => {
    expect(existsSync(new URL("../src/stores/interopCenter.js", import.meta.url))).toBe(true);
    expect(existsSync(new URL("../src/views/InteropCenterView.vue", import.meta.url))).toBe(true);
  });
});

describe("review inbox store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    let recoveryStatus = "open";
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/review-items")) {
        if (url.includes("/approve")) {
          return {
            ok: true,
            json: async () => ({
              ok: true,
              data: {
                review_id: "review_style_pending",
                actor_ref: "ops.duwei",
              },
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  review_id: "review_style_pending",
                  candidate_text: "pending review",
                  materialize_status: "pending",
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/human-review-events/") && url.includes("/actions")) {
        recoveryStatus = "resolved";
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              event_id: "human_review_idempotency_recovery_approve-review-stale",
              action: "retry_request",
              status: "resolved",
              linked_target_ref: "review_item:review_style_pending",
              resolution_reason: "review action replay reached a terminal state",
              replay_result: {
                review_id: "review_style_pending",
                materialize_status: "succeeded",
              },
            },
          }),
        };
      }

      if (url.includes("/human-review-events")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  event_id: "human_review_idempotency_recovery_approve-review-stale",
                  event_source: "idempotency_recovery",
                  object_ref: "approve-review-stale",
                  status: recoveryStatus,
                },
                {
                  event_id: "human_review_manual_scene",
                  event_source: "manual_scene_review",
                  object_ref: "CH001_SC01",
                  status: "open",
                },
              ],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads review items and groups recovery-generated human review events", async () => {
    const store = useReviewInboxStore();

    await store.load();

    expect(store.items).toHaveLength(1);
    expect(store.systemRecoveryItems).toEqual([
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_approve-review-stale",
        event_source: "idempotency_recovery",
      }),
    ]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("includes the operator ref in ordinary review approval notices", async () => {
    const store = useReviewInboxStore();

    const message = await store.approve("review_style_pending");

    expect(message).toContain("已批准 review_style_pending");
    expect(message).toContain("ops.duwei");
  });

  it("keeps a just-approved pending review visible for same-card release", async () => {
    let approved = false;
    let released = false;
    globalThis.fetch = vi.fn(async (url) => {
      const requestUrl = String(url);
      if (requestUrl.includes("/review-items/review_style_pending/approve")) {
        approved = true;
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_id: "review_style_pending",
              status: "approved",
              materialize_status: "succeeded",
              approved_item_row_id: "style_observation_review_style_pending_v1",
              actor_ref: "ops.duwei",
            },
          }),
        };
      }
      if (requestUrl.includes("/review-items/review_style_pending/release")) {
        released = true;
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_id: "review_style_pending",
              released: true,
              actor_ref: "ops.duwei",
            },
          }),
        };
      }
      if (requestUrl.includes("/review-items")) {
        const pendingFilter = requestUrl.includes("status=pending");
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items:
                pendingFilter && approved
                  ? []
                  : [
                      {
                        review_id: "review_style_pending",
                        status: "pending",
                        item_type: "style_observation",
                        target_collection: "style_observations",
                        candidate_text: "pending review",
                        materialize_status: "pending",
                      },
                    ],
            },
          }),
        };
      }
      if (requestUrl.includes("/human-review-events")) {
        return {
          ok: true,
          json: async () => ({ ok: true, data: { items: [] } }),
        };
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useReviewInboxStore();
    store.reviewFilters.status = "pending";
    await store.load({ resetReview: true, resetHumanReview: true, force: true });
    await store.approve("review_style_pending");

    expect(store.items).toEqual([
      expect.objectContaining({
        review_id: "review_style_pending",
        status: "approved",
        materialize_status: "succeeded",
        approved_item_row_id: "style_observation_review_style_pending_v1",
      }),
    ]);

    await store.release("review_style_pending");

    expect(released).toBe(true);
    expect(store.items).toEqual([]);
  });

  it("localizes not-verified release failures in the review inbox", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      const requestUrl = String(url);
      if (requestUrl.includes("/review-items/review_style_pending/release")) {
        return {
          ok: false,
          status: 409,
          json: async () => ({
            ok: false,
            data: null,
            error: { code: "RELEASE_PRECONDITION_FAILED", message: "candidate is not verified" },
          }),
        };
      }
      if (requestUrl.endsWith("/review-items/review_style_pending")) {
        return ok({
          review_id: "review_style_pending",
          status: "approved",
          materialize_status: "succeeded",
          release_state: {
            state: "blocked",
            blocked_reason: "not_verified",
            message: "候选尚未通过索引校验，请先在索引控制台重试校验，成功后再发布。",
            recommended_action: "retry_verify",
            verify_job_id: "verify_review_style_pending",
          },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useReviewInboxStore();

    await expect(store.release("review_style_pending")).rejects.toThrow("候选尚未通过索引校验");
    expect(store.error).toContain("索引控制台");
    expect(store.error).not.toContain("candidate is not verified");
  });

  it("reconciles failed approve requests when the latest review state is already approved", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      const requestUrl = String(url);
      if (requestUrl.includes("/review-items/review_style_pending/approve")) {
        throw new TypeError("Failed to fetch");
      }
      if (requestUrl.endsWith("/review-items/review_style_pending")) {
        return ok({
          review_id: "review_style_pending",
          status: "approved",
          materialize_status: "succeeded",
          approved_item_row_id: "style_observation_review_style_pending_v1",
          release_state: {
            state: "ready",
            blocked_reason: "",
            message: "候选已批准、已物化且校验通过，可以发布到运行时。",
            recommended_action: "none",
            verify_job_id: "verify_review_style_pending",
          },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const store = useReviewInboxStore();
    const message = await store.approve("review_style_pending");

    expect(message).toContain("当前状态已完成");
    expect(message).toContain("已批准");
    expect(store.error).toBe("");
    expect(store.pinnedApprovedReviewItems).toEqual([
      expect.objectContaining({
        review_id: "review_style_pending",
        status: "approved",
        materialize_status: "succeeded",
      }),
    ]);
  });

  it("retries a recovery event request and refreshes the inbox state", async () => {
    const store = useReviewInboxStore();

    const message = await store.actOnHumanReviewEvent(
      "human_review_idempotency_recovery_approve-review-stale",
      "retry_request",
    );

    expect(message).toContain("retry_request");
    expect(message).toContain("resolved");
    expect(store.systemRecoveryItems).toHaveLength(0);
    expect(store.lastActionResult).toEqual(
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_approve-review-stale",
        status: "resolved",
      }),
    );
    expect(store.actionId).toBe("");
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
  });
});

describe("knowledge console store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes("/api/v1/knowledge-entries/voice_card/VOICE_CHAR_A/workflow")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_items: [
                {
                  review_id: "review_voice_card_candidate",
                  status: "pending",
                  materialize_status: "pending",
                },
              ],
              jobs: [],
              human_review_events: [],
              target_activity_groups: [],
              recommended_primary_action: {
                kind: "review",
                action: "approve_review",
                review_id: "review_voice_card_candidate",
                label: "Approve",
                target_ref: "review_item:review_voice_card_candidate",
              },
            },
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries/voice_card/VOICE_CHAR_A")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              object_type: "voice_card",
              lineage_key: "VOICE_CHAR_A",
              active_version: {
                row_id: "voice_card_VOICE_CHAR_A_v1",
                version: 1,
                text: "short clipped lines; pressure makes the tone harder",
              },
              candidate_version: {
                review_id: "review_voice_card_candidate",
                text: "candidate voice update",
                scope: null,
                scope_ref_id: null,
              },
              versions: [
                {
                  row_id: "voice_card_VOICE_CHAR_A_v1",
                  version: 1,
                  text: "short clipped lines; pressure makes the tone harder",
                },
              ],
              runtime_refs: {
                mode: "direct_read",
              },
              review_refs: ["review_voice_card_candidate"],
              bundle_refs: [
                {
                  bundle_id: "bundle_CH001_SC01",
                  scene_id: "CH001_SC01",
                  chapter_id: "CH001",
                  object_type: "voice_card",
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  object_type: "voice_card",
                  lineage_key: "VOICE_CHAR_A",
                  status: "active",
                  active_version: {
                    row_id: "voice_card_VOICE_CHAR_A_v1",
                    version: 1,
                    text: "short clipped lines; pressure makes the tone harder",
                  },
                  candidate_version: {
                    review_id: "review_voice_card_candidate",
                    text: "candidate voice update",
                    scope: null,
                    scope_ref_id: null,
                  },
                  versions: [
                    {
                      row_id: "voice_card_VOICE_CHAR_A_v1",
                      version: 1,
                      text: "short clipped lines; pressure makes the tone harder",
                    },
                  ],
                  runtime_refs: {
                    mode: "direct_read",
                  },
                  review_refs: [],
                },
              ],
              supported_object_types: ["voice_card", "style_rule", "calibration_line"],
            },
          }),
        };
      }

      if (url.includes("/api/v1/review-items") && options.method === "POST") {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_id: "review_voice_card_candidate",
              item_type: "voice_card_candidate",
              candidate_text: "candidate voice update",
              candidate_payload_json: {
                lineage_key: "VOICE_CHAR_A",
                character_id: "CHAR_A",
                text: "candidate voice update",
              },
              status: "pending",
              target_collection: "voice_cards",
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("merges pending review candidates into the knowledge catalog and loads detail", async () => {
    const store = useKnowledgeConsoleStore();

    await store.load();
    await store.selectItem("voice_card", "VOICE_CHAR_A");

    expect(store.items).toEqual([
      expect.objectContaining({
        object_type: "voice_card",
        lineage_key: "VOICE_CHAR_A",
        candidate_version: expect.objectContaining({
          review_id: "review_voice_card_candidate",
          text: "candidate voice update",
        }),
      }),
    ]);
    expect(store.detail).toEqual(
      expect.objectContaining({
        object_type: "voice_card",
        lineage_key: "VOICE_CHAR_A",
        runtime_refs: expect.objectContaining({
          mode: "direct_read",
        }),
      }),
    );
  });

  it("creates a candidate review item from the knowledge console form", async () => {
    const store = useKnowledgeConsoleStore();

    const message = await store.createCandidate({
      reviewId: "review_voice_card_candidate",
      itemType: "voice_card_candidate",
      lineageKey: "VOICE_CHAR_A",
      candidateText: "candidate voice update",
      characterId: "CHAR_A",
      displayName: "林岑",
      pronouns: "她",
      role: "档案修复师",
      aliases: "小林, 林修复",
      activeOnApprove: 0,
    });

    expect(message).toContain("review_voice_card_candidate");
    expect(store.lastCreateResult).toEqual(
      expect.objectContaining({
        review_id: "review_voice_card_candidate",
        target_collection: "voice_cards",
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/review-items",
      expect.objectContaining({
        method: "POST",
      }),
    );
    const createCall = globalThis.fetch.mock.calls.find(([url, options]) =>
      String(url).includes("/api/v1/review-items") && options?.method === "POST"
    );
    const requestBody = JSON.parse(createCall[1].body);
    expect(requestBody.candidate_payload_json).toEqual(
      expect.objectContaining({
        display_name: "林岑",
        pronouns: ["她"],
        role: "档案修复师",
        aliases: ["小林", "林修复"],
      }),
    );
  });

  it("treats already-active release conflicts as an idempotent knowledge success", async () => {
    const store = useKnowledgeConsoleStore();
    let releaseAttempted = false;

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes("/api/v1/review-items/review_voice_card_candidate/release")) {
        releaseAttempted = true;
        return {
          ok: false,
          status: 409,
          json: async () => ({
            ok: false,
            data: null,
            error: { code: "REVIEW_RELEASE_CONFLICT", message: "candidate is already active" },
          }),
        };
      }
      if (url.includes("/api/v1/knowledge-entries/voice_card/VOICE_CHAR_A/workflow")) {
        return ok({ recommended_primary_action: null, review_items: [], jobs: [], human_review_events: [] });
      }
      if (url.includes("/api/v1/knowledge-entries/voice_card/VOICE_CHAR_A")) {
        return ok({ object_type: "voice_card", lineage_key: "VOICE_CHAR_A", status: "active" });
      }
      if (url.includes("/api/v1/knowledge-entries")) {
        return ok({ items: [{ object_type: "voice_card", lineage_key: "VOICE_CHAR_A", status: "active" }] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    store.selectedObjectType = "voice_card";
    store.selectedLineageKey = "VOICE_CHAR_A";

    const message = await store.releaseReview("review_voice_card_candidate");

    expect(releaseAttempted).toBe(true);
    expect(message).toContain("已是最新发布状态");
    expect(message).toContain("review_voice_card_candidate");
    expect(store.error).toBe("");
  });

  it("explains not-verified release conflicts with the next knowledge action", async () => {
    const store = useKnowledgeConsoleStore();

    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/api/v1/review-items/review_voice_card_candidate/release")) {
        return {
          ok: false,
          status: 409,
          json: async () => ({
            ok: false,
            data: null,
            error: { code: "REVIEW_RELEASE_CONFLICT", message: "candidate is not verified" },
          }),
        };
      }
      if (url.includes("/api/v1/knowledge-entries/voice_card/VOICE_CHAR_A/workflow")) {
        return ok({
          recommended_primary_action: { action: "retry_verify", job_id: "verify_review_voice_card_candidate" },
          review_items: [],
          jobs: [],
          human_review_events: [],
        });
      }
      if (url.includes("/api/v1/knowledge-entries/voice_card/VOICE_CHAR_A")) {
        return ok({ object_type: "voice_card", lineage_key: "VOICE_CHAR_A", status: "candidate" });
      }
      if (url.includes("/api/v1/knowledge-entries")) {
        return ok({ items: [{ object_type: "voice_card", lineage_key: "VOICE_CHAR_A", status: "candidate" }] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    store.selectedObjectType = "voice_card";
    store.selectedLineageKey = "VOICE_CHAR_A";

    await expect(store.releaseReview("review_voice_card_candidate")).rejects.toThrow("候选尚未通过校验");
    expect(store.error).toContain("先重试校验");
  });

  it("applies object, scope, scope ref, and status filters to pending knowledge candidates", async () => {
    const store = useKnowledgeConsoleStore();

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes("/api/v1/knowledge-entries")) {
        expect(url).toContain("object_type=style_rule");
        expect(url).toContain("scope=global");
        expect(url).toContain("scope_ref_id=global");
        expect(url).toContain("status=candidate");
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  object_type: "style_rule",
                  lineage_key: "STYLE_PENDING_GLOBAL",
                  status: "candidate",
                  active_version: null,
                  candidate_version: {
                    review_id: "review_style_rule_global_candidate",
                    text: "keep the reunion tight and gesture-led",
                    scope: "global",
                    scope_ref_id: "global",
                  },
                  versions: [],
                  runtime_refs: { mode: "pending_review" },
                  review_refs: ["review_style_rule_global_candidate"],
                  bundle_refs: [],
                },
              ],
              supported_object_types: ["voice_card", "style_rule", "calibration_line"],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    await store.load({
      objectType: "style_rule",
      scope: "global",
      scopeRefId: "global",
      status: "candidate",
    });

    expect(store.filters).toEqual({
      objectType: "style_rule",
      scope: "global",
      scopeRefId: "global",
      status: "candidate",
    });
    expect(store.items).toEqual([
      expect.objectContaining({
        object_type: "style_rule",
        lineage_key: "STYLE_PENDING_GLOBAL",
        status: "candidate",
        candidate_version: expect.objectContaining({
          review_id: "review_style_rule_global_candidate",
          scope: "global",
          scope_ref_id: "global",
        }),
      }),
    ]);
  });

  it("ignores stale detail responses after filters move to a different lineage", async () => {
    const store = useKnowledgeConsoleStore();
    let resolveOldDetail;
    let resolveOldWorkflow;
    let resolveNewDetail;
    let resolveNewWorkflow;

    const oldDetailPromise = new Promise((resolve) => {
      resolveOldDetail = resolve;
    });
    const oldWorkflowPromise = new Promise((resolve) => {
      resolveOldWorkflow = resolve;
    });
    const newDetailPromise = new Promise((resolve) => {
      resolveNewDetail = resolve;
    });
    const newWorkflowPromise = new Promise((resolve) => {
      resolveNewWorkflow = resolve;
    });

    store.items = [
      {
        object_type: "style_observation",
        lineage_key: "STY_DEMO_001",
        status: "candidate",
        active_version: null,
        candidate_version: { review_id: "review_demo_style_observation" },
        versions: [{ row_id: "style_observation_STY_DEMO_001_v1", version: 1 }],
        runtime_refs: { mode: "pending_review" },
        review_refs: ["review_demo_style_observation"],
        bundle_refs: [],
      },
    ];

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes("/api/v1/knowledge-entries/style_observation/STY_DEMO_001/workflow")) {
        return oldWorkflowPromise;
      }

      if (url.includes("/api/v1/knowledge-entries/style_observation/STY_DEMO_001")) {
        return oldDetailPromise;
      }

      if (url.includes("/api/v1/knowledge-entries/style_rule/STYLE_KNOWLEDGE_E2E/workflow")) {
        return newWorkflowPromise;
      }

      if (url.includes("/api/v1/knowledge-entries/style_rule/STYLE_KNOWLEDGE_E2E")) {
        return newDetailPromise;
      }

      if (
        url.includes("/api/v1/knowledge-entries")
        && url.includes("object_type=style_rule")
        && url.includes("scope=global")
        && url.includes("scope_ref_id=global")
        && url.includes("status=active")
      ) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  object_type: "style_rule",
                  lineage_key: "STYLE_KNOWLEDGE_E2E",
                  status: "active",
                  active_version: {
                    row_id: "style_rule_STYLE_KNOWLEDGE_E2E_v1",
                    version: 1,
                    text: "keep the reunion tight and gesture-led",
                    scope: "global",
                    scope_ref_id: "global",
                  },
                  candidate_version: null,
                  versions: [{ row_id: "style_rule_STYLE_KNOWLEDGE_E2E_v1", version: 1 }],
                  runtime_refs: { mode: "direct_read" },
                  review_refs: ["review_knowledge_style_rule"],
                  bundle_refs: [],
                },
              ],
              supported_object_types: ["style_rule", "style_observation"],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    const staleSelection = store.selectItem("style_observation", "STY_DEMO_001");
    await store.load({
      objectType: "style_rule",
      scope: "global",
      scopeRefId: "global",
      status: "active",
    });
    const activeSelection = store.selectItem("style_rule", "STYLE_KNOWLEDGE_E2E");

    resolveNewDetail({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          object_type: "style_rule",
          lineage_key: "STYLE_KNOWLEDGE_E2E",
          status: "active",
          active_version: {
            row_id: "style_rule_STYLE_KNOWLEDGE_E2E_v1",
            version: 1,
            text: "keep the reunion tight and gesture-led",
            scope: "global",
            scope_ref_id: "global",
          },
          candidate_version: null,
          versions: [{ row_id: "style_rule_STYLE_KNOWLEDGE_E2E_v1", version: 1 }],
          runtime_refs: { mode: "direct_read" },
          review_refs: ["review_knowledge_style_rule"],
          bundle_refs: [],
        },
      }),
    });
    resolveNewWorkflow({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          review_items: [],
          jobs: [],
          human_review_events: [],
          target_activity_groups: [],
          recommended_primary_action: null,
        },
      }),
    });

    await activeSelection;

    resolveOldDetail({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          object_type: "style_observation",
          lineage_key: "STY_DEMO_001",
          status: "candidate",
          active_version: null,
          candidate_version: {
            review_id: "review_demo_style_observation",
            text: "leave the final beat compressed",
          },
          versions: [],
          runtime_refs: { mode: "pending_review" },
          review_refs: ["review_demo_style_observation"],
          bundle_refs: [],
        },
      }),
    });
    resolveOldWorkflow({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          review_items: [],
          jobs: [],
          human_review_events: [],
          target_activity_groups: [],
          recommended_primary_action: null,
        },
      }),
    });

    await staleSelection;

    expect(store.detail).toEqual(
      expect.objectContaining({
        object_type: "style_rule",
        lineage_key: "STYLE_KNOWLEDGE_E2E",
      }),
    );
  });

  it("preserves the selected detail when unrelated pending reviews are merged in", async () => {
    const store = useKnowledgeConsoleStore();

    store.items = [
      {
        object_type: "style_rule",
        lineage_key: "STYLE_KNOWLEDGE_E2E",
        status: "candidate",
        active_version: null,
        candidate_version: { review_id: "review_knowledge_style_rule" },
        versions: [],
        runtime_refs: { mode: "pending_review" },
        review_refs: ["review_knowledge_style_rule"],
        bundle_refs: [],
      },
    ];
    store.pendingReviewItems = [
      {
        review_id: "review_demo_style_observation",
        item_type: "style_observation",
        status: "pending",
        materialize_status: "pending",
        candidate_text: "leave the final beat compressed",
        candidate_payload_json: {
          lineage_key: "STY_DEMO_001",
          scope: "global",
          scope_ref_id: "global",
        },
      },
      {
        review_id: "review_knowledge_style_rule",
        item_type: "style_rule_set",
        status: "pending",
        materialize_status: "pending",
        candidate_text: "keep the reunion tight and gesture-led",
        candidate_payload_json: {
          lineage_key: "STYLE_KNOWLEDGE_E2E",
          scope: "global",
          scope_ref_id: "global",
        },
      },
    ];

    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/api/v1/knowledge-entries/style_rule/STYLE_KNOWLEDGE_E2E/workflow")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_items: [
                {
                  review_id: "review_knowledge_style_rule",
                  status: "pending",
                  materialize_status: "pending",
                },
              ],
              jobs: [],
              human_review_events: [],
              target_activity_groups: [],
              recommended_primary_action: {
                kind: "review",
                action: "approve_review",
                review_id: "review_knowledge_style_rule",
                label: "Approve",
              },
            },
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries/style_rule/STYLE_KNOWLEDGE_E2E")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              object_type: "style_rule",
              lineage_key: "STYLE_KNOWLEDGE_E2E",
              status: "candidate",
              active_version: null,
              candidate_version: {
                review_id: "review_knowledge_style_rule",
                text: "keep the reunion tight and gesture-led",
                scope: "global",
                scope_ref_id: "global",
              },
              versions: [],
              runtime_refs: { mode: "pending_review" },
              review_refs: ["review_knowledge_style_rule"],
              bundle_refs: [],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    await store.selectItem("style_rule", "STYLE_KNOWLEDGE_E2E");

    expect(store.detail).toEqual(
      expect.objectContaining({
        object_type: "style_rule",
        lineage_key: "STYLE_KNOWLEDGE_E2E",
      }),
    );
    expect(store.detail.workflow.review_items[0].review_id).toBe("review_knowledge_style_rule");
  });

  it("approves, verifies, and releases the selected knowledge lineage while keeping detail refreshed", async () => {
    const store = useKnowledgeConsoleStore();
    let phase = "pending";

    function workflowDetail() {
      const base = {
        object_type: "calibration_line",
        lineage_key: "CAL_WORKFLOW",
        status: phase === "released" ? "active" : "candidate",
        active_version:
          phase === "released"
            ? {
                row_id: "calibration_line_CAL_WORKFLOW_v1",
                version: 1,
                text: "the gate sighed shut on the unfinished question",
                scope: "global",
                scope_ref_id: "global",
              }
            : null,
        candidate_version:
          phase === "released"
            ? null
            : {
                review_id: "review_workflow_calibration",
                text: "the gate sighed shut on the unfinished question",
                scope: "global",
                scope_ref_id: "global",
              },
        versions:
          phase === "pending"
            ? []
            : [
                {
                  row_id: "calibration_line_CAL_WORKFLOW_v1",
                  version: 1,
                  text: "the gate sighed shut on the unfinished question",
                },
              ],
        runtime_refs:
          phase === "pending"
            ? { mode: "pending_review" }
            : {
                mode: "vector",
                alias_scope: "calibration_line:global:global",
                active_alias: phase === "released" ? "calibration_line_global_global__candidate__calibration_line_CAL_WORKFLOW_v1" : null,
                candidate_alias:
                  phase === "released" ? null : "calibration_line_global_global__candidate__calibration_line_CAL_WORKFLOW_v1",
                verify_status: phase === "verified" || phase === "released" ? "succeeded" : "pending",
              },
        review_refs: ["review_workflow_calibration"],
        bundle_refs: [],
      };

      if (phase === "pending") {
        return {
          ...base,
          workflow: {
            review_items: [
              {
                review_id: "review_workflow_calibration",
                status: "pending",
                materialize_status: "pending",
                approved_item_row_id: null,
              },
            ],
            jobs: [],
            human_review_events: [],
            target_activity_groups: [],
            recommended_primary_action: {
              kind: "review",
              action: "approve_review",
              review_id: "review_workflow_calibration",
              label: "Approve",
              target_ref: "review_item:review_workflow_calibration",
            },
          },
        };
      }

      if (phase === "approved") {
        return {
          ...base,
          workflow: {
            review_items: [
              {
                review_id: "review_workflow_calibration",
                status: "approved",
                materialize_status: "succeeded",
                approved_item_row_id: "calibration_line_CAL_WORKFLOW_v1",
              },
            ],
            jobs: [
              {
                job_id: "reindex_review_workflow_calibration",
                review_id: "review_workflow_calibration",
                status: "succeeded",
                job_type: "reindex",
                target_ref: "reindex_job:reindex_review_workflow_calibration",
              },
              {
                job_id: "verify_review_workflow_calibration",
                review_id: "review_workflow_calibration",
                status: "queued",
                job_type: "verify",
                target_ref: "verify_job:verify_review_workflow_calibration",
              },
            ],
            human_review_events: [],
            target_activity_groups: [],
            recommended_primary_action: {
              kind: "verify_job",
              action: "retry_verify",
              job_id: "verify_review_workflow_calibration",
              label: "Retry Verify",
              target_ref: "verify_job:verify_review_workflow_calibration",
            },
          },
        };
      }

      if (phase === "verified") {
        return {
          ...base,
          workflow: {
            review_items: [
              {
                review_id: "review_workflow_calibration",
                status: "approved",
                materialize_status: "succeeded",
                approved_item_row_id: "calibration_line_CAL_WORKFLOW_v1",
              },
            ],
            jobs: [
              {
                job_id: "reindex_review_workflow_calibration",
                review_id: "review_workflow_calibration",
                status: "succeeded",
                job_type: "reindex",
                target_ref: "reindex_job:reindex_review_workflow_calibration",
              },
              {
                job_id: "verify_review_workflow_calibration",
                review_id: "review_workflow_calibration",
                status: "succeeded",
                job_type: "verify",
                target_ref: "verify_job:verify_review_workflow_calibration",
              },
            ],
            human_review_events: [],
            target_activity_groups: [],
            recommended_primary_action: {
              kind: "review",
              action: "release_review",
              review_id: "review_workflow_calibration",
              label: "Release",
              target_ref: "review_item:review_workflow_calibration",
            },
          },
        };
      }

      return {
        ...base,
        workflow: {
          review_items: [
            {
              review_id: "review_workflow_calibration",
              status: "approved",
              materialize_status: "succeeded",
              approved_item_row_id: "calibration_line_CAL_WORKFLOW_v1",
            },
          ],
          jobs: [
            {
              job_id: "reindex_review_workflow_calibration",
              review_id: "review_workflow_calibration",
              status: "succeeded",
              job_type: "reindex",
              target_ref: "reindex_job:reindex_review_workflow_calibration",
            },
            {
              job_id: "verify_review_workflow_calibration",
              review_id: "review_workflow_calibration",
              status: "succeeded",
              job_type: "verify",
              target_ref: "verify_job:verify_review_workflow_calibration",
            },
          ],
          human_review_events: [],
          target_activity_groups: [],
          recommended_primary_action: null,
        },
      };
    }

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes("/api/v1/knowledge-entries/calibration_line/CAL_WORKFLOW/workflow")) {
        const detail = workflowDetail();
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: detail.workflow,
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries/calibration_line/CAL_WORKFLOW")) {
        const detail = workflowDetail();
        const { workflow, ...entry } = detail;
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: entry,
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  object_type: "calibration_line",
                  lineage_key: "CAL_WORKFLOW",
                  status: phase === "released" ? "active" : "candidate",
                  active_version:
                    phase === "released"
                      ? {
                          row_id: "calibration_line_CAL_WORKFLOW_v1",
                          version: 1,
                          text: "the gate sighed shut on the unfinished question",
                        }
                      : null,
                  candidate_version:
                    phase === "released"
                      ? null
                      : {
                          review_id: "review_workflow_calibration",
                          text: "the gate sighed shut on the unfinished question",
                        },
                  versions: [],
                  runtime_refs:
                    phase === "pending"
                      ? { mode: "pending_review" }
                      : { alias_scope: "calibration_line:global:global", mode: "vector" },
                  review_refs: ["review_workflow_calibration"],
                  bundle_refs: [],
                },
              ],
              supported_object_types: ["calibration_line"],
            },
          }),
        };
      }

      if (url.includes("/api/v1/review-items/review_workflow_calibration/approve")) {
        phase = "approved";
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_id: "review_workflow_calibration",
              actor_ref: "ops.duwei",
              approved_item_row_id: "calibration_line_CAL_WORKFLOW_v1",
            },
          }),
        };
      }

      if (url.includes("/api/v1/index/verify/verify_review_workflow_calibration/retry")) {
        phase = "verified";
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              job_id: "verify_review_workflow_calibration",
              status: "succeeded",
              actor_ref: "ops.duwei",
            },
          }),
        };
      }

      if (url.includes("/api/v1/review-items/review_workflow_calibration/release")) {
        phase = "released";
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_id: "review_workflow_calibration",
              released: true,
              actor_ref: "ops.duwei",
            },
          }),
        };
      }

      if (url.includes("/api/v1/review-items") && !options.method) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  review_id: "review_workflow_calibration",
                  item_type: "calibration_candidate",
                  candidate_text: "the gate sighed shut on the unfinished question",
                  candidate_payload_json: {
                    lineage_key: "CAL_WORKFLOW",
                    scope: "global",
                    scope_ref_id: "global",
                    text: "the gate sighed shut on the unfinished question",
                  },
                  status: phase === "pending" ? "pending" : "approved",
                  materialize_status: phase === "pending" ? "pending" : "succeeded",
                  target_collection: "calibration_lines",
                  approved_item_row_id: phase === "pending" ? null : "calibration_line_CAL_WORKFLOW_v1",
                },
              ],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    await store.load();
    await store.selectItem("calibration_line", "CAL_WORKFLOW");

    expect(store.detail.workflow.recommended_primary_action.action).toBe("approve_review");

    const approveMessage = await store.approveReview("review_workflow_calibration");
    expect(approveMessage).toContain("review_workflow_calibration");
    expect(approveMessage).toContain("ops.duwei");
    expect(store.detail.lineage_key).toBe("CAL_WORKFLOW");
    expect(store.detail.workflow.recommended_primary_action.action).toBe("retry_verify");

    const verifyMessage = await store.retryVerifyJob("verify_review_workflow_calibration");
    expect(verifyMessage).toContain("verify_review_workflow_calibration");
    expect(verifyMessage).toContain("ops.duwei");
    expect(store.detail.workflow.recommended_primary_action.action).toBe("release_review");

    const releaseMessage = await store.releaseReview("review_workflow_calibration");
    expect(releaseMessage).toContain("review_workflow_calibration");
    expect(releaseMessage).toContain("ops.duwei");
    expect(store.detail.lineage_key).toBe("CAL_WORKFLOW");
    expect(store.detail.active_version).toEqual(
      expect.objectContaining({
        row_id: "calibration_line_CAL_WORKFLOW_v1",
      }),
    );
    expect(store.detail.workflow.recommended_primary_action).toBeNull();
  });

  it("applies related human review actions from the workflow detail and refreshes the selected lineage", async () => {
    const store = useKnowledgeConsoleStore();
    let eventStatus = "needs_followup";

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.includes("/api/v1/knowledge-entries/style_observation/STY_WORKFLOW/workflow")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              review_items: [
                {
                  review_id: "review_workflow_style_observation",
                  status: "approved",
                  materialize_status: "succeeded",
                  approved_item_row_id: "style_observation_STY_WORKFLOW_v1",
                },
              ],
              jobs: [
                {
                  job_id: "verify_review_workflow_style_observation",
                  review_id: "review_workflow_style_observation",
                  status: "succeeded",
                  job_type: "verify",
                  target_ref: "verify_job:verify_review_workflow_style_observation",
                },
              ],
              human_review_events: [
                {
                  event_id: "human_review_workflow_style_observation",
                  status: eventStatus,
                  default_action: eventStatus === "resolved" ? "inspect" : "release_review",
                  allowed_actions_json: eventStatus === "resolved" ? ["inspect"] : ["inspect", "release_review"],
                  linked_target: {
                    target_type: "review_item",
                    target_id: "review_workflow_style_observation",
                    target_ref: "review_item:review_workflow_style_observation",
                  },
                  followup_target: eventStatus === "resolved"
                    ? null
                    : {
                        target_type: "review_item",
                        target_id: "review_workflow_style_observation",
                        target_ref: "review_item:review_workflow_style_observation",
                      },
                  replay_target: {
                    target_type: "verify_job",
                    target_id: "verify_review_workflow_style_observation",
                    target_ref: "verify_job:verify_review_workflow_style_observation",
                  },
                },
              ],
              target_activity_groups: [
                {
                  target: {
                    target_type: "review_item",
                    target_id: "review_workflow_style_observation",
                    target_ref: "review_item:review_workflow_style_observation",
                  },
                  latest_at: "2026-04-11T13:20:00+00:00",
                  activity_count: 1,
                  sources: ["recovery_timeline"],
                  activity_items: [],
                },
              ],
              recommended_primary_action:
                eventStatus === "resolved"
                  ? null
                  : {
                      kind: "human_review_event",
                      action: "release_review",
                      event_id: "human_review_workflow_style_observation",
                      label: "Release",
                      target_ref: "human_review_event:human_review_workflow_style_observation",
                    },
            },
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries/style_observation/STY_WORKFLOW")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              object_type: "style_observation",
              lineage_key: "STY_WORKFLOW",
              status: "candidate",
              active_version: null,
              candidate_version: {
                review_id: "review_workflow_style_observation",
                text: "hold the last line on a half-finished breath",
              },
              versions: [
                {
                  row_id: "style_observation_STY_WORKFLOW_v1",
                  version: 1,
                  text: "hold the last line on a half-finished breath",
                },
              ],
              runtime_refs: {
                mode: "vector",
                alias_scope: "style_observation:global:global",
                verify_status: "succeeded",
              },
              review_refs: ["review_workflow_style_observation"],
              bundle_refs: [],
            },
          }),
        };
      }

      if (url.includes("/api/v1/knowledge-entries")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  object_type: "style_observation",
                  lineage_key: "STY_WORKFLOW",
                  status: "candidate",
                  active_version: null,
                  candidate_version: {
                    review_id: "review_workflow_style_observation",
                    text: "hold the last line on a half-finished breath",
                  },
                  versions: [],
                  runtime_refs: { alias_scope: "style_observation:global:global", mode: "vector" },
                  review_refs: ["review_workflow_style_observation"],
                  bundle_refs: [],
                },
              ],
              supported_object_types: ["style_observation"],
            },
          }),
        };
      }

      if (url.includes("/api/v1/human-review-events/human_review_workflow_style_observation/actions")) {
        eventStatus = "resolved";
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              event_id: "human_review_workflow_style_observation",
              action: "release_review",
              status: "resolved",
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });

    await store.load();
    await store.selectItem("style_observation", "STY_WORKFLOW");

    const message = await store.actOnHumanReviewEvent(
      "human_review_workflow_style_observation",
      "release_review",
    );

    expect(message).toContain("human_review_workflow_style_observation");
    expect(message).toContain("resolved");
    expect(store.detail.lineage_key).toBe("STY_WORKFLOW");
    expect(store.detail.workflow.human_review_events[0]).toEqual(
      expect.objectContaining({
        status: "resolved",
      }),
    );
    expect(store.detail.workflow.recommended_primary_action).toBeNull();
  });
});

describe("scene workbench source", () => {
  it("exposes a stable scene-card target for cross-view focus assertions", () => {
    const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(source).toContain("scene-workbench-scene-card");
  });

  it("passes the full scene-scoped human review list into the drawer", () => {
    const source = readFileSync(new URL("../src/views/SceneWorkbenchView.vue", import.meta.url), "utf8");

    expect(source).toContain(':items="workbench.humanReviewItems"');
    expect(source).not.toContain(".slice(0, 3)");
  });
});

describe("knowledge console source", () => {
  it("renders catalog filters and detail reference sections", () => {
    const source = readFileSync(new URL("../src/views/KnowledgeConsoleView.vue", import.meta.url), "utf8");

    expect(source).toContain("knowledge-scope-filter");
    expect(source).toContain("knowledge-scope-ref-filter");
    expect(source).toContain("knowledge-status-filter");
    expect(source).toContain("knowledge-detail-drawer");
    expect(source).toContain("knowledge-detail-empty");
    expect(source).toContain("审核引用");
    expect(source).toContain("包引用");
    expect(source).toContain("knowledge-open-review-ref-");
    expect(source).toContain("knowledge-open-bundle-ref-");
    expect(source).toContain("打开场景工作台");
  });

  it("ships workflow status, actions, and related activity sections in the detail drawer", () => {
    const source = readFileSync(new URL("../src/views/KnowledgeConsoleView.vue", import.meta.url), "utf8");

    expect(source).toContain("流程状态");
    expect(source).toContain("knowledge-workflow-primary-action");
    expect(source).toContain("knowledge-approve-review-");
    expect(source).toContain("knowledge-retry-verify-");
    expect(source).toContain("knowledge-release-review-");
    expect(source).toContain("关联人工审核");
    expect(source).toContain("关联任务");
    expect(source).toContain("目标活动");
  });
});

describe("index console store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/runtime/recovery/sweep")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              reclaimed_jobs: 1,
              reclaimed_job_summaries: [
                {
                  job_id: "verify_job_reclaimable",
                  job_type: "verify",
                  alias_scope: "style_observation:global:global",
                  previous_worker_id: "verify-worker-stale",
                  attempt_no: 2,
                  previous_lease_expires_at: "2000-01-01T00:00:00+00:00",
                },
              ],
              failed_jobs: 1,
              failed_job_summaries: [
                {
                  job_id: "verify_job_failed_recent",
                  job_type: "verify",
                  alias_scope: "style_observation:global:global",
                  error_text: "candidate alias verify failed",
                  finished_at: "2026-04-09T16:05:00+00:00",
                },
              ],
              reclaimed_idempotency_keys: 1,
              failed_idempotency_keys: 1,
              reclaimed_idempotency_key_summaries: [
                {
                  idempotency_key: "approve-review-stale",
                  previous_worker_id: "http",
                  attempt_no: 2,
                  previous_lease_expires_at: "2000-01-01T00:00:00+00:00",
                },
              ],
              created_human_review_events: 1,
              created_human_review_event_ids: [
                "human_review_idempotency_recovery_approve-review-stale",
              ],
              actor_ref: "ops.duwei",
            },
          }),
        };
      }

      if (url.includes("/runtime/promotions/run-due")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              promoted: 1,
              promoted_review_ids: ["review_style_due_promotion"],
              promoted_alias_scopes: ["style_observation:global:global"],
              actor_ref: "ops.duwei",
            },
          }),
        };
      }

      if (url.includes("/vector-alias-scopes")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  alias_scope: "style_observation:global:global",
                  active_alias: "style_observation_global_global_candidate_v1",
                  candidate_alias: null,
                  verify_status: "succeeded",
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/jobs")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }

      if (url.includes("/target-activity-groups")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  target: {
                    target_type: "review_item",
                    target_id: "review_style_released",
                    target_ref: "review_item:review_style_released",
                  },
                  latest_at: "2026-04-10T01:40:00+00:00",
                  activity_count: 2,
                  sources: ["system_runtime", "recovery_timeline"],
                  activity_items: [
                    {
                      activity_key: "system_runtime:12",
                      source: "system_runtime",
                      timestamp: "2026-04-10T01:40:00+00:00",
                      actor_ref: "system/due_promotion",
                      label: "runtime_due_promotion",
                      status: null,
                      summary: "promoted verified future-effective candidate",
                      object_ref: "style_observation_STY_RELEASED_v1",
                      target_refs: [
                        {
                          target_type: "review_item",
                          target_id: "review_style_released",
                          target_ref: "review_item:review_style_released",
                        },
                      ],
                    },
                    {
                      activity_key: "recovery_timeline:human_review_idempotency_recovery_release-review-stale",
                      source: "recovery_timeline",
                      timestamp: "2026-04-10T01:35:00+00:00",
                      actor_ref: "ops.duwei",
                      label: "release_review",
                      status: "resolved",
                      summary: "review released and active alias promoted",
                      object_ref: "release-review-stale",
                      target_refs: [
                        {
                          target_type: "review_item",
                          target_id: "review_style_released",
                          target_ref: "review_item:review_style_released",
                        },
                      ],
                    },
                  ],
                },
                {
                  target: {
                    target_type: "review_item",
                    target_id: "review_style_pending",
                    target_ref: "review_item:review_style_pending",
                  },
                  latest_at: "2026-04-10T01:32:00+00:00",
                  activity_count: 2,
                  sources: ["operator_action", "recovery_timeline"],
                  activity_items: [],
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/activity-events?stream=recovery_timeline")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  event_id: "human_review_idempotency_recovery_approve-review-stale",
                  event_source: "idempotency_recovery",
                  status: "needs_followup",
                  last_action: "retry_request",
                  last_action_at: "2026-04-10T01:30:00+00:00",
                  last_actor_ref: "ops.duwei",
                  linked_target_ref: "review_item:review_style_pending",
                  resolution_reason: "review approved; verify job is ready to run",
                  followup_action: "retry_verify",
                  followup_target_ref: "verify_job:verify_review_style_pending",
                  default_action: "retry_verify",
                  details_json: {
                    linked_target_ref: "review_item:review_style_pending",
                    resolution_reason: "review approved; verify job is ready to run",
                    last_action: "retry_request",
                    last_action_at: "2026-04-10T01:30:00+00:00",
                  },
                },
                {
                  event_id: "human_review_idempotency_recovery_release-review-stale",
                  event_source: "idempotency_recovery",
                  status: "resolved",
                  last_action: "release_review",
                  last_action_at: "2026-04-10T01:35:00+00:00",
                  last_actor_ref: "ops.duwei",
                  linked_target_ref: "review_item:review_style_released",
                  resolution_reason: "review released and active alias promoted",
                  default_action: "inspect",
                  replay_target: {
                    target_type: "review_item",
                    target_id: "review_style_released",
                    target_ref: "review_item:review_style_released",
                  },
                  details_json: {
                    linked_target_ref: "review_item:review_style_released",
                    resolution_reason: "review released and active alias promoted",
                    last_action: "release_review",
                    last_action_at: "2026-04-10T01:35:00+00:00",
                  },
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/activity-events?stream=system_runtime")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  operation_id: 12,
                  event_type: "runtime_due_promotion",
                  object_ref: "style_observation_STY_RELEASED_v1",
                  actor_ref: "system/due_promotion",
                  summary: "promoted verified future-effective candidate",
                  created_at: "2026-04-10T01:40:00+00:00",
                  target_refs: [
                    {
                      target_type: "review_item",
                      target_id: "review_style_released",
                      target_ref: "review_item:review_style_released",
                    },
                  ],
                  payload_json: {
                    actor_ref: "system/due_promotion",
                    review_id: "review_style_released",
                  },
                },
                {
                  operation_id: 11,
                  event_type: "runtime_job_reclaimed",
                  object_ref: "verify_job_reclaimable",
                  actor_ref: "system/recovery_sweep",
                  summary: "reclaimed stale verify lease",
                  created_at: "2026-04-10T01:20:00+00:00",
                  target_refs: [
                    {
                      target_type: "verify_job",
                      target_id: "verify_job_reclaimable",
                      target_ref: "verify_job:verify_job_reclaimable",
                    },
                  ],
                  payload_json: {
                    actor_ref: "system/recovery_sweep",
                    job_id: "verify_job_reclaimable",
                  },
                },
              ],
            },
          }),
        };
      }

      if (url.includes("/activity-events?stream=operator_action")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [
                {
                  operation_id: 13,
                  event_type: "human_review_action",
                  event_id: "human_review_idempotency_recovery_approve-review-stale",
                  object_ref: "human_review_idempotency_recovery_approve-review-stale",
                  actor_ref: "ops.duwei",
                  action: "retry_verify",
                  status_before: "needs_followup",
                  status_after: "needs_followup",
                  resolution_reason: "verify succeeded but review still awaits manual release",
                  created_at: "2026-04-10T01:32:00+00:00",
                  target_refs: [
                    {
                      target_type: "human_review_event",
                      target_id: "human_review_idempotency_recovery_approve-review-stale",
                      target_ref: "human_review_event:human_review_idempotency_recovery_approve-review-stale",
                    },
                    {
                      target_type: "review_item",
                      target_id: "review_style_pending",
                      target_ref: "review_item:review_style_pending",
                    },
                    {
                      target_type: "verify_job",
                      target_id: "verify_review_style_pending",
                      target_ref: "verify_job:verify_review_style_pending",
                    },
                  ],
                  payload_json: {
                    actor_ref: "ops.duwei",
                    action: "retry_verify",
                  },
                },
              ],
            },
          }),
        };
      }

      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("runs due promotions and refreshes the index console state", async () => {
    const store = useIndexConsoleStore();

    await store.load();
    await store.ensureActivityLoaded();
    vi.clearAllMocks();

    const message = await store.runDuePromotions();

    expect(message).toContain("1");
    expect(message).toContain("ops.duwei");
    expect(store.lastPromotionResult.promoted).toBe(1);
    expect(store.lastPromotionResult.actor_ref).toBe("ops.duwei");
    expect(store.aliasScopes).toHaveLength(1);
    expect(store.recoveryTimelineItems).toHaveLength(2);
    expect(store.systemRuntimeTimelineItems).toHaveLength(2);
    expect(store.operatorActionTimelineItems).toHaveLength(1);
    expect(store.targetActivityGroups).toHaveLength(2);
    expect(store.targetActivityGroups[0]).toEqual(
      expect.objectContaining({
        target: expect.objectContaining({
          target_type: "review_item",
          target_id: "review_style_released",
        }),
        activity_count: 2,
      }),
    );
    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        action: "release_review",
        status: "resolved",
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledTimes(7);
  });

  it("runs recovery sweep, keeps the latest receipt, and refreshes the index console state", async () => {
    const store = useIndexConsoleStore();

    await store.load();
    await store.ensureActivityLoaded();
    vi.clearAllMocks();

    const message = await store.runRecovery();

    expect(message).toContain("已执行恢复扫描");
    expect(store.lastRecoveryResult.reclaimed_jobs).toBe(1);
    expect(store.lastRecoveryResult.actor_ref).toBe("ops.duwei");
    expect(store.lastRecoveryResult.failed_job_summaries).toHaveLength(1);
    expect(store.lastRecoveryResult.failed_job_summaries[0].job_id).toBe("verify_job_failed_recent");
    expect(store.lastRecoveryResult.reclaimed_idempotency_key_summaries).toHaveLength(1);
    expect(store.lastRecoveryResult.created_human_review_event_ids).toEqual([
      "human_review_idempotency_recovery_approve-review-stale",
    ]);
    expect(store.aliasScopes).toHaveLength(1);
    expect(store.recoveryTimelineItems[0]).toEqual(
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_release-review-stale",
        status: "resolved",
      }),
    );
    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_release-review-stale",
        action: "release_review",
        replay_target: expect.objectContaining({
          target_type: "review_item",
          target_id: "review_style_released",
        }),
      }),
    );
    expect(store.systemRuntimeTimelineItems[0]).toEqual(
      expect.objectContaining({
        event_type: "runtime_due_promotion",
        actor_ref: "system/due_promotion",
        target_refs: [
          expect.objectContaining({
            target_type: "review_item",
            target_id: "review_style_released",
          }),
        ],
      }),
    );
    expect(store.operatorActionTimelineItems[0]).toEqual(
      expect.objectContaining({
        action: "retry_verify",
        actor_ref: "ops.duwei",
        target_refs: expect.arrayContaining([
          expect.objectContaining({
            target_type: "verify_job",
            target_id: "verify_review_style_pending",
          }),
        ]),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledTimes(7);
  });

  it("rehydrates the latest recovery follow-up receipt from the backend activity streams", async () => {
    const store = useIndexConsoleStore();

    await store.load();

    expect(store.lastRecoveryActionResult).toBeNull();
    expect(store.recoveryTimelineItems).toHaveLength(0);
    expect(store.systemRuntimeTimelineItems).toHaveLength(0);
    expect(store.operatorActionTimelineItems).toHaveLength(0);
    expect(store.targetActivityGroups).toHaveLength(0);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);

    await store.ensureActivityLoaded();

    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        event_id: "human_review_idempotency_recovery_release-review-stale",
        action: "release_review",
        actor_ref: "ops.duwei",
        linked_target_ref: "review_item:review_style_released",
        replay_target: expect.objectContaining({
          target_type: "review_item",
          target_id: "review_style_released",
        }),
      }),
    );
    expect(store.recoveryTimelineItems).toHaveLength(2);
    expect(store.systemRuntimeTimelineItems).toHaveLength(2);
    expect(store.operatorActionTimelineItems).toHaveLength(1);
    expect(store.targetActivityGroups).toHaveLength(2);
    expect(globalThis.fetch).toHaveBeenCalledTimes(6);
  });

  it("records the latest recovery follow-up action receipt", () => {
    const store = useIndexConsoleStore();

    store.recordRecoveryAction({
      event_id: "human_review_idempotency_recovery_approve-review-stale",
      action: "retry_verify",
      status: "needs_followup",
      resolution_reason: "verify succeeded but review still awaits manual release",
      followup_action: "release_review",
      followup_target_ref: "review_item:review_style_pending",
      replay_target: {
        target_type: "verify_job",
        target_id: "verify_review_style_pending",
        target_ref: "verify_job:verify_review_style_pending",
      },
    });

    expect(store.lastRecoveryActionResult).toEqual(
      expect.objectContaining({
        action: "retry_verify",
        followup_action: "release_review",
        replay_target: expect.objectContaining({
          target_type: "verify_job",
          target_id: "verify_review_style_pending",
        }),
      }),
    );
  });

  it("includes the operator ref in verify retry notices", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/index/verify/verify_job_actor/retry")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              job_id: "verify_job_actor",
              status: "succeeded",
              actor_ref: "ops.duwei",
            },
          }),
        };
      }
      if (url.includes("/vector-alias-scopes")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }
      if (url.includes("/jobs")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }
      if (url.includes("/target-activity-groups")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: { items: [] },
          }),
        };
      }
      if (url.includes("/activity-events?stream=recovery_timeline")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [],
            },
          }),
        };
      }
      if (url.includes("/activity-events?stream=system_runtime")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [],
            },
          }),
        };
      }
      if (url.includes("/activity-events?stream=operator_action")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              items: [],
            },
          }),
        };
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    const store = useIndexConsoleStore();

    const message = await store.retryVerifyJob("verify_job_actor");

    expect(message).toContain("verify_job_actor");
    expect(message).toContain("ops.duwei");
  });
});
