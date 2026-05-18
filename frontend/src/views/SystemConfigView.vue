<script setup>
import { computed, onMounted, ref, watch } from "vue";

import BaseEmptyState from "../components/base/BaseEmptyState.vue";
import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import PanelShell from "../components/PanelShell.vue";
import EvidenceDisclosure from "../components/EvidenceDisclosure.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useUiMode } from "../composables/useUiMode";
import { buildLiteraryEvalCaseRows } from "../lib/literaryEvalSummary";
import { useSystemConfigStore } from "../stores/systemConfig";

const emit = defineEmits(["notice"]);
const systemConfig = useSystemConfigStore();
const activeConfigSection = ref("setup");
const connectionExpanded = ref(false);
const { isAdvancedMode } = useUiMode();
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});
const CONFIG_ACTION_SCOPE = "config:action";

const categoryLabels = {
  api: "连接与密钥",
  models: "模型路由",
  prompts: "提示词模板",
  allowlists: "Allowlist",
  hash_contract: "Hash Contract",
};

const selectedPayload = computed(() => systemConfig.selectedPayload || {});
const selectedValidation = computed(() => selectedPayload.value.validation || {});
const activeSnapshot = computed(() => selectedPayload.value.active_snapshot || null);
const categoryHistory = computed(() =>
  systemConfig.history.filter((item) => item.category === systemConfig.selectedCategory),
);
const literaryEvalReport = computed(() => systemConfig.literaryEval.report || null);
const literaryEvalSummary = computed(() => literaryEvalReport.value?.summary || null);
const literaryEvalCases = computed(() => buildLiteraryEvalCaseRows(literaryEvalReport.value));
const styleProfileContract = computed(() => systemConfig.styleProfileContract || null);
const styleProfileDraftReady = computed(() => Boolean(systemConfig.styleProfileDraftYaml.trim()));
const providerTypeOptions = computed(() => systemConfig.providerCatalogOptions);
const providerRows = computed(() => systemConfig.providerRows);
const configDashboardSummary = computed(() => systemConfig.configDashboardSummary);
const missingActiveRouteCount = computed(() => systemConfig.llm.missing_active_routes?.length || 0);
const providerDraftSavedProvider = computed(() => systemConfig.llm.providers?.[systemConfig.providerDraft.provider_id] || null);
const providerDraftKeyStatus = computed(() => {
  if (systemConfig.providerDraft.credential_mode === "none") {
    return "当前凭据模式无需密钥。";
  }
  if (String(systemConfig.providerDraft.api_key || "").trim()) {
    return "已输入新密钥；保存后会替换后端密钥，不会回显原文。";
  }
  const secret = providerDraftSavedProvider.value?.secret || {};
  if (secret.configured) {
    return `已配置密钥 ${secret.hint || "configured"}；留空会继续使用现有密钥。`;
  }
  return "尚未配置密钥；保存时填写后只提交到后端，不会回显。";
});
function containsCjk(value) {
  return /[\u3400-\u9fff\uf900-\ufaff]/u.test(String(value || ""));
}

function normalizeProviderModelLabel(value) {
  const text = String(value || "").trim();
  if (!text.includes("/")) {
    return text;
  }
  const [prefix, ...rest] = text.split("/");
  const suffix = rest.join("/").trim();
  if (containsCjk(prefix) && suffix && !containsCjk(suffix) && !/\s/u.test(suffix) && /[a-z0-9]/iu.test(suffix)) {
    return suffix;
  }
  return text;
}

const providerDraftModelLines = computed(() =>
  Array.from(new Set(String(systemConfig.providerDraft.modelsText || "")
    .split(/\r?\n/u)
    .map((item) => item.trim())
    .map(normalizeProviderModelLabel)
    .filter(Boolean))),
);
const providerDraftSavedModelLines = computed(() =>
  Array.from(new Set((providerDraftSavedProvider.value?.models || [])
    .map(normalizeProviderModelLabel)
    .filter(Boolean))),
);
const providerDraftConfiguredModelLines = computed(() => {
  if (providerDraftModelLines.value.length > 8 && providerDraftSavedModelLines.value.length) {
    return providerDraftSavedModelLines.value;
  }
  return providerDraftModelLines.value;
});
const providerModelCatalogCount = computed(() =>
  Math.max(
    systemConfig.providerModelCatalogCount || 0,
    providerDraftModelLines.value.length > providerDraftConfiguredModelLines.value.length ? providerDraftModelLines.value.length : 0,
  ),
);
const providerDraftVisibleModels = computed(() => providerDraftConfiguredModelLines.value.slice(0, 8));
const providerDraftHiddenModelCount = computed(() => Math.max(0, providerDraftConfiguredModelLines.value.length - providerDraftVisibleModels.value.length));
const routeBatchModelOptions = computed(() => systemConfig.providerModels(systemConfig.nodeRouteBatchDraft.provider_id));
const reasoningLevels = ["off", "low", "medium", "high"];
const responseFormatOptions = ["text", "json_object", "json_schema"];

watch(isAdvancedMode, (advanced) => {
  if (!advanced && activeConfigSection.value === "advanced") {
    activeConfigSection.value = "setup";
  }
});

onMounted(async () => {
  if (!Object.keys(systemConfig.categories).length) {
    await runAction(() => systemConfig.load(), { silent: true });
  }
  await runAction(() => systemConfig.loadLlmConfig(), { silent: true });
  await runAction(() => systemConfig.loadLiteraryEvalLatest(), { silent: true });
  await runAction(() => systemConfig.loadStyleProfileContract(), { silent: true });
});

