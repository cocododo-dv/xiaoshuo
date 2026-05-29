<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  preview: {
    // 形态:{ fragments: {positive_block, forbidden_block, metric_anchor_block, strategy}, prefix: string }
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

const fragments = computed(() => props.preview?.fragments || null);
const prefix = computed(() => props.preview?.prefix || "");
const hasAnyContent = computed(() => {
  if (!fragments.value) return false;
  return Boolean(
    (fragments.value.positive_block || "").trim()
      || (fragments.value.forbidden_block || "").trim()
      || (fragments.value.metric_anchor_block || "").trim()
  );
});

const prefixExpanded = ref(false);
// PR-13 a11y — aria-controls 关联折叠 body(每实例唯一 id)
const prefixBodyId = `bp-prefix-body-${Math.random().toString(36).slice(2, 10)}`;

function toggle() { prefixExpanded.value = !prefixExpanded.value; }
</script>

<template>
  <section class="bundle-preview" data-testid="bundle-preview">
    <header class="bp-head">
      <strong>注入预览</strong>
      <span v-if="fragments" class="bp-strategy">strategy={{ fragments.strategy }}</span>
    </header>

    <p v-if="loading" class="bp-loading" data-testid="bundle-preview-loading">加载中…</p>
    <p v-else-if="error" class="bp-error" data-testid="bundle-preview-error">{{ error }}</p>
    <p v-else-if="!fragments" class="bp-empty" data-testid="bundle-preview-empty">尚未生成预览。</p>
    <template v-else>
      <div class="bp-blocks">
        <div v-if="fragments.positive_block" class="bp-block bp-block-positive">
          <p class="bp-block-title">正向风格特征 · {{ fragments.positive_block.length }} 字</p>
          <pre>{{ fragments.positive_block }}</pre>
        </div>
        <div v-if="fragments.forbidden_block" class="bp-block bp-block-forbidden">
          <p class="bp-block-title">禁忌模式 · {{ fragments.forbidden_block.length }} 字</p>
          <pre>{{ fragments.forbidden_block }}</pre>
        </div>
        <div v-if="fragments.metric_anchor_block" class="bp-block bp-block-metric">
          <p class="bp-block-title">量化锚点 · {{ fragments.metric_anchor_block.length }} 字</p>
          <pre>{{ fragments.metric_anchor_block }}</pre>
        </div>
      </div>
      <p v-if="!hasAnyContent" class="bp-empty">strategy {{ fragments.strategy }} 命中空注入(可能 profile 缺少配置)。</p>
      <div v-if="prefix" class="bp-prefix" data-testid="bundle-preview-prefix">
        <button
          type="button"
          class="bp-prefix-toggle"
          :aria-expanded="prefixExpanded"
          :aria-controls="prefixBodyId"
          @click="toggle"
        >
          {{ prefixExpanded ? "▾" : "▸" }} 拼接后 system_prompt 前缀(共 {{ prefix.length }} 字)
        </button>
        <pre v-if="prefixExpanded" :id="prefixBodyId" class="bp-prefix-body">{{ prefix }}</pre>
      </div>
    </template>
  </section>
</template>

<style scoped>
.bundle-preview {
  display: grid;
  gap: 0.5rem;
  padding: 0.75rem 0.9rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.12));
  border-radius: var(--radius-md, 6px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 85%, transparent);
}
.bp-head { display: flex; align-items: center; gap: 0.5rem; }
/* PR-13 a11y — 提对比(原 0.6~0.62 → 0.72,≥ 4.5:1) */
.bp-strategy {
  font-size: 0.72rem;
  color: rgba(33, 26, 21, 0.78);
  padding: 0.05rem 0.4rem;
  border-radius: var(--radius-pill, 999px);
  background: rgba(0, 0, 0, 0.05);
}
.bp-loading { font-size: 0.86rem; color: rgba(33, 26, 21, 0.72); }
.bp-error { color: #9a3434; font-size: 0.86rem; }
.bp-empty { font-size: 0.82rem; color: rgba(33, 26, 21, 0.72); }
.bp-blocks { display: grid; gap: 0.45rem; }
.bp-block { padding: 0.4rem 0.55rem; border-radius: var(--radius-sm, 4px); background: rgba(0, 0, 0, 0.03); }
.bp-block-title { margin: 0 0 0.2rem 0; font-size: 0.78rem; font-weight: 600; color: var(--text-muted, rgba(33, 26, 21, 0.7)); }
.bp-block pre { margin: 0; font-size: 0.82rem; white-space: pre-wrap; font-family: var(--font-mono, monospace); line-height: 1.55; }
.bp-prefix { display: grid; gap: 0.3rem; }
.bp-prefix-toggle {
  text-align: left;
  background: transparent;
  border: none;
  font-size: 0.78rem;
  color: rgba(33, 26, 21, 0.78);
  cursor: pointer;
  padding: 0;
}
.bp-prefix-toggle:focus-visible {
  outline: 2px solid var(--color-primary, #2f6f62);
  outline-offset: 2px;
}
.bp-prefix-body {
  margin: 0;
  font-size: 0.78rem;
  white-space: pre-wrap;
  background: rgba(0, 0, 0, 0.04);
  padding: 0.5rem;
  border-radius: var(--radius-sm, 4px);
  max-height: 220px;
  overflow: auto;
}
</style>
