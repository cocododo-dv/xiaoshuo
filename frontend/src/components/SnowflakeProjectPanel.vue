<script setup>
import { ref } from "vue";
import { FolderOpen, Plus, RefreshCw, X } from "lucide-vue-next";

import FlowActionReceipt from "./FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const store = useSnowflakeWorkbenchStore();
const panelOpen = ref(false);
const panelTrigger = ref(null);
const SNOWFLAKE_PROJECT_SCOPE = "snowflake:project";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

async function initialize(force = false) {
  await runFlowAction({
    scopeKey: SNOWFLAKE_PROJECT_SCOPE,
    actionLabel: force ? "刷新雪花工作台" : "加载雪花工作台",
    runningMessage: force ? "正在刷新项目和雪花步骤..." : "正在加载当前雪花项目...",
    successMessage: () => force ? "雪花项目已刷新。" : "",
    nextStep: () => store.currentStep ? "下一步：继续编辑并确认当前雪花步骤。" : "下一步：创建或选择一个雪花项目。",
    notify: force,
    action: () => store.initialize({ force }),
  });
}

async function createProject() {
  const result = await runFlowAction({
    scopeKey: SNOWFLAKE_PROJECT_SCOPE,
    actionLabel: "创建雪花项目",
    runningMessage: "正在创建雪花项目...",
    successMessage: () => store.lastActionMessage || "雪花项目已创建。",
    nextStep: () => "下一步：从第一层雪花开始生成候选并确认。",
    action: () => store.createProject(),
  });
  if (result) {
    closePanel();
  }
}

async function selectProjectFromPanel(projectId) {
  const result = await runFlowAction({
    scopeKey: SNOWFLAKE_PROJECT_SCOPE,
    actionLabel: "切换雪花项目",
    runningMessage: "正在切换项目...",
    successMessage: () => "已切换到选中的雪花项目。",
    nextStep: () => "下一步：检查当前雪花步骤和未保存状态。",
    action: () => store.selectProject(projectId),
  });
  if (result) {
    closePanel();
  }
}

function openPanel() {
  panelOpen.value = true;
}

function closePanel() {
  panelOpen.value = false;
  const restoreFocus = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (callback) => setTimeout(callback, 0);
  restoreFocus(() => {
    panelTrigger.value?.focus?.();
  });
}

defineExpose({ initialize });
</script>

<template>
  <div class="snowflake-project-launcher" data-testid="snowflake-project-launcher">
    <div>
      <span class="eyebrow">当前项目</span>
      <h2>{{ store.project?.title || "未选择雪花项目" }}</h2>
      <p class="muted">
        {{ store.project?.genre || "项目管理已收起，需要时再打开。" }}
        <span v-if="store.project?.status"> / {{ store.project.status }}</span>
      </p>
    </div>
    <div class="action-row">
      <button type="button" class="icon-btn" :disabled="store.loading" aria-label="刷新项目" @click="initialize(true)">
        <RefreshCw :size="16" />
      </button>
      <button
        ref="panelTrigger"
        type="button"
        class="ghost action-btn"
        :aria-expanded="panelOpen ? 'true' : 'false'"
        aria-controls="snowflake-project-drawer-panel"
        @click="openPanel"
      >
        <FolderOpen :size="16" />
        <span>项目 / 新建</span>
      </button>
    </div>
  </div>
  <FlowActionReceipt compact :receipt="receipt(SNOWFLAKE_PROJECT_SCOPE)" />

  <div
    v-if="panelOpen"
    class="project-drawer-backdrop"
    data-testid="snowflake-project-drawer"
    @click.self="closePanel"
    @keydown.esc="closePanel"
  >
    <aside id="snowflake-project-drawer-panel" class="snowflake-project-drawer" aria-label="雪花项目管理">
      <div class="panel-head">
        <div>
          <span class="eyebrow">项目</span>
          <h2>雪花项目</h2>
          <p class="muted">只在切换项目或开新书时打开。</p>
        </div>
        <button type="button" class="icon-btn" aria-label="关闭项目面板" @click="closePanel">
          <X :size="16" />
        </button>
      </div>

      <div class="project-list">
        <button
          v-for="item in store.projects"
          :key="item.project_id"
          type="button"
          class="project-row"
          :class="{ active: item.project_id === store.selectedProjectId }"
          @click="selectProjectFromPanel(item.project_id)"
        >
          <strong>{{ item.title }}</strong>
          <small>{{ item.status }}</small>
        </button>
        <p v-if="!store.projects.length" class="muted">还没有雪花项目。</p>
      </div>

      <form class="project-form" @submit.prevent="createProject">
        <label>
          <span>标题</span>
          <input v-model="store.draft.title" class="control-input" placeholder="新小说标题" />
        </label>
        <label>
          <span>题材</span>
          <input v-model="store.draft.genre" class="control-input" placeholder="都市悬疑 / 奇幻 / 言情" />
        </label>
        <div class="project-form-grid">
          <label>
            <span>章节数</span>
            <input v-model="store.draft.target_chapter_count" class="control-input" inputmode="numeric" />
          </label>
          <label>
            <span>目标字数</span>
            <input v-model="store.draft.target_word_count" class="control-input" inputmode="numeric" />
          </label>
        </div>
        <label>
          <span>故事起始大纲</span>
          <textarea
            v-model="store.draft.outline_text"
            class="control-input outline-input"
            placeholder="粘贴你的故事起点、人物关系和核心冲突。"
          />
        </label>
        <button
          type="submit"
          class="primary action-btn"
          :disabled="!store.canCreate || store.actionId === 'create-project'"
        >
          <Plus :size="16" />
          <span>创建雪花项目</span>
        </button>
      </form>
    </aside>
  </div>
</template>
