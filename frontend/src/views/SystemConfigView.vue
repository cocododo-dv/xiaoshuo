<script setup>
import { computed, onMounted, ref } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import PanelShell from "../components/PanelShell.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { buildLiteraryEvalCaseRows } from "../lib/literaryEvalSummary";
import { useSystemConfigStore } from "../stores/systemConfig";

const emit = defineEmits(["notice"]);
const systemConfig = useSystemConfigStore();
const activeConfigSection = ref("setup");
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
const reasoningLevels = ["off", "low", "medium", "high"];
const responseFormatOptions = ["text", "json_object", "json_schema"];

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

function saveLlmNodeRoutes() {
  runAction(() => systemConfig.saveLlmNodeRoutes(), { actionLabel: "保存节点路由", runningMessage: "正在保存 LLM 节点路由...", nextStep: "下一步：运行评测或回到生成流程验证。" });
}

function probeLlmProvider(providerId) {
  runAction(() => systemConfig.probeLlmProvider(providerId), { actionLabel: "测试模型连接", runningMessage: "正在测试模型提供方连接...", nextStep: "下一步：连接成功后保存路由；失败则检查密钥或模型名。" });
}

function startGeminiOAuth() {
  runAction(() => systemConfig.startLlmOAuth(), { actionLabel: "启动 OAuth", runningMessage: "正在启动 OAuth 授权...", nextStep: "下一步：按浏览器授权结果继续配置。" });
}

function editLlmProvider(provider) {
  systemConfig.editLlmProviderDraft(provider);
}

