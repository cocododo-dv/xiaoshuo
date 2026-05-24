<script setup>
import { computed } from "vue";
import BaseBadge from "../base/BaseBadge.vue";

const props = defineProps({
  sample: {
    type: Object,
    required: true,
  },
});

const verdictTone = computed(() => {
  switch (props.sample.verdict) {
    case "pass": return "success";
    case "partial": return "warning";
    case "fail": return "danger";
    case "plagiarism": return "danger";
    default: return "neutral";
  }
});

const verdictLabel = computed(() => {
  if (props.sample.error) return "降级失败";
  switch (props.sample.verdict) {
    case "pass": return "通过";
    case "partial": return "部分通过";
    case "fail": return "未通过";
    case "plagiarism": return "抄袭命中";
    default: return props.sample.verdict || "未知";
  }
});
</script>

<template>
  <section class="validation-report">
    <header class="report-head">
      <BaseBadge :tone="verdictTone">{{ verdictLabel }}</BaseBadge>
      <span class="report-hint">{{ sample.paragraph_type }}</span>
    </header>

    <p v-if="sample.error" class="report-error">
      该段示例生成失败:{{ sample.error }}。PR-7 完整 validation 三路并发后,UX 可降级到自动重试。
    </p>

    <p class="report-note">
      PR-5 阶段:plagiarism + 字面 banned_terms 双层最低限度校验;quantitative / semantic 待 PR-7 落齐。
    </p>
  </section>
</template>

<style scoped>
.validation-report {
  display: grid;
  gap: 0.35rem;
  padding: 0.55rem 0.75rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.12));
  border-radius: var(--radius-md, 6px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 88%, transparent);
}
.report-head { display: flex; align-items: center; gap: 0.45rem; }
.report-hint { font-size: 0.78rem; color: var(--text-muted, rgba(33, 26, 21, 0.6)); }
.report-error { margin: 0; color: #9a3434; font-size: 0.82rem; }
.report-note { margin: 0; font-size: 0.74rem; color: var(--text-muted, rgba(33, 26, 21, 0.55)); }
</style>
