<script setup>
import { computed } from "vue";

const props = defineProps({
  pagination: {
    type: Object,
    default: () => null,
  },
  canPrevious: {
    type: Boolean,
    default: false,
  },
  canNext: {
    type: Boolean,
    default: false,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  testIdPrefix: {
    type: String,
    default: "cursor-pager",
  },
});

defineEmits(["previous", "next"]);

const summary = computed(() => {
  const pagination = props.pagination || {};
  const returned = pagination.returned ?? 0;
  const total = pagination.total ?? 0;
  if (pagination.mode === "page" && pagination.page) {
    return `Page ${pagination.page} - ${returned} of ${total}`;
  }
  return `Showing ${returned} of ${total}`;
});
</script>

<template>
  <div class="cursor-pager" :data-testid="testIdPrefix">
    <button
      class="ghost"
      :data-testid="`${testIdPrefix}-previous`"
      :disabled="disabled || !canPrevious"
      @click="$emit('previous')"
    >
      Previous
    </button>
    <span class="muted cursor-pager-summary" :data-testid="`${testIdPrefix}-summary`">
      {{ summary }}
    </span>
    <button
      :data-testid="`${testIdPrefix}-next`"
      :disabled="disabled || !canNext"
      @click="$emit('next')"
    >
      Next
    </button>
  </div>
</template>
