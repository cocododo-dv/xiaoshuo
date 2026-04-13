<script setup>
import { ref } from "vue";

import { getApiBase, getOperatorRef, setApiBase, setOperatorRef } from "./lib/api";
import { useAuthorWorkspaceStore } from "./stores/authorWorkspace";
import { useIndexConsoleStore } from "./stores/indexConsole";
import { useInteropCenterStore } from "./stores/interopCenter";
import { useKnowledgeConsoleStore } from "./stores/knowledgeConsole";
import { useReviewInboxStore } from "./stores/reviewInbox";
import { useWorkbenchStore } from "./stores/workbench";
import { useShellRouter } from "./router";
import AuthorWorkspaceView from "./views/AuthorWorkspaceView.vue";
import IndexConsoleView from "./views/IndexConsoleView.vue";
import InteropCenterView from "./views/InteropCenterView.vue";
import KnowledgeConsoleView from "./views/KnowledgeConsoleView.vue";
import ReviewInboxView from "./views/ReviewInboxView.vue";
import SceneWorkbenchView from "./views/SceneWorkbenchView.vue";

const { activeView, views, navigate } = useShellRouter();
const apiBase = ref(getApiBase());
const operatorRef = ref(getOperatorRef());
const notices = ref([]);

const authorWorkspace = useAuthorWorkspaceStore();
const workbench = useWorkbenchStore();
const reviewInbox = useReviewInboxStore();
const indexConsole = useIndexConsoleStore();
const knowledgeConsole = useKnowledgeConsoleStore();
const interopCenter = useInteropCenterStore();

function pushNotice(message) {
  if (!message) {
    return;
  }
  notices.value = [message, ...notices.value].slice(0, 4);
}

function updateApiBase() {
  apiBase.value = setApiBase(apiBase.value);
  pushNotice(`已保存 API 地址：${apiBase.value}`);
}

function updateOperator() {
  operatorRef.value = setOperatorRef(operatorRef.value);
  pushNotice(`已保存操作员标识：${operatorRef.value}`);
}

async function reloadAll() {
  await Promise.all([
    authorWorkspace.initialize(),
    workbench.refreshAll(),
    reviewInbox.load(),
    indexConsole.load(),
    knowledgeConsole.load(),
  ]);
  if (authorWorkspace.error) pushNotice(authorWorkspace.error);
  if (workbench.error) pushNotice(workbench.error);
  if (reviewInbox.error) pushNotice(reviewInbox.error);
  if (indexConsole.error) pushNotice(indexConsole.error);
  if (knowledgeConsole.error) pushNotice(knowledgeConsole.error);
  if (interopCenter.error) pushNotice(interopCenter.error);
  if (!authorWorkspace.error && !workbench.error && !reviewInbox.error && !indexConsole.error && !knowledgeConsole.error && !interopCenter.error) {
    pushNotice("已刷新全部视图");
  }
}
</script>

<template>
  <div class="shell">
    <aside class="rail">
      <div class="brand">
        <div class="eyebrow">P2 编辑运营</div>
        <h1>小说系统控制台</h1>
        <p>把场景生产、审核决策和索引操作集中在同一块面板里。</p>
      </div>

      <label class="api-label">
        <span>API 地址</span>
        <input v-model="apiBase" class="control-input" data-testid="api-base-input" @change="updateApiBase" />
      </label>

      <label class="api-label">
        <span>操作员标识</span>
        <input v-model="operatorRef" class="control-input" data-testid="operator-ref-input" @change="updateOperator" />
      </label>

      <nav class="nav">
        <button
          v-for="view in views"
          :key="view.id"
          class="nav-btn"
          :class="{ active: activeView === view.id }"
          :data-testid="`nav-${view.id}`"
          @click="navigate(view.id)"
        >
          {{ view.label }}
        </button>
      </nav>

      <button class="ghost" @click="reloadAll">全部刷新</button>

      <div class="notice-stack" data-testid="notice-stack">
        <div v-for="notice in notices" :key="notice" class="notice">
          {{ notice }}
        </div>
      </div>
    </aside>

    <main class="stage">
      <div class="view-stack">
        <AuthorWorkspaceView
          v-show="activeView === 'author'"
          @notice="pushNotice"
        />
        <SceneWorkbenchView
          v-show="activeView === 'workbench'"
          @notice="pushNotice"
        />
        <ReviewInboxView
          v-show="activeView === 'review'"
          @notice="pushNotice"
        />
        <IndexConsoleView
          v-show="activeView === 'index'"
          @notice="pushNotice"
        />
        <KnowledgeConsoleView
          v-show="activeView === 'knowledge'"
          @notice="pushNotice"
        />
        <InteropCenterView
          v-show="activeView === 'interop'"
          @notice="pushNotice"
        />
      </div>
    </main>
  </div>
</template>
