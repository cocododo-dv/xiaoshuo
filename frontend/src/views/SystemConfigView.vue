<script setup>
import { computed, onMounted } from "vue";

import PanelShell from "../components/PanelShell.vue";
import { buildLiteraryEvalCaseRows } from "../lib/literaryEvalSummary";
import { useSystemConfigStore } from "../stores/systemConfig";

const emit = defineEmits(["notice"]);
const systemConfig = useSystemConfigStore();

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
  try {
    const message = await action();
    if (message && !options.silent) {
      emit("notice", message);
    }
  } catch (error) {
    emit("notice", error.message);
  }
}

function selectCategory(category) {
  systemConfig.selectCategory(category);
}

function saveDraft() {
  runAction(() => systemConfig.saveDraft());
}

function activate(snapshotId) {
  runAction(() => systemConfig.activateSnapshot(snapshotId));
}

function testProvider() {
  runAction(() => systemConfig.testProvider());
}

function saveLlmProvider() {
  runAction(() => systemConfig.saveLlmProvider());
}

function saveLlmNodeRoutes() {
  runAction(() => systemConfig.saveLlmNodeRoutes());
}

function probeLlmProvider(providerId) {
  runAction(() => systemConfig.probeLlmProvider(providerId));
}

function startGeminiOAuth() {
  runAction(() => systemConfig.startLlmOAuth());
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

function runLiteraryEval(mode = "baseline") {
  runAction(() => systemConfig.runLiteraryEval(mode));
}

function extractStyleProfileDraft() {
  runAction(() => systemConfig.extractStyleProfileDraft());
}

function submitStyleProfileCandidate() {
  runAction(() => systemConfig.submitStyleProfileCandidate());
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
</script>

<template>
  <div class="system-config-view" data-testid="system-config-view">
    <PanelShell
      eyebrow="System Config"
      title="系统配置中心"
      description="运行配置、模型路由、提示词与版本快照集中管理。"
    >
      <template #actions>
        <button class="ghost" data-testid="config-refresh" :disabled="systemConfig.loading" @click="runAction(() => systemConfig.load())">
          刷新
        </button>
      </template>

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
      </div>
    </PanelShell>

    <div class="config-layout">
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
          <label>
            <span>LLM API Key</span>
            <input
              v-model="systemConfig.apiKeyInput"
              class="control-input"
              data-testid="config-api-key-input"
              type="password"
              placeholder="保存 api 类别草稿时更新"
            />
          </label>
        </div>
        <div class="config-action-row">
          <button class="ghost" data-testid="config-provider-test" :disabled="systemConfig.testing" @click="testProvider">
            Provider 探测
          </button>
          <span v-if="systemConfig.providerProbe" class="muted">
            {{ systemConfig.providerProbe.ok ? "探测成功" : systemConfig.providerProbe.message }}
          </span>
        </div>
      </PanelShell>

      <PanelShell
        class="config-wide-panel"
        data-testid="config-llm-provider-panel"
        eyebrow="LLM Accounts"
        title="供应商账号"
        description="API Key、账号标识和模型目录统一走服务端密钥管理。"
      >
        <template #actions>
          <button data-testid="config-llm-provider-save" :disabled="systemConfig.llmSaving" @click="saveLlmProvider">
            保存账号
          </button>
        </template>

        <div class="llm-provider-grid">
          <div class="llm-provider-form">
            <label>
              <span>Provider ID</span>
              <input
                v-model="systemConfig.providerDraft.provider_id"
                class="control-input"
                data-testid="config-llm-provider-id"
                placeholder="openai_primary"
              />
            </label>
            <label>
              <span>供应商</span>
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
              <span>账号</span>
              <input
                v-model="systemConfig.providerDraft.account_id"
                class="control-input"
                data-testid="config-llm-provider-account"
                placeholder="acct_ops"
              />
            </label>
            <label>
              <span>Base URL</span>
              <input
                v-model="systemConfig.providerDraft.base_url"
                class="control-input"
                data-testid="config-llm-provider-base-url"
                placeholder="留空使用默认地址"
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
              <span>API 模式</span>
              <select v-model="systemConfig.providerDraft.api_mode" class="control-input">
                <option value="">默认</option>
                <option value="responses">responses</option>
                <option value="chat">chat</option>
              </select>
            </label>
            <label class="config-wide-field">
              <span>模型目录</span>
              <textarea
                v-model="systemConfig.providerDraft.modelsText"
                class="control-input control-textarea llm-model-list-editor"
                data-testid="config-llm-provider-models"
                placeholder="gpt-5.4&#10;gpt-5.4-mini"
                spellcheck="false"
              />
            </label>
            <label class="config-wide-field">
              <span>API Key</span>
              <input
                v-model="systemConfig.providerDraft.api_key"
                class="control-input"
                data-testid="config-llm-provider-api-key"
                type="password"
                placeholder="只提交到后端，不回显"
              />
            </label>
          </div>

          <div class="llm-provider-list">
            <div v-if="!providerRows.length" class="empty">还没有配置供应商账号。</div>
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
                {{ provider.secret?.configured ? provider.secret.hint || "configured" : "未配置密钥" }}
              </span>
              <span class="badge">{{ provider.models?.length || 0 }} models</span>
              <div class="config-action-row">
                <button class="ghost" type="button" @click="editLlmProvider(provider)">编辑</button>
                <button class="ghost" type="button" :disabled="systemConfig.testing" @click="probeLlmProvider(provider.provider_id)">
                  探测
                </button>
              </div>
              <p v-if="systemConfig.providerProbeResults[provider.provider_id]" class="muted llm-probe-result">
                {{ systemConfig.providerProbeResults[provider.provider_id].message }}
              </p>
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
    </div>
  </div>
</template>
