<script setup>
import { computed } from "vue";

import { useUiMode } from "../composables/useUiMode";
import { useShellRouter } from "../router";

const props = defineProps({
  viewId: {
    type: String,
    required: true,
  },
  kicker: {
    type: String,
    default: "",
  },
});

const { navigate, viewMeta } = useShellRouter();
const { isAdvancedMode } = useUiMode();

const meta = computed(() => viewMeta(props.viewId));
const nextViews = computed(() =>
  (meta.value.nextViews || [])
    .map((viewId) => viewMeta(viewId))
    .filter(Boolean),
);
</script>

<template>
  <header class="workflow-page-header" :data-testid="`workflow-header-${viewId}`">
    <div class="workflow-page-copy">
      <div class="workflow-step-kicker">
        <span>{{ meta.label }}</span>
        <span>{{ kicker || meta.group }}</span>
      </div>
      <h1>{{ meta.stepLabel }}</h1>
      <p>
        <strong>{{ meta.legacyLabel }}</strong>
        <span v-if="meta.description"> / {{ meta.description }}</span>
      </p>
      <div
        v-if="!isAdvancedMode"
        class="workflow-guided-brief"
        :data-testid="`workflow-guided-brief-${viewId}`"
      >
        <span>当前目标</span>
        <strong>{{ meta.description }}</strong>
      </div>
      <div
        v-else
        class="workflow-advanced-meta"
        :data-testid="`workflow-advanced-meta-${viewId}`"
      >
        <span>view: {{ meta.id }}</span>
        <span>cache: {{ meta.cacheMode || "none" }}</span>
        <span>group: {{ meta.groupId || meta.group }}</span>
      </div>
    </div>
    <div v-if="nextViews.length" class="workflow-next">
      <span>常见下一步</span>
      <div class="workflow-next-actions">
        <button
          v-for="view in nextViews"
          :key="view.id"
          type="button"
          class="ghost"
          :data-testid="`workflow-next-${view.id}`"
          @click="navigate(view.id)"
        >
          {{ view.label }}
        </button>
      </div>
    </div>
  </header>
</template>