async function runAction(action, options = {}) {
  if (options.silent) {
    try {
      await action();
    } catch (error) {
      emit("notice", error.message);
    }
    return;
  }
  await runFlowAction({
    scopeKey: options.scopeKey || CONFIG_ACTION_SCOPE,
    actionLabel: options.actionLabel || "系统配置",
    runningMessage: options.runningMessage || "正在处理系统配置动作...",
    successMessage: (message) => message || options.successMessage || "系统配置已更新。",
    nextStep: () => options.nextStep || "下一步：继续检查配置状态，或回到相关工作台验证效果。",
    action,
    notify: true,
  });
}

function selectCategory(category) {
  systemConfig.selectCategory(category);
}

function saveDraft() {
  runAction(() => systemConfig.saveDraft(), { actionLabel: "保存草稿", runningMessage: "正在保存配置草稿...", nextStep: "下一步：确认验证结果后可激活快照。" });
}

function activate(snapshotId) {
  runAction(() => systemConfig.activateSnapshot(snapshotId), { actionLabel: "激活快照", runningMessage: "正在激活配置快照...", nextStep: "下一步：返回相关流程验证新配置。" });
}

function saveLlmProvider() {
  runAction(() => systemConfig.saveLlmProvider(), { actionLabel: "保存模型提供方", runningMessage: "正在保存模型提供方配置...", nextStep: "下一步：测试连接或配置节点路由。" });
}

function discoverProviderDraftModels() {
  runAction(() => systemConfig.discoverProviderDraftModels(), { actionLabel: "获取模型列表", runningMessage: "正在读取提供方模型列表...", nextStep: "下一步：确认模型名后保存接入。" });
}

function saveLlmNodeRoutes() {
  runAction(() => systemConfig.saveLlmNodeRoutes(), { actionLabel: "保存节点路由", runningMessage: "正在保存 LLM 节点路由...", nextStep: "下一步：运行评测或回到生成流程验证。" });
}

function syncMissingLlmNodeRoutes() {
  runAction(() => systemConfig.syncMissingLlmNodeRoutes(), {
    actionLabel: "补全节点路由",
    runningMessage: "正在补全未配置的 LLM 节点...",
    nextStep: "下一步：检查节点矩阵状态，再运行创作闭环。",
  });
}

function applyNodeRouteBatch() {
  runAction(() => systemConfig.applyNodeRouteBatch(), { actionLabel: "批量设置节点", runningMessage: "正在批量更新节点路由草稿...", nextStep: "下一步：检查节点状态后保存并激活。" });
}

function probeLlmProvider(providerId) {
  runAction(() => systemConfig.probeLlmProvider(providerId), { actionLabel: "测试模型连接", runningMessage: "正在测试模型提供方连接...", nextStep: "下一步：连接成功后保存路由；失败则检查密钥或模型名。" });
}

function editLlmProvider(provider) {
  systemConfig.editLlmProviderDraft(provider);
}

function setDefaultLlmProvider(providerId) {
  runAction(() => systemConfig.setDefaultLlmProvider(providerId), { actionLabel: "设置默认账号", runningMessage: "正在设置默认模型账号...", nextStep: "下一步：如需批量改路由，可在节点矩阵顶部应用。" });
}

function providerTypeLabel(providerType) {
  return providerTypeOptions.value.find((item) => item.provider_type === providerType)?.label || providerType;
}

function providerSecretLabel(provider) {
  if (provider.credential_mode === "none") {
    return "无需密钥";
  }
  return provider.secret?.configured ? provider.secret.hint || "configured" : "未配置密钥";
}

function credentialModesFor(providerType) {
  return providerTypeOptions.value.find((item) => item.provider_type === providerType)?.credential_modes || ["api_key"];
}

function providerProbeCheckItems(result) {
  const checks = result?.checks || {};
  return [
    ["connection", "连接"],
    ["model", "模型名"],
    ["completion", "生成"],
  ]
    .filter(([key]) => checks[key])
    .map(([key, label]) => ({
      key,
      label,
      ok: checks[key].ok,
    }));
}

function nodeRouteDatalistId(nodeId) {
  return `config-llm-node-model-options-${nodeId}`;
}

function runLiteraryEval(mode = "baseline") {
  runAction(() => systemConfig.runLiteraryEval(mode), { actionLabel: "运行文学评测", runningMessage: "正在运行文学评测...", nextStep: "下一步：查看评测结果并调整模型路由。" });
}

function extractStyleProfileDraft() {
  runAction(() => systemConfig.extractStyleProfileDraft(), { actionLabel: "提取风格画像", runningMessage: "正在提取风格画像草稿...", nextStep: "下一步：检查草稿，确认后提交候选。" });
}

function submitStyleProfileCandidate() {
  runAction(() => systemConfig.submitStyleProfileCandidate(), { actionLabel: "提交风格候选", runningMessage: "正在提交风格画像候选...", nextStep: "下一步：到审核收件箱批准候选。" });
}

function exportCurrent() {
  runAction(async () => {
    await systemConfig.exportCategory();
    return `已导出 ${categoryLabels[systemConfig.selectedCategory] || systemConfig.selectedCategory}`;
  });
}

function updateApiBase() {
  emit("notice", systemConfig.updateApiBase(systemConfig.apiBase));
}

function probeApiBase() {
  runAction(() => systemConfig.probeApiBase(), {
    actionLabel: "测试 API 地址",
    runningMessage: "正在测试当前 API 地址...",
    nextStep: "下一步：连接成功后继续配置模型接入；失败则检查端口或后端服务。",
  });
}

