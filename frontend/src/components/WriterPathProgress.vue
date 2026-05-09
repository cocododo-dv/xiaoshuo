<script setup>
import { computed } from "vue";

import { useWriterPathProgress, WRITER_PATH_STATUS_LABELS } from "../composables/useWriterPathProgress";

const { items, activeItem, navigateToItem } = useWriterPathProgress();

const activeSummary = computed(() => {
  if (!activeItem.value) {
    return "作家主路径准备就绪。";
  }
  const label = activeItem.value.isActive ? `当前：${activeItem.value.label}` : `优先：${activeItem.value.label}`;
  return `${label}。${activeItem.value.summary} 下一步：${activeItem.value.nextAction}`;
});

function statusLabel(status) {
  return WRITER_PATH_STATUS_LABELS[status] || status || "进行中";
}
</script>

<template>
  <section class="writer-path-progress" data-testid="writer-path-progress" aria-label="作家主路径任务条">
    <div class="writer-path-head">
      <div>
        <span class="eyebrow">Writer Path</span>
        <h2>作家主路径</h2>
      </div>
      <p
        class="writer-path-active-summary"
        data-testid="writer-path-active-summary"
        role="status"
        aria-live="polite"
      >
        {{ activeSummary }}
      </p>
    </div>

    <div class="writer-path-list">
      <button
        v-for="item in items"
        :key="item.viewId"
        type="button"
        class="writer-path-item"
        :class="[`writer-path-${item.status}`, { active: item.isActive }]"
        :data-testid="`writer-path-item-${item.viewId}`"
        :aria-current="item.isActive ? 'step' : undefined"
        @click="navigateToItem(item)"
      >
        <span class="writer-path-item-top">
          <strong>{{ item.label }}</strong>
          <span class="writer-path-status">{{ statusLabel(item.status) }}</span>
        </span>
        <span class="writer-path-summary">{{ item.summary }}</span>
        <span class="writer-path-next">下一步：{{ item.nextAction }}</span>
        <span class="writer-path-count">{{ item.countLabel }}</span>
      </button>
    </div>
  </section>
</template>
