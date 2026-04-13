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
    return `第 ${pagination.page} 页，当前 ${returned} / 共 ${total}`;
  }
  return `当前显示 ${returned} / 共 ${total}`;
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
      上一页
    </button>
    <span class="muted cursor-pager-summary" :data-testid="`${testIdPrefix}-summary`">
      {{ summary }}
    </span>
    <button
      :data-testid="`${testIdPrefix}-next`"
      :disabled="disabled || !canNext"
      @click="$emit('next')"
    >
      下一页
    </button>
  </div>
</template>