function updateOperatorRef() {
  emit("notice", systemConfig.updateOperatorRef(systemConfig.operatorRef));
}

function selectConfigSection(sectionId) {
  if (sectionId === "advanced" && !isAdvancedMode.value) {
    return;
  }
  activeConfigSection.value = sectionId;
}
</script>

<template>
  <div class="system-config-view" data-testid="system-config-view">
    <WorkflowPageHeader view-id="config" />
    <PanelShell
      eyebrow="System Config"
      title="配置驾驶舱"
      description="按连接、账号、节点、验证四步完成日常配置；YAML 和历史放在高级工具里。"
    >
      <template #actions>
        <button class="ghost" data-testid="config-refresh" :disabled="systemConfig.loading" @click="runAction(() => systemConfig.load())">
          刷新
        </button>
      </template>
      <FlowActionReceipt :receipt="receipt(CONFIG_ACTION_SCOPE)" />

      <div class="config-overview">
        <div class="stat">
          <span>管理令牌</span>
          <strong>{{ systemConfig.runtime.admin_configured ? "已启用" : "未启用" }}</strong>
        </div>
        <div class="stat">
          <span>密钥主密钥</span>
          <strong>{{ systemConfig.runtime.secret_configured ? "已配置" : "未配置" }}</strong>
        </div>
        <div class="stat">
          <span>当前类别</span>
          <strong>{{ categoryLabels[systemConfig.selectedCategory] || systemConfig.selectedCategory }}</strong>
        </div>
        <div class="stat">
          <span>模型接入</span>
          <strong>{{ configDashboardSummary.providerCount }}</strong>
        </div>
        <div class="stat">
          <span>已接入节点</span>
          <strong>{{ configDashboardSummary.activeNodeCount }}</strong>
        </div>
      </div>
    </PanelShell>

    <div class="config-dashboard-tabs" data-testid="config-dashboard-tabs" role="tablist" aria-label="配置区块">
      <button
        id="config-dashboard-tab-setup"
        class="config-dashboard-tab"
        :class="{ active: activeConfigSection === 'setup' }"
        :aria-selected="activeConfigSection === 'setup'"
        :tabindex="activeConfigSection === 'setup' ? 0 : -1"
        aria-controls="config-section-setup"
        data-testid="config-dashboard-tab-setup"
        role="tab"
        type="button"
        @click="selectConfigSection('setup')"
      >
        <strong>连接与模型</strong>
        <span>先连后端，再接本地或云端模型</span>
      </button>
      <button
        id="config-dashboard-tab-routing"
        class="config-dashboard-tab"
        :class="{ active: activeConfigSection === 'routing' }"
        :aria-selected="activeConfigSection === 'routing'"
        :tabindex="activeConfigSection === 'routing' ? 0 : -1"
        aria-controls="config-section-routing"
        data-testid="config-dashboard-tab-routing"
        role="tab"
        type="button"
        @click="selectConfigSection('routing')"
      >
        <strong>节点路由</strong>
        <span>再指定每个 LLM 节点用哪个模型</span>
      </button>
      <button
        id="config-dashboard-tab-validation"
        class="config-dashboard-tab"
        :class="{ active: activeConfigSection === 'validation' }"
        :aria-selected="activeConfigSection === 'validation'"
        :tabindex="activeConfigSection === 'validation' ? 0 : -1"
        aria-controls="config-section-validation"
        data-testid="config-dashboard-tab-validation"
        role="tab"
        type="button"
        @click="selectConfigSection('validation')"
      >
        <strong>验证发布</strong>
        <span>最后探测、评测、确认快照</span>
      </button>
      <button
        v-if="isAdvancedMode"
        id="config-dashboard-tab-advanced"
        class="config-dashboard-tab"
        :class="{ active: activeConfigSection === 'advanced' }"
        :aria-selected="activeConfigSection === 'advanced'"
        :tabindex="activeConfigSection === 'advanced' ? 0 : -1"
        aria-controls="config-section-advanced"
        data-testid="config-dashboard-tab-advanced"
        role="tab"
        type="button"
        @click="selectConfigSection('advanced')"
      >
        <strong>高级工具</strong>
        <span>YAML、历史、风格画像放这里</span>
      </button>
    </div>

    <div class="config-layout">
      <section
        id="config-section-setup"
        v-show="activeConfigSection === 'setup'"
        class="config-dashboard-section config-section-setup"
        aria-labelledby="config-dashboard-tab-setup"
        data-testid="config-section-setup"
        role="tabpanel"
      >
      <PanelShell
        class="config-connection-panel"
        :class="{ 'is-collapsed': !connectionExpanded }"
        eyebrow="Connection"
        title="连接设置"
        description="本机控制台连接与后端管理令牌。"
      >
        <template #actions>
          <button
            class="ghost"
            type="button"
            data-testid="config-connection-collapse-toggle"
            :aria-expanded="connectionExpanded"
            @click="connectionExpanded = !connectionExpanded"
          >
            {{ connectionExpanded ? "收起" : "展开" }}
          </button>
        </template>
        <div class="config-connection-summary">
          <span class="badge ghost" data-testid="config-api-base-effective">
            当前生效 {{ systemConfig.apiBase }}
          </span>
          <span class="badge ghost">操作员 {{ systemConfig.operatorRef || "operator" }}</span>
          <span class="badge" :class="{ danger: missingActiveRouteCount > 0 }">
            缺失节点 {{ missingActiveRouteCount }}
          </span>
          <button
            class="ghost"
            type="button"
            data-testid="config-llm-node-routes-sync-missing"
            :disabled="systemConfig.llmSaving || configDashboardSummary.needsProvider"
            @click="syncMissingLlmNodeRoutes"
          >
            一键补齐
          </button>
          <span class="badge ghost">
            管理令牌 {{ systemConfig.adminToken ? "已填写" : systemConfig.runtime.admin_configured ? "未填写" : "本地模式" }}
          </span>
          <button
            type="button"
            class="ghost"
            data-testid="config-api-base-probe"
            :disabled="systemConfig.testing"
            @click="probeApiBase"
          >
            {{ systemConfig.testing ? "测试中..." : "测试连接" }}
          </button>
        </div>
        <form class="config-form-grid" v-show="connectionExpanded" autocomplete="off" @submit.prevent>
          <label>
            <span>API 地址</span>
            <input
              v-model="systemConfig.apiBase"
              class="control-input"
              data-testid="config-api-base-input"
              @change="updateApiBase"
            />
          </label>
          <label>
            <span>操作员标识</span>
            <input
              v-model="systemConfig.operatorRef"
              class="control-input"
              data-testid="config-operator-ref-input"
              @change="updateOperatorRef"
            />
          </label>
          <label>
            <span>管理令牌</span>
            <input
              v-model="systemConfig.adminToken"
              class="control-input"
              data-testid="config-admin-token-input"
              type="password"
              @change="systemConfig.setAdminToken(systemConfig.adminToken)"
            />
          </label>
        </form>
        <p
          v-if="systemConfig.apiBaseProbe"
          class="muted"
          :class="{ 'reference-risk': systemConfig.apiBaseProbe.ok === false }"
        >
          {{ systemConfig.apiBaseProbe.ok ? "API 地址可用" : "API 地址不可用" }} ·
          {{ systemConfig.apiBaseProbe.url }}
        </p>
      </PanelShell>

      <PanelShell
        class="config-wide-panel"
        data-testid="config-llm-provider-panel"
        eyebrow="Model Access"
        title="模型接入"
        description="本地 / 中转站 / 云厂商 API Key 统一接入；OpenAI-compatible 可覆盖 Ollama、LM Studio、CLIProxyAPI、NewAPI、OpenRouter 等。"
      >
        <template #actions>
          <button
            data-testid="config-llm-provider-save"
            :disabled="systemConfig.llmSaving || Boolean(systemConfig.writeBlockedMessage)"
            @click="saveLlmProvider"
          >
            保存接入
          </button>
        </template>

        <div v-if="systemConfig.writeBlockedMessage" class="config-inline-alert warning" data-testid="config-write-warning">
          <strong>暂时不能保存</strong>
          <span>{{ systemConfig.writeBlockedMessage }}</span>
        </div>
        <div
          v-else-if="systemConfig.localSetupMessage"
          class="config-inline-alert info"
          data-testid="config-local-setup-note"
        >
          <strong>本地单机模式</strong>
          <span>{{ systemConfig.localSetupMessage }}</span>
        </div>
        <div
          v-if="systemConfig.llmActionMessage"
          class="config-action-message"
          :class="systemConfig.llmActionTone"
          data-testid="config-llm-action-message"
        >
          {{ systemConfig.llmActionMessage }}
        </div>

        <div class="llm-connection-shortcuts" data-testid="config-llm-connection-shortcuts">
          <button
            class="llm-mode-card"
            data-testid="config-llm-local-preset-ollama"
            type="button"
            @click="systemConfig.applyLocalProviderPreset('ollama')"
          >
            <strong>本地 Ollama</strong>
            <span>默认 http://127.0.0.1:11434/v1，无需密钥</span>
          </button>
          <button
            class="llm-mode-card"
            data-testid="config-llm-local-preset-lm-studio"
            type="button"
            @click="systemConfig.applyLocalProviderPreset('lm-studio')"
          >
            <strong>本地 LM Studio</strong>
            <span>默认 http://127.0.0.1:1234/v1，无需密钥</span>
          </button>
          <button
            class="llm-mode-card"
            data-testid="config-llm-local-preset-custom"
            type="button"
            @click="systemConfig.applyLocalProviderPreset('custom')"
          >
            <strong>自定义本地服务</strong>
            <span>vLLM、LocalAI、llama.cpp server 等兼容 /v1 的地址</span>
          </button>
          <button
            class="llm-mode-card"
            data-testid="config-llm-local-preset-cli-proxy"
            type="button"
            @click="systemConfig.applyLocalProviderPreset('cli-proxy')"
          >
            <strong>中转站 / CLIProxyAPI</strong>
            <span>默认 http://127.0.0.1:8317/v1，填写 API Key 和自定义模型名</span>
          </button>
          <div class="llm-mode-card passive">
            <strong>云厂商 API Key</strong>
            <span>在下方选择 OpenAI、Claude、DeepSeek、智谱或 Gemini，并填写 API Key</span>
          </div>
        </div>

        <div class="llm-provider-grid">
          <form class="llm-provider-form" autocomplete="off" @submit.prevent="saveLlmProvider">
            <label>
              <span>{{ isAdvancedMode ? "接入 ID" : "接入名称" }}</span>
              <input
                v-model="systemConfig.providerDraft.provider_id"
                class="control-input"
                data-testid="config-llm-provider-id"
                placeholder="local_ollama"
              />
            </label>
            <label>
              <span>类型</span>
              <select
                v-model="systemConfig.providerDraft.provider_type"
                class="control-input"
                data-testid="config-llm-provider-type"
              >
                <option v-for="provider in providerTypeOptions" :key="provider.provider_type" :value="provider.provider_type">
                  {{ provider.label }}
                </option>
              </select>
            </label>
            <label>
              <span>账号 / 环境</span>
              <input
                v-model="systemConfig.providerDraft.account_id"
                class="control-input"
                data-testid="config-llm-provider-account"
                placeholder="local"
              />
            </label>
            <label>
              <span>服务地址（到 /v1）</span>
              <input
                v-model="systemConfig.providerDraft.base_url"
                class="control-input"
                data-testid="config-llm-provider-base-url"
                placeholder="http://127.0.0.1:8080/v1"
              />
            </label>
            <label>
              <span>凭据模式</span>
              <select
                v-model="systemConfig.providerDraft.credential_mode"
                class="control-input"
                data-testid="config-llm-provider-credential-mode"
              >
                <option
                  v-for="mode in credentialModesFor(systemConfig.providerDraft.provider_type)"
                  :key="mode"
                  :value="mode"
                >
                  {{ mode }}
                </option>
              </select>
            </label>
            <label>
              <span>调用协议</span>
              <select v-model="systemConfig.providerDraft.api_mode" class="control-input">
                <option value="">默认</option>
                <option value="responses">responses</option>
                <option value="chat">chat</option>
              </select>
            </label>
            <div class="config-wide-field config-labeled-control">
              <div class="config-field-head">
                <span>模型清单</span>
                <button
                  class="ghost"
                  type="button"
                  data-testid="config-llm-provider-model-discover"
                  :disabled="systemConfig.providerModelDiscoveryPending"
                  @click="discoverProviderDraftModels"
                >
                  {{ systemConfig.providerModelDiscoveryPending ? "获取中..." : "获取模型列表" }}
                </button>
              </div>
              <div class="llm-model-editor-shell">
                <div
                  class="llm-model-preview"
                  data-testid="config-llm-provider-model-preview"
                >
                  <span class="badge">已配置 {{ providerDraftConfiguredModelLines.length || 0 }} 个模型</span>
                  <span
                    v-for="model in providerDraftVisibleModels"
                    :key="model"
                    class="llm-model-chip"
                    :title="model"
                  >
                    {{ model }}
                  </span>
                  <span v-if="providerDraftHiddenModelCount" class="llm-model-chip muted">
                    +{{ providerDraftHiddenModelCount }} 个
                  </span>
                  <span v-if="!providerDraftVisibleModels.length" class="muted">尚未填写模型名。</span>
                </div>
                <p
                  v-if="providerModelCatalogCount > providerDraftConfiguredModelLines.length"
                  class="llm-model-catalog-note"
                  data-testid="config-llm-provider-model-catalog-note"
                >
                  可用目录 {{ providerModelCatalogCount }} 个；当前只保存上方 {{ providerDraftConfiguredModelLines.length }} 个模型用于路由。
                </p>
                <details class="llm-model-raw-editor" data-testid="config-llm-provider-model-editor">
                  <summary>批量编辑模型名</summary>
                  <textarea
                    v-model="systemConfig.providerDraft.modelsText"
                    class="control-input control-textarea llm-model-list-editor"
                    data-testid="config-llm-provider-models"
                    placeholder="qwen2.5:7b&#10;llama3.1:8b"
                    rows="4"
                    spellcheck="false"
                  />
                </details>
              </div>
            </div>
            <label v-if='systemConfig.providerDraft.credential_mode !== "none"' class="config-wide-field">
              <span>API Key（云厂商 / 中转站）</span>
              <input
                v-model="systemConfig.providerDraft.api_key"
                class="control-input"
                data-testid="config-llm-provider-api-key"
                type="password"
                placeholder="只提交到后端，不回显"
              />
              <small class="llm-key-status" data-testid="config-llm-provider-key-status">
                {{ providerDraftKeyStatus }}
              </small>
            </label>
            <div v-else class="config-wide-field llm-no-secret-note" data-testid="config-llm-provider-no-secret">
              无需密钥：本地 OpenAI-compatible 服务通常只需要服务地址和模型名。
            </div>
          </form>

          <div class="llm-provider-list">
            <BaseEmptyState v-if="!providerRows.length" description="还没有配置模型接入。" />
            <div
              v-for="provider in providerRows"
              v-else
              :key="provider.provider_id"
              class="llm-account-row"
              :data-testid="`config-llm-provider-row-${provider.provider_id}`"
            >
              <div>
                <strong>{{ provider.provider_id }}</strong>
                <p class="muted">
                  {{ providerTypeLabel(provider.provider_type) }} · {{ provider.account_id || "default" }}
                </p>
              </div>
              <span v-if="provider.is_default" class="badge llm-default-badge">默认账号</span>
              <span class="badge">{{ providerSecretLabel(provider) }}</span>
              <span class="badge">{{ provider.models?.length || 0 }}{{ isAdvancedMode ? " models" : " 个模型" }}</span>
              <div class="config-action-row">
                <button class="ghost" type="button" @click="editLlmProvider(provider)">编辑</button>
                <button
                  class="ghost"
                  type="button"
                  :data-testid="`config-llm-provider-default-${provider.provider_id}`"
                  :disabled="provider.is_default || systemConfig.llmSaving"
                  @click="setDefaultLlmProvider(provider.provider_id)"
                >
                  {{ provider.is_default ? "已默认" : "设为默认" }}
                </button>
                <button
                  class="ghost"
                  type="button"
                  :disabled="systemConfig.providerProbePending[provider.provider_id]"
                  @click="probeLlmProvider(provider.provider_id)"
                >
                  {{ systemConfig.providerProbePending[provider.provider_id] ? "验证中..." : "验证模型" }}
                </button>
              </div>
              <div v-if="systemConfig.providerProbeResults[provider.provider_id]" class="llm-probe-result">
                <p class="muted">{{ systemConfig.providerProbeResults[provider.provider_id].message }}</p>
                <div class="llm-probe-checks">
                  <span
                    v-for="check in providerProbeCheckItems(systemConfig.providerProbeResults[provider.provider_id])"
                    :key="check.key"
                    class="llm-probe-check"
                    :class="{
                      'is-ok': check.ok === true,
                      'is-fail': check.ok === false,
                      'is-skip': check.ok === null,
                    }"
                  >
                    {{ check.label }} {{ check.ok === true ? "通过" : check.ok === false ? "未通过" : "跳过" }}
                  </span>
                </div>
              </div>
              <div v-else-if="systemConfig.providerProbePending[provider.provider_id]" class="llm-probe-result is-pending">
                <p class="muted">正在验证模型...</p>
              </div>
              <div v-else class="llm-probe-result is-empty">
                <p class="muted">尚未验证</p>
              </div>
            </div>
          </div>
        </div>
      </PanelShell>
      </section>

      <section
        id="config-section-routing"
        v-show="activeConfigSection === 'routing'"
        class="config-dashboard-section config-section-routing"
        aria-labelledby="config-dashboard-tab-routing"
        data-testid="config-section-routing"
        role="tabpanel"
      >
      <PanelShell
        class="config-wide-panel"
        data-testid="config-llm-node-matrix"
        eyebrow="Node Matrix"
        title="节点路由矩阵"
        description="每个真实 LLM 调用节点都可以独立绑定供应商账号、模型、结构化输出和思考档位。"
      >
        <div class="config-route-publication-strip" data-testid="config-route-publication-strip">
          <span class="badge">模型接入 {{ configDashboardSummary.providerCount }}</span>
          <span class="badge">可用节点 {{ configDashboardSummary.activeNodeCount }}</span>
          <span class="badge" :class="{ danger: configDashboardSummary.blockedNodeCount > 0 }">
            阻塞 {{ configDashboardSummary.blockedNodeCount }}
          </span>
          <span class="badge ghost">
            快照 {{ systemConfig.llm.models_snapshot?.snapshot_id || "默认配置" }}
          </span>
          <button
            data-testid="config-llm-node-routes-save"
            :disabled="
              systemConfig.llmSaving ||
              configDashboardSummary.needsProvider ||
              configDashboardSummary.needsActiveRoutes ||
              configDashboardSummary.needsRouteProviders
            "
            @click="saveLlmNodeRoutes"
          >
            保存并激活
          </button>
        </div>

        <div class="llm-route-batch-toolbar" data-testid="config-llm-route-batch">
          <label>
            <span>范围</span>
            <select v-model="systemConfig.nodeRouteBatchDraft.scope" class="control-input">
              <option value="blocked">仅未完成/异常节点</option>
              <option value="all-active">全部真实节点</option>
            </select>
          </label>
          <label>
            <span>账号</span>
            <select v-model="systemConfig.nodeRouteBatchDraft.provider_id" class="control-input">
              <option value="">不改账号</option>
              <option v-for="provider in providerRows" :key="provider.provider_id" :value="provider.provider_id">
                {{ provider.provider_id }} · {{ providerTypeLabel(provider.provider_type) }}
              </option>
            </select>
          </label>
          <label>
            <span>模型</span>
            <input
              v-model="systemConfig.nodeRouteBatchDraft.model"
              class="control-input"
              list="config-llm-route-batch-model-options"
              placeholder="不改模型"
            />
            <datalist id="config-llm-route-batch-model-options">
              <option v-for="model in routeBatchModelOptions" :key="model" :value="model" />
            </datalist>
          </label>
          <label>
            <span>思考</span>
            <select v-model="systemConfig.nodeRouteBatchDraft.reasoning_level" class="control-input">
              <option value="">不改</option>
              <option v-for="level in reasoningLevels" :key="level" :value="level">{{ level }}</option>
            </select>
          </label>
          <label>
            <span>温度</span>
            <input v-model.number="systemConfig.nodeRouteBatchDraft.temperature" class="control-input" type="number" min="0" max="2" step="0.1" />
          </label>
          <label>
            <span>tokens</span>
            <input v-model.number="systemConfig.nodeRouteBatchDraft.max_output_tokens" class="control-input" type="number" min="1" step="256" />
          </label>
          <label>
            <span>格式</span>
            <select v-model="systemConfig.nodeRouteBatchDraft.response_format" class="control-input">
              <option value="">不改</option>
              <option v-for="format in responseFormatOptions" :key="format" :value="format">{{ format }}</option>
            </select>
          </label>
          <button class="ghost" type="button" @click="applyNodeRouteBatch">批量应用</button>
        </div>

        <div class="llm-node-matrix-table">
          <div
            v-for="row in systemConfig.nodeRouteRows"
            :key="row.node_id"
            class="llm-node-row"
            :class="{ reserved: row.status === 'reserved' }"
            :data-testid="`config-llm-node-row-${row.node_id}`"
          >
            <div class="llm-node-name">
              <strong>{{ row.node_id }}</strong>
              <span class="badge">{{ row.status === "reserved" ? "预留" : "已接入" }}</span>
            </div>
            <div v-if="systemConfig.nodeRouteDrafts[row.node_id]" class="llm-node-controls">
              <label>
                <span>{{ isAdvancedMode ? "account" : "接入账号" }}</span>
                <select
                  v-model="systemConfig.nodeRouteDrafts[row.node_id].provider_id"
                  class="control-input"
                  @change="systemConfig.setNodeRouteProvider(row.node_id, systemConfig.nodeRouteDrafts[row.node_id].provider_id)"
                >
                  <option value="">选择账号</option>
                  <option v-for="provider in providerRows" :key="provider.provider_id" :value="provider.provider_id">
                    {{ provider.provider_id }} · {{ providerTypeLabel(provider.provider_type) }}
                  </option>
                </select>
              </label>
              <label>
                <span>{{ isAdvancedMode ? "model" : "模型名称" }}</span>
                <input
                  v-model="systemConfig.nodeRouteDrafts[row.node_id].model"
                  class="control-input"
                  :list="nodeRouteDatalistId(row.node_id)"
                />
                <datalist :id="nodeRouteDatalistId(row.node_id)" :data-testid="`config-llm-node-model-options-${row.node_id}`">
                  <option v-for="model in systemConfig.routeModelOptions(row.node_id)" :key="model" :value="model" />
                </datalist>
              </label>
              <label>
                <span>{{ isAdvancedMode ? "reasoning" : "思考强度" }}</span>
                <select v-model="systemConfig.nodeRouteDrafts[row.node_id].reasoning_level" class="control-input">
                  <option v-for="level in reasoningLevels" :key="level" :value="level">{{ level }}</option>
                </select>
              </label>
              <label>
                <span>{{ isAdvancedMode ? "temp" : "创作随机度" }}</span>
                <input
                  v-model.number="systemConfig.nodeRouteDrafts[row.node_id].temperature"
                  class="control-input"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                />
              </label>
              <label>
                <span>{{ isAdvancedMode ? "tokens" : "输出上限" }}</span>
                <input
                  v-model.number="systemConfig.nodeRouteDrafts[row.node_id].max_output_tokens"
                  class="control-input"
                  type="number"
                  min="1"
                  step="256"
                />
              </label>
              <label>
                <span>{{ isAdvancedMode ? "json" : "输出格式" }}</span>
                <select v-model="systemConfig.nodeRouteDrafts[row.node_id].response_format" class="control-input">
                  <option v-for="format in responseFormatOptions" :key="format" :value="format">{{ format }}</option>
                </select>
              </label>
            </div>
          </div>
        </div>
      </PanelShell>
      </section>

      <section
        id="config-section-validation"
        v-show="activeConfigSection === 'validation'"
        class="config-dashboard-section config-section-validation"
        aria-labelledby="config-dashboard-tab-validation"
        data-testid="config-section-validation"
        role="tabpanel"
      >
      <PanelShell eyebrow="Literary Eval" title="文学评测" description="小规模评测集用于检查风格与场景生成质量。">
        <template #actions>
          <button
            class="ghost"
            data-testid="config-literary-eval-run"
            :disabled="systemConfig.literaryEvalRunning"
            @click="runLiteraryEval('baseline')"
          >
            运行 baseline
          </button>
          <button
            data-testid="config-literary-eval-run-live"
            :disabled="systemConfig.literaryEvalRunning"
            @click="runLiteraryEval('live')"
          >
            运行 live
          </button>
        </template>

        <label class="config-inline-field">
          <span>Live 模型</span>
          <input
            v-model="systemConfig.literaryEvalModel"
            class="control-input"
            data-testid="config-literary-eval-model"
            placeholder="Configure literary_eval_live route or enter a model"
          />
        </label>
        <div class="config-overview" data-testid="config-literary-eval-summary">
          <div class="stat">
            <span>套件</span>
            <strong>{{ literaryEvalReport?.suite_id || "未运行" }}</strong>
          </div>
          <div class="stat">
            <span>通过</span>
            <strong>
              {{
                literaryEvalSummary
                  ? `${literaryEvalSummary.passed_count}/${literaryEvalSummary.case_count}`
                  : "-"
              }}
            </strong>
          </div>
          <div class="stat">
            <span>均分</span>
            <strong>{{ literaryEvalSummary ? literaryEvalSummary.mean_score : "-" }}</strong>
          </div>
        </div>
        <p v-if="literaryEvalReport" class="muted">
          {{ literaryEvalReport.mode || "baseline" }} · failed {{ literaryEvalSummary?.failed_count ?? 0 }} · threshold
          {{ literaryEvalSummary?.pass_threshold ?? "-" }}
        </p>
        <ol v-if="literaryEvalCases.length" class="literary-eval-case-list" data-testid="config-literary-eval-cases">
          <li
            v-for="row in literaryEvalCases"
            :key="row.caseId"
            class="literary-eval-case"
            :class="{ failed: !row.passed }"
            :data-testid="`config-literary-eval-case-${row.caseId}`"
          >
            <div class="source-top">
              <strong>{{ row.title }}</strong>
              <span class="badge">{{ row.statusLabel }} · {{ row.scoreLabel }}</span>
            </div>
            <p class="muted">{{ row.generatedPreview }}</p>
            <div v-if="row.dimensions.length" class="literary-eval-dimensions">
              <span v-for="dimension in row.dimensions" :key="dimension.key">
                {{ dimension.label }} {{ dimension.score }}
              </span>
            </div>
            <p class="muted literary-eval-issues">{{ row.issueText }}</p>
          </li>
        </ol>
      </PanelShell>
      </section>

      <section
        v-if="isAdvancedMode"
        id="config-section-advanced"
        v-show="activeConfigSection === 'advanced'"
        class="config-dashboard-section config-section-advanced"
        aria-labelledby="config-dashboard-tab-advanced"
        data-testid="config-section-advanced"
        role="tabpanel"
      >
      <EvidenceDisclosure
        title="高级配置证据"
        summary="YAML、历史、风格画像契约和导出内容默认收起，避免干扰日常配置。"
        test-id="config-advanced-evidence"
      >
      <PanelShell eyebrow="Style Profile" title="风格画像契约" description="结构化风格特征的调试样例，用于校准提示词和 QC 输出。">
        <div class="config-overview" data-testid="config-style-profile-contract">
          <div class="stat">
            <span>契约</span>
            <strong>{{ styleProfileContract?.contract_version || "-" }}</strong>
          </div>
          <div class="stat">
            <span>特征数</span>
            <strong>{{ styleProfileContract?.feature_names?.length ?? "-" }}</strong>
          </div>
          <div class="stat">
            <span>来源</span>
            <strong>runtime</strong>
          </div>
        </div>
        <pre class="config-export-block">{{ styleProfileContract?.example_yaml || "style_profile: {}" }}</pre>
        <textarea
          v-model="systemConfig.styleProfileSampleText"
          class="control-input control-textarea"
          data-testid="config-style-profile-sample"
          placeholder="粘贴一段样本文本或风格规则"
          spellcheck="false"
        />
        <div class="config-action-row">
          <button
            class="ghost"
            data-testid="config-style-profile-extract"
            :disabled="systemConfig.styleProfileExtracting"
            @click="extractStyleProfileDraft"
          >
            生成 YAML
          </button>
          <button
            data-testid="config-style-profile-submit"
            :disabled="systemConfig.styleProfileExtracting || !styleProfileDraftReady"
            @click="submitStyleProfileCandidate"
          >
            送审 YAML
          </button>
        </div>
        <label class="config-style-profile-editor">
          <span>YAML 草稿</span>
          <textarea
            v-model="systemConfig.styleProfileDraftYaml"
            class="control-input control-textarea style-profile-yaml-editor"
            data-testid="config-style-profile-yaml"
            placeholder="生成后可在这里微调 Style Feature Contract YAML"
            spellcheck="false"
          />
        </label>
        <p
          v-if="systemConfig.styleProfileReview"
          class="muted"
          data-testid="config-style-profile-review"
        >
          已送审 {{ systemConfig.styleProfileReview.review_id }} · {{ systemConfig.styleProfileReview.target_collection }}
        </p>
      </PanelShell>

      <PanelShell eyebrow="Categories" title="配置类别" description="仓库默认与数据库激活快照并行可见。">
        <div class="config-category-list">
          <button
            v-for="category in systemConfig.categoryIds"
            :key="category"
            class="config-category-btn"
            :class="{ active: systemConfig.selectedCategory === category }"
            :data-testid="`config-category-${category}`"
            @click="selectCategory(category)"
          >
            <strong>{{ categoryLabels[category] || category }}</strong>
            <span>{{ systemConfig.categories[category]?.source || "-" }}</span>
          </button>
        </div>
      </PanelShell>

      <PanelShell
        class="config-editor-panel"
        eyebrow="YAML"
        :title="categoryLabels[systemConfig.selectedCategory] || systemConfig.selectedCategory"
        :description="activeSnapshot ? `激活版本 v${activeSnapshot.version}` : '当前使用出厂默认配置。'"
      >
        <template #actions>
          <button class="ghost" data-testid="config-export" @click="exportCurrent">导出</button>
          <button data-testid="config-save-draft" :disabled="systemConfig.saving" @click="saveDraft">保存草稿</button>
        </template>

        <div class="config-validation" :class="{ invalid: selectedValidation.ok === false }">
          <strong>{{ selectedValidation.ok === false ? "校验失败" : "校验通过" }}</strong>
          <span>{{ selectedValidation.message || "等待校验" }}</span>
        </div>

        <textarea
          v-model="systemConfig.editorYaml"
          class="control-input control-textarea config-yaml-editor"
          data-testid="config-yaml-editor"
          spellcheck="false"
        />
      </PanelShell>

      <PanelShell eyebrow="History" title="版本历史" description="草稿、激活和回滚入口。">
        <BaseEmptyState v-if="!categoryHistory.length" description="当前类别还没有数据库快照。" />
        <div v-else class="config-history-list">
          <div v-for="snapshot in categoryHistory" :key="snapshot.snapshot_id" class="config-history-row">
            <div>
              <strong>{{ snapshot.snapshot_id }}</strong>
              <p class="muted">
                v{{ snapshot.version }} · {{ snapshot.status }} · {{ snapshot.created_by || "-" }}
              </p>
            </div>
            <button
              class="ghost"
              :data-testid="`config-activate-${snapshot.snapshot_id}`"
              :disabled="snapshot.active || systemConfig.saving"
              @click="activate(snapshot.snapshot_id)"
            >
              {{ snapshot.active ? "已激活" : "激活" }}
            </button>
          </div>
        </div>
      </PanelShell>

      <PanelShell v-if="systemConfig.exportResult" eyebrow="Export" title="导出 YAML" description="当前导出内容。">
        <pre class="config-export-block" data-testid="config-export-yaml">{{ systemConfig.exportResult.yaml_raw }}</pre>
      </PanelShell>
      </EvidenceDisclosure>
      </section>
    </div>
  </div>
</template>
