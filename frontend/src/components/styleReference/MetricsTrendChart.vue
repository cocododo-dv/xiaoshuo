<script setup>
import { computed } from "vue";

// PR-22 — injection 调用量每日趋势:手写 SVG 柱状图(无 Chart.js 依赖)
const props = defineProps({
  // [{ date: "YYYY-MM-DD", count: number }]
  daily: {
    type: Array,
    default: () => [],
  },
});

const VIEW_W = 320;
const VIEW_H = 64;
const GAP = 2;

const bars = computed(() => {
  const rows = Array.isArray(props.daily) ? props.daily : [];
  const n = rows.length;
  if (n === 0) return [];
  const maxCount = Math.max(1, ...rows.map((r) => Number(r.count) || 0));
  const slot = VIEW_W / n;
  const width = Math.max(1, slot - GAP);
  return rows.map((r, i) => {
    const count = Number(r.count) || 0;
    const h = count === 0 ? 0 : Math.max(1, (count / maxCount) * VIEW_H);
    return {
      date: r.date,
      count,
      x: i * slot + GAP / 2,
      y: VIEW_H - h,
      width,
      height: h,
    };
  });
});

const hasData = computed(() => bars.value.length > 0);
const peak = computed(() => bars.value.reduce((m, b) => Math.max(m, b.count), 0));
const summary = computed(
  () => `近 ${bars.value.length} 日 injection 调用量趋势,峰值 ${peak.value} 次`,
);
</script>

<template>
  <figure class="trend-chart" data-testid="metrics-trend-chart">
    <figcaption class="trend-cap">injection 调用量(每日)</figcaption>
    <p v-if="!hasData" class="trend-empty" data-testid="trend-empty">暂无趋势数据。</p>
    <svg
      v-else
      class="trend-svg"
      :viewBox="`0 0 ${VIEW_W} ${VIEW_H}`"
      preserveAspectRatio="none"
      role="img"
      :aria-label="summary"
    >
      <rect
        v-for="bar in bars"
        :key="bar.date"
        class="trend-bar"
        data-testid="trend-bar"
        :x="bar.x"
        :y="bar.y"
        :width="bar.width"
        :height="bar.height"
        :data-date="bar.date"
        :data-count="bar.count"
      >
        <title>{{ bar.date }}:{{ bar.count }} 次</title>
      </rect>
    </svg>
  </figure>
</template>

<style scoped>
.trend-chart {
  margin: 0;
  display: grid;
  gap: 0.3rem;
}
.trend-cap {
  font-size: 0.72rem;
  color: rgba(33, 26, 21, 0.72);
  font-weight: 600;
}
.trend-empty {
  margin: 0;
  font-size: 0.74rem;
  color: rgba(33, 26, 21, 0.72);
}
.trend-svg {
  width: 100%;
  height: 64px;
  display: block;
}
.trend-bar {
  fill: var(--color-primary, #4a90e2);
}
</style>
