import { existsSync, readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";

function ok(data) {
  return {
    ok: true,
    json: async () => ({ ok: true, data }),
  };
}

describe("system config api helpers", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn(async () => ok({}));
  });

  it("calls the system config endpoints with admin token where required", async () => {
    await api.fetchSystemConfig();
    await api.saveSystemConfigDraft({ category: "models", yaml_raw: "task_routing: {}\n" }, "admin-token");
    await api.activateSystemConfigSnapshot("config_models_001", "admin-token");
    await api.testSystemConfigProvider({ provider: "openai_compatible", base_url: "https://llm.example/v1" }, "admin-token");
    await api.exportSystemConfigCategory("models");

    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/system-config");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/system-config/drafts",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Admin-Token": "admin-token" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/system-config/config_models_001/activate",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Admin-Token": "admin-token" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/system-config/test-provider",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Admin-Token": "admin-token" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/system-config/export/models");
  });
});

describe("system config store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/system-config") && !options.method) {
        return ok({
          runtime: { admin_configured: true, secret_configured: true },
          categories: {
            models: {
              category: "models",
              source: "repo_default",
              yaml_raw: "task_routing: {}\nretry_budget: {}\njob_runtime: {}\n",
              parsed: {},
              validation: { ok: true, message: "models config is valid" },
              active_snapshot: null,
            },
          },
          history: [],
        });
      }
      if (url.endsWith("/api/v1/system-config/drafts") && options.method === "POST") {
        expect(options.headers["X-Admin-Token"]).toBe("admin-token");
        return ok({
          snapshot: {
            snapshot_id: "config_models_001",
            category: "models",
            version: 1,
            validation: { ok: true, message: "models config is valid" },
            active: false,
          },
        });
      }
      if (url.endsWith("/api/v1/system-config/config_models_001/activate")) {
        expect(options.headers["X-Admin-Token"]).toBe("admin-token");
        return ok({
          snapshot: {
            snapshot_id: "config_models_001",
            category: "models",
            version: 1,
            active: true,
          },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
  });

  it("loads category YAML and saves then activates a config snapshot", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    await store.load();
    store.setAdminToken("admin-token");
    store.selectCategory("models");
    store.editorYaml = "task_routing: {}\nretry_budget: {}\njob_runtime: {}\n";

    const draftMessage = await store.saveDraft();
    const activateMessage = await store.activateSnapshot("config_models_001");

    expect(store.selectedCategory).toBe("models");
    expect(store.editorYaml).toContain("task_routing");
    expect(draftMessage).toContain("config_models_001");
    expect(activateMessage).toContain("config_models_001");
    expect(store.lastDraft.snapshot_id).toBe("config_models_001");
    expect(store.lastActivated.active).toBe(true);
  });
});

describe("system config shell registration", () => {
  it("registers the system config view and store", () => {
    const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");

    expect(appSource).toContain("SystemConfigView");
    expect(routerSource).toContain('id: "config"');
    expect(routerSource).toContain('label: "系统配置"');
    expect(existsSync(new URL("../src/stores/systemConfig.js", import.meta.url))).toBe(true);
    expect(existsSync(new URL("../src/views/SystemConfigView.vue", import.meta.url))).toBe(true);
  });
});
