<script setup>
import { computed } from "vue";
import BaseBadge from "../base/BaseBadge.vue";

const props = defineProps({
  sample: {
    type: Object,
    required: true,
  },
  report: {
    type: Object,
    default: null,
  },
});

// `report` 优先(PR-7 完整 4 路);否则降级到 sample(PR-5 简化态)
const effective = computed(() => props.report || props.sample || {});

const verdict = computed(() => effective.value.verdict || "");
const mode = computed(() => effective.value.mode_executed || "");

const verdictTone = computed(() => {
  switch (verdict.value) {
    case "pass": return "success";
    case "partial": return "warning";
    case "fail": return "danger";
    case "plagiarism": return "danger";
    case "": return "neutral";
    default: return "neutral";
  }
});

const verdictLabel = computed(() => {
  if (effective.value.error) return "降级失败";
  switch (verdict.value) {
    case "pass": return "通过";
    case "partial": return "部分通过";
    case "fail": return "未通过";
    case "plagiarism": return "抄袭命中";
    case "": return "等待中";
    default: return verdict.value || "未知";
  }
});

const plagiarismHits = computed(() => {
  const plag = effective.value.plagiarism_json || effective.value.plagiarism || {};
  return Array.isArray(plag.hits) ? plag.hits : [];
});

const forbiddenHits = computed(() => effective.value.forbidden_hits_json || effective.value.forbidden_hits || []);
const quantitative = computed(() => effective.value.quantitative_json || effective.value.quantitative || []);
const semantic = computed(() => effective.value.semantic_json || effective.value.semantic || []);

const quantitativeFailed = computed(() => quantitative.value.filter((q) => !q.passed));
const quantitativeFailedCount = computed(() => quantitativeFailed.value.length);

function barWidth(q) {
  // deviation_ratio 1.0 = 边界,>1 = fail;映射到 0-100% 进度条(超 100% 截至 100)
  const ratio = q.deviation_ratio ?? 0;
  return Math.min(100, ratio * 100).toFixed(0);
}
</script>

<template>
  <section class="validation-report">
    <header class="report-head">
      <BaseBadge :tone="verdictTone">{{ verdictLabel }}</BaseBadge>
      <span v-if="sample.paragraph_type" class="report-hint">{{ sample.paragraph_type }}</span>
      <span v-if="mode" class="mode-tag">{{ mode }}</span>
    </header>

    <p v-if="effective.error || sample.error" class="report-error">
      该段示例生成失败:{{ effective.error || sample.error }}。
    </p>

    <!-- Plagiarism hits -->
    <div v-if="plagiarismHits.length > 0" class="hits-block hits-danger">
      <p class="hits-title">抄袭命中({{ plagiarismHits.length }})</p>
      <ul class="hits-list">
        <li v-for="hit in plagiarismHits" :key="hit.position">
          <code class="hit-snippet">{{ hit.matched_text }}</code>
          <span class="hit-meta">{{ hit.matched_length }} 字 @ pos {{ hit.position }}</span>
        </li>
      </ul>
    </div>

    <!-- Forbidden hits -->
    <div v-if="forbiddenHits.length > 0" class="hits-block hits-warn">
      <p class="hits-title">禁忌模式命中({{ forbiddenHits.length }})</p>
      <ul class="hits-list">
        <li v-for="hit in forbiddenHits" :key="hit.pattern_statement">
          <strong>{{ hit.pattern_statement }}</strong>
          <span v-if="hit.matched_excerpt" class="hit-meta">「{{ hit.matched_excerpt }}」</span>
        </li>
      </ul>
    </div>

    <!-- Quantitative bars -->
    <div v-if="quantitative.length > 0" class="quant-block">
      <p class="hits-title">
        硬指标({{ quantitative.length - quantitativeFailedCount }} / {{ quantitative.length }} 通过)
      </p>
      <div v-for="q in quantitativeFailed" :key="q.metric" class="quant-row">
        <span class="quant-label">{{ q.metric }}</span>
        <span class="quant-bar">
          <span class="quant-bar-fill" :style="{ width: barWidth(q) + '%' }" />
        </span>
        <span class="quant-value">
          target {{ Number(q.target_mean).toFixed(2) }} ± {{ Number(q.tolerance).toFixed(2) }} ·
          actual {{ Number(q.actual).toFixed(2) }}
        </span>
      </div>
    </div>

    <!-- Semantic scores -->
    <div v-if="semantic.length > 0" class="semantic-block">
      <p class="hits-title">语义评分</p>
      <div v-for="s in semantic" :key="s.dimension" class="semantic-row">
        <header class="semantic-head">
          <strong>{{ s.dimension }}</strong>
          <span class="semantic-score">{{ Number(s.score).toFixed(1) }} / 10</span>
          <span v-if="!s.quotes_found" class="semantic-warn">无引文,已截至 4</span>
        </header>
        <p class="semantic-explanation">{{ s.explanation }}</p>
      </div>
    </div>

    <p v-if="quantitative.length === 0 && semantic.length === 0 && plagiarismHits.length === 0 && forbiddenHits.length === 0 && !effective.error" class="report-note">
      PR-5 简化态:plagiarism + 字面 banned_terms 双层最低限度校验;PR-7 之后 quantitative / semantic 由完整 ValidationOrchestrator 填充。
    </p>
  </section>