function providerTypeLabel(providerType) {
  return providerTypeOptions.value.find((item) => item.provider_type === providerType)?.label || providerType;
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

function updateOperatorRef() {
  emit("notice", systemConfig.updateOperatorRef(systemConfig.operatorRef));
}

function selectConfigSection(sectionId) {
  activeConfigSection.value = sectionId;
}
</script>

<template>
  <div class="system-config-view" data-testid="system-config-view">
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
      <PanelShell eyebrow="Connection" title="连接设置" description="本机控制台连接与后端管理令牌。">
        <div class="config-form-grid">
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
        </div>
      </PanelShell>

      <PanelShell
        class="config-wide-panel"
        data-testid="config-llm-provider-panel"
        eyebrow="Model Access"
        title="模型接入"
        description="本地模型走 OpenAI-compatible 地址；云厂商走服务端密钥管理。"
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
          <div class="llm-mode-card passive">
            <strong>云厂商 API Key</strong>
            <span>在下方选择 OpenAI、Claude、DeepSeek、智谱或 Gemini，并填写 API Key</span>
          </div>
        </div>

        <div class="llm-provider-grid">
          <div class="llm-provider-form">
            <label>
              <span>接入 ID</span>
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
            <label class="config-wide-field">
              <span>模型名（每行一个）</span>
              <textarea
                v-model="systemConfig.providerDraft.modelsText"
                class="control-input control-textarea llm-model-list-editor"
                data-testid="config-llm-provider-models"
                placeholder="qwen2.5:7b&#10;llama3.1:8b"
                spellcheck="false"
              />
            </label>
            <label v-if='systemConfig.providerDraft.credential_mode !== "none"' class="config-wide-field">
              <span>API Key（云厂商）</span>
              <input
                v-model="systemConfig.providerDraft.api_key"
                class="control-input"
                data-testid="config-llm-provider-api-key"
                type="password"
                placeholder="只提交到后端，不回显"
              />
            </label>
            <div v-else class="config-wide-field llm-no-secret-note" data-testid="config-llm-provider-no-secret">
              无需密钥：本地 OpenAI-compatible 服务通常只需要服务地址和模型名。
            </div>
          </div>

          <div class="llm-provider-list">
            <div v-if="!providerRows.length" class="empty">还没有配置模型接入。</div>
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
              <span class="badge">
                {{
                  provider.credential_mode === "none"
                    ? "无需密钥"
                    : provider.secret?.configured
                      ? provider.secret.hint || "configured"
                      : "未配置密钥"
                }}
              </span>
              <span class="badge">{{ provider.models?.length || 0 }} models</span>
              <div class="config-action-row">
                <button class="ghost" type="button" @click="editLlmProvider(provider)">编辑</button>
                <button class="ghost" type="button" :disabled="systemConfig.testing" @click="probeLlmProvider(provider.provider_id)">
                  验证模型
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
            </div>
          </div>
        </div>
      </PanelShell>

      <PanelShell
        class="config-wide-panel"
        data-testid="config-llm-oauth-panel"
        eyebrow="OAuth2"
        title="Gemini 授权"
        description="首版启用 Google/Gemini OAuth2，授权完成后由服务端保存和刷新 token。"
      >
        <div class="config-oauth-grid">
          <label>
            <span>Provider ID</span>
            <input v-model="systemConfig.oauthDraft.provider_id" class="control-input" placeholder="gemini_oauth" />
          </label>
          <label>
            <span>账号</span>
            <input v-model="systemConfig.oauthDraft.account_id" class="control-input" placeholder="acct_google" />
          </label>
          <label>
            <span>Client ID</span>
            <input v-model="systemConfig.oauthDraft.client_id" class="control-input" />
          </label>
          <label>
            <span>Redirect URI</span>
            <input v-model="systemConfig.oauthDraft.redirect_uri" class="control-input" />
          </label>
          <label class="config-wide-field">
            <span>Scopes</span>
            <textarea
              v-model="systemConfig.oauthDraft.scopesText"
              class="control-input control-textarea llm-scope-editor"
              spellcheck="false"
            />
          </label>
        </div>
        <div class="config-action-row">
          <button
            data-testid="config-llm-oauth-start"
            :disabled="systemConfig.llmSaving"
            @click="startGeminiOAuth"
          >
            开始 Gemini OAuth
          </button>
          <a
            v-if="systemConfig.oauthStart?.authorization_url"
            class="badge"
            :href="systemConfig.oauthStart.authorization_url"
            target="_blank"
            rel="noreferrer"
          >
            打开授权页
          </a>
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
        <template #actions>
          <button
            data-testid="config-llm-node-routes-save"
            :disabled="systemConfig.llmSaving"
            @click="saveLlmNodeRoutes"
          >
            保存并激活
          </button>
        </template>

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
                <span>provider</span>
                <select v-model="systemConfig.nodeRouteDrafts[row.node_id].provider" class="control-input">
                  <option
                    v-for="provider in providerTypeOptions"
                    :key="provider.provider_type"
                    :value="provider.provider_type"
                  >
                    {{ provider.label }}
                  </option>
                </select>
              </label>
              <label>
                <span>account</span>
                <select v-model="systemConfig.nodeRouteDrafts[row.node_id].provider_id" class="control-input">
                  <option value="">默认账号</option>
                  <option v-for="provider in providerRows" :key="provider.provider_id" :value="provider.provider_id">
                    {{ provider.provider_id }}
                  </option>
                </select>
              </label>
              <label>
                <span>model</span>
                <input v-model="systemConfig.nodeRouteDrafts[row.node_id].model" class="control-input" />
              </label>
              <label>
                <span>reasoning</span>
                <select v-model="systemConfig.nodeRouteDrafts[row.node_id].reasoning_level" class="control-input">
                  <option v-for="level in reasoningLevels" :key="level" :value="level">{{ level }}</option>
                </select>
              </label>
              <label>
                <span>temp</span>
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
                <span>tokens</span>
                <input
                  v-model.number="systemConfig.nodeRouteDrafts[row.node_id].max_output_tokens"
                  class="control-input"
                  type="number"
                  min="1"
                  step="256"
                />
              </label>
              <label>
                <span>json</span>
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
      <PanelShell
        class="config-wide-panel"
        eyebrow="Readiness"
        title="验证发布"
        description="这里集中检查账号、节点、探测结果和最近激活快照。"
      >
        <div class="config-readiness-grid">
          <div class="config-readiness-item" :class="{ warning: configDashboardSummary.needsProvider }">
            <span>模型接入</span>
            <strong>{{ configDashboardSummary.providerCount }}</strong>
            <small>{{ configDashboardSummary.needsProvider ? "先添加至少一个模型接入" : "可用于节点路由" }}</small>
          </div>
          <div class="config-readiness-item" :class="{ warning: configDashboardSummary.needsActiveRoutes }">
            <span>已接入节点</span>
            <strong>{{ configDashboardSummary.activeNodeCount }}</strong>
            <small>{{ configDashboardSummary.needsActiveRoutes ? "先为真实调用节点选择模型" : "可以保存并激活" }}</small>
          </div>
          <div class="config-readiness-item">
            <span>预留节点</span>
            <strong>{{ configDashboardSummary.reservedNodeCount }}</strong>
            <small>后续功能打开时再接入</small>
          </div>
          <div class="config-readiness-item">
            <span>模型快照</span>
            <strong>{{ systemConfig.llm.models_snapshot?.snapshot_id || "默认配置" }}</strong>
            <small>{{ systemConfig.llm.models_snapshot?.active ? "已激活" : "尚未激活新快照" }}</small>
          </div>
        </div>
        <div class="config-action-row">
          <button
            data-testid="config-llm-node-routes-save-validation"
            :disabled="systemConfig.llmSaving || configDashboardSummary.needsProvider || configDashboardSummary.needsActiveRoutes"
            @click="saveLlmNodeRoutes"
          >
            保存并激活节点路由
          </button>
          <span class="muted">日常发布只需要确认上面的状态，再保存节点路由。</span>
        </div>
      </PanelShell>

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
            placeholder="留空使用 stylize 路由"
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
        id="config-section-advanced"
        v-show="activeConfigSection === 'advanced'"
        class="config-dashboard-section config-section-advanced"
        aria-labelledby="config-dashboard-tab-advanced"
        data-testid="config-section-advanced"
        role="tabpanel"
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
        <div v-if="!categoryHistory.length" class="empty">当前类别还没有数据库快照。</div>
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
      </section>
    </div>
  </div>
</template>
