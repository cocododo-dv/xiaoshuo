import { readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkbenchStore } from "../src/stores/workbench";

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

  it("runs a full scene and refreshes the workbench state", async () => {
    globalThis.fetch = vi.fn(async (url) => {
      if (url.includes("/run/full")) {
        return {
          ok: true,
          json: async () => ({
            ok: true,
            data: {
              scene_status: "archived",
              current_bundle_id: "bundle_CH001_SC01",
              current_bundle_hash: "hash_123",
              current_final_scene_row_id: "final_scene_CH001_SC01",
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
            data: { items: [] },
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
    expect(globalThis.fetch).toHaveBeenCalledTimes(3);
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
      if (url.includes("/run/full")) {
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

    expect(source).toContain("Scene Workbench");
    expect(source).toContain("Review Inbox");
    expect(source).toContain("Index Console");
  });
});
