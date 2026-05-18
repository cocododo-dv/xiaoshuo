import { existsSync, readFileSync } from "node:fs";

import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../src/lib/api";
import { buildLiteraryEvalCaseRows } from "../src/lib/literaryEvalSummary";

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
    await api.fetchLlmConfig();
    await api.saveLlmProviderConfig(
      {
        provider_id: "openai_primary",
        provider_type: "openai",
        base_url: "https://api.openai.example/v1",
        api_key: "sk-secret",
      },
      "admin-token",
    );
    await api.setDefaultLlmProvider("openai_primary", "admin-token");
    await api.saveLlmNodeRoutes(
      {
        activate: true,
        node_routing: {
          neutral_draft: {
            provider: "openai",
            provider_id: "openai_primary",
            model: "gpt-5.4",
            temperature: 0.2,
            max_output_tokens: 3000,
            response_format: "json_object",
            reasoning_level: "medium",
          },
        },
      },
      "admin-token",
    );
    await api.syncMissingLlmNodeRoutes({ activate: true }, "admin-token");
    await api.probeLlmProvider("openai_primary", {}, "admin-token");
    await api.exportSystemConfigCategory("models");
    await api.fetchLiteraryEvalLatest();
    await api.runLiteraryEval({ mode: "baseline" });
    await api.runLiteraryEval({ mode: "live", model: "writer-live-model" });
    await api.fetchStyleProfileContract();
    await api.extractStyleProfile({ sample_texts: ["short rhythm and dialogue pressure"] });
    await api.submitStyleProfileCandidate({
      profile_yaml: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
    });

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
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/literary-eval/latest");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/literary-eval/run",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Idempotency-Key": expect.any(String) }),
        body: JSON.stringify({ mode: "baseline" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/system-config/llm");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/system-config/llm/providers",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Admin-Token": "admin-token" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/system-config/llm/providers/openai_primary/default",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Admin-Token": "admin-token" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/system-config/llm/node-routes",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Admin-Token": "admin-token" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/system-config/llm/node-routes/sync-missing",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Admin-Token": "admin-token" }),
        body: JSON.stringify({ activate: true }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/system-config/llm/providers/openai_primary/probe",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Admin-Token": "admin-token" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/literary-eval/run",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Idempotency-Key": expect.any(String) }),
        body: JSON.stringify({ mode: "live", model: "writer-live-model" }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/style-profile/contract");
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/style-profile/extract",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Idempotency-Key": expect.any(String) }),
        body: JSON.stringify({ sample_texts: ["short rhythm and dialogue pressure"] }),
      }),
    );
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/api/v1/style-profile/review-candidate",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-Idempotency-Key": expect.any(String) }),
        body: JSON.stringify({
          profile_yaml: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
        }),
      }),
    );
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
      if (url.endsWith("/api/v1/system-config/llm") && !options.method) {
        return ok({
          provider_catalog: {
            openai_compatible: {
              label: "本地 / OpenAI 兼容",
              credential_modes: ["none", "api_key"],
              default_base_url: "http://127.0.0.1:11434/v1",
            },
            openai: { label: "OpenAI", credential_modes: ["api_key"] },
            gemini: { label: "Gemini / Google", credential_modes: ["api_key"] },
          },
          providers: {
            openai_primary: {
              provider_id: "openai_primary",
              provider_type: "openai",
              account_id: "acct_ops",
              base_url: "https://api.openai.example/v1",
              enabled: true,
              credential_mode: "api_key",
              api_mode: "responses",
              models: ["gpt-5.4"],
              secret: { configured: true, hint: "sk-...test" },
            },
          },
          default_provider_id: "openai_primary",
          node_routes: {
            neutral_draft: {
              node_id: "neutral_draft",
              status: "active",
              configured: true,
              provider: "openai",
              provider_id: "openai_primary",
              account_id: "acct_ops",
              model: "gpt-5.4",
              temperature: 0.2,
              max_output_tokens: 3000,
              response_format: "json_object",
              reasoning_level: "medium",
            },
            chapter_summary: {
              node_id: "chapter_summary",
              status: "reserved",
              configured: false,
            },
          },
        });
      }
      if (url.endsWith("/api/v1/system-config/llm/providers") && options.method === "POST") {
        const body = JSON.parse(options.body);
        if (body.provider_id === "local_ollama") {
          expect(body.provider_type).toBe("openai_compatible");
          expect(body.credential_mode).toBe("none");
          expect(body.base_url).toBe("http://127.0.0.1:11434/v1");
          expect(body.api_key).toBeUndefined();
        } else if (body.provider_id === "local_qwen") {
          expect(body.provider_type).toBe("openai_compatible");
          expect(body.credential_mode).toBe("none");
          expect(body.base_url).toBe("http://127.0.0.1:8080/v1");
          expect(body.models).toEqual(["Qwen3-14B-Q8_0.gguf"]);
          expect(body.api_key).toBeUndefined();
        } else {
          expect(body.api_key).toBe("sk-secret");
        }
        return ok({
          provider: {
            provider_id: body.provider_id,
            provider_type: body.provider_type,
            base_url: body.base_url,
            credential_mode: body.credential_mode || "api_key",
            models: body.models || [],
            secret:
              body.credential_mode === "none"
                ? { configured: false, secret_type: "none" }
                : { configured: true, hint: "sk-...cret" },
          },
        });
      }
      if (url.endsWith("/api/v1/system-config/llm/node-routes") && options.method === "POST") {
        const body = JSON.parse(options.body);
        return ok({
          snapshot: {
            snapshot_id: "config_models_llm_001",
            active: Boolean(body.activate),
            parsed: body,
          },
        });
      }
      if (url.endsWith("/api/v1/system-config/llm/node-routes/sync-missing") && options.method === "POST") {
        return ok({
          snapshot: {
            snapshot_id: "config_models_sync_001",
            active: true,
          },
          synced_node_ids: ["project_outline_plan", "writer_deep_review"],
        });
      }
      if (url.endsWith("/api/v1/system-config/llm/providers/openai_primary/probe") && options.method === "POST") {
        return ok({ ok: true, status_code: 200, latency_ms: 42, message: "provider probe succeeded" });
      }
      if (url.endsWith("/api/v1/system-config/llm/providers/local_qwen/probe") && options.method === "POST") {
        const body = JSON.parse(options.body);
        expect(body).toEqual({ model: "qwen3:14b", check_completion: true });
        return ok({
          ok: true,
          status_code: 200,
          latency_ms: 36,
          message: "模型 qwen3:14b 可用：连接、模型名、生成均通过",
          checks: {
            connection: { ok: true },
            model: { ok: true, requested_model: "qwen3:14b" },
            completion: { ok: true },
          },
        });
      }
      if (url.endsWith("/api/v1/literary-eval/latest") && !options.method) {
        return ok({ report: null });
      }
      if (url.endsWith("/api/v1/literary-eval/run") && options.method === "POST") {
        const body = JSON.parse(options.body);
        return ok({
          report: {
            mode: body.mode || "baseline",
            model: body.model || null,
            suite_id: "literary_small_v1",
            summary: {
              case_count: 3,
              passed_count: 2,
              failed_count: 1,
              mean_score: 0.82,
              pass_threshold: 0.72,
            },
            cases: [
              {
                case_id: "style-pressure-001",
                title: "压迫感转场",
                prompt: "写一个带有压迫感的转场。",
                generated_text: "门轴轻响，灯线压低，所有人都停在同一口气里。",
                score: 0.64,
                passed: false,
                dimensions: {
                  required_terms: 0.5,
                  style_cues: 0.5,
                  banned_terms: 1,
                  length: 0.7,
                },
                issues: ["missing required term: corridor", "style cue not present: delayed sentence release"],
              },
              {
                case_id: "dialogue-silence-001",
                title: "对白留白",
                prompt: "写一段少对白的冲突。",
                generated_text: "她没有回答，只把杯沿转向窗外。",
                score: 0.93,
                passed: true,
                dimensions: {
                  required_terms: 1,
                  style_cues: 1,
                  banned_terms: 1,
                  length: 0.72,
                },
                issues: [],
              },
            ],
          },
        });
      }
      if (url.endsWith("/api/v1/style-profile/contract") && !options.method) {
        return ok({
          contract_version: "STYLE_FEATURE_CONTRACT_v1",
          feature_names: ["rhythm", "syntax", "dialogue_ratio"],
          example_yaml: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
        });
      }
      if (url.endsWith("/api/v1/style-profile/extract") && options.method === "POST") {
        return ok({
          profile: {
            contract_version: "STYLE_FEATURE_CONTRACT_v1",
            features: {
              rhythm: { guidance: ["short rhythm and dialogue pressure"] },
            },
          },
          profile_yaml: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
        });
      }
      if (url.endsWith("/api/v1/style-profile/review-candidate") && options.method === "POST") {
        const body = JSON.parse(options.body);
        expect(body.profile_yaml).toContain("style_profile:");
        return ok({
          review: {
            review_id: "review_style_profile_global_global_abc123",
            item_type: "style_rule_set",
            target_collection: "style_rules",
            status: "pending",
            candidate_text: body.profile_yaml,
            candidate_payload_json: {
              lineage_key: "style_profile_global_global",
              source: "style_profile_extract",
            },
          },
          target: {
            target_ref: "review_item:review_style_profile_global_global_abc123",
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

  it("probes the currently configured api base without requiring an admin token", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    store.updateApiBase("http://127.0.0.1:8010");
    const message = await store.probeApiBase();

    expect(message).toContain("http://127.0.0.1:8010");
    expect(store.apiBaseProbe.ok).toBe(true);
    expect(store.apiBaseProbe.url).toBe("http://127.0.0.1:8010");
    expect(store.apiBaseProbe.runtime.admin_configured).toBe(true);
    expect(globalThis.fetch).toHaveBeenCalledWith("http://127.0.0.1:8010/api/v1/system-config");
  });

  it("loads llm provider config and saves provider, node routes, and probes", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");

    await store.loadLlmConfig();
    store.providerDraft = {
      provider_id: "openai_primary",
      provider_type: "openai",
      account_id: "acct_ops",
      base_url: "https://api.openai.example/v1",
      credential_mode: "api_key",
      modelsText: "gpt-5.4\n",
      api_key: "sk-secret",
    };
    const providerMessage = await store.saveLlmProvider();
    store.nodeRouteDrafts.neutral_draft.model = "gpt-5.4-mini";
    store.nodeRouteDrafts.neutral_draft.reasoning_level = "high";
    const routeMessage = await store.saveLlmNodeRoutes();
    const probeMessage = await store.probeLlmProvider("openai_primary");
    expect(store.llm.providers.openai_primary.secret.hint).toBe("sk-...test");
    expect(store.defaultProviderId).toBe("openai_primary");
    expect(store.nodeRouteRows.some((row) => row.node_id === "chapter_summary" && row.status === "reserved")).toBe(true);
    expect(store.configDashboardSummary).toEqual({
      providerCount: 1,
      configuredNodeCount: 1,
      missingActiveRouteCount: 0,
      activeNodeCount: 1,
      blockedNodeCount: 0,
      reservedNodeCount: 1,
      needsProvider: false,
      needsActiveRoutes: false,
      needsRouteProviders: false,
    });
    expect(providerMessage).toContain("openai_primary");
    expect(routeMessage).toContain("config_models_llm_001");
    expect(probeMessage).toContain("成功");
    expect(store.providerDraft.api_key).toBe("");
  });

  it("uses backend node catalog ordering and syncs missing active routes", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");
    let syncCalled = false;
    const llmPayload = {
      provider_catalog: {},
      default_provider_id: "local_qwen",
      providers: {
        local_qwen: {
          provider_id: "local_qwen",
          provider_type: "openai_compatible",
          account_id: "local",
          base_url: "http://127.0.0.1:8080/v1",
          enabled: true,
          credential_mode: "none",
          api_mode: "chat",
          models: ["qwen3:14b"],
          secret: { configured: false, secret_type: "none" },
        },
      },
      node_catalog: {
        project_outline_plan: {
          node_id: "project_outline_plan",
          label: "Project outline plan",
          group: "project",
          status: "active",
          requires_llm: true,
          order: 0,
        },
        neutral_draft: {
          node_id: "neutral_draft",
          label: "Neutral draft",
          group: "scene_generation",
          status: "active",
          requires_llm: true,
          order: 1,
        },
        chapter_summary: {
          node_id: "chapter_summary",
          label: "Chapter summary",
          group: "local",
          status: "reserved",
          requires_llm: false,
          order: 2,
        },
      },
      node_routes: {
        project_outline_plan: {
          node_id: "project_outline_plan",
          status: "active",
          group: "project",
          configured: false,
          requires_llm: true,
          ready: false,
          readiness_reason: "not_configured",
        },
        neutral_draft: {
          node_id: "neutral_draft",
          status: "active",
          group: "scene_generation",
          configured: true,
          requires_llm: true,
          provider: "openai_compatible",
          provider_id: "local_qwen",
          model: "qwen3:14b",
          temperature: 0.6,
          max_output_tokens: 6000,
          response_format: "json_object",
          reasoning_level: "medium",
          ready: true,
        },
        chapter_summary: {
          node_id: "chapter_summary",
          status: "reserved",
          group: "local",
          configured: false,
          requires_llm: false,
        },
      },
      missing_active_routes: ["project_outline_plan"],
      blocked_routes: [],
    };
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/system-config/llm") && !options.method) {
        return ok(llmPayload);
      }
      if (url.endsWith("/api/v1/system-config") && !options.method) {
        return ok({
          runtime: { admin_configured: true },
          categories: { models: { parsed: {} } },
          history: [],
        });
      }
      if (url.endsWith("/api/v1/system-config/llm/node-routes/sync-missing") && options.method === "POST") {
        syncCalled = true;
        expect(JSON.parse(options.body)).toEqual({ activate: true });
        return ok({
          snapshot: { snapshot_id: "config_models_sync_001", active: true },
          synced_node_ids: ["project_outline_plan"],
        });
      }
      if (url.endsWith("/api/v1/system-config/llm/providers/local_qwen/probe") && options.method === "POST") {
        return ok({ ok: true, message: "provider probe succeeded" });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    await store.loadLlmConfig();

    expect(store.nodeRouteRows.map((row) => row.node_id)).toEqual([
      "project_outline_plan",
      "neutral_draft",
      "chapter_summary",
    ]);
    expect(store.nodeRouteRows[0]).toMatchObject({
      node_id: "project_outline_plan",
      group: "project",
      requires_llm: true,
      configured: false,
    });
    expect(store.configDashboardSummary.missingActiveRouteCount).toBe(1);

    const message = await store.syncMissingLlmNodeRoutes();

    expect(syncCalled).toBe(true);
    expect(message).toContain("Synced 1");
  });

  it("discovers provider models without blocking manual entry on failure", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");
    store.providerDraft = {
      provider_id: "local_qwen",
      provider_type: "openai_compatible",
      account_id: "local",
      base_url: "http://127.0.0.1:8080/v1",
      credential_mode: "none",
      api_mode: "chat",
      modelsText: "manual-model",
      api_key: "",
    };
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/system-config/test-provider") && options.method === "POST") {
        const body = JSON.parse(options.body);
        expect(body).toMatchObject({
          provider_id: "local_qwen",
          provider_type: "openai_compatible",
          base_url: "http://127.0.0.1:8080/v1",
          credential_mode: "none",
          check_completion: false,
        });
        return ok({
          ok: true,
          available_models: ["qwen3:14b", "假流式/qwen3:14b", "流式抗截断/llama3.1:8b"],
          checks: { connection: { ok: true } },
          message: "provider probe succeeded",
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const message = await store.discoverProviderDraftModels();

    expect(message).toContain("2");
    expect(store.providerDraft.modelsText).toBe("qwen3:14b\nllama3.1:8b");

    store.providerDraft.modelsText = "keep-this-model";
    globalThis.fetch = vi.fn(async () => {
      throw new Error("connect ECONNREFUSED");
    });

    const failure = await store.discoverProviderDraftModels();

    expect(failure).toContain("获取模型列表失败");
    expect(store.providerDraft.modelsText).toBe("keep-this-model");
    expect(store.llmActionTone).toBe("error");
  });

  it("keeps large discovered provider catalogs separate from configured models", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");
    store.llm.providers = {
      gcli2api: {
        provider_id: "gcli2api",
        provider_type: "openai",
        models: ["gemini-3.1-pro-preview", "gemini-3.1-flash-lite-preview"],
      },
    };
    store.providerDraft = {
      provider_id: "gcli2api",
      provider_type: "openai",
      account_id: "relay",
      base_url: "http://127.0.0.1:7861/v1",
      credential_mode: "api_key",
      api_mode: "responses",
      modelsText: Array.from({ length: 144 }, (_, index) => `legacy-model-${index}`).join("\n"),
      api_key: "",
    };
    const catalog = [
      "gemini-3.1-pro-preview",
      "gemini-3.1-flash-lite-preview",
      ...Array.from({ length: 142 }, (_, index) => `假流式/gemini-extra-${index}`),
    ];
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/system-config/test-provider") && options.method === "POST") {
        return ok({
          ok: true,
          available_models: catalog,
          checks: { connection: { ok: true } },
          message: "provider probe succeeded",
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const message = await store.discoverProviderDraftModels();

    expect(message).toContain("144");
    expect(message).toContain("2");
    expect(store.providerModelCatalogCount).toBe(144);
    expect(store.providerDraft.modelsText).toBe("gemini-3.1-pro-preview\ngemini-3.1-flash-lite-preview");
  });

  it("persists provider probe results and auto-probes with lightweight checks only", async () => {
    const storage = new Map();
    globalThis.window = {
      localStorage: {
        getItem: (key) => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: (key) => storage.delete(key),
      },
    };
    vi.resetModules();
    setActivePinia(createPinia());
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.runtime = { admin_configured: true };
    store.setAdminToken("admin-token");

    await store.loadLlmConfig();

    const autoProbeCall = globalThis.fetch.mock.calls.find(([url, options]) =>
      url.endsWith("/api/v1/system-config/llm/providers/openai_primary/probe") && options.method === "POST"
    );
    expect(JSON.parse(autoProbeCall[1].body)).toEqual({ model: "gpt-5.4", check_completion: false });
    expect(store.providerProbeResults.openai_primary.ok).toBe(true);

    vi.resetModules();
    setActivePinia(createPinia());
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/system-config/llm") && !options.method) {
        return ok({
          provider_catalog: {},
          default_provider_id: "openai_primary",
          providers: {
            openai_primary: {
              provider_id: "openai_primary",
              provider_type: "openai",
              account_id: "acct_ops",
              base_url: "https://api.openai.example/v1",
              enabled: true,
              credential_mode: "api_key",
              api_mode: "responses",
              models: ["gpt-5.4"],
              secret: { configured: true, hint: "sk-...test" },
            },
          },
          node_routes: {},
        });
      }
      throw new Error(`Unexpected fetch after persisted probe: ${url}`);
    });
    const { useSystemConfigStore: useReloadedSystemConfigStore } = await import("../src/stores/systemConfig");
    const reloaded = useReloadedSystemConfigStore();
    reloaded.runtime = { admin_configured: true };
    reloaded.setAdminToken("admin-token");

    await reloaded.loadLlmConfig();

    expect(reloaded.providerProbeResults.openai_primary.ok).toBe(true);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    delete globalThis.window;
  });

  it("sets default provider and infers node routes from selected accounts", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");
    await store.loadLlmConfig();
    store.llm.providers.openai_backup = {
      provider_id: "openai_backup",
      provider_type: "openai",
      account_id: "acct_backup",
      base_url: "https://api.openai.example/v1",
      enabled: true,
      credential_mode: "api_key",
      api_mode: "responses",
      models: ["gpt-5.4-mini", "gpt-5.4"],
      secret: { configured: true, hint: "sk-...test" },
    };
    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/system-config/llm/providers/openai_backup/default") && options.method === "POST") {
        return ok({
          default_provider_id: "openai_backup",
          snapshot: { snapshot_id: "config_api_default_001", active: true },
        });
      }
      if (url.endsWith("/api/v1/system-config/llm") && !options.method) {
        return ok({
          provider_catalog: {},
          default_provider_id: "openai_backup",
          providers: store.llm.providers,
          node_routes: store.llm.node_routes,
        });
      }
      return ok({});
    });

    const message = await store.setDefaultLlmProvider("openai_backup");
    store.setNodeRouteProvider("neutral_draft", "openai_backup");

    expect(message).toContain("openai_backup");
    expect(store.defaultProviderId).toBe("openai_backup");
    expect(store.nodeRouteDrafts.neutral_draft).toMatchObject({
      provider: "openai",
      provider_id: "openai_backup",
      account_id: "acct_backup",
      api_mode: "responses",
      credential_mode: "api_key",
      model: "gpt-5.4-mini",
    });
    expect(store.routeModelOptions("neutral_draft")).toEqual(["gpt-5.4-mini", "gpt-5.4"]);
  });

  it("applies batch node route edits only to active rows in the selected scope", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    await store.loadLlmConfig();
    store.llm.providers.local_qwen = {
      provider_id: "local_qwen",
      provider_type: "openai_compatible",
      account_id: "local",
      base_url: "http://127.0.0.1:8080/v1",
      enabled: true,
      credential_mode: "none",
      api_mode: "chat",
      models: ["qwen3:14b"],
      secret: { configured: false, secret_type: "none" },
    };
    store.nodeRouteDrafts.neutral_draft.provider_id = "";
    store.nodeRouteBatchDraft = {
      scope: "blocked",
      provider_id: "local_qwen",
      model: "qwen3:14b",
      reasoning_level: "low",
      temperature: 0.4,
      max_output_tokens: 2048,
      response_format: "json_object",
    };

    const message = store.applyNodeRouteBatch();

    expect(message).toContain("1");
    expect(store.nodeRouteDrafts.neutral_draft).toMatchObject({
      provider: "openai_compatible",
      provider_id: "local_qwen",
      account_id: "local",
      api_mode: "chat",
      credential_mode: "none",
      model: "qwen3:14b",
      reasoning_level: "low",
      temperature: 0.4,
      max_output_tokens: 2048,
    });
    expect(store.nodeRouteDrafts.chapter_summary.provider_id).not.toBe("local_qwen");
  });

  it("does not count provider-missing node routes as runnable active routes", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    globalThis.fetch = vi.fn(async (url) => {
      if (url.endsWith("/api/v1/system-config/llm")) {
        return ok({
          provider_catalog: {},
          providers: {},
          node_routes: {
            style_draft: {
              node_id: "style_draft",
              status: "active",
              configured: true,
              ready: false,
              provider_ready: false,
              provider_missing: true,
              provider: "openai_compatible",
              provider_id: "missing_qwen",
              model: "Qwen3-14B-Q8_0.gguf",
            },
            chapter_summary: {
              node_id: "chapter_summary",
              status: "reserved",
              configured: false,
              ready: false,
            },
          },
          readiness: {
            provider_count: 0,
            active_provider_count: 0,
            configured_route_count: 1,
            active_route_count: 1,
            ready_route_count: 0,
            blocked_route_count: 1,
            ready: false,
          },
        });
      }
      return ok({});
    });

    await store.loadLlmConfig();

    const styleDraftRow = store.nodeRouteRows.find((row) => row.node_id === "style_draft");
    expect(styleDraftRow.ready).toBe(false);
    expect(styleDraftRow.provider_missing).toBe(true);
    expect(store.configDashboardSummary).toMatchObject({
      providerCount: 0,
      configuredNodeCount: 1,
      activeNodeCount: 0,
      blockedNodeCount: 1,
      needsProvider: true,
      needsActiveRoutes: true,
      needsRouteProviders: true,
    });
  });

  it("recomputes draft route readiness when the selected provider or model changes", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    await store.loadLlmConfig();
    store.nodeRouteDrafts.neutral_draft.provider_id = "";
    let neutralDraftRow = store.nodeRouteRows.find((row) => row.node_id === "neutral_draft");
    expect(neutralDraftRow.ready).toBe(false);
    expect(neutralDraftRow.provider_missing).toBe(true);
    expect(store.configDashboardSummary).toMatchObject({
      providerCount: 1,
      activeNodeCount: 0,
      blockedNodeCount: 1,
      needsRouteProviders: true,
    });

    store.nodeRouteDrafts.neutral_draft.provider_id = "openai_primary";
    store.nodeRouteDrafts.neutral_draft.model = "not-listed";
    neutralDraftRow = store.nodeRouteRows.find((row) => row.node_id === "neutral_draft");
    expect(neutralDraftRow.ready).toBe(false);
    expect(neutralDraftRow.provider_missing).toBe(false);
    expect(neutralDraftRow.model_missing).toBe(true);
    expect(neutralDraftRow.readiness_reason).toContain("model_not_listed");
  });

  it("prefills a local OpenAI-compatible provider without sending an api key", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");

    await store.loadLlmConfig();
    store.applyLocalProviderPreset("ollama");
    const providerMessage = await store.saveLlmProvider();

    expect(store.providerDraft.provider_id).toBe("local_ollama");
    expect(store.providerDraft.provider_type).toBe("openai_compatible");
    expect(store.providerDraft.credential_mode).toBe("none");
    expect(store.providerDraft.base_url).toBe("http://127.0.0.1:11434/v1");
    expect(store.providerDraft.api_key).toBe("");
    expect(providerMessage).toContain("local_ollama");
  });

  it("prefills a CLIProxyAPI relay provider with api key mode and manual models", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    store.applyLocalProviderPreset("cli-proxy");

    expect(store.providerDraft.provider_id).toBe("cli_proxy");
    expect(store.providerDraft.provider_type).toBe("openai_compatible");
    expect(store.providerDraft.account_id).toBe("relay");
    expect(store.providerDraft.base_url).toBe("http://127.0.0.1:8317/v1");
    expect(store.providerDraft.credential_mode).toBe("api_key");
    expect(store.providerDraft.api_mode).toBe("chat");
    expect(store.providerDraft.modelsText).toBe("");
  });

  it("initializes the provider form from the configured local_qwen3 provider", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    globalThis.fetch = vi.fn(async (url) => {
      if (url.endsWith("/api/v1/system-config/llm")) {
        return ok({
          provider_catalog: {
            openai_compatible: {
              label: "本地 / OpenAI 兼容",
              credential_modes: ["none", "api_key"],
            },
          },
          providers: {
            local_qwen3: {
              provider_id: "local_qwen3",
              provider_type: "openai_compatible",
              account_id: "local",
              base_url: "http://127.0.0.1:8080/v1",
              enabled: true,
              credential_mode: "none",
              api_mode: "chat",
              models: ["qwen3"],
              secret: { configured: false, secret_type: "none" },
            },
          },
          node_routes: {
            neutral_draft: {
              node_id: "neutral_draft",
              status: "active",
              configured: true,
              provider: "openai_compatible",
              provider_id: "local_qwen3",
              model: "qwen3",
            },
          },
        });
      }
      return ok({});
    });

    await store.loadLlmConfig();

    expect(store.providerDraft.provider_id).toBe("local_qwen3");
    expect(store.providerDraft.base_url).toBe("http://127.0.0.1:8080/v1");
    expect(store.providerDraft.credential_mode).toBe("none");
    expect(store.providerDraft.modelsText).toBe("qwen3");
  });

  it("normalizes a pasted chat completions endpoint before saving a local provider", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");

    store.providerDraft = {
      provider_id: "local_qwen",
      provider_type: "openai_compatible",
      account_id: "local",
      base_url: "http://127.0.0.1:8080/v1/chat/completions",
      credential_mode: "none",
      api_mode: "chat",
      modelsText: "Qwen3-14B-Q8_0.gguf",
      api_key: "",
    };

    const providerMessage = await store.saveLlmProvider();

    expect(providerMessage).toContain("local_qwen");
  });

  it("allows local setup mode without an admin token and keeps inline save feedback", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.runtime = { admin_configured: false };
    expect(store.localSetupMessage).toContain("本地单机模式");
    expect(store.writeBlockedMessage).toBe("");

    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        ok: true,
        data: {
          provider: {
            provider_id: "local_qwen",
            provider_type: "openai_compatible",
            base_url: "http://127.0.0.1:8080/v1",
            credential_mode: "none",
            models: ["Qwen3-14B-Q8_0.gguf"],
            secret: { configured: false, secret_type: "none" },
          },
        },
      }),
    }));
    store.providerDraft = {
      provider_id: "local_qwen",
      provider_type: "openai_compatible",
      account_id: "local",
      base_url: "http://127.0.0.1:8080/v1",
      credential_mode: "none",
      api_mode: "chat",
      modelsText: "Qwen3-14B-Q8_0.gguf",
      api_key: "",
    };

    const message = await store.saveLlmProvider();

    expect(message).toContain("local_qwen");
    expect(store.llmActionMessage).toContain("local_qwen");
    expect(store.llmActionTone).toBe("success");
  });

  it("verifies the configured local model instead of only probing the base url", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");

    await store.loadLlmConfig();
    store.llm.providers.local_qwen = {
      provider_id: "local_qwen",
      provider_type: "openai_compatible",
      account_id: "local",
      base_url: "http://127.0.0.1:11434/v1",
      enabled: true,
      credential_mode: "none",
      models: ["qwen3:14b"],
      secret: { configured: false, secret_type: "none" },
    };

    const message = await store.probeLlmProvider("local_qwen");

    expect(message).toContain("qwen3:14b");
    expect(store.providerProbeResults.local_qwen.checks.completion.ok).toBe(true);
  });

  it("runs completion checks for OpenAI relay providers too", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");

    await store.loadLlmConfig();
    store.llm.providers.gcli2api = {
      provider_id: "gcli2api",
      provider_type: "openai",
      account_id: "relay",
      base_url: "http://127.0.0.1:7861/v1",
      enabled: true,
      credential_mode: "api_key",
      api_mode: "responses",
      models: ["gemini-3.1-pro-preview"],
      secret: { configured: true, secret_type: "api_key" },
    };

    globalThis.fetch = vi.fn(async (url, options = {}) => {
      if (url.endsWith("/api/v1/system-config/llm/providers/gcli2api/probe") && options.method === "POST") {
        expect(JSON.parse(options.body)).toEqual({ model: "gemini-3.1-pro-preview", check_completion: true });
        return ok({
          ok: false,
          status_code: 404,
          message: "Responses API endpoint returned 404; switch api_mode to chat",
          checks: {
            completion: {
              ok: false,
              endpoint: "/responses",
              api_mode: "responses",
              next_action: "switch_provider_api_mode_to_chat_or_use_responses_compatible_provider",
            },
          },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const message = await store.probeLlmProvider("gcli2api");

    expect(message).toContain("Responses API");
    expect(store.providerProbeResults.gcli2api.checks.completion.endpoint).toBe("/responses");
  });

  it("tracks llm provider probe loading per provider", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.setAdminToken("admin-token");

    await store.loadLlmConfig();

    let resolveProbe;
    globalThis.fetch = vi.fn((url, options = {}) => {
      if (url.endsWith("/api/v1/system-config/llm/providers/openai_primary/probe") && options.method === "POST") {
        return new Promise((resolve) => {
          resolveProbe = () => resolve(ok({
            ok: true,
            status_code: 200,
            latency_ms: 42,
            message: "模型 gpt-5.4 已在服务列表中找到",
            checks: {
              connection: { ok: true },
              model: { ok: true, requested_model: "gpt-5.4" },
            },
          }));
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const probePromise = store.probeLlmProvider("openai_primary");
    await Promise.resolve();

    expect(store.testing).toBe(false);
    expect(store.providerProbePending.openai_primary).toBe(true);
    expect(store.providerProbePending.local_qwen).toBeUndefined();

    resolveProbe();
    await probePromise;

    expect(store.providerProbePending).toEqual({});
    expect(store.providerProbeResults.openai_primary.ok).toBe(true);
  });

  it("drops stale provider probe results when provider config reloads", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();
    store.providerProbeResults = {
      cli_proxy: {
        ok: false,
        message: "404 page not found",
        checks: {
          connection: { ok: false },
          completion: { ok: false },
        },
      },
    };
    globalThis.fetch = vi.fn(async (url) => {
      if (url.endsWith("/api/v1/system-config/llm")) {
        return ok({
          provider_catalog: {},
          providers: {
            cli_proxy: {
              provider_id: "cli_proxy",
              provider_type: "openai_compatible",
              account_id: "relay",
              base_url: "http://127.0.0.1:8317/v1",
              enabled: true,
              credential_mode: "api_key",
              api_mode: "chat",
              models: ["gemini-3.1-pro-preview"],
              secret: { configured: true, hint: "****" },
            },
          },
          node_routes: {},
        });
      }
      return ok({});
    });

    await store.loadLlmConfig();

    expect(store.providerProbeResults).toEqual({});
  });

  it("loads and runs the literary eval summary from system config", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    await store.loadLiteraryEvalLatest();
    const message = await store.runLiteraryEval();

    expect(store.literaryEval.report.summary.passed_count).toBe(2);
    expect(store.literaryEval.report.summary.case_count).toBe(3);
    expect(store.literaryEval.report.cases[0].issues[0]).toContain("corridor");
    expect(message).toContain("2/3");
  });

  it("runs live literary eval with an optional model override", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    store.literaryEvalModel = "writer-live-model";
    const message = await store.runLiteraryEval("live");

    const call = globalThis.fetch.mock.calls.find(([url, options]) => {
      if (!url.endsWith("/api/v1/literary-eval/run") || options.method !== "POST") {
        return false;
      }
      return JSON.parse(options.body).mode === "live";
    });
    expect(call).toBeTruthy();
    expect(JSON.parse(call[1].body)).toEqual({ mode: "live", model: "writer-live-model" });
    expect(store.literaryEval.report.mode).toBe("live");
    expect(store.literaryEval.report.model).toBe("writer-live-model");
    expect(message).toContain("2/3");
  });

  it("builds literary eval diagnostic rows with status, dimensions, and preview text", () => {
    const rows = buildLiteraryEvalCaseRows({
      cases: [
        {
          case_id: "style-pressure-001",
          title: "压迫感转场",
          generated_text: "门轴轻响，灯线压低，所有人都停在同一口气里。",
          score: 0.64,
          passed: false,
          dimensions: {
            required_terms: 0.5,
            style_cues: 0.5,
            banned_terms: 1,
            length: 0.7,
          },
          issues: ["missing required term: corridor"],
        },
      ],
    });

    expect(rows).toEqual([
      expect.objectContaining({
        caseId: "style-pressure-001",
        title: "压迫感转场",
        statusLabel: "未通过",
        scoreLabel: "0.64",
        issueText: "missing required term: corridor",
        generatedPreview: "门轴轻响，灯线压低，所有人都停在同一口气里。",
      }),
    ]);
    expect(rows[0].dimensions).toContainEqual(expect.objectContaining({ label: "必备词", score: "0.50" }));
  });

  it("loads the style profile contract for configuration debugging", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    await store.loadStyleProfileContract();

    expect(store.styleProfileContract.contract_version).toBe("STYLE_FEATURE_CONTRACT_v1");
    expect(store.styleProfileContract.example_yaml).toContain("style_profile:");
  });

  it("extracts a style profile YAML draft from pasted sample text", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    store.styleProfileSampleText = "short rhythm and dialogue pressure";
    const message = await store.extractStyleProfileDraft();

    expect(store.styleProfileExtract.profile_yaml).toContain("style_profile:");
    expect(store.styleProfileDraftYaml).toContain("style_profile:");
    expect(store.styleProfileExtract.profile.contract_version).toBe("STYLE_FEATURE_CONTRACT_v1");
    expect(message).toContain("STYLE_FEATURE_CONTRACT_v1");
  });

  it("submits the edited style profile YAML as a review candidate", async () => {
    const { useSystemConfigStore } = await import("../src/stores/systemConfig");
    const store = useSystemConfigStore();

    store.styleProfileExtract = {
      profile_yaml: "style_profile:\n  contract_version: STYLE_FEATURE_CONTRACT_v1\n",
    };
    store.styleProfileDraftYaml = [
      "style_profile:",
      "  contract_version: STYLE_FEATURE_CONTRACT_v1",
      "  features:",
      "    rhythm:",
      "      guidance:",
      "        - edited cadence",
      "",
    ].join("\n");
    const message = await store.submitStyleProfileCandidate();

    expect(store.styleProfileReview.review_id).toBe("review_style_profile_global_global_abc123");
    expect(store.styleProfileReview.candidate_text).toContain("edited cadence");
    expect(message).toContain("review_style_profile_global_global_abc123");
  });
});

describe("system config shell registration", () => {
  it("registers the system config view and store", () => {
    const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
    const routerSource = readFileSync(new URL("../src/router.js", import.meta.url), "utf8");
    const viewSource = readFileSync(new URL("../src/views/SystemConfigView.vue", import.meta.url), "utf8");
    const storeSource = readFileSync(new URL("../src/stores/systemConfig.js", import.meta.url), "utf8");

    expect(appSource).toContain("SystemConfigView");
    expect(routerSource).toContain('id: "config"');
    expect(routerSource).toContain('label: "配置环境"');
    expect(routerSource).toContain('legacyLabel: "系统配置"');
    expect(existsSync(new URL("../src/stores/systemConfig.js", import.meta.url))).toBe(true);
    expect(existsSync(new URL("../src/views/SystemConfigView.vue", import.meta.url))).toBe(true);
    expect(viewSource).toContain("config-literary-eval-summary");
    expect(viewSource).toContain("config-literary-eval-run");
    expect(viewSource).toContain("config-literary-eval-run-live");
    expect(viewSource).toContain("systemConfig.literaryEvalModel");
    expect(viewSource).toContain("literaryEvalCases");
    expect(viewSource).toContain("config-literary-eval-cases");
    expect(viewSource).toContain("config-literary-eval-case-");
    expect(viewSource).toContain("config-style-profile-contract");
    expect(viewSource).toContain("config-style-profile-sample");
    expect(viewSource).toContain("config-style-profile-extract");
    expect(viewSource).toContain("config-style-profile-submit");
    expect(viewSource).toContain("config-style-profile-yaml");
    expect(viewSource).toContain("systemConfig.styleProfileDraftYaml");
    expect(viewSource).toContain("config-style-profile-review");
    expect(viewSource).toContain("config-dashboard-tabs");
    expect(viewSource).toContain("config-dashboard-tab-setup");
    expect(viewSource).toContain("config-dashboard-tab-routing");
    expect(viewSource).toContain("config-dashboard-tab-validation");
    expect(viewSource).toContain("config-dashboard-tab-advanced");
    expect(viewSource).toContain("config-section-setup");
    expect(viewSource).toContain("config-section-routing");
    expect(viewSource).toContain("config-section-validation");
    expect(viewSource).toContain("config-section-advanced");
    expect(viewSource).toContain("configDashboardSummary");
    expect(viewSource).toContain("config-write-warning");
    expect(viewSource).toContain("config-local-setup-note");
    expect(viewSource).toContain("config-llm-action-message");
    expect(viewSource).toContain("config-api-base-effective");
    expect(viewSource).toContain("config-api-base-probe");
    expect(viewSource).toContain("probeApiBase");
    expect(viewSource).toContain("config-connection-collapse-toggle");
    expect(storeSource).toContain("apiBaseProbe");
    expect(storeSource).toContain("probeApiBase");
    expect(viewSource).toContain('<form class="config-form-grid"');
    expect(viewSource).toContain('<form class="llm-provider-form"');
    expect(viewSource).toContain("config-llm-provider-panel");
    expect(viewSource).toContain("config-llm-local-preset-ollama");
    expect(viewSource).toContain("config-llm-local-preset-lm-studio");
    expect(viewSource).toContain("config-llm-local-preset-cli-proxy");
    expect(viewSource).toContain("config-llm-local-preset-custom");
    expect(viewSource).toContain("config-llm-provider-model-discover");
    expect(viewSource).toContain("normalizeProviderModelLabel");
    expect(viewSource).toContain("providerDraftVisibleModels");
    expect(viewSource).toContain("providerDraftHiddenModelCount");
    expect(viewSource).toContain("providerDraftConfiguredModelLines");
    expect(viewSource).toContain("providerModelCatalogCount");
    expect(viewSource).toContain("config-llm-provider-model-preview");
    expect(viewSource).toContain("config-llm-provider-model-catalog-note");
    expect(viewSource).toContain("llm-model-chip");
    expect(viewSource).toContain("config-llm-provider-key-status");
    expect(viewSource).toContain("config-llm-provider-default-");
    expect(viewSource).toContain("config-llm-route-batch");
    expect(viewSource).toContain("config-llm-node-model-options-");
    expect(viewSource).toContain("config-route-publication-strip");
    expect(viewSource).toContain("config-llm-node-routes-sync-missing");
    expect(viewSource).toContain("systemConfig.applyLocalProviderPreset");
    expect(viewSource).toContain("systemConfig.providerDraft.credential_mode !== \"none\"");
    expect(viewSource).toContain("无需密钥");
    expect(viewSource).not.toContain("config-llm-oauth-panel");
    expect(viewSource).toContain("config-llm-node-matrix");
    expect(viewSource).toContain("config-llm-node-row-");
    expect(viewSource).toContain("systemConfig.nodeRouteRows");
    expect(viewSource).toContain("saveLlmNodeRoutes");
    expect(viewSource).toContain("补全节点路由");
    expect(viewSource).toContain("缺失节点");
    expect(viewSource).toContain("一键补齐");
    expect(viewSource).not.toMatch(/[\uE000-\uF8FF]|\u741b\u30e5\u53cf|\u947a\u509c\u5063|\u6d93\u20ac\u95bf|\u7f02\u509a/);
    expect(storeSource).toContain("syncMissingLlmNodeRoutes");
    expect(viewSource).not.toContain("config-readiness-grid");
    expect(viewSource).not.toContain("config-api-key-input");
    expect(viewSource).not.toContain("config-provider-test");
    expect(viewSource).not.toContain("systemConfig.apiKeyInput");
    expect(storeSource).toContain("localSetupMessage");
    expect(storeSource).toContain("writeBlockedMessage");
    expect(storeSource).toContain("llmActionMessage");
    expect(storeSource).not.toContain("apiKeyInput");
  });
});
