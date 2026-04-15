<script setup>
defineProps({
  items: {
    type: Array,
    default: () => [],
  },
});

const STATUS_LABELS = {
  pending: "待处理",
  running: "进行中",
  succeeded: "成功",
  failed: "失败",
  archived: "已归档",
};

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}
</script>

<template>
  <div class="timeline" data-testid="attempt-timeline">
    <div v-if="!items.length" class="empty">还没有执行尝试记录。</div>
    <div v-for="item in items" :key="item.attempt_id || item.step" class="attempt">
      <div class="attempt-step">{{ item.step }}</div>
      <div class="attempt-body">
        <div>{{ formatStatus(item.status) }}</div>
        <div class="muted">{{ item.source_bundle_id || "预构包" }}</div>
      </div>
    </div>
  </div>
</template>
