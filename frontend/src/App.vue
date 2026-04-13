<script setup>
import { ref } from "vue";

import { getApiBase, getOperatorRef, setApiBase, setOperatorRef } from "./lib/api";
import { useAuthorTrashStore } from "./stores/authorTrash";
import { useAuthorWorkspaceStore } from "./stores/authorWorkspace";
import { useIndexConsoleStore } from "./stores/indexConsole";
import { useInteropCenterStore } from "./stores/interopCenter";
import { useKnowledgeConsoleStore } from "./stores/knowledgeConsole";
import { useReviewInboxStore } from "./stores/reviewInbox";
import { useWorkbenchStore } from "./stores/workbench";
import { useShellRouter } from "./router";
import AuthorTrashView from "./views/AuthorTrashView.vue";
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

const authorTrash = useAuthorTrashStore();
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
  pushNotice(`Saved API base: ${apiBase.value}`);
}

function updateOperator() {
  operatorRef.value = setOperatorRef(operatorRef.value);
  pushNotice(`Saved operator ref: ${operatorRef.value}`);
}

async function reloadAll() {
  await Promise.all([
    authorWorkspace.initialize(),
    authorTrash.load(),
    workbench.refreshAll(),
    reviewInbox.load(),
    indexConsole.load(),
    knowledgeConsole.load(),
  ]);
  if (authorWorkspace.error) pushNotice(authorWorkspace.error);
  if (authorTrash.error) pushNotice(authorTrash.error);
  if (workbench.error) pushNotice(workbench.error);
  if (reviewInbox.error) pushNotice(reviewInbox.error);
  if (indexConsole.error) pushNotice(indexConsole.error);
  if (knowledgeConsole.error) pushNotice(knowledgeConsole.error);
  if (interopCenter.error) pushNotice(interopCenter.error);
  if (
    !authorWorkspace.error
    && !authorTrash.error
    && !workbench.error
    && !reviewInbox.error
    && !indexConsole.error
    && !knowledgeConsole.error
    && !interopCenter.error
  ) {
    pushNotice("Refreshed all views.");
  }
}
</script>

<template>
  <div class="shell">
    <aside class="rail">
      <div class="brand">
        <div class="eyebrow">P2 Editorial Ops</div>
        <h1>Novel System Console</h1>
        <p>Keep authoring, runtime review, and index operations in one shared control room.</p>
      </div>

      <label class="api-label">
        <span>API Base</span>
        <input v-model="apiBase" class="control-input" data-testid="api-base-input" @change="updateApiBase" />
      </label>

      <label class="api-label">
        <span>Operator Ref / 操作员标识</span>
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

      <button class="ghost" @click="reloadAll">Refresh Everything</button>

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
        <AuthorTrashView
          v-show="activeView === 'trash'"
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
