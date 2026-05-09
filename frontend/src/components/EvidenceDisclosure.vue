<script setup>
import { computed, ref, watch } from "vue";

import { useUiMode } from "../composables/useUiMode";

const props = defineProps({
  title: {
    type: String,
    required: true,
  },
  summary: {
    type: String,
    default: "",
  },
  testId: {
    type: String,
    default: "",
  },
  initiallyOpen: {
    type: Boolean,
    default: false,
  },
});

const { isAdvancedMode } = useUiMode();
const expanded = ref(props.initiallyOpen || isAdvancedMode.value);
const bodyId = computed(() => {
  const source = props.testId || props.title || "evidence-disclosure";
  return `${source.replace(/[^a-zA-Z0-9_-]+/g, "-")}-body`;
});

watch(isAdvancedMode, (advanced) => {
  expanded.value = advanced || props.initiallyOpen;
});

const buttonLabel = computed(() => (expanded.value ? "收起证据" : "查看证据"));
</script>

<template>
  <section
    class="evidence-disclosure"
    :class="{ 'evidence-disclosure-advanced': isAdvancedMode }"
    :data-testid="testId || undefined"
  >
    <div class="evidence-disclosure-head">
      <div>
        <h3>{{ title }}</h3>
        <p v-if="summary" class="muted">{{ summary }}</p>
      </div>
      <button
        type="button"
        class="ghost evidence-disclosure-toggle"
        :data-testid="testId ? `${testId}-toggle` : undefined"
        :aria-expanded="expanded ? 'true' : 'false'"
        :aria-controls="bodyId"
        @click="expanded = !expanded"
      >
        {{ buttonLabel }}
      </button>
    </div>
    <div v-show="expanded" :id="bodyId" class="evidence-disclosure-body">
      <slot />
    </div>
  </section>
</template>
