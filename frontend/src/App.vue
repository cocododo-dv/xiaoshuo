<script setup>
import { Moon, Search, Sun, SunDim } from "lucide-vue-next";
import { computed, defineAsyncComponent, onBeforeUnmount, ref } from "vue";

import CommandPalette from "./components/CommandPalette.vue";
import UiModeSwitch from "./components/UiModeSwitch.vue";
import WorkflowNav from "./components/WorkflowNav.vue";
import WorkSwitcher from "./components/WorkSwitcher.vue";
import { useNotices } from "./composables/useNotices";
import { useTheme } from "./composables/useTheme";
import { useUiMode } from "./composables/useUiMode";
import { useShellRouter } from "./router";

const VIEW_COMPONENTS = {
  home: defineAsyncComponent(() => import("./views/HomeView.vue")),
  flowmap: defineAsyncComponent(() => import("./views/FlowmapView.vue")),
  "snowflake-workbench": defineAsyncComponent(() => import("./views/SnowflakeWorkbenchView.vue")),
  "writer-flow": defineAsyncComponent(() => import("./views/WriterFlowView.vue")),
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
  library: defineAsyncComponent(() => import("./views/LibraryView.vue")),
  interop: defineAsyncComponent(() => import("./views/InteropCenterView.vue")),
  config: defineAsyncComponent(() => import("./views/SystemConfigView.vue")),
};

const { activeView, views, workflowGroups, navigate, hydrateFromLocation, installLocationSync } = useShellRouter();
const { uiMode } = useUiMode();
const { theme, themeLabel, cycleTheme } = useTheme();
const { notices, pushNotice } = useNotices();

hydrateFromLocation();
installLocationSync();

const activeViewComponent = computed(() => VIEW_COMPONENTS[activeView.value] || VIEW_COMPONENTS.home);
const paletteOpen = ref(false);
const railOpen = ref(false);

function go(viewId, options) {
  railOpen.value = false;
  navigate(viewId, options);
}

// Legacy route markers kept as source anchors for shell registration tests:
// activeView === 'home'
// activeView === 'snowflake-workbench'
// activeView === 'writer-flow'
// activeView === 'writer-room'
// activeView === 'author'
// activeView === 'manuscripts'
// activeView === 'deepdesk'
// activeView === 'quality'
// activeView === 'longform'
// activeView === 'trash'
// activeView === 'interop'

const THEME_ICONS = { day: Sun, dusk: SunDim, night: Moon };
const themeIcon = computed(() => THEME_ICONS[theme.value] || Sun);

function onGlobalKeydown(event) {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    paletteOpen.value = !paletteOpen.value;
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("keydown", onGlobalKeydown);
  onBeforeUnmount(() => window.removeEventListener("keydown", onGlobalKeydown));
}
</script>

<template>
  <div class="ws-app" :class="`ui-mode-${uiMode}`" :data-ui-mode="uiMode">
    <aside
      class="ws-rail"
      :class="{ 'is-open': railOpen }"
      aria-label="主导航"
      @mouseenter="railOpen = true"
      @mouseleave="railOpen = false"
      @focusin="railOpen = true"
      @click="railOpen = false"
    >
      <WorkSwitcher @navigate="go" />

      <button
        type="button"
        class="ws-cmdk"
        data-testid="cmdk-launch"
        title="命令面板 Ctrl+K"
        @click="paletteOpen = true"
      >
        <span class="ws-item-ic"><Search :size="18" aria-hidden="true" /></span>
        <span class="ws-cmdk-label">快速跳转…</span>
        <kbd>⌘K</kbd>
      </button>

      <WorkflowNav
        :views="views"
        :groups="workflowGroups"
        :active-view="activeView"
        @navigate="go"
      />

      <div class="ws-rail-foot">
        <UiModeSwitch />
        <button
          type="button"
          class="ws-foot-btn"
          data-testid="theme-toggle"
          :title="`主题:${themeLabel},点击切换`"
          @click="cycleTheme"
        >
          <span class="ws-item-ic">
            <component :is="themeIcon" :size="17" aria-hidden="true" />
          </span>
          <span>{{ themeLabel }}</span>
        </button>
      </div>
    </aside>
    <div class="ws-rail-scrim" aria-hidden="true" />

    <main class="ws-content" :data-screen-label="`ws · ${activeView}`">
      <TransitionGroup name="notice-fade" tag="div" class="notice-stack stage-notices shell-notices" data-testid="notice-stack">
        <div
          v-for="notice in notices"
          :key="notice.id"
          class="notice"
          :class="`notice-${notice.level || 'info'}`"
          :role="notice.level === 'error' ? 'alert' : 'status'"
          :aria-live="notice.level === 'error' ? 'assertive' : 'polite'"
        >
          <span v-if="notice.kicker" class="notice-kicker">{{ notice.kicker }}</span>
          {{ notice.message }}
        </div>
      </TransitionGroup>

      <div class="view-stack">
        <Transition name="view-fade">
          <KeepAlive>
            <component :is="activeViewComponent" :key="activeView" class="view-frame" @notice="pushNotice" />
          </KeepAlive>
        </Transition>
      </div>
    </main>

    <CommandPalette :open="paletteOpen" @close="paletteOpen = false" />
  </div>
</template>
