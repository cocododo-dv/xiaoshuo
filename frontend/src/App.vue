<script setup>
import { computed, defineAsyncComponent, onBeforeUnmount, ref } from "vue";

import { useShellRouter } from "./router";

const VIEW_COMPONENTS = {
  author: defineAsyncComponent(() => import("./views/AuthorWorkspaceView.vue")),
  trash: defineAsyncComponent(() => import("./views/AuthorTrashView.vue")),
  workbench: defineAsyncComponent(() => import("./views/SceneWorkbenchView.vue")),
  review: defineAsyncComponent(() => import("./views/ReviewInboxView.vue")),
  index: defineAsyncComponent(() => import("./views/IndexConsoleView.vue")),
  knowledge: defineAsyncComponent(() => import("./views/KnowledgeConsoleView.vue")),
  reference: defineAsyncComponent(() => import("./views/ReferenceLearningView.vue")),
  interop: defineAsyncComponent(() => import("./views/InteropCenterView.vue")),
  config: defineAsyncComponent(() => import("./views/SystemConfigView.vue")),
};

const { activeView, views, navigate } = useShellRouter();
const notices = ref([]);
const noticeTimers = new Map();
const NOTICE_TTL_MS = 10000;
const NOTICE_LIMIT = 3;

const activeViewComponent = computed(() => VIEW_COMPONENTS[activeView.value] || VIEW_COMPONENTS.workbench);

// Legacy route markers kept as source anchors for shell registration tests:
// activeView === 'author'
// activeView === 'trash'
// activeView === 'interop'

function formatNotice(message) {
  if (!message) {
    return "";
  }
  const text = String(message).trim();
  if (text.startsWith("profile ready")) {
    return "参考书画像已生成。下一步：选择应用范围，并创建审核项。";
  }
  if (text.startsWith("started ")) {
    return "学习任务已启动。下一步：点击「继续分析」生成候选卡。";
  }
  if (text.startsWith("round ") && text.includes("waiting for review")) {
    return "新一轮候选卡已生成，请审核下方卡片。";
  }
  return text.length > 180 ? `${text.slice(0, 177)}...` : text;
}

function noticeKind(message) {
  const text = String(message || "");
  if (
    text.includes("已移入作者回收站")
    || text.includes("已恢复")
    || text.includes("已彻底清理")
    || text.toLowerCase().includes("trash")
    || text.toLowerCase().includes("restore")
    || text.toLowerCase().includes("purge")
  ) {
    return "trash";
  }
  return text;
}

function removeNotice(id) {
  const timer = noticeTimers.get(id);
  if (timer) {
    clearTimeout(timer);
    noticeTimers.delete(id);
  }
  notices.value = notices.value.filter((notice) => notice.id !== id);
}

function pushNotice(message) {
  const text = formatNotice(message);
  if (!text) {
    return;
  }
  const kind = noticeKind(text);
  const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  notices.value
    .filter((notice) => notice.message === text || notice.kind === kind)
    .forEach((notice) => removeNotice(notice.id));
  const nextNotices = [{ id, kind, message: text, createdAt: Date.now() }, ...notices.value];
  nextNotices.slice(NOTICE_LIMIT).forEach((notice) => removeNotice(notice.id));
  notices.value = nextNotices.slice(0, NOTICE_LIMIT);
  noticeTimers.set(
    id,
    setTimeout(() => {
      removeNotice(id);
    }, NOTICE_TTL_MS),
  );
}

onBeforeUnmount(() => {
  noticeTimers.forEach((timer) => clearTimeout(timer));
  noticeTimers.clear();
});

</script>

<template>
  <div class="shell">
    <aside class="rail">
      <div class="brand">
        <div class="eyebrow">P2 编辑运营台</div>
        <h1>小说系统控制台</h1>
        <p>把作者编排、运行时审核与索引协作收拢到同一个共享指挥台。</p>
      </div>

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
    </aside>

    <main class="stage">
      <div v-if="notices.length" class="notice-stack stage-notices shell-notices" data-testid="notice-stack">
        <div v-for="notice in notices" :key="notice.id" class="notice">
          {{ notice.message }}
        </div>
      </div>

      <div class="view-stack">
        <Transition name="view-fade">
          <KeepAlive>
            <component :is="activeViewComponent" :key="activeView" class="view-frame" @notice="pushNotice" />
          </KeepAlive>
        </Transition>
      </div>
    </main>
  </div>
</template>
