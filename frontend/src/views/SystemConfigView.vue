<script setup>
import { computed, onMounted } from "vue";

import PanelShell from "../components/PanelShell.vue";
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

onMounted(async () => {
  if (!Object.keys(systemConfig.categories).length) {
    await runAction(() => systemConfig.load(), { silent: true });
  }
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
