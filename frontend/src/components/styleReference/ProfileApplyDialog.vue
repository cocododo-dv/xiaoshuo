<script setup>
import { reactive, watch } from "vue";
import BaseButton from "../base/BaseButton.vue";

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
});

const emit = defineEmits(["close", "submit", "update:draft"]);

const localDraft = reactive({
  scope: "project",
  scope_ref_id: "",
  task_type: "scene_generation",
  strategy: "A",
});

watch(
  () => props.draft,
  (next) => {
    if (!next) return;
    localDraft.scope = next.scope || "project";
    localDraft.scope_ref_id = next.scope_ref_id || "";
    localDraft.task_type = next.task_type || "scene_generation";
    localDraft.strategy = next.strategy || "A";
  },
  { immediate: true, deep: true },
);

function update(field, value) {
  localDraft[field] = value;
  emit("update:draft", { ...localDraft });
}

function submit() {
  emit("submit", { ...localDraft });
}
</script>

<template>
  <div v-if="open" class="apply-dialog-mask" role="dialog" aria-modal="true">
    <div class="apply-dialog">
      <header class="dialog-head">
        <p class="dialog-title">应用 Profile 到项目</p>
        <button type="button" class="dialog-close" aria-label="关闭" @click="emit('close')">×</button>
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

        <label class="field">
          <span class="field-label">注入策略(strategy)</span>
          <select :value="localDraft.strategy" @change="update('strategy', $event.target.value)">
            <option value="A">A — System Prompt 注入(PR-8 完整接入)</option>
            <option value="B">B — Few-shot(PR-8)</option>
            <option value="C">C — RAG(Phase 3)</option>
            <option value="mixed">mixed</option>
          </select>
        </label>
      </div>

      <footer class="dialog-actions">
        <BaseButton variant="ghost" @click="emit('close')">取消</BaseButton>
        <BaseButton variant="primary" :loading="busy" @click="submit">应用</BaseButton>
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
  width: min(28rem, 92vw);
  display: grid;
  gap: 0.8rem;
  padding: 1.2rem 1.4rem;
  border-radius: var(--radius-panel, 10px);
  background: var(--color-panel-solid, #fffdf7);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}
.dialog-head { display: flex; justify-content: space-between; align-items: center; }
.dialog-title { margin: 0; font-weight: 700; font-size: 1rem; }
.dialog-close {
  background: none;
  border: none;
  font-size: 1.3rem;
  cursor: pointer;
  color: var(--text-muted, rgba(33, 26, 21, 0.55));
}
.dialog-body { display: grid; gap: 0.6rem; }
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
