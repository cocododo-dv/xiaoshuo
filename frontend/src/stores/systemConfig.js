import { defineStore } from "pinia";

import {
  activateSystemConfigSnapshot,
  extractStyleProfile,
  exportSystemConfigCategory,
  fetchLlmConfig,
  fetchLiteraryEvalLatest,
  fetchStyleProfileContract,
  fetchSystemConfig,
  fetchSystemConfigAtBase,
  getApiBase,
  getOperatorRef,
  probeLlmProvider as probeLlmProviderRequest,
  runLiteraryEval as runLiteraryEvalRequest,
  saveLlmNodeRoutes as saveLlmNodeRoutesRequest,
  saveLlmProviderConfig,
  saveSystemConfigDraft,
  setApiBase,
  setDefaultLlmProvider as setDefaultLlmProviderRequest,
  setOperatorRef,
  syncMissingLlmNodeRoutes as syncMissingLlmNodeRoutesRequest,
  submitStyleProfileCandidate as submitStyleProfileCandidateRequest,
  testSystemConfigProvider,
} from "../lib/api";

const ADMIN_TOKEN_KEY = "novel-system-admin-token";
const PROVIDER_PROBE_RESULTS_KEY = "novel-system-provider-probe-results";
const PROVIDER_DISCOVERY_CONFIG_LIMIT = 8;
const DEFAULT_CATEGORY = "api";
const REASONING_LEVELS = new Set(["off", "low", "medium", "high"]);
const FALLBACK_LLM_NODE_ORDER = [
  "neutral_draft",
  "style_draft",
  "style_patch",
  "hard_qc",
  "soft_qc",
  "literary_eval_live",
  "style_profile_extract",
  "reference_sample_ranker",
  "reference_style_structure_extract",
  "reference_profile_synthesize",
  "chapter_summary",
  "continuity_compression",
  "archive",
  "chapter_aggregate",
];
const DEFAULT_PROVIDER_DRAFT = {
  provider_id: "local_ollama",
  provider_type: "openai_compatible",
  account_id: "local",
  base_url: "http://127.0.0.1:11434/v1",
  enabled: true,
  credential_mode: "none",
  api_mode: "chat",
  modelsText: "qwen2.5:7b\nllama3.1:8b",
  api_key: "",
};
const LOCAL_PROVIDER_PRESETS = {
  ollama: {
    provider_id: "local_ollama",
    account_id: "local",
    base_url: "http://127.0.0.1:11434/v1",
    modelsText: "qwen2.5:7b\nllama3.1:8b",
  },
  "lm-studio": {
    provider_id: "local_lm_studio",
    account_id: "local",
    base_url: "http://127.0.0.1:1234/v1",
    modelsText: "local-model",
  },
  "cli-proxy": {
    provider_id: "cli_proxy",
    account_id: "relay",
    base_url: "http://127.0.0.1:8317/v1",
    credential_mode: "api_key",
    modelsText: "",
  },
  custom: {
    provider_id: "local_llm",
    account_id: "local",
    base_url: "http://127.0.0.1:8080/v1",
    modelsText: "local-model",
  },
};
const DEFAULT_NODE_ROUTE = {
  provider: "openai",
  provider_id: "",
  account_id: "",
  model: "",
  temperature: 0.2,
  max_output_tokens: 3000,
  response_format: "json_object",
  reasoning_level: "medium",
  api_mode: "",
  credential_mode: "api_key",
  provider_options: {},
};
const DEFAULT_NODE_ROUTE_BATCH = {
  scope: "blocked",
  provider_id: "",
  model: "",
  reasoning_level: "",
  temperature: null,
  max_output_tokens: null,
  response_format: "",
};

function browserStorage() {
  return typeof window !== "undefined" && window.localStorage ? window.localStorage : null;
}

function browserSessionStorage() {
  return typeof window !== "undefined" && window.sessionStorage ? window.sessionStorage : null;
}

function storedAdminToken() {
  const storage = browserSessionStorage();
  if (!storage) {
    return "";
  }
  const legacyStorage = browserStorage();
  const current = storage.getItem(ADMIN_TOKEN_KEY) || "";
  const legacy = legacyStorage?.getItem(ADMIN_TOKEN_KEY) || "";
  legacyStorage?.removeItem(ADMIN_TOKEN_KEY);
  if (!current && legacy) {
    storage.setItem(ADMIN_TOKEN_KEY, legacy);
  }
  return current || legacy;
}

function persistAdminToken(value) {
  const storage = browserSessionStorage();
  browserStorage()?.removeItem(ADMIN_TOKEN_KEY);
  if (storage) {
    if (value) storage.setItem(ADMIN_TOKEN_KEY, value);
    else storage.removeItem(ADMIN_TOKEN_KEY);
  }
}

