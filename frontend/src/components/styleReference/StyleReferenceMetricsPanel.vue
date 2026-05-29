<script setup>
import { computed } from "vue";

const props = defineProps({
  metrics: {
    type: Object,
    default: null,
  },
  loading: {
    type: Boolean,
    default: false,
  },
  error: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["reload"]);

const WINDOW_OPTIONS = Object.freeze([
  { label: "近 7 日", hours: 168 },
  { label: "近 30 日", hours: 720 },
  { label: "全部", hours: 0 },
]);

const hasMetrics = computed(() => Boolean(props.metrics));
const sampleCounts = computed(() => props.metrics?.sample_counts || {});
const windowHours = computed(() => Number(props.metrics?.window_hours ?? 168));

function selectWindow(hours) {
  emit("reload", hours);
}

const injectionPct = computed(() => formatPercent(props.metrics?.injection_hit_rate));
const qcRejectPct = computed(() => formatPercent(props.metrics?.qc_gate_reject_rate));
const autoRewritePct = computed(() => formatPercent(props.metrics?.auto_rewrite_pass_rate));
const p95Ms = computed(() => {
  const v = props.metrics?.validation_p95_latency_ms;
  if (v === undefined || v === null) return "—";
  return `${Number(v).toFixed(0)} ms`;
});

function formatPercent(value) {
  if (value === undefined || value === null) return "—";
  const pct = Number(value) * 100;
  return `${pct.toFixed(1)}%`;
}

function barWidth(value) {
  if (value === undefined || value === null) return "0%";
  return `${Math.min(100, Math.max(0, Number(value) * 100)).toFixed(1)}%`;
}

function totalEvents() {
  const counts = sampleCounts.value || {};
  return Object.values(counts).reduce((acc, n) => acc + (Number(n) || 0), 0);
}
</script>

<template>
  <section class="sr-metrics" data-testid="style-reference-metrics-panel">
    <header class="sr-metrics-head">
      <strong>Style Reference 运营指标</strong>
      <div class="window-tabs" role="group" aria-label="时间窗口">
        <button
          v-for="opt in WINDOW_OPTIONS"
          :key="opt.hours"
          type="button"
          :class="['win-btn', { active: windowHours === opt.hours }]"
          :disabled="loading"
          :aria-pressed="windowHours === opt.hours"
          @click="selectWindow(opt.hours)"
          :data-testid="`window-${opt.hours}`"
        >
          {{ opt.label }}
        </button>
      </div>
    </header>

    <p v-if="loading" class="sr-metrics-loading" data-testid="metrics-loading">加载中…</p>
    <p v-else-if="error" class="sr-metrics-error" data-testid="metrics-error">{{ error }}</p>
    <p v-else-if="!hasMetrics" class="sr-metrics-empty" data-testid="metrics-empty">
      暂无数据。请触发 SceneCard 生成或人工 validate 后再返回查看。
    </p>
    <template v-else>
      <div class="metrics-grid">
        <article class="metric-card" data-testid="metric-injection">
          <p class="metric-label">注入命中率</p>
          <p class="metric-value">{{ injectionPct }}</p>
          <div class="metric-bar"><span :style="{ width: barWidth(metrics.injection_hit_rate) }" /></div>
          <p class="metric-hint">{{ sampleCounts.injection_invoked || 0 }} 次注入调用</p>
        </article>
        <article class="metric-card warn" data-testid="metric-qc-reject">
          <p class="metric-label">qc gate 拒绝率</p>
          <p class="metric-value">{{ qcRejectPct }}</p>
          <div class="metric-bar warn"><span :style="{ width: barWidth(metrics.qc_gate_reject_rate) }" /></div>
          <p class="metric-hint">{{ sampleCounts.qc_gate_decided || 0 }} 次门闸判决</p>
        </article>
        <article class="metric-card success" data-testid="metric-auto-rewrite">
          <p class="metric-label">auto_rewrite 通过率</p>
          <p class="metric-value">{{ autoRewritePct }}</p>
          <div class="metric-bar success"><span :style="{ width: barWidth(metrics.auto_rewrite_pass_rate) }" /></div>
          <p class="metric-hint">{{ sampleCounts.auto_rewrite_triggered || 0 }} 次触发</p>
        </article>
        <article class="metric-card neutral" data-testid="metric-p95">
          <p class="metric-label">validation P95 延迟</p>
          <p class="metric-value">{{ p95Ms }}</p>
          <p class="metric-hint">{{ sampleCounts.validation_executed || 0 }} 次执行</p>
        </article>
      </div>
      <footer class="sr-metrics-foot">
        <span>窗口:{{ windowHours === 0 ? "全部" : `${windowHours}h` }} · 共 {{ totalEvents() }} 个事件</span>
        <span v-if="metrics.computed_at" class="computed-at">采集于 {{ metrics.computed_at }}</span>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.sr-metrics {
  display: grid;
  gap: 0.55rem;
  padding: 0.7rem 0.85rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.12));
  border-radius: var(--radius-md, 6px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 88%, transparent);
}
.sr-metrics-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.4rem; }
.window-tabs { display: flex; gap: 0.3rem; }
.win-btn {
  font-size: 0.72rem;
  padding: 0.15rem 0.55rem;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: var(--radius-pill, 999px);
  background: transparent;
  cursor: pointer;
}
.win-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.win-btn.active {
  background: color-mix(in srgb, var(--color-primary, #4a90e2) 12%, transparent);
  border-color: var(--color-primary, #4a90e2);
}
.win-btn:focus-visible {
  outline: 2px solid var(--color-primary, #2f6f62);
  outline-offset: 2px;
}
/* PR-13 a11y — 提对比(原 0.6 → 0.72,≥ 4.5:1) */
.sr-metrics-loading, .sr-metrics-error, .sr-metrics-empty {
  margin: 0; font-size: 0.82rem; color: rgba(33, 26, 21, 0.72);
}
.sr-metrics-error { color: #9a3434; }
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: 0.6rem; }
.metric-card {
  display: grid;
  gap: 0.2rem;
  padding: 0.6rem 0.7rem;
  border-radius: var(--radius-sm, 4px);
  background: rgba(0, 0, 0, 0.03);
}
.metric-label { margin: 0; font-size: 0.74rem; color: rgba(33, 26, 21, 0.72); }
.metric-value { margin: 0; font-size: 1.4rem; font-weight: 700; font-family: var(--font-mono, monospace); }
/* PR-13 a11y — hint 提对比(原 0.55 → 0.72) */
.metric-hint { margin: 0; font-size: 0.7rem; color: rgba(33, 26, 21, 0.72); }
.metric-bar { height: 0.4rem; background: rgba(0, 0, 0, 0.08); border-radius: var(--radius-pill, 999px); overflow: hidden; }
.metric-bar > span { display: block; height: 100%; background: var(--color-primary, #4a90e2); transition: width 0.18s; }
.metric-bar.warn > span { background: linear-gradient(to right, #d4a73c, #c14848); }
.metric-bar.success > span { background: linear-gradient(to right, #3f7748, #5b9d63); }
.sr-metrics-foot {
  display: flex;
  justify-content: space-between;
  font-size: 0.7rem;
  color: rgba(33, 26, 21, 0.72);
}
.computed-at { font-family: var(--font-mono, monospace); }
</style>
