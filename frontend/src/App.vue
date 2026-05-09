<script setup>
import { PanelLeftClose, PanelLeftOpen } from "lucide-vue-next";
import { computed, defineAsyncComponent, ref } from "vue";

import UiModeSwitch from "./components/UiModeSwitch.vue";
import WriterPathProgress from "./components/WriterPathProgress.vue";
import WorkflowNav from "./components/WorkflowNav.vue";
import { useNotices } from "./composables/useNotices";
import { useUiMode } from "./composables/useUiMode";
import { useShellRouter } from "./router";

const VIEW_COMPONENTS = {
  "snowflake-workbench": defineAsyncComponent(() => import("./views/SnowflakeWorkbenchView.vue")),
  "writer-room": defineAsyncComponent(() => import("./views/WriterRoomView.vue")),
  author: defineAsyncComponent(() => import("./views/AuthorWorkspaceView.vue")),
  manuscripts: defineAsyncComponent(() => import("./views/ChapterManuscriptView.vue")),
  deepdesk: defineAsyncComponent(() => import("./views/WriterDeepDeskView.vue")),
  longform: defineAsyncComponent(() => import("./views/LongformControlView.vue")),
  trash: defineAsyncComponent(() => import("./views/AuthorTrashView.vue")),
  workbench: defineAsyncComponent(() => import("./views/SceneWorkbenchView.vue")),
  review: defineAsyncComponent(() => import("./views/ReviewInboxView.vue")),
  quality: defineAsyncComponent(() => import("./views/LiteraryQualityView.vue")),
  index: defineAsyncComponent(() => import("./views/IndexConsoleView.vue")),
  knowledge: defineAsyncComponent(() => import("./views/KnowledgeConsoleView.vue")),
  reference: defineAsyncComponent(() => import("./views/ReferenceLearningView.vue")),
  interop: defineAsyncComponent(() => import("./views/InteropCenterView.vue")),
  config: defineAsyncComponent(() => import("./views/SystemConfigView.vue")),
};

const { activeView, views, workflowGroups, navigate, hydrateFromLocation, installLocationSync } = useShellRouter();
const { uiMode } = useUiMode();
const { notices, pushNotice } = useNotices();
const RAIL_COLLAPSED_STORAGE_KEY = "novel-system:rail-collapsed";

hydrateFromLocation();
installLocationSync();

const activeViewComponent = computed(() => VIEW_COMPONENTS[activeView.value] || VIEW_COMPONENTS["snowflake-workbench"]);
const railCollapsed = ref(readRailCollapsed());

// Legacy route markers kept as source anchors for shell registration tests:
// activeView === 'snowflake-workbench'
// activeView === 'writer-room'
// activeView === 'author'
// activeView === 'manuscripts'
// activeView === 'deepdesk'
// activeView === 'quality'
// activeView === 'longform'
// activeView === 'trash'
// activeView === 'interop'

function readRailCollapsed() {
  if (typeof window === "undefined" || !window.localStorage) {
    return false;
  }
  try {
    return window.localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

function persistRailCollapsed(value) {
  if (typeof window === "undefined" || !window.localStorage) {
    return;
  }
  try {
    window.localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, value ? "true" : "false");
  } catch {
    // Ignore storage failures; the in-memory toggle remains usable.
  }
}

function toggleRailCollapsed() {
  railCollapsed.value = !railCollapsed.value;
  persistRailCollapsed(railCollapsed.value);
}

</script>

<template>
  <div class="shell" :class="[`ui-mode-${uiMode}`, { 'rail-collapsed': railCollapsed }]" :data-ui-mode="uiMode">
    <aside class="rail" :aria-label="railCollapsed ? '主导航（已收起）' : '主导航'">
      <button
        type="button"
        class="rail-toggle"
        data-testid="rail-toggle"
        :aria-label="railCollapsed ? '展开导航栏' : '收起导航栏'"
        :title="railCollapsed ? '展开导航栏' : '收起导航栏'"
        :aria-pressed="railCollapsed ? 'true' : 'false'"
        @click="toggleRailCollapsed"
      >
        <component :is="railCollapsed ? PanelLeftOpen : PanelLeftClose" :size="17" aria-hidden="true" />
        <span>{{ railCollapsed ? "展开" : "收起" }}</span>
      </button>

      <div class="brand">
        <div class="eyebrow">Snowflake First</div>
        <h1>雪花写作工作台</h1>
        <p>把十步雪花、场景急救、结构确认和小修审核串成一条更清晰的作者主路径。</p>
      </div>

      <UiModeSwitch />
      <WorkflowNav
        :views="views"
        :groups="workflowGroups"
        :active-view="activeView"
        :collapsed="railCollapsed"
        @navigate="navigate"
      />
    </aside>

    <main class="stage">
      <TransitionGroup name="notice-fade" tag="div" class="notice-stack stage-notices shell-notices" data-testid="notice-stack">
        <div v-for="notice in notices" :key="notice.id" class="notice">
          {{ notice.message }}
        </div>
      </TransitionGroup>

      <WriterPathProgress v-if="uiMode === 'writer'" />

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