</template>

<style scoped>
.validation-report {
  display: grid;
  gap: 0.55rem;
  padding: 0.7rem 0.85rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.12));
  border-radius: var(--radius-md, 6px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 88%, transparent);
}
.report-head { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; }
.report-hint { font-size: 0.78rem; color: var(--text-muted, rgba(33, 26, 21, 0.6)); }
.mode-tag {
  font-size: 0.7rem;
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill, 999px);
  background: rgba(0, 0, 0, 0.05);
  color: var(--text-muted, rgba(33, 26, 21, 0.62));
}
.report-error { margin: 0; color: #9a3434; font-size: 0.82rem; }
.report-note { margin: 0; font-size: 0.74rem; color: var(--text-muted, rgba(33, 26, 21, 0.55)); }

.hits-block { display: grid; gap: 0.3rem; }
.hits-title { margin: 0; font-weight: 600; font-size: 0.82rem; color: var(--text-muted, rgba(33, 26, 21, 0.7)); }
.hits-list { margin: 0; padding-left: 1rem; display: grid; gap: 0.2rem; font-size: 0.86rem; }
.hits-danger { color: #8a2c2c; }
.hits-warn { color: #946f1b; }
.hit-snippet {
  display: inline-block;
  padding: 0.05rem 0.3rem;
  border-radius: var(--radius-sm, 4px);
  background: rgba(0, 0, 0, 0.06);
  font-family: var(--font-mono, monospace);
}
.hit-meta { font-size: 0.74rem; color: var(--text-muted, rgba(33, 26, 21, 0.6)); margin-left: 0.4rem; }

.quant-block { display: grid; gap: 0.3rem; }
.quant-row { display: grid; grid-template-columns: 9rem 1fr auto; gap: 0.45rem; align-items: center; font-size: 0.78rem; }
.quant-label { font-family: var(--font-mono, monospace); }
.quant-bar {
  height: 0.5rem;
  background: rgba(0, 0, 0, 0.08);
  border-radius: var(--radius-pill, 999px);
  position: relative;
  overflow: hidden;
}
.quant-bar-fill {
  display: block;
  height: 100%;
  background: linear-gradient(to right, #d4a73c, #c14848);
}
.quant-value { color: var(--text-muted, rgba(33, 26, 21, 0.62)); }

.semantic-block { display: grid; gap: 0.5rem; }
.semantic-row { display: grid; gap: 0.25rem; }
.semantic-head { display: flex; align-items: baseline; gap: 0.5rem; font-size: 0.84rem; }
.semantic-score { font-weight: 700; color: #3f7748; }
.semantic-warn { font-size: 0.72rem; color: #946f1b; }
.semantic-explanation { margin: 0; font-size: 0.84rem; line-height: 1.55; color: var(--text-muted, rgba(33, 26, 21, 0.78)); }
</style>
