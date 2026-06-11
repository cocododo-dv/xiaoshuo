<script setup>
import { computed } from "vue";

import { useUiMode } from "../composables/useUiMode";
import { RAIL_GROUPS, railLabel } from "../lib/railGroups";
import { iconForView } from "../lib/viewIcons";

const props = defineProps({
  views: {
    type: Array,
    required: true,
  },
  groups: {
    type: Array,
    required: true,
  },
  activeView: {
    type: String,
    required: true,
  },
  collapsed: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["navigate"]);
const { isAdvancedMode } = useUiMode();

const viewMap = computed(() => Object.fromEntries(props.views.map((view) => [view.id, view])));

const visibleGroups = computed(() =>
  RAIL_GROUPS.filter((group) => !group.advanced || isAdvancedMode.value)
    .map((group) => ({
      ...group,
      items: group.items
        .filter((item) => viewMap.value[item.id])
        .map((item) => ({ ...item, view: viewMap.value[item.id] })),
    }))
    .filter((group) => group.items.length),
);

const flatItems = computed(() => visibleGroups.value.flatMap((group) => group.items.map((item) => ({ ...item, groupLabel: group.label }))));

function labelFor(item) {
  return item.label || railLabel(item.id) || item.view?.label || item.id;
}
</script>

<template>
  <nav class="workflow-nav" aria-label="主导航" data-testid="workflow-nav">
    <label class="workflow-nav-mobile" data-testid="workflow-nav-mobile">
      <span>当前页面</span>
      <select
        class="mobile-nav-select"
        :value="activeView"
        data-testid="workflow-nav-mobile-select"
        @change="emit('navigate', $event.target.value)"
      >
        <option v-for="item in flatItems" :key="`mobile-${item.id}`" :value="item.id">
          {{ labelFor(item) }} / {{ item.groupLabel }}
        </option>
      </select>
    </label>

    <div class="ws-nav-scroll workflow-nav-desktop-list" data-testid="workflow-nav-desktop-list">
      <div v-for="group in visibleGroups" :key="group.id" class="ws-nav-group">
        <div class="ws-nav-label">{{ group.label }}</div>
        <button
          v-for="item in group.items"
          :key="item.id"
          type="button"
          class="ws-item"
          :class="{ 'is-active': activeView === item.id }"
          :aria-current="activeView === item.id ? 'page' : undefined"
          :aria-label="labelFor(item)"
          :title="labelFor(item)"
          :data-testid="`nav-${item.id}`"
          @click="emit('navigate', item.id)"
        >
          <span class="ws-item-ic" aria-hidden="true">
            <component :is="iconForView(item.view)" :size="19" />
          </span>
          <span class="ws-item-label">{{ labelFor(item) }}</span>
        </button>
      </div>
    </div>
  </nav>
</template>
