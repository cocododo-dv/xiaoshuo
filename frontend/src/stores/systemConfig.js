import { defineStore } from "pinia";

import {
  activateSystemConfigSnapshot,
  exportSystemConfigCategory,
  fetchSystemConfig,
  getApiBase,
  getOperatorRef,
  saveSystemConfigDraft,
  setApiBase,
  setOperatorRef,
  testSystemConfigProvider,
} from "../lib/api";

const ADMIN_TOKEN_KEY = "novel-system-admin-token";
const DEFAULT_CATEGORY = "api";

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
    exportResult: null,
    lastDraft: null,
    lastActivated: null,
    loading: false,
    saving: false,
    testing: false,
    error: "",
  }),
  getters: {
    selectedPayload: (state) => categoryPayload(state.categories, state.selectedCategory),
    categoryIds: (state) => Object.keys(state.categories),
    activeSnapshots: (state) => state.history.filter((item) => item.active),
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
    async exportCategory(category = this.selectedCategory) {
      this.exportResult = await exportSystemConfigCategory(category);
      return this.exportResult;
    },
  },
});
