<script setup>
import { CornerDownLeft, Moon, PenLine, Search, SlidersHorizontal, Sun, SunDim } from "lucide-vue-next";
import { computed, nextTick, ref, watch } from "vue";

import { useTheme } from "../composables/useTheme";
import { useUiMode } from "../composables/useUiMode";
import { isAdvancedOnlyView, railLabel } from "../lib/railGroups";
import { iconForView } from "../lib/viewIcons";
import { useShellRouter } from "../router";

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["close"]);

const { views, navigate, activeView } = useShellRouter();
const { uiMode, isAdvancedMode, setUiMode } = useUiMode();
const { setTheme } = useTheme();

const query = ref("");
const selectedIndex = ref(0);
const inputEl = ref(null);
const listEl = ref(null);

function viewLabel(view) {
  return railLabel(view.id) || view.label;
}

const allCommands = computed(() => {
  const viewCommands = views.map((view) => ({
    id: `go:${view.id}`,
    group: "页面",
    label: viewLabel(view),
    hint: view.legacyLabel || view.id,
    keywords: `${view.label} ${view.writerLabel || ""} ${view.legacyLabel || ""} ${view.stepLabel || ""} ${view.id}`,
    icon: iconForView(view),
    run: () => {
      if (uiMode.value === "writer" && isAdvancedOnlyView(view.id)) {
        setUiMode("advanced");
      }
      navigate(view.id);
    },
  }));

  const themeCommands = [
    { id: "theme:day", label: "切换到白昼", icon: Sun, theme: "day" },
    { id: "theme:dusk", label: "切换到暮色", icon: SunDim, theme: "dusk" },
    { id: "theme:night", label: "切换到夜灯", icon: Moon, theme: "night" },
  ].map((item) => ({
    id: item.id,
    group: "外观",
    label: item.label,
    hint: "主题",
    keywords: `${item.label} theme 主题`,
    icon: item.icon,
    run: () => setTheme(item.theme),
  }));

  const modeCommands = [
    { id: "mode:writer", label: "作家模式", icon: PenLine, mode: "writer" },
    { id: "mode:advanced", label: "高级模式", icon: SlidersHorizontal, mode: "advanced" },
  ].map((item) => ({
    id: item.id,
    group: "模式",
    label: item.label,
    hint: "界面模式",
    keywords: `${item.label} mode 模式`,
    icon: item.icon,
    run: () => setUiMode(item.mode),
  }));

  return [...viewCommands, ...themeCommands, ...modeCommands];
});

const filteredCommands = computed(() => {
  const needle = query.value.trim().toLowerCase();
  if (!needle) {
    return allCommands.value;
  }
  return allCommands.value.filter((command) => command.keywords.toLowerCase().includes(needle));
});

const groupedCommands = computed(() => {
  const groups = [];
  let offset = 0;
  for (const groupName of ["页面", "外观", "模式"]) {
    const items = filteredCommands.value.filter((command) => command.group === groupName);
    if (items.length) {
      groups.push({ name: groupName, items, offset });
      offset += items.length;
    }
  }
  return groups;
});

watch(
  () => props.open,
  async (open) => {
    if (open) {
      query.value = "";
      selectedIndex.value = 0;
      await nextTick();
      inputEl.value?.focus();
    }
  },
);

watch(query, () => {
  selectedIndex.value = 0;
});

function runCommand(command) {
  emit("close");
  command.run();
}

function moveSelection(delta) {
  const total = filteredCommands.value.length;
  if (!total) {
    return;
  }
  selectedIndex.value = (selectedIndex.value + delta + total) % total;
  scrollSelectionIntoView();
}

function scrollSelectionIntoView() {
  nextTick(() => {
    listEl.value
      ?.querySelector(".pal-item.is-sel")
      ?.scrollIntoView({ block: "nearest" });
  });
}

function onKeydown(event) {
  if (event.key === "Escape") {
    event.preventDefault();
    emit("close");
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveSelection(1);
    return;
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    moveSelection(-1);
    return;
  }
  if (event.key === "Enter") {
    event.preventDefault();
    const command = filteredCommands.value[selectedIndex.value];
    if (command) {
      runCommand(command);
    }
  }
}

function isSelected(group, indexInGroup) {
  return group.offset + indexInGroup === selectedIndex.value;
}

function isActiveViewCommand(command) {
  return command.id === `go:${activeView.value}`;
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="pal-wrap"
      data-testid="command-palette"
      @mousedown.self="emit('close')"
      @keydown="onKeydown"
    >
      <div class="pal" role="dialog" aria-modal="true" aria-label="命令面板">
        <div class="pal-search">
          <Search :size="18" aria-hidden="true" />
          <input
            ref="inputEl"
            v-model="query"
            class="pal-input"
            type="text"
            placeholder="跳转页面、切换主题或模式…"
            data-testid="command-palette-input"
            aria-label="搜索命令"
          />
          <kbd class="pal-esc">Esc</kbd>
        </div>

        <div ref="listEl" class="pal-list" role="listbox">
          <template v-if="filteredCommands.length">
            <div v-for="group in groupedCommands" :key="group.name" class="pal-group">
              <div class="pal-group-h">{{ group.name }}</div>
              <button
                v-for="(command, index) in group.items"
                :key="command.id"
                type="button"
                class="pal-item"
                :class="{ 'is-sel': isSelected(group, index) }"
                role="option"
                :aria-selected="isSelected(group, index)"
                :data-testid="`command-${command.id}`"
                @mouseenter="selectedIndex = group.offset + index"
                @click="runCommand(command)"
              >
                <span class="pal-item-ic"><component :is="command.icon" :size="17" aria-hidden="true" /></span>
                <span class="pal-item-label">{{ command.label }}</span>
                <span v-if="isActiveViewCommand(command)" class="pal-item-hint">当前</span>
                <span v-else class="pal-item-hint">{{ command.hint }}</span>
                <span v-if="isSelected(group, index)" class="pal-enter">
                  <CornerDownLeft :size="15" aria-hidden="true" />
                </span>
              </button>
            </div>
          </template>
          <div v-else class="pal-empty">
            <Search :size="22" aria-hidden="true" />
            <span>没有匹配「{{ query }}」的命令</span>
          </div>
        </div>

        <div class="pal-foot">
          <span><kbd>↑</kbd><kbd>↓</kbd> 选择</span>
          <span><kbd>Enter</kbd> 前往</span>
          <span><kbd>Esc</kbd> 关闭</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>
