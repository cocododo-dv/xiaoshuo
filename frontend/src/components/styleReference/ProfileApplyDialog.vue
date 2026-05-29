<script setup>
import { computed, nextTick, reactive, ref, watch } from "vue";

import BaseButton from "../base/BaseButton.vue";
import InjectionStrategyPicker from "./InjectionStrategyPicker.vue";
import InjectionBundlePreview from "./InjectionBundlePreview.vue";

const ALL_SUB_DIMS = Object.freeze([
  "language.sentence_structure",
  "language.vocabulary",
  "language.rhetoric",
  "language.punctuation",
  "narrative.perspective",
  "narrative.pacing",
  "narrative.time_handling",
  "narrative.information_density",
  "scene.environment",
  "scene.character_portrayal",
  "scene.dialogue",
  "scene.sensory_priority",
  "theme.emotional_tone",
  "theme.values",
  "theme.motifs",
  "theme.narrative_philosophy",
]);

const props = defineProps({
  open: {
    type: Boolean,
    default: false,
  },
  draft: {
    type: Object,
    required: true,
  },
  busy: {
    type: Boolean,
    default: false,
  },
  preview: {
    type: Object,
    default: null,
  },
  previewLoading: {
    type: Boolean,
    default: false,
  },
  previewError: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["close", "submit", "update:draft", "request-preview"]);

// PR-13 a11y — 打开时焦点落到关闭按钮(供读屏朗读 dialog 标题)
const closeButton = ref(null);
watch(
  () => props.open,
  async (open) => {
    if (!open) return;
    await nextTick();
    closeButton.value?.focus?.();
  },
  { immediate: true },
);

const localDraft = reactive({
  scope: "project",
  scope_ref_id: "",
  task_type: "scene_generation",
  strategy: "A",
  intensity: 50,
  sub_dimensions: [...ALL_SUB_DIMS],
});

watch(
  () => props.draft,
  (next) => {
    if (!next) return;
    localDraft.scope = next.scope || "project";
    localDraft.scope_ref_id = next.scope_ref_id || "";
    localDraft.task_type = next.task_type || "scene_generation";
    localDraft.strategy = next.strategy || "A";
    localDraft.intensity = Number(next.intensity ?? 50);
    localDraft.sub_dimensions = Array.isArray(next.sub_dimensions) && next.sub_dimensions.length > 0
      ? [...next.sub_dimensions]
      : [...ALL_SUB_DIMS];
  },
  { immediate: true, deep: true },
);

const strategyConfig = computed({
  get() {
    return {
      strategy: localDraft.strategy,
      intensity: localDraft.intensity,
      sub_dimensions: localDraft.sub_dimensions,
    };
  },
  set(value) {
    localDraft.strategy = value.strategy;
    localDraft.intensity = Number(value.intensity ?? 50);
    localDraft.sub_dimensions = Array.isArray(value.sub_dimensions) ? [...value.sub_dimensions] : [];
    emit("update:draft", snapshot());
    schedulePreviewFetch();
  },
});

let previewTimer = null;
function schedulePreviewFetch() {
  if (typeof window === "undefined") return;
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = window.setTimeout(() => {
    emit("request-preview", snapshot());
    previewTimer = null;
  }, 300);
}

function snapshot() {
  return {
    scope: localDraft.scope,
    scope_ref_id: localDraft.scope_ref_id,
    task_type: localDraft.task_type,
    strategy: localDraft.strategy,
    intensity: localDraft.intensity,
    sub_dimensions: [...localDraft.sub_dimensions],
  };
}

function update(field, value) {
  localDraft[field] = value;
  emit("update:draft", snapshot());
  if (field === "task_type") schedulePreviewFetch();
}

function submit() {
  emit("submit", snapshot());
}
</script>

<template>
  <div v-if="open" class="apply-dialog-mask" @click.self="emit('close')">
    <div
      class="apply-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="apply-dialog-title"
      tabindex="-1"
      @keydown.esc="emit('close')"
    >
      <header class="dialog-head">
        <p id="apply-dialog-title" class="dialog-title">应用 Profile 到项目</p>
        <button ref="closeButton" type="button" class="dialog-close" aria-label="关闭" @click="emit('close')">×</button>
      </header>

      <div class="dialog-body">
        <label class="field">
          <span class="field-label">作用范围(scope)</span>
          <select :value="localDraft.scope" @change="update('scope', $event.target.value)">
            <option value="project">project(整个项目)</option>
            <option value="scene">scene(单个场景)</option>
            <option value="character">character(单个角色)</option>
          </select>
        </label>

        <label class="field">
          <span class="field-label">范围引用 ID(可选)</span>
          <input
            type="text"
            :value="localDraft.scope_ref_id"
            placeholder="如 proj_001 / scene_005 / char_zh01"
            @input="update('scope_ref_id', $event.target.value)"
          />
        </label>

        <label class="field">
          <span class="field-label">任务类型(task_type)</span>
          <select :value="localDraft.task_type" @change="update('task_type', $event.target.value)">
            <option value="scene_generation">scene_generation</option>
            <option value="project_init">project_init</option>
            <option value="fine_tuning">fine_tuning</option>
            <option value="long_form_continuation">long_form_continuation</option>
            <option value="key_chapter">key_chapter</option>
          </select>
        </label>

        <div class="field">
          <span class="field-label">注入策略</span>
          <InjectionStrategyPicker v-model="strategyConfig" />
        </div>

        <InjectionBundlePreview
          :preview="preview"
          :loading="previewLoading"
          :error="previewError"
        />
      </div>

      <footer class="dialog-actions">
        <BaseButton variant="ghost" @click="emit('close')">取消</BaseButton>
        <BaseButton variant="primary" :loading="busy" @click="submit" data-testid="confirm-apply">应用</BaseButton>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.apply-dialog-mask {
  position: fixed;
  inset: 0;
  display: grid;
  place-items: center;
  background: rgba(0, 0, 0, 0.35);
  z-index: 1000;
}
.apply-dialog {
  width: min(38rem, 96vw);
  max-height: 90vh;
  display: grid;
  gap: 0.7rem;
  padding: 1.1rem 1.3rem;
  border-radius: var(--radius-panel, 10px);
  background: var(--color-panel-solid, #fffdf7);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
  overflow: auto;
}
.dialog-head { display: flex; justify-content: space-between; align-items: center; }
.dialog-title { margin: 0; font-weight: 700; font-size: 1rem; }
.dialog-close {
  background: none;
  border: none;
  font-size: 1.3rem;
  cursor: pointer;
  /* PR-13 a11y — 提对比(原 0.55 alpha 偏低,× 关闭按钮 ≥ 4.5:1) */
  color: rgba(33, 26, 21, 0.72);
}
.dialog-close:focus-visible {
  outline: 2px solid var(--color-primary, #2f6f62);
  outline-offset: 2px;
  border-radius: var(--radius-sm, 4px);
}
.dialog-body { display: grid; gap: 0.65rem; }
.field { display: grid; gap: 0.25rem; font-size: 0.85rem; }
.field-label { color: var(--text-muted, rgba(33, 26, 21, 0.68)); font-weight: 600; }
.field input,
.field select {
  padding: 0.45rem 0.6rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.18));
  border-radius: var(--radius-sm, 4px);
  background: #fff;
  font: inherit;
}
.dialog-actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
</style>
