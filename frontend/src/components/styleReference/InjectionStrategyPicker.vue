<script setup>
import { computed } from "vue";

import IntensitySlider from "./IntensitySlider.vue";
import DimensionMultiSelect from "./DimensionMultiSelect.vue";

const props = defineProps({
  modelValue: {
    type: Object,
    required: true,
    // 形态 { strategy, intensity, sub_dimensions }
  },
  disabled: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["update:modelValue"]);

const STRATEGIES = Object.freeze([
  { value: "A", label: "策略 A", desc: "系统提示词全文注入,适合短篇 / 关键章节" },
  { value: "B", label: "策略 B", desc: "Few-shot,按 token 预算截断,适合中篇" },
  { value: "C", label: "策略 C", desc: "RAG 摘要,positive 全文 + forbidden 摘要" },
  { value: "mixed", label: "策略 MIXED", desc: "组合策略,可调强度与子维度" },
]);

const strategy = computed(() => props.modelValue.strategy || "A");
const intensity = computed(() => Number(props.modelValue.intensity ?? 50));
const subDimensions = computed(() => props.modelValue.sub_dimensions || []);
const isMixed = computed(() => strategy.value === "mixed");

function update(patch) {
  emit("update:modelValue", { ...props.modelValue, ...patch });
}

function selectStrategy(value) {
  if (props.disabled) return;
  update({ strategy: value });
}

function updateIntensity(value) {
  update({ intensity: value });
}

function updateSubDimensions(value) {
  update({ sub_dimensions: value });
}
</script>

<template>
  <div :class="['strategy-picker', { disabled }]">
    <div class="strategy-buttons" role="group" aria-label="注入策略">
      <button
        v-for="opt in STRATEGIES"
        :key="opt.value"
        type="button"
        :class="['strat-btn', { active: strategy === opt.value }]"
        :disabled="disabled"
        :aria-pressed="strategy === opt.value"
        @click="selectStrategy(opt.value)"
        :data-testid="`strategy-${opt.value}`"
      >
        <span class="strat-label">{{ opt.label }}</span>
        <span class="strat-desc">{{ opt.desc }}</span>
      </button>
    </div>
    <div v-if="isMixed" class="mixed-controls" data-testid="mixed-controls">
      <IntensitySlider :model-value="intensity" :disabled="disabled" @update:model-value="updateIntensity" />
      <DimensionMultiSelect
        :model-value="subDimensions"
        :disabled="disabled"
        @update:model-value="updateSubDimensions"
      />
    </div>
  </div>
</template>

<style scoped>
.strategy-picker { display: grid; gap: 0.55rem; }
.strategy-buttons {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.5rem;
}
.strat-btn {
  display: grid;
  gap: 0.2rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid rgba(0, 0, 0, 0.14);
  border-radius: var(--radius-md, 6px);
  background: transparent;
  cursor: pointer;
  text-align: left;
}
.strat-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.strat-btn.active {
  border-color: var(--color-primary, #4a90e2);
  background: color-mix(in srgb, var(--color-primary, #4a90e2) 8%, transparent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--color-primary, #4a90e2) 30%, transparent);
}
.strat-label { font-weight: 700; font-size: 0.92rem; }
/* PR-13 a11y — strat-desc 提对比(原 0.62 → 0.72,≥ 4.5:1) */
.strat-desc { font-size: 0.74rem; color: rgba(33, 26, 21, 0.72); }
.strat-btn:focus-visible {
  outline: 2px solid var(--color-primary, #2f6f62);
  outline-offset: 2px;
}
.mixed-controls { display: grid; gap: 0.55rem; }
.strategy-picker.disabled { opacity: 0.55; }
</style>
