import React from "react";
import { apiAdminGet, apiAdminPost, apiGet } from "./lib/client.js";

/* ==========================================================
   WsAiProviders — AI 模型接入 store(设置 → AI 模型)
   ----------------------------------------------------------
   后端真相:/api/v1/system-config/llm 系列接口(Provider CRUD、
   探活、模型列表、分工槽位、节点路由)。管理面板低频写,统一采用
   「写后重拉 overview」而非乐观更新;唯一本地持久化是管理令牌
   (localStorage novel-system-admin-token,与旧 Vue 高级界面共享)。
   ========================================================== */

const ADMIN_TOKEN_KEY = "novel-system-admin-token";

let AIP = {
  loading: false,
  loaded: false,
  error: null,          // ApiRequestError | null —— overview 拉取失败
  overview: null,       // GET /llm 的 data(providers/node_routes/role_slots/readiness…)
  presets: null,        // GET /llm/provider-presets 的 data({presets, provider_catalog})
  adminConfigured: false, // 后端是否设置了 NOVEL_SYSTEM_ADMIN_TOKEN
  busy: {},             // { [动作key]: true } —— 行内按钮加载态
  probes: {},           // { [provider_id]: 最近一次探活结果 }
};

const aipSubs = new Set();
function aipNotify() { aipSubs.forEach(fn => { try { fn(); } catch (e) {} }); }
function aipPatch(patch) { AIP = { ...AIP, ...patch }; aipNotify(); }
function aipBusy(key, on) {
  const busy = { ...AIP.busy };
  if (on) busy[key] = true; else delete busy[key];
  aipPatch({ busy });
}

function adminToken() {
  try { return (localStorage.getItem(ADMIN_TOKEN_KEY) || "").trim(); } catch (e) { return ""; }
}

const WsAiProviders = {
  subscribe(fn) { aipSubs.add(fn); return () => aipSubs.delete(fn); },
  state: () => AIP,
  adminToken,
  /* 管理令牌缺失/错误 → 视图提示输入(ADMIN_TOKEN_REQUIRED 由调用处捕获) */
  setAdminToken(value) {
    try {
      const v = (value || "").trim();
      if (v) localStorage.setItem(ADMIN_TOKEN_KEY, v);
      else localStorage.removeItem(ADMIN_TOKEN_KEY);
    } catch (e) {}
    aipNotify();
  },

  async refresh() {
    aipPatch({ loading: true, error: null });
    try {
      const [overview, root] = await Promise.all([
        apiGet("/api/v1/system-config/llm"),
        apiGet("/api/v1/system-config").catch(() => null),
      ]);
      aipPatch({
        loading: false,
        loaded: true,
        overview,
        adminConfigured: Boolean(root?.runtime?.admin_configured),
      });
      return overview;
    } catch (error) {
      aipPatch({ loading: false, error });
      throw error;
    }
  },

  async loadPresets() {
    if (AIP.presets) return AIP.presets;
    const presets = await apiGet("/api/v1/system-config/llm/provider-presets");
    aipPatch({ presets });
    return presets;
  },

  /* 保存(新增或编辑)一个模型服务;成功后重拉 overview */
  async saveProvider(payload) {
    const key = `save:${payload.provider_id}`;
    aipBusy(key, true);
    try {
      const result = await apiAdminPost("/api/v1/system-config/llm/providers", payload, adminToken());
      await WsAiProviders.refresh();
      return result;
    } finally {
      aipBusy(key, false);
    }
  },

  async setDefault(providerId) {
    const key = `default:${providerId}`;
    aipBusy(key, true);
    try {
      const result = await apiAdminPost(
        `/api/v1/system-config/llm/providers/${encodeURIComponent(providerId)}/default`, {}, adminToken(),
      );
      await WsAiProviders.refresh();
      return result;
    } finally {
      aipBusy(key, false);
    }
  },

  /* 已保存服务的连接测试;结果留在 probes[providerId] 供行内展示 */
  async probe(providerId, extra = {}) {
    const key = `probe:${providerId}`;
    aipBusy(key, true);
    try {
      const result = await apiAdminPost(
        `/api/v1/system-config/llm/providers/${encodeURIComponent(providerId)}/probe`,
        { check_completion: true, ...extra },
        adminToken(),
      );
      aipPatch({ probes: { ...AIP.probes, [providerId]: result } });
      return result;
    } catch (error) {
      aipPatch({ probes: { ...AIP.probes, [providerId]: { ok: false, message: error.message } } });
      throw error;
    } finally {
      aipBusy(key, false);
    }
  },

  /* 已保存服务的模型列表(实时拉取,失败回退预设) */
  async fetchModels(providerId) {
    const key = `models:${providerId}`;
    aipBusy(key, true);
    try {
      return await apiAdminGet(
        `/api/v1/system-config/llm/providers/${encodeURIComponent(providerId)}/models`, adminToken(),
      );
    } finally {
      aipBusy(key, false);
    }
  },

  /* 保存前的草稿试连(添加流程用):同样能带回 available_models */
  async testDraft(payload) {
    aipBusy("draft-test", true);
    try {
      return await apiAdminPost("/api/v1/system-config/test-provider", payload, adminToken());
    } finally {
      aipBusy("draft-test", false);
    }
  },

  /* 分工槽位:{slot_id: {provider_id, model}} 批量展开为节点路由 */
  async saveRoleRoutes(assignments, activate = true) {
    aipBusy("role-routes", true);
    try {
      const result = await apiAdminPost(
        "/api/v1/system-config/llm/role-routes", { assignments, activate }, adminToken(),
      );
      if (result?.overview) aipPatch({ overview: result.overview });
      else await WsAiProviders.refresh();
      return result;
    } finally {
      aipBusy("role-routes", false);
    }
  },

  /* 高级路由:整表保存(node_routing 全量) */
  async saveNodeRoutes(payload) {
    aipBusy("node-routes", true);
    try {
      const result = await apiAdminPost(
        "/api/v1/system-config/llm/node-routes", { activate: true, ...payload }, adminToken(),
      );
      await WsAiProviders.refresh();
      return result;
    } finally {
      aipBusy("node-routes", false);
    }
  },

  /* 一键补齐缺失路由(默认 provider 或指定 provider/model) */
  async syncMissing(payload = {}) {
    aipBusy("sync-missing", true);
    try {
      const result = await apiAdminPost(
        "/api/v1/system-config/llm/node-routes/sync-missing", { activate: true, ...payload }, adminToken(),
      );
      if (result?.overview) aipPatch({ overview: result.overview });
      else await WsAiProviders.refresh();
      return result;
    } finally {
      aipBusy("sync-missing", false);
    }
  },
};

function useAiProviders() {
  const [, force] = React.useState(0);
  React.useEffect(() => WsAiProviders.subscribe(() => force(n => n + 1)), []);
  return AIP;
}

Object.assign(window, { WsAiProviders, useAiProviders });

/* ESM 导出(window.* 赋值过渡期保留) */
export { WsAiProviders, useAiProviders };
