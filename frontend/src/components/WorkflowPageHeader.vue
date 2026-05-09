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
const writerBriefItems = computed(() => [
  { label: "当前目标", value: meta.value.writerGoal },
  { label: "完成信号", value: meta.value.writerDoneSignal },
  { label: "下一步", value: meta.value.writerNextAction },
].filter((item) => item.value));
const hasWriterBrief = computed(() => !isAdvancedMode.value && writerBriefItems.value.length > 0);
</script>

<template>
  <header class="workflow-page-header" :data-testid="`workflow-header-${viewId}`">
    <div class="workflow-page-copy">
      <div class="workflow-step-kicker">
        <span>{{ meta.label }}</span>
        <span>{{ kicker || meta.group }}</span>
      </div>
      <h1>{{ meta.stepLabel }}</h1>
      <p v-if="isAdvancedMode">
        <strong>{{ meta.legacyLabel }}</strong>
        <span v-if="meta.description"> / {{ meta.description }}</span>
      </p>
      <p v-else>{{ meta.description }}</p>
      <div
        v-if="hasWriterBrief"
        class="workflow-writer-brief"
        :data-testid="`workflow-writer-brief-${viewId}`"
      >
        <div v-for="item in writerBriefItems" :key="item.label" class="workflow-writer-brief-item">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
      <div
        v-else-if="!isAdvancedMode"
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
