<script setup>
import { computed } from "vue";

const props = defineProps({
  modelValue: {
    type: Number,
    default: 50,
  },
  disabled: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["update:modelValue"]);

const TICKS = Object.freeze([
  { value: 0, label: "0.3x" },
  { value: 50, label: "0.9x 基线" },
  { value: 100, label: "1.5x" },
]);

const clamped = computed(() => Math.max(0, Math.min(100, Number(props.modelValue) || 0)));
const scaleLabel = computed(() => {
  const scale = 0.3 + (clamped.value / 100) * 1.2;
  return `${scale.toFixed(2)}x`;
});

function onInput(event) {
  if (props.disabled) return;
  const raw = Number(event.target.value);
  const next = Math.max(0, Math.min(100, isNaN(raw) ? 50 : raw));
  emit("update:modelValue", next);
}
</script>

<template>
  <div :class="['intensity-slider', { disabled }]">
    <div class="slider-row">
      <input
        type="range"
        min="0"
        max="100"
        step="1"
        :value="clamped"
        :disabled="disabled"
        @input="onInput"
        data-testid="intensity-input"
      />
      <span class="intensity-value">{{ clamped }}</span>
      <span class="intensity-scale">{{ scaleLabel }}</span>
    </div>
    <div class="ticks">
      <span v-for="tick in TICKS" :key="tick.value" class="tick">
        <span class="tick-mark">{{ tick.value }}</span>
        <span class="tick-label">{{ tick.label }}</span>
      </span>
    </div>
  </div>
</template>

<style scoped>
.intensity-slider {
  display: grid;
  gap: 0.3rem;
  padding: 0.55rem 0.7rem;
  border-radius: var(--radius-md, 6px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 90%, transparent);
}
.intensity-slider.disabled { opacity: 0.55; }
.slider-row { display: flex; align-items: center; gap: 0.6rem; }
.slider-row input[type="range"] {
  flex: 1;
  accent-color: var(--color-primary, #4a90e2);
}
.intensity-value {
  font-family: var(--font-mono, monospace);
  font-weight: 700;
  min-width: 2.5rem;
  text-align: right;
}
.intensity-scale {
  font-size: 0.78rem;
  color: var(--text-muted, rgba(33, 26, 21, 0.6));
}
.ticks {
  display: flex;
  justify-content: space-between;
  font-size: 0.72rem;
  color: var(--text-muted, rgba(33, 26, 21, 0.55));
}
.tick { display: inline-flex; flex-direction: column; align-items: center; }
.tick-mark { font-family: var(--font-mono, monospace); }
.tick-label { font-size: 0.7rem; }
</style>
