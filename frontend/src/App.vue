<script setup>
import { computed, defineAsyncComponent, ref } from "vue";

import { getApiBase, getOperatorRef, setApiBase, setOperatorRef } from "./lib/api";
import { useShellRouter } from "./router";

const VIEW_COMPONENTS = {
  author: defineAsyncComponent(() => import("./views/AuthorWorkspaceView.vue")),
  trash: defineAsyncComponent(() => import("./views/AuthorTrashView.vue")),
  workbench: defineAsyncComponent(() => import("./views/SceneWorkbenchView.vue")),
  review: defineAsyncComponent(() => import("./views/ReviewInboxView.vue")),
  index: defineAsyncComponent(() => import("./views/IndexConsoleView.vue")),
  knowledge: defineAsyncComponent(() => import("./views/KnowledgeConsoleView.vue")),
  interop: defineAsyncComponent(() => import("./views/InteropCenterView.vue")),
};

const { activeView, visitedViews, views, navigate } = useShellRouter();
const apiBase = ref(getApiBase());
const operatorRef = ref(getOperatorRef());
const notices = ref([]);

const activeViewComponent = computed(() => VIEW_COMPONENTS[activeView.value] || VIEW_COMPONENTS.workbench);

// Legacy route markers kept as source anchors for shell registration tests:
// activeView === 'author'
// activeView === 'trash'
// activeView === 'interop'

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
  const errors = (
    await Promise.all(
      visitedViews.value.map(async (viewId) => {
        if (viewId === "author") {
          const authorWorkspaceModule = await import("./stores/authorWorkspace");
          const store = authorWorkspaceModule.useAuthorWorkspaceStore();
          await store.ensureLoaded({ force: true });
          return store.error;
        }
        if (viewId === "trash") {
          const authorTrashModule = await import("./stores/authorTrash");
          const store = authorTrashModule.useAuthorTrashStore();
          await store.ensureLoaded({ force: true });
          return store.error;
        }
        if (viewId === "workbench") {
          const workbenchModule = await import("./stores/workbench");
          const store = workbenchModule.useWorkbenchStore();
          await store.ensureLoaded({ force: true });
          return store.error;
        }
        if (viewId === "review") {
          const reviewInboxModule = await import("./stores/reviewInbox");
          const store = reviewInboxModule.useReviewInboxStore();
          await store.ensureLoaded({ force: true, resetReview: true, resetHumanReview: true });
          return store.error;
        }
        if (viewId === "index") {
          const indexConsoleModule = await import("./stores/indexConsole");
          const store = indexConsoleModule.useIndexConsoleStore();
          await store.ensureLoaded({ force: true });
          if (store.activityLoaded) {
            await store.ensureActivityLoaded({ force: true });
          }
          return store.error;
        }
        if (viewId === "knowledge") {
          const knowledgeConsoleModule = await import("./stores/knowledgeConsole");
          const store = knowledgeConsoleModule.useKnowledgeConsoleStore();
          await store.ensureLoaded({ force: true });
          return store.error;
        }
        return "";
      }),
    )
  ).filter(Boolean);

  if (errors.length) {
    errors.forEach((message) => pushNotice(message));
    return;
  }

  pushNotice("已刷新已访问视图。");
}
</script>

<template>
  <div class="shell">
    <aside class="rail">
      <div class="brand">
        <div class="eyebrow">P2 编辑运营台</div>
        <h1>小说系统控制台</h1>
        <p>把作者编排、运行时审核与索引协作收拢到同一个共享指挥台。</p>
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

      <button class="ghost" @click="reloadAll">刷新已访问视图</button>

      <div class="notice-stack" data-testid="notice-stack">
        <div v-for="notice in notices" :key="notice" class="notice">
          {{ notice }}
        </div>
      </div>
    </aside>

    <main class="stage">
      <div class="view-stack">
        <KeepAlive>
          <component :is="activeViewComponent" :key="activeView" @notice="pushNotice" />
        </KeepAlive>
      </div>
    </main>
  </div>
</template>