function storedProviderProbeResults() {
  const storage = browserStorage();
  if (!storage) {
    return {};
  }
  try {
    const parsed = JSON.parse(storage.getItem(PROVIDER_PROBE_RESULTS_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function persistProviderProbeResults(results = {}) {
  const storage = browserStorage();
  if (storage) {
    storage.setItem(PROVIDER_PROBE_RESULTS_KEY, JSON.stringify(results || {}));
  }
}

function categoryPayload(categories, category) {
  return categories?.[category] || null;
}

function parseTextList(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  return String(value || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function containsCjk(value) {
  return /[\u3400-\u9fff\uf900-\ufaff]/u.test(String(value || ""));
}

function looksLikeProviderModelId(value) {
  const text = String(value || "").trim();
  return Boolean(text) && !containsCjk(text) && !/\s/u.test(text) && /[a-z0-9]/iu.test(text);
}

function normalizeProviderModelId(value) {
  const text = String(value || "").trim();
  if (!text.includes("/")) {
    return text;
  }
  const [prefix, ...rest] = text.split("/");
  const suffix = rest.join("/").trim();
  if (containsCjk(prefix) && looksLikeProviderModelId(suffix)) {
    return suffix;
  }
  return text;
}

function parseProviderModelList(value) {
  return Array.from(new Set(parseTextList(value).map(normalizeProviderModelId).filter(Boolean)));
}

function configuredModelsFromDiscovery({ availableModels = [], draftModels = [], savedModels = [] } = {}) {
  const available = parseProviderModelList(availableModels);
  const availableSet = new Set(available);
  const saved = parseProviderModelList(savedModels).filter((model) => !availableSet.size || availableSet.has(model));
  if (saved.length) {
    return saved.slice(0, PROVIDER_DISCOVERY_CONFIG_LIMIT);
  }
  const current = parseProviderModelList(draftModels).filter((model) => !availableSet.size || availableSet.has(model));
  if (current.length && current.length <= PROVIDER_DISCOVERY_CONFIG_LIMIT) {
    return current;
  }
  if (available.length <= PROVIDER_DISCOVERY_CONFIG_LIMIT) {
    return available;
  }
  return available.slice(0, PROVIDER_DISCOVERY_CONFIG_LIMIT);
}

function firstProviderModel(provider) {
  return parseProviderModelList(provider?.models || []).find(Boolean) || "";
}

function buildProviderProbePayload(provider, options = {}) {
  const model = firstProviderModel(provider);
  const completionCheckProviders = new Set(["openai", "openai_compatible", "deepseek", "zhipu_glm"]);
  const payload = {};
  if (model) {
    payload.model = model;
    payload.check_completion = options.light ? false : completionCheckProviders.has(provider?.provider_type);
  } else if (options.light) {
    payload.check_completion = false;
  }
  return payload;
}

function normalizeProviderBaseUrl(value) {
  let baseUrl = String(value || "").trim().replace(/\/+$/, "");
  for (const suffix of ["/chat/completions", "/completions", "/responses", "/models"]) {
    if (baseUrl.endsWith(suffix)) {
      baseUrl = baseUrl.slice(0, -suffix.length).replace(/\/+$/, "");
      break;
    }
  }
  return baseUrl;
}

function configWriteErrorMessage(error) {
  const message = error?.message || "保存失败";
  if (message.includes("X-Admin-Token") || message.includes("ADMIN_TOKEN")) {
    return "保存失败：后端需要管理令牌。请用 NOVEL_SYSTEM_ADMIN_TOKEN 启动后端，并在上方填写同一个管理令牌。";
  }
  return `保存失败：${message}`;
}

function normalizeNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeReasoningLevel(value) {
  return REASONING_LEVELS.has(value) ? value : DEFAULT_NODE_ROUTE.reasoning_level;
}

function normalizeNodeRouteDraft(nodeId, route = {}, catalogEntry = {}) {
  return {
    ...DEFAULT_NODE_ROUTE,
    node_id: nodeId,
    group: route.group || catalogEntry.group || "custom",
    label: route.label || catalogEntry.label || nodeId,
    requires_llm: route.requires_llm !== undefined ? Boolean(route.requires_llm) : catalogEntry.requires_llm !== false,
    template_name: route.template_name || catalogEntry.template_name || "",
    order: Number.isFinite(Number(route.order ?? catalogEntry.order)) ? Number(route.order ?? catalogEntry.order) : 9999,
    status: route.status || "active",
    configured: Boolean(route.configured),
    provider: route.provider || route.provider_type || DEFAULT_NODE_ROUTE.provider,
    provider_id: route.provider_id || "",
    account_id: route.account_id || "",
    model: route.model || "",
    temperature: normalizeNumber(route.temperature, DEFAULT_NODE_ROUTE.temperature),
    max_output_tokens: normalizeNumber(route.max_output_tokens, DEFAULT_NODE_ROUTE.max_output_tokens),
    response_format: route.response_format || DEFAULT_NODE_ROUTE.response_format,
    reasoning_level: normalizeReasoningLevel(route.reasoning_level),
    api_mode: route.api_mode || "",
    credential_mode: route.credential_mode || DEFAULT_NODE_ROUTE.credential_mode,
    provider_options:
      route.provider_options && typeof route.provider_options === "object" ? { ...route.provider_options } : {},
  };
}

function nodeIdsFromCatalogAndRoutes(catalog = {}, routes = {}) {
  const catalogIds = Object.entries(catalog || {})
    .sort(([, left], [, right]) => Number(left?.order ?? 9999) - Number(right?.order ?? 9999))
    .map(([nodeId]) => nodeId);
  const baseIds = catalogIds.length ? catalogIds : FALLBACK_LLM_NODE_ORDER;
  return [
    ...baseIds,
    ...Object.keys(routes || {}).filter((nodeId) => !baseIds.includes(nodeId)),
  ];
}

function normalizeNodeRouteDrafts(routes = {}, catalog = {}) {
  const nodeIds = nodeIdsFromCatalogAndRoutes(catalog, routes);
  return nodeIds.reduce((drafts, nodeId) => {
    drafts[nodeId] = normalizeNodeRouteDraft(nodeId, routes?.[nodeId] || {}, catalog?.[nodeId] || {});
    return drafts;
  }, {});
}

function providerDraftFrom(provider = {}) {
  return {
    ...DEFAULT_PROVIDER_DRAFT,
    provider_id: provider.provider_id || "",
    provider_type: provider.provider_type || provider.provider || DEFAULT_PROVIDER_DRAFT.provider_type,
    account_id: provider.account_id || "",
    base_url: provider.base_url || "",
    enabled: provider.enabled !== false,
    credential_mode: provider.credential_mode || DEFAULT_PROVIDER_DRAFT.credential_mode,
    api_mode: provider.api_mode || "",
    modelsText: parseProviderModelList(provider.models || []).join("\n"),
    api_key: "",
  };
}

function providerDraftIsDefault(draft = {}) {
  return (
    !draft.provider_id
    || (
      draft.provider_id === DEFAULT_PROVIDER_DRAFT.provider_id
      && draft.base_url === DEFAULT_PROVIDER_DRAFT.base_url
      && draft.modelsText === DEFAULT_PROVIDER_DRAFT.modelsText
    )
  );
}

function selectPreferredProvider(providers = {}, nodeRoutes = {}) {
  const providerRows = Object.values(providers || {});
  if (!providerRows.length) {
    return null;
  }
  const routedProvider = Object.values(nodeRoutes || {})
    .map((route) => providers?.[route?.provider_id])
    .find((provider) => provider && provider.enabled !== false);
  if (routedProvider) {
    return routedProvider;
  }
  return (
    providerRows.find((provider) => provider.enabled !== false && String(provider.provider_id || "").includes("qwen"))
    || providerRows.find((provider) => provider.enabled !== false && String(provider.base_url || "").includes("127.0.0.1:8080"))
    || providerRows.find((provider) => provider.enabled !== false)
    || providerRows[0]
  );
}

function providerViewReady(provider = {}) {
  if (!provider || provider.enabled === false) {
    return false;
  }
  const credentialMode = provider.credential_mode || "api_key";
  if (credentialMode === "none") {
    return true;
  }
  return provider.secret?.configured === true;
}

function providerProbeSignature(provider = {}) {
  return JSON.stringify({
    provider_id: provider.provider_id || "",
    provider_type: provider.provider_type || provider.provider || "",
    base_url: provider.base_url || "",
    credential_mode: provider.credential_mode || "api_key",
    api_mode: provider.api_mode || "",
    models: parseProviderModelList(provider.models || []).join("\n"),
    secret_configured: provider.secret?.configured === true,
    secret_hint: provider.secret?.hint || "",
    secret_updated_at: provider.secret?.updated_at || "",
  });
}

function reconcileProviderProbeResults(results = {}, providers = {}) {
  return Object.entries(results || {}).reduce((nextResults, [providerId, result]) => {
    const provider = providers?.[providerId];
    if (provider && result?._provider_signature === providerProbeSignature(provider)) {
      nextResults[providerId] = result;
    }
    return nextResults;
  }, {});
}

function routeReadinessFromDraft(draft, source = {}, providers = {}) {
  const status = draft.status || source.status || "active";
  const requiresLlm = draft.requires_llm !== false && source.requires_llm !== false;
  const providerId = draft.provider_id || "";
  const model = draft.model || "";
  const configured = Boolean(providerId || model || source.configured);
  const sourceMatchesDraft =
    source.ready !== undefined &&
    (source.provider_id || "") === providerId &&
    (source.model || "") === model &&
    (source.status || "active") === status;

  if (sourceMatchesDraft) {
    return {
      status,
      configured,
      ready: Boolean(source.ready),
      provider_ready: source.provider_ready !== undefined ? Boolean(source.provider_ready) : true,
      provider_missing: Boolean(source.provider_missing),
      model_missing: Boolean(source.model_missing),
      readiness_reason: source.readiness_reason || "",
    };
  }

  if (status === "reserved" || !requiresLlm) {
    return {
      status,
      configured: false,
      ready: false,
      provider_ready: false,
      provider_missing: false,
      model_missing: false,
      readiness_reason: "reserved",
    };
  }
  if (!configured) {
    return {
      status,
      configured: false,
      ready: false,
      provider_ready: false,
      provider_missing: false,
      model_missing: false,
      readiness_reason: "not_configured",
    };
  }
  if (!providerId) {
    return {
      status,
      configured: true,
      ready: false,
      provider_ready: false,
      provider_missing: true,
      model_missing: false,
      readiness_reason: "provider_id_missing",
    };
  }
  const provider = providers[providerId];
  if (!provider) {
    return {
      status,
      configured: true,
      ready: false,
      provider_ready: false,
      provider_missing: true,
      model_missing: false,
      readiness_reason: `provider_not_found:${providerId}`,
    };
  }

  const providerReady = providerViewReady(provider);
  const models = Array.isArray(provider.models) ? provider.models.map((item) => String(item)) : [];
  const modelMissing = !model || (models.length > 0 && !models.includes(model));
  return {
    status,
    configured: true,
    ready: providerReady && !modelMissing,
    provider_ready: providerReady,
    provider_missing: false,
    model_missing: modelMissing,
    readiness_reason: !providerReady ? "provider_not_ready" : modelMissing ? `model_not_listed:${model}` : "ready",
  };
}

function buildProviderPayload(draft) {
  const providerId = String(draft.provider_id || "").trim();
  if (!providerId) {
    throw new Error("请填写 provider_id");
  }
  const payload = {
    provider_id: providerId,
    provider_type: String(draft.provider_type || DEFAULT_PROVIDER_DRAFT.provider_type).trim(),
    enabled: draft.enabled !== false,
    credential_mode: String(draft.credential_mode || DEFAULT_PROVIDER_DRAFT.credential_mode).trim(),
    models: parseProviderModelList(draft.modelsText),
  };
  ["account_id", "base_url", "api_mode"].forEach((field) => {
    const value = String(draft[field] || "").trim();
    if (value) {
      payload[field] = field === "base_url" ? normalizeProviderBaseUrl(value) : value;
    }
  });
  const apiKey = String(draft.api_key || "").trim();
  if (payload.credential_mode !== "none" && apiKey) {
    payload.api_key = apiKey;
  }
  return payload;
}

function buildNodeRoutePayload(draft) {
  const payload = {
    provider: draft.provider || DEFAULT_NODE_ROUTE.provider,
    model: String(draft.model || "").trim(),
    temperature: normalizeNumber(draft.temperature, DEFAULT_NODE_ROUTE.temperature),
    max_output_tokens: normalizeNumber(draft.max_output_tokens, DEFAULT_NODE_ROUTE.max_output_tokens),
    response_format: draft.response_format || DEFAULT_NODE_ROUTE.response_format,
    reasoning_level: normalizeReasoningLevel(draft.reasoning_level),
  };
  ["provider_id", "account_id", "api_mode", "credential_mode"].forEach((field) => {
    const value = String(draft[field] || "").trim();
    if (value) {
      payload[field] = value;
    }
  });
  if (draft.provider_options && Object.keys(draft.provider_options).length) {
    payload.provider_options = { ...draft.provider_options };
  }
  return payload;
}

function applyProviderToRouteDraft(draft, provider, options = {}) {
  if (!draft || !provider) {
    return;
  }
  const previousProviderId = draft.provider_id || "";
  const models = parseProviderModelList(provider.models || []);
  draft.provider = provider.provider_type || provider.provider || draft.provider || DEFAULT_NODE_ROUTE.provider;
  draft.provider_id = provider.provider_id || "";
  draft.account_id = provider.account_id || "";
  draft.api_mode = provider.api_mode || "";
  draft.credential_mode = provider.credential_mode || DEFAULT_NODE_ROUTE.credential_mode;
  if (models.length && (options.forceModel || previousProviderId !== provider.provider_id || !draft.model || !models.includes(draft.model))) {
    draft.model = models[0];
  }
}

function buildNodeRoutingPayload(drafts) {
  return Object.entries(drafts || {}).reduce((nodeRouting, [nodeId, draft]) => {
    if (!String(draft?.model || "").trim()) {
      return nodeRouting;
    }
    nodeRouting[nodeId] = buildNodeRoutePayload(draft);
    return nodeRouting;
  }, {});
}

export const useSystemConfigStore = defineStore("systemConfig", {
  state: () => ({
    runtime: {},
    categories: {},
    history: [],
    selectedCategory: DEFAULT_CATEGORY,
    editorYaml: "",
    adminToken: storedAdminToken(),
    apiBase: getApiBase(),
    apiBaseProbe: null,
    operatorRef: getOperatorRef(),
    providerProbe: null,
    llm: {
      provider_catalog: {},
      default_provider_id: "",
      providers: {},
      node_catalog: {},
      node_routes: {},
      missing_active_routes: [],
      blocked_routes: [],
      readiness: {},
      api_snapshot: null,
      models_snapshot: null,
    },
    providerDraft: { ...DEFAULT_PROVIDER_DRAFT },
    providerDraftTouched: false,
    nodeRouteDrafts: normalizeNodeRouteDrafts({}),
    nodeRouteBatchDraft: { ...DEFAULT_NODE_ROUTE_BATCH },
    providerProbeResults: storedProviderProbeResults(),
    providerProbePending: {},
    providerModelDiscoveryPending: false,
    providerModelCatalogCount: 0,
    providerModelCatalogSample: [],
    llmActionMessage: "",
    llmActionTone: "",
    exportResult: null,
    literaryEval: { report: null },
    literaryEvalModel: "",
    styleProfileContract: null,
    styleProfileSampleText: "",
    styleProfileExtract: null,
    styleProfileDraftYaml: "",
    styleProfileReview: null,
    lastDraft: null,
    lastActivated: null,
    loading: false,
    saving: false,
    testing: false,
    llmLoading: false,
    llmSaving: false,
    literaryEvalRunning: false,
    styleProfileExtracting: false,
    error: "",
  }),
  getters: {
    selectedPayload: (state) => categoryPayload(state.categories, state.selectedCategory),
    categoryIds: (state) => Object.keys(state.categories),
    activeSnapshots: (state) => state.history.filter((item) => item.active),
    providerCatalogOptions: (state) =>
      Object.entries(state.llm.provider_catalog || {}).map(([providerType, item]) => ({
        provider_type: providerType,
        label: item?.label || providerType,
        credential_modes: item?.credential_modes || ["api_key"],
        default_base_url: item?.default_base_url || "",
      })),
    defaultProviderId: (state) => state.llm.default_provider_id || "",
    providerRows: (state) =>
      Object.values(state.llm.providers || {})
        .map((provider) => ({
          ...provider,
          is_default: provider.provider_id === (state.llm.default_provider_id || ""),
        }))
        .sort((left, right) => {
          if (left.is_default !== right.is_default) {
            return left.is_default ? -1 : 1;
          }
          return String(left.provider_id || "").localeCompare(String(right.provider_id || ""));
        }),
    providerModels: (state) => (providerId) => parseProviderModelList(state.llm.providers?.[providerId]?.models || []),
    routeModelOptions: (state) => (nodeId) => {
      const providerId = state.nodeRouteDrafts?.[nodeId]?.provider_id || "";
      return parseProviderModelList(state.llm.providers?.[providerId]?.models || []);
    },
    nodeRouteRows: (state) => {
      const drafts = state.nodeRouteDrafts || {};
      const providers = state.llm.providers || {};
      const nodeIds = nodeIdsFromCatalogAndRoutes(state.llm.node_catalog || {}, drafts);
      return nodeIds.map((nodeId) => {
        const catalogEntry = state.llm.node_catalog?.[nodeId] || {};
        const draft = drafts[nodeId] || normalizeNodeRouteDraft(nodeId, {}, catalogEntry);
        const source = state.llm.node_routes?.[nodeId] || {};
        const readiness = routeReadinessFromDraft(draft, source, providers);
        return {
          ...draft,
          node_id: nodeId,
          label: draft.label || source.label || catalogEntry.label || nodeId,
          group: draft.group || source.group || catalogEntry.group || "custom",
          requires_llm: draft.requires_llm !== false && source.requires_llm !== false && catalogEntry.requires_llm !== false,
          template_name: draft.template_name || source.template_name || catalogEntry.template_name || "",
          status: readiness.status,
          configured: readiness.configured,
          ready: readiness.ready,
          provider_ready: readiness.provider_ready,
          provider_missing: readiness.provider_missing,
          model_missing: readiness.model_missing,
          readiness_reason: readiness.readiness_reason,
        };
      });
    },
    configDashboardSummary() {
      const providerCount = this.providerRows.length;
      const configuredRows = this.nodeRouteRows.filter((row) => row.configured);
      const activeRows = this.nodeRouteRows.filter((row) => row.status !== "reserved" && row.requires_llm !== false);
      const runnableRows = activeRows.filter((row) => row.ready);
      const blockedRows = activeRows.filter((row) => row.configured && !row.ready);
      const reservedRows = this.nodeRouteRows.filter((row) => row.status === "reserved" || row.requires_llm === false);
      return {
        providerCount,
        configuredNodeCount: configuredRows.length,
        missingActiveRouteCount: Array.isArray(this.llm.missing_active_routes) ? this.llm.missing_active_routes.length : 0,
        activeNodeCount: runnableRows.length,
        blockedNodeCount: blockedRows.length,
        reservedNodeCount: reservedRows.length,
        needsProvider: providerCount === 0,
        needsActiveRoutes: runnableRows.length === 0,
        needsRouteProviders: blockedRows.some((row) => row.provider_missing || row.provider_ready === false || row.model_missing),
      };
    },
    localSetupMessage: (state) => {
      if (state.runtime.admin_configured === false) {
        return "本地单机模式：后端没有设置管理令牌，来自本机 127.0.0.1 的配置写入会被允许。";
      }
      return "";
    },
    writeBlockedMessage: (state) => {
      if (state.runtime.admin_configured === true && !String(state.adminToken || "").trim()) {
        return "请先填写管理令牌，才能保存系统配置。";
      }
      return "";
    },
  },
  actions: {
    setAdminToken(value) {
      this.adminToken = value.trim();
      persistAdminToken(this.adminToken);
    },
    updateApiBase(value) {
      this.apiBase = setApiBase(value ?? this.apiBase);
      return `已保存 API 地址：${this.apiBase}`;
    },
    async probeApiBase() {
      this.testing = true;
      this.error = "";
      const url = this.apiBase;
      try {
        const payload = await fetchSystemConfigAtBase(url);
        this.apiBaseProbe = {
          ok: true,
          url,
          runtime: payload.runtime || {},
          category_count: Object.keys(payload.categories || {}).length,
          checked_at: new Date().toISOString(),
        };
        this.runtime = payload.runtime || this.runtime;
        return `API 地址可用：${url}`;
      } catch (error) {
        this.apiBaseProbe = {
          ok: false,
          url,
          message: error.message,
          checked_at: new Date().toISOString(),
        };
        this.error = error.message;
        throw error;
      } finally {
        this.testing = false;
      }
    },
    updateOperatorRef(value) {
      this.operatorRef = setOperatorRef(value ?? this.operatorRef);
      return `已保存操作员标识：${this.operatorRef}`;
    },
    selectCategory(category) {
      this.selectedCategory = category || DEFAULT_CATEGORY;
      this.editorYaml = categoryPayload(this.categories, this.selectedCategory)?.yaml_raw || "";
      this.error = "";
    },
    async load() {
      this.loading = true;
      this.error = "";
      try {
        const payload = await fetchSystemConfig();
        this.runtime = payload.runtime || {};
        this.categories = payload.categories || {};
        this.history = payload.history || [];
        if (!this.categories[this.selectedCategory]) {
          this.selectedCategory = Object.keys(this.categories)[0] || DEFAULT_CATEGORY;
        }
        this.editorYaml = categoryPayload(this.categories, this.selectedCategory)?.yaml_raw || "";
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.loading = false;
      }
    },
    async saveDraft() {
      this.saving = true;
      this.error = "";
      try {
        const payload = {
          category: this.selectedCategory,
          yaml_raw: this.editorYaml,
        };
        const result = await saveSystemConfigDraft(payload, this.adminToken);
        this.lastDraft = result.snapshot;
        await this.load();
        return `已保存配置草稿 ${result.snapshot.snapshot_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.saving = false;
      }
    },
    async activateSnapshot(snapshotId) {
      this.saving = true;
      this.error = "";
      try {
        const result = await activateSystemConfigSnapshot(snapshotId, this.adminToken);
        this.lastActivated = result.snapshot;
        await this.load();
        return `已激活配置 ${result.snapshot.snapshot_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.saving = false;
      }
    },
    async testProvider() {
      this.testing = true;
      this.error = "";
      try {
        const payload = categoryPayload(this.categories, "api")?.parsed?.llm || {};
        this.providerProbe = await testSystemConfigProvider(payload, this.adminToken);
        return this.providerProbe.ok ? "Provider 探测成功" : `Provider 探测失败：${this.providerProbe.message}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.testing = false;
      }
    },
    async loadLlmConfig() {
      this.llmLoading = true;
      this.error = "";
      try {
        const payload = await fetchLlmConfig();
        this.llm = {
          provider_catalog: payload.provider_catalog || {},
          default_provider_id: payload.default_provider_id || "",
          providers: payload.providers || {},
          node_catalog: payload.node_catalog || {},
          node_routes: payload.node_routes || {},
          missing_active_routes: payload.missing_active_routes || [],
          blocked_routes: payload.blocked_routes || [],
          readiness: payload.readiness || {},
          api_snapshot: payload.api_snapshot || null,
          models_snapshot: payload.models_snapshot || null,
        };
        this.providerProbeResults = reconcileProviderProbeResults(this.providerProbeResults, this.llm.providers);
        persistProviderProbeResults(this.providerProbeResults);
        this.nodeRouteDrafts = normalizeNodeRouteDrafts(this.llm.node_routes, this.llm.node_catalog);
        const preferredProvider = selectPreferredProvider(this.llm.providers, this.llm.node_routes);
        if (preferredProvider && !this.providerDraftTouched && providerDraftIsDefault(this.providerDraft)) {
          this.providerDraft = providerDraftFrom(preferredProvider);
        }
        await this.autoProbeLlmProviders();
        return this.llm;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.llmLoading = false;
      }
    },
    editLlmProviderDraft(provider) {
      this.providerDraft = providerDraftFrom(provider);
      this.providerDraftTouched = true;
    },
    applyLocalProviderPreset(presetId = "ollama") {
      const preset = LOCAL_PROVIDER_PRESETS[presetId] || LOCAL_PROVIDER_PRESETS.custom;
      this.providerDraft = {
        ...DEFAULT_PROVIDER_DRAFT,
        ...preset,
        provider_type: "openai_compatible",
        enabled: true,
        credential_mode: preset.credential_mode || "none",
        api_mode: "chat",
        api_key: "",
      };
      this.providerDraftTouched = true;
    },
    async saveLlmProvider() {
      this.llmSaving = true;
      this.error = "";
      this.llmActionMessage = "正在保存模型接入...";
      this.llmActionTone = "info";
      try {
        const savedModels = parseProviderModelList(this.llm.providers?.[this.providerDraft.provider_id]?.models || []);
        const draftModels = parseProviderModelList(this.providerDraft.modelsText);
        if (savedModels.length && draftModels.length > PROVIDER_DISCOVERY_CONFIG_LIMIT) {
          this.providerDraft.modelsText = savedModels.slice(0, PROVIDER_DISCOVERY_CONFIG_LIMIT).join("\n");
        }
        const payload = buildProviderPayload(this.providerDraft);
        const result = await saveLlmProviderConfig(payload, this.adminToken);
        this.providerDraft.api_key = "";
        await this.loadLlmConfig();
        const message = `模型接入已保存：${result.provider?.provider_id || payload.provider_id}`;
        this.llmActionMessage = message;
        this.llmActionTone = "success";
        return message;
      } catch (error) {
        this.error = error.message;
        this.llmActionMessage = configWriteErrorMessage(error);
        this.llmActionTone = "error";
        throw error;
      } finally {
        this.llmSaving = false;
      }
    },
    async discoverProviderDraftModels() {
      this.providerModelDiscoveryPending = true;
      this.error = "";
      try {
        const payload = {
          ...buildProviderPayload(this.providerDraft),
          check_completion: false,
        };
        const result = await testSystemConfigProvider(payload, this.adminToken);
        const availableModels = parseProviderModelList(result.available_models || result.checks?.model?.available_models || []);
        if (!availableModels.length) {
          this.providerModelCatalogCount = 0;
          this.providerModelCatalogSample = [];
          const message = "未从服务返回中发现模型列表，可以继续手动填写。";
          this.llmActionMessage = message;
          this.llmActionTone = "info";
          return message;
        }
        this.providerModelCatalogCount = availableModels.length;
        this.providerModelCatalogSample = availableModels.slice(0, PROVIDER_DISCOVERY_CONFIG_LIMIT);
        const configuredModels = configuredModelsFromDiscovery({
          availableModels,
          draftModels: this.providerDraft.modelsText,
          savedModels: this.llm.providers?.[this.providerDraft.provider_id]?.models || [],
        });
        this.providerDraft.modelsText = configuredModels.join("\n");
        const message = availableModels.length > configuredModels.length
          ? `已发现 ${availableModels.length} 个可用目录项，当前配置 ${configuredModels.length} 个模型`
          : `已获取 ${configuredModels.length} 个模型`;
        this.llmActionMessage = message;
        this.llmActionTone = "success";
        return message;
      } catch (error) {
        const message = `获取模型列表失败：${error.message}`;
        this.error = error.message;
        this.llmActionMessage = message;
        this.llmActionTone = "error";
        return message;
      } finally {
        this.providerModelDiscoveryPending = false;
      }
    },
    async setDefaultLlmProvider(providerId) {
      const result = await setDefaultLlmProviderRequest(providerId, this.adminToken);
      this.llm = {
        ...this.llm,
        default_provider_id: result.default_provider_id || providerId,
        api_snapshot: result.snapshot || this.llm.api_snapshot,
      };
      return `默认账号已设置：${result.default_provider_id || providerId}`;
    },
    setNodeRouteProvider(nodeId, providerId) {
      const draft = this.nodeRouteDrafts?.[nodeId];
      const provider = this.llm.providers?.[providerId];
      applyProviderToRouteDraft(draft, provider, { forceModel: draft?.provider_id !== providerId });
    },
    applyNodeRouteBatch() {
      const batch = this.nodeRouteBatchDraft || {};
      const targetRows = this.nodeRouteRows.filter((row) => {
        if (row.status === "reserved") {
          return false;
        }
        if (batch.scope === "all-active") {
          return true;
        }
        return row.ready !== true;
      });
      targetRows.forEach((row) => {
        const draft = this.nodeRouteDrafts[row.node_id];
        if (!draft) {
          return;
        }
        if (batch.provider_id) {
          this.setNodeRouteProvider(row.node_id, batch.provider_id);
        }
        if (batch.model) {
          draft.model = String(batch.model).trim();
        }
        if (batch.reasoning_level) {
          draft.reasoning_level = normalizeReasoningLevel(batch.reasoning_level);
        }
        if (batch.temperature !== null && batch.temperature !== "" && batch.temperature !== undefined) {
          draft.temperature = normalizeNumber(batch.temperature, draft.temperature);
        }
        if (batch.max_output_tokens !== null && batch.max_output_tokens !== "" && batch.max_output_tokens !== undefined) {
          draft.max_output_tokens = normalizeNumber(batch.max_output_tokens, draft.max_output_tokens);
        }
        if (batch.response_format) {
          draft.response_format = batch.response_format;
        }
      });
      return `已批量更新 ${targetRows.length} 个节点`;
    },
    async saveLlmNodeRoutes() {
      this.llmSaving = true;
      this.error = "";
      try {
        const modelsPayload = categoryPayload(this.categories, "models")?.parsed || {};
        const payload = {
          activate: true,
          model_profiles: modelsPayload.model_profiles || {},
          task_routing: modelsPayload.task_routing || {},
          node_routing: buildNodeRoutingPayload(this.nodeRouteDrafts),
          retry_budget: modelsPayload.retry_budget || {},
          job_runtime: modelsPayload.job_runtime || {},
        };
        const result = await saveLlmNodeRoutesRequest(payload, this.adminToken);
        await this.load();
        await this.loadLlmConfig();
        return `已保存节点路由 ${result.snapshot.snapshot_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.llmSaving = false;
      }
    },
    async syncMissingLlmNodeRoutes() {
      this.llmSaving = true;
      this.error = "";
      this.llmActionMessage = "Syncing missing LLM node routes...";
      this.llmActionTone = "info";
      try {
        const result = await syncMissingLlmNodeRoutesRequest({ activate: true }, this.adminToken);
        await this.load();
        await this.loadLlmConfig();
        const count = Array.isArray(result.synced_node_ids) ? result.synced_node_ids.length : 0;
        const message = `Synced ${count} missing LLM node routes`;
        this.llmActionMessage = message;
        this.llmActionTone = "success";
        return message;
      } catch (error) {
        this.error = error.message;
        this.llmActionMessage = configWriteErrorMessage(error);
        this.llmActionTone = "error";
        throw error;
      } finally {
        this.llmSaving = false;
      }
    },
    async probeLlmProvider(providerId, options = {}) {
      this.providerProbePending = {
        ...this.providerProbePending,
        [providerId]: true,
      };
      this.error = "";
      try {
        const provider = this.llm.providers?.[providerId] || {};
        const probePayload = buildProviderProbePayload(provider, options);
        const result = await probeLlmProviderRequest(providerId, probePayload, this.adminToken);
        this.providerProbeResults = {
          ...this.providerProbeResults,
          [providerId]: {
            ...result,
            _provider_signature: providerProbeSignature(provider),
          },
        };
        persistProviderProbeResults(this.providerProbeResults);
        if (!result.ok) {
          return `模型验证失败：${result.message || providerId}`;
        }
        return `模型验证成功：${result.message || providerId}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        const providerProbePending = { ...this.providerProbePending };
        delete providerProbePending[providerId];
        this.providerProbePending = providerProbePending;
      }
    },
    async autoProbeLlmProviders() {
      if (this.runtime.admin_configured !== false && !String(this.adminToken || "").trim()) {
        return;
      }
      const providers = Object.values(this.llm.providers || {}).filter((provider) => {
        const providerId = provider.provider_id || "";
        return (
          providerId
          && providerViewReady(provider)
          && !this.providerProbePending[providerId]
          && !this.providerProbeResults[providerId]
        );
      });
      await Promise.allSettled(providers.map((provider) => this.probeLlmProvider(provider.provider_id, { light: true })));
    },
    async exportCategory(category = this.selectedCategory) {
      this.exportResult = await exportSystemConfigCategory(category);
      return this.exportResult;
    },
    async loadLiteraryEvalLatest() {
      this.literaryEval = await fetchLiteraryEvalLatest();
      return this.literaryEval;
    },
    async loadStyleProfileContract() {
      this.styleProfileContract = await fetchStyleProfileContract();
      return this.styleProfileContract;
    },
    async extractStyleProfileDraft() {
      this.styleProfileExtracting = true;
      this.error = "";
      try {
        this.styleProfileExtract = await extractStyleProfile({
          sample_texts: this.styleProfileSampleText.trim() ? [this.styleProfileSampleText.trim()] : [],
        });
        this.styleProfileDraftYaml = this.styleProfileExtract.profile_yaml || "";
        const version = this.styleProfileExtract.profile?.contract_version || "style_profile";
        return `风格画像 YAML 已生成：${version}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.styleProfileExtracting = false;
      }
    },
    async submitStyleProfileCandidate() {
      const profileYaml = this.styleProfileDraftYaml.trim();
      if (!profileYaml) {
        throw new Error("请先生成或填写风格画像 YAML");
      }
      this.styleProfileExtracting = true;
      this.error = "";
      try {
        const result = await submitStyleProfileCandidateRequest({
          profile_yaml: profileYaml,
          scope: "global",
          scope_ref_id: "global",
        });
        this.styleProfileReview = result.review;
        return `风格画像已送审：${result.review.review_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.styleProfileExtracting = false;
      }
    },
    async runLiteraryEval(mode = "baseline") {
      this.literaryEvalRunning = true;
      this.error = "";
      try {
        const payload = { mode };
        if (mode === "live" && this.literaryEvalModel.trim()) {
          payload.model = this.literaryEvalModel.trim();
        }
        this.literaryEval = await runLiteraryEvalRequest(payload);
        const summary = this.literaryEval.report?.summary;
        if (!summary) {
          return "文学评测已完成";
        }
        return `文学评测已完成：${summary.passed_count}/${summary.case_count} 通过`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.literaryEvalRunning = false;
      }
    },
  },
});
