<script setup>
import {
  BookOpenCheck,
  ClipboardCheck,
  Files,
  GraduationCap,
  Library,
  PenLine,
  PlayCircle,
  Settings2,
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
});

const emit = defineEmits(["navigate"]);
const { isAdvancedMode } = useUiMode();

const ICONS = {
  BookOpenCheck,
  ClipboardCheck,
  Files,
  GraduationCap,
  Library,
  PenLine,
  PlayCircle,
  Settings2,
  Trash2,
  UploadCloud,
};

const groupMap = computed(() => Object.fromEntries(props.groups.map((group) => [group.id, group])));
const orderedRows = computed(() =>
  props.views.map((view, index) => {
    const previous = props.views[index - 1];
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
</script>

<template>
  <nav class="workflow-nav" aria-label="工作流步骤" data-testid="workflow-nav">
    <section v-for="row in orderedRows" :key="row.view.id" class="workflow-nav-group">
      <div v-if="row.showGroup" class="workflow-nav-group-head">
        <strong>{{ row.group.label }}</strong>
        <span>{{ row.group.description }}</span>
      </div>
      <button
        type="button"
        class="workflow-nav-btn"
        :class="{ active: activeView === row.view.id }"
        :aria-current="activeView === row.view.id ? 'page' : undefined"
        :data-testid="`nav-${row.view.id}`"
        @click="emit('navigate', row.view.id)"
      >
        <span class="workflow-nav-icon" aria-hidden="true">
          <component :is="iconFor(row.view)" :size="17" />
        </span>
        <span class="workflow-nav-copy">
          <strong>{{ row.view.label }}</strong>
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
  </nav>
</template>
