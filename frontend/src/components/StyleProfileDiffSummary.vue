<script setup>
const props = defineProps({
  summary: {
    type: Object,
    default: null,
  },
  testId: {
    type: String,
    default: "style-profile-diff-summary",
  },
});

const STATUS_LABELS = {
  added: "新增",
  changed: "修改",
  removed: "移除",
};
</script>

<template>
  <section
    v-if="props.summary?.available"
    class="style-profile-diff-summary"
    :data-testid="props.testId"
  >
    <div class="style-profile-summary-head">
      <div>
        <strong>批准前差异</strong>
        <p class="muted">{{ props.summary.baselineLabel }}</p>
      </div>
      <span class="badge">
        +{{ props.summary.counts.added }} / ~{{ props.summary.counts.changed }} / -{{ props.summary.counts.removed }}
      </span>
    </div>

    <ol class="style-profile-diff-list">
      <li v-for="row in props.summary.rows" :key="`${row.key}-${row.status}`" :data-status="row.status">
        <span class="badge">{{ STATUS_LABELS[row.status] || row.status }}</span>
        <div>
          <strong>{{ row.label }}</strong>
          <small v-if="row.before.length">当前：{{ row.before.join("；") }}</small>
          <small v-if="row.after.length">候选：{{ row.after.join("；") }}</small>
        </div>
      </li>
    </ol>
  </section>
</template>
