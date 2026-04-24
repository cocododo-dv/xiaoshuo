<script setup>
import { ref, watch } from "vue";

import { useUiMode } from "../composables/useUiMode";

const props = defineProps({
  title: {
    type: String,
    required: true,
  },
  toggleTestId: {
    type: String,
    default: "",
  },
  collapsedLabel: {
    type: String,
    default: "展开",
  },
  expandedLabel: {
    type: String,
    default: "收起",
  },
  initiallyOpen: {
    type: Boolean,
    default: false,
  },
});

const { isAdvancedMode } = useUiMode();
const expanded = ref(props.initiallyOpen || isAdvancedMode.value);

watch(isAdvancedMode, (advanced) => {
  expanded.value = advanced || props.initiallyOpen;
});
</script>

<template>
  <section class="history-stack lazy-section">
    <div class="lazy-section-head">
      <p class="history-title">{{ props.title }}</p>
      <button
        type="button"
        class="ghost lazy-section-toggle"
        :data-testid="props.toggleTestId || undefined"
        @click="expanded = !expanded"
      >
        {{ expanded ? props.expandedLabel : props.collapsedLabel }}
      </button>
    </div>
    <div v-if="expanded" class="lazy-section-body">
      <slot />
    </div>
  </section>
</template>
