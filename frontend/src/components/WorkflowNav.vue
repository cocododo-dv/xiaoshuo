<script setup>
import {
  BookOpenText,
  ClipboardCheck,
  Feather,
  FileInput,
  GraduationCap,
  Library,
  Microscope,
  PlayCircle,
  Radar,
  ScrollText,
  Settings2,
  ShieldCheck,
  Snowflake,
  Trash2,
  UploadCloud,
} from "lucide-vue-next";
import { computed } from "vue";

import { useUiMode } from "../composables/useUiMode";

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

const ICONS = {
  BookOpenText,
  ClipboardCheck,
  Feather,
  FileInput,
  GraduationCap,
  Library,
  Microscope,
  PlayCircle,
  Radar,
  ScrollText,
  Settings2,
  ShieldCheck,
  Snowflake,
  Trash2,
  UploadCloud,
};

const groupMap = computed(() => Object.fromEntries(props.groups.map((group) => [group.id, group])));
const visibleViews = computed(() => {
  if (isAdvancedMode.value) {
    return props.views;
  }
  return props.views
    .filter((view) => view.writerPrimary || view.id === props.activeView)
    .sort((left, right) => (left.writerOrder || 99) - (right.writerOrder || 99));
});
const orderedRows = computed(() =>
  visibleViews.value.map((view, index) => {
    const previous = visibleViews.value[index - 1];
    return {
      view,
      group: groupMap.value[view.groupId] || { label: view.group, description: "" },
      showGroup: !previous || previous.groupId !== view.groupId,
    };
  }),
);

function iconFor(view) {
  return ICONS[view.icon] || PlayCircle;
}

function labelFor(view) {
  return !isAdvancedMode.value && view.writerLabel ? view.writerLabel : view.label;
}
</script>

<template>
  <nav
    class="workflow-nav"
    :class="{ collapsed }"
    aria-label="工作流步骤导航"
    data-testid="workflow-nav"
  >
    <label class="workflow-nav-mobile" data-testid="workflow-nav-mobile">
      <span>当前步骤</span>
      <select
        class="mobile-nav-select"
        :value="activeView"
        data-testid="workflow-nav-mobile-select"
        @change="emit('navigate', $event.target.value)"
      >
        <option
          v-for="row in orderedRows"
          :key="`mobile-${row.view.id}`"
          :value="row.view.id"
        >
          {{ labelFor(row.view) }} / {{ row.group.label }}
        </option>
      </select>
    </label>

    <div class="workflow-nav-desktop-list" data-testid="workflow-nav-desktop-list">
      <section v-for="row in orderedRows" :key="row.view.id" class="workflow-nav-group">
        <div v-if="row.showGroup && !collapsed" class="workflow-nav-group-head">
          <strong>{{ row.group.label }}</strong>
          <span>{{ row.group.description }}</span>
        </div>
        <button
          type="button"
          class="workflow-nav-btn"
          :class="{ active: activeView === row.view.id }"
          :aria-current="activeView === row.view.id ? 'page' : undefined"
          :aria-label="collapsed ? labelFor(row.view) : undefined"
          :data-testid="`nav-${row.view.id}`"
          :title="collapsed ? labelFor(row.view) : undefined"
          @click="emit('navigate', row.view.id)"
        >
          <span class="workflow-nav-icon" aria-hidden="true">
            <component :is="iconFor(row.view)" :size="17" />
          </span>
          <span v-if="!collapsed" class="workflow-nav-copy">
            <strong>{{ labelFor(row.view) }}</strong>
            <small v-if="isAdvancedMode">{{ row.view.legacyLabel }}</small>
            <span
              v-if="isAdvancedMode"
              class="workflow-nav-route"
              :data-testid="`nav-${row.view.id}-route`"
            >
              view: {{ row.view.id }}
            </span>
          </span>
        </button>
      </section>
    </div>
  </nav>
</template>
