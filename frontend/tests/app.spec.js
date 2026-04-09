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
});

describe("vue shell", () => {
  it("renders the three required views from the Vue shell", () => {
    const source = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

    expect(source).toContain("Scene Workbench");
    expect(source).toContain("Review Inbox");
    expect(source).toContain("Index Console");
  });
});
