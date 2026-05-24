<script setup>
defineProps({
  confidence: {
    type: String,
    default: "skip",
    validator: (value) => ["high", "medium", "low", "skip"].includes(value),
  },
});
</script>

<template>
  <span class="confidence-bar" :class="`confidence-${confidence}`" :aria-label="`置信度 ${confidence}`">
    <span class="confidence-fill" :class="`fill-${confidence}`" />
    <span class="confidence-label">{{ confidence }}</span>
  </span>
</template>

<style scoped>
.confidence-bar {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.confidence-fill {
  display: inline-block;
  width: 2.2rem;
  height: 0.45rem;
  border-radius: var(--radius-pill, 999px);
  background: rgba(0, 0, 0, 0.08);
  position: relative;
  overflow: hidden;
}

.fill-high::after { content: ""; position: absolute; inset: 0; width: 100%; background: #2f8a4d; }
.fill-medium::after { content: ""; position: absolute; inset: 0; width: 66%; background: #6cba79; }
.fill-low::after { content: ""; position: absolute; inset: 0; width: 33%; background: #d4a73c; }
.fill-skip::after { content: ""; position: absolute; inset: 0; width: 100%; background: rgba(0, 0, 0, 0.12); }

.confidence-label { color: var(--text-muted, rgba(33, 26, 21, 0.58)); }
.confidence-high .confidence-label { color: #1e6a39; }
.confidence-medium .confidence-label { color: #3f7748; }
.confidence-low .confidence-label { color: #946f1b; }
</style>
