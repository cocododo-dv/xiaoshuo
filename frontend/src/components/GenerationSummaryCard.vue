<script setup>
defineProps({
  summary: {
    type: Object,
    default: null,
  },
});

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return value;
}
</script>

<template>
  <article class="paper" data-testid="scene-generation-summary-card">
    <h3>生成证据</h3>
    <div v-if="summary" class="evidence-card-body">
      <div class="receipt-head">
        <div>
          <p class="muted">{{ formatValue(summary.step) }}</p>
          <p v-if="summary.raw_step && summary.raw_step !== summary.step" class="muted">
            原始 step：{{ summary.raw_step }}
          </p>
        </div>
        <span class="badge">{{ formatValue(summary.provider) }}</span>
      </div>
      <p><strong>模型</strong><br />{{ formatValue(summary.model) }}</p>
      <p><strong>Prompt Hash</strong><br />{{ formatValue(summary.prompt_hash) }}</p>
      <p><strong>Token</strong><br />{{ formatValue(summary.prompt_tokens) }} / {{ formatValue(summary.completion_tokens) }} / {{ formatValue(summary.total_tokens) }}</p>
      <p><strong>Latency</strong><br />{{ formatValue(summary.latency_ms) }} ms</p>
      <p><strong>Finish Reason</strong><br />{{ formatValue(summary.finish_reason) }}</p>
      <p v-if="summary.error_code"><strong>Error Code</strong><br />{{ summary.error_code }}</p>
    </div>
    <p v-else class="muted">暂无生成证据。完成一次场景运行后，这里会展示最近一次生成调用的摘要。</p>
  </article>
</template>
