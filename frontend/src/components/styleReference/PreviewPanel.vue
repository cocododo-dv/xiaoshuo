<script setup>
import BaseButton from "../base/BaseButton.vue";
import BaseEmptyState from "../base/BaseEmptyState.vue";
import ValidationReportCard from "./ValidationReportCard.vue";

defineProps({
  samples: {
    type: Array,
    default: () => [],
  },
  busy: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["regenerate"]);
</script>

<template>
  <section class="preview-panel">
    <header class="panel-head">
      <p class="panel-title">3 段示例预览</p>
      <BaseButton variant="secondary" size="sm" :loading="busy" @click="emit('regenerate')">
        重新生成
      </BaseButton>
    </header>

    <BaseEmptyState
      v-if="samples.length === 0"
      title="尚未生成预览"
      description="点击「重新生成」让 profile 在 dialogue / description_env / psychology 三种段类型上各产出一段示例并验证。"
    />

    <div v-else class="sample-list">
      <article v-for="sample in samples" :key="`${sample.paragraph_type}-${sample.report_id || sample.error || 'none'}`" class="sample-item">
        <p v-if="sample.sample_text" class="sample-text">{{ sample.sample_text }}</p>
        <ValidationReportCard :sample="sample" />
      </article>
    </div>
  </section>
</template>

<style scoped>
.preview-panel { display: grid; gap: 0.8rem; }
.panel-head { display: flex; justify-content: space-between; align-items: center; }
.panel-title { margin: 0; font-weight: 700; font-size: 0.95rem; }
.sample-list { display: grid; gap: 0.7rem; }
.sample-item {
  display: grid;
  gap: 0.5rem;
  padding: 0.85rem 1rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.15));
  border-radius: var(--radius-md, 6px);
  background: var(--color-panel-solid, #fffdf7);
}
.sample-text { margin: 0; line-height: 1.65; white-space: pre-wrap; font-size: 0.95rem; }
</style>
