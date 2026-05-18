<script setup>
import { computed } from "vue";

import { useUiMode } from "../composables/useUiMode";
import { useShellRouter, workflowGroups } from "../router";

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
const stageLabel = computed(() => {
  const stage = workflowGroups.find((group) => group.id === meta.value.stage);
  return stage?.label || meta.value.stage || "";
});
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
        <span>{{ kicker || stageLabel }}</span>
      </div>
      <h1>{{ meta.stepLabel }}</h1>
      <p v-if="isAdvancedMode">
        <strong>{{ meta.legacyLabel }}</strong>
        <span v-if="meta.description"> / {{ meta.description }}</span>
      </p>
      <p v-else>{{ meta.description }}</p>
      <dl
        v-if="!isAdvancedMode && (meta.writerGoal || meta.writerDoneSignal)"
        class="workflow-writer-aim"
        :data-testid="`workflow-writer-aim-${viewId}`"
      >
        <div v-if="meta.writerGoal"><dt>目标</dt><dd>{{ meta.writerGoal }}</dd></div>
        <div v-if="meta.writerDoneSignal"><dt>完成信号</dt><dd>{{ meta.writerDoneSignal }}</dd></div>
      </dl>
      <div
        v-if="isAdvancedMode"
        class="workflow-advanced-meta"
        :data-testid="`workflow-advanced-meta-${viewId}`"
      >
        <span>view: {{ meta.id }}</span>
        <span>cache: {{ meta.cacheMode || "none" }}</span>
        <span>stage: {{ meta.stage }}</span>
      </div>
    </div>
    <div v-if="isAdvancedMode && nextViews.length" class="workflow-next">
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
