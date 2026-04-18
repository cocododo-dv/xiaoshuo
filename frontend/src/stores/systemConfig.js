import { defineStore } from "pinia";

import {
  activateSystemConfigSnapshot,
  extractStyleProfile,
  exportSystemConfigCategory,
  fetchLlmConfig,
  fetchLiteraryEvalLatest,
  fetchStyleProfileContract,
  fetchSystemConfig,
  getApiBase,
  getOperatorRef,
  probeLlmProvider as probeLlmProviderRequest,
  runLiteraryEval as runLiteraryEvalRequest,
  saveLlmNodeRoutes as saveLlmNodeRoutesRequest,
  saveLlmProviderConfig,
  saveSystemConfigDraft,
  setApiBase,
  setOperatorRef,
  startLlmOAuth as startLlmOAuthRequest,
  submitStyleProfileCandidate as submitStyleProfileCandidateRequest,
  testSystemConfigProvider,
} from "../lib/api";

const ADMIN_TOKEN_KEY = "novel-system-admin-token";
const DEFAULT_CATEGORY = "api";
const REASONING_LEVELS = new Set(["off", "low", "medium", "high"]);
const LLM_NODE_ORDER = [
  "neutral_draft",
  "style_draft",
  "style_patch",
  "hard_qc",
  "soft_qc",
  "literary_eval_live",
  "style_profile_extract",
  "chapter_summary",
  "continuity_compression",
  "archive",
  "chapter_aggregate",
];
const DEFAULT_PROVIDER_DRAFT = {
  provider_id: "",
  provider_type: "openai",
  account_id: "",
  base_url: "",
  enabled: true,
  credential_mode: "api_key",
  api_mode: "",
  modelsText: "",
  api_key: "",
};
const DEFAULT_OAUTH_DRAFT = {
  provider_id: "gemini_oauth",
  account_id: "",
  client_id: "",
  redirect_uri: "",
  scopesText: "https://www.googleapis.com/auth/cloud-platform",
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

function storedAdminToken() {
  if (typeof window === "undefined") {
    return "";
  }
  return window.localStorage.getItem(ADMIN_TOKEN_KEY) || "";
}

function persistAdminToken(value) {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(ADMIN_TOKEN_KEY, value);
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

function normalizeNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeReasoningLevel(value) {
  return REASONING_LEVELS.has(value) ? value : DEFAULT_NODE_ROUTE.reasoning_level;
}

function normalizeNodeRouteDraft(nodeId, route = {}) {
  return {
    ...DEFAULT_NODE_ROUTE,
    node_id: nodeId,
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

function normalizeNodeRouteDrafts(routes = {}) {
  const nodeIds = [
    ...LLM_NODE_ORDER,
    ...Object.keys(routes || {}).filter((nodeId) => !LLM_NODE_ORDER.includes(nodeId)),
  ];
  return nodeIds.reduce((drafts, nodeId) => {
    drafts[nodeId] = normalizeNodeRouteDraft(nodeId, routes?.[nodeId] || {});
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
    modelsText: parseTextList(provider.models || []).join("\n"),
    api_key: "",
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
    models: parseTextList(draft.modelsText),
  };
  ["account_id", "base_url", "api_mode", "api_key"].forEach((field) => {
    const value = String(draft[field] || "").trim();
    if (value) {
      payload[field] = value;
    }
  });
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
    operatorRef: getOperatorRef(),
    apiKeyInput: "",
    providerProbe: null,
    llm: {
      provider_catalog: {},
      providers: {},
      node_routes: {},
      api_snapshot: null,
      models_snapshot: null,
    },
    providerDraft: { ...DEFAULT_PROVIDER_DRAFT },
    oauthDraft: { ...DEFAULT_OAUTH_DRAFT },
    nodeRouteDrafts: normalizeNodeRouteDrafts({}),
    providerProbeResults: {},
    oauthStart: null,
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
    providerRows: (state) =>
      Object.values(state.llm.providers || {}).sort((left, right) =>
        String(left.provider_id || "").localeCompare(String(right.provider_id || "")),
      ),
    nodeRouteRows: (state) => {
      const drafts = state.nodeRouteDrafts || {};
      const nodeIds = [
        ...LLM_NODE_ORDER,
        ...Object.keys(drafts).filter((nodeId) => !LLM_NODE_ORDER.includes(nodeId)),
      ];
      return nodeIds.map((nodeId) => {
        const draft = drafts[nodeId] || normalizeNodeRouteDraft(nodeId, {});
        const source = state.llm.node_routes?.[nodeId] || {};
        return {
          ...draft,
          node_id: nodeId,
          status: source.status || draft.status || "active",
          configured: Boolean(source.configured || draft.provider_id || draft.model),
        };
      });
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
        if (this.selectedCategory === "api" && this.apiKeyInput.trim()) {
          payload.secrets = { llm_api_key: this.apiKeyInput.trim() };
        }
        const result = await saveSystemConfigDraft(payload, this.adminToken);
        this.lastDraft = result.snapshot;
        this.apiKeyInput = "";
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
          providers: payload.providers || {},
          node_routes: payload.node_routes || {},
          api_snapshot: payload.api_snapshot || null,
          models_snapshot: payload.models_snapshot || null,
        };
        this.nodeRouteDrafts = normalizeNodeRouteDrafts(this.llm.node_routes);
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
    },
    async saveLlmProvider() {
      this.llmSaving = true;
      this.error = "";
      try {
        const payload = buildProviderPayload(this.providerDraft);
        const result = await saveLlmProviderConfig(payload, this.adminToken);
        this.providerDraft.api_key = "";
        await this.loadLlmConfig();
        return `LLM Provider 已保存：${result.provider?.provider_id || payload.provider_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.llmSaving = false;
      }
    },
    async saveLlmNodeRoutes() {
      this.llmSaving = true;
      this.error = "";
      try {
        const modelsPayload = categoryPayload(this.categories, "models")?.parsed || {};
        const payload = {
          activate: true,
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
    async probeLlmProvider(providerId) {
      this.testing = true;
      this.error = "";
      try {
        const result = await probeLlmProviderRequest(providerId, {}, this.adminToken);
        this.providerProbeResults = {
          ...this.providerProbeResults,
          [providerId]: result,
        };
        return result.ok ? `Provider ${providerId} 探测成功` : `Provider ${providerId} 探测失败：${result.message}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.testing = false;
      }
    },
    async startLlmOAuth(payload = this.oauthDraft) {
      this.llmSaving = true;
      this.error = "";
      try {
        const requestPayload = {
          provider_id: String(payload.provider_id || "").trim(),
          account_id: String(payload.account_id || "").trim(),
          client_id: String(payload.client_id || "").trim(),
          redirect_uri: String(payload.redirect_uri || "").trim(),
          scopes: Array.isArray(payload.scopes) ? payload.scopes : parseTextList(payload.scopesText),
        };
        this.oauthStart = await startLlmOAuthRequest("gemini", requestPayload, this.adminToken);
        return `Gemini OAuth 授权已创建：${this.oauthStart.provider_id}`;
      } catch (error) {
        this.error = error.message;
        throw error;
      } finally {
        this.llmSaving = false;
      }
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
