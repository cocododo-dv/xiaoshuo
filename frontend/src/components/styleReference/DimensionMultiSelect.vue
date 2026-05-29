<script setup>
import { computed } from "vue";

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => [],
  },
  disabled: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["update:modelValue"]);

const LAYERS = Object.freeze([
  {
    key: "language",
    label: "语言",
    items: [
      { value: "language.sentence_structure", label: "句法" },
      { value: "language.vocabulary", label: "词汇" },
      { value: "language.rhetoric", label: "修辞" },
      { value: "language.punctuation", label: "标点" },
    ],
  },
  {
    key: "narrative",
    label: "叙事",
    items: [
      { value: "narrative.perspective", label: "视角" },
      { value: "narrative.pacing", label: "节奏" },
      { value: "narrative.time_handling", label: "时序" },
      { value: "narrative.information_density", label: "信息密度" },
    ],
  },
  {
    key: "scene",
    label: "场景",
    items: [
      { value: "scene.environment", label: "环境" },
      { value: "scene.character_portrayal", label: "人物描摹" },
      { value: "scene.dialogue", label: "对白" },
      { value: "scene.sensory_priority", label: "感官优先" },
    ],
  },
  {
    key: "theme",
    label: "主题",
    items: [
      { value: "theme.emotional_tone", label: "情绪" },
      { value: "theme.values", label: "价值观" },
      { value: "theme.motifs", label: "母题" },
      { value: "theme.narrative_philosophy", label: "叙事哲学" },
    ],
  },
]);

const ALL_VALUES = computed(() => LAYERS.flatMap((l) => l.items.map((i) => i.value)));
const selected = computed(() => new Set(props.modelValue || []));

function toggle(value) {
  if (props.disabled) return;
  const next = new Set(selected.value);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  emit("update:modelValue", Array.from(next));
}

function selectAll() {
  if (props.disabled) return;
  emit("update:modelValue", [...ALL_VALUES.value]);
}

function clearAll() {
  if (props.disabled) return;
  emit("update:modelValue", []);
}

function selectLayer(layerKey) {
  if (props.disabled) return;
  const layer = LAYERS.find((l) => l.key === layerKey);
  if (!layer) return;
  const next = new Set(selected.value);
  for (const item of layer.items) next.add(item.value);
  emit("update:modelValue", Array.from(next));
}
</script>

<template>
  <div :class="['dimension-multi-select', { disabled }]" role="group" aria-label="子维度筛选">
    <header class="dms-head">
      <strong>子维度筛选(默认全选 16 项)</strong>
      <div class="dms-actions">
        <button type="button" class="dms-action" :disabled="disabled" aria-label="全选所有子维度" @click="selectAll" data-testid="select-all">
          全选
        </button>
        <button type="button" class="dms-action" :disabled="disabled" aria-label="清空所有子维度" @click="clearAll" data-testid="clear-all">
          全反选
        </button>
      </div>
    </header>
    <div class="dms-grid">
      <div v-for="layer in LAYERS" :key="layer.key" class="dms-layer">
        <header class="dms-layer-head">
          <strong>{{ layer.label }}</strong>
          <button
            type="button"
            class="dms-layer-select"
            :disabled="disabled"
            :aria-label="`全选${layer.label}层子维度`"
            @click="selectLayer(layer.key)"
            :data-testid="`select-layer-${layer.key}`"
          >
            全选本层
          </button>
        </header>
        <ul class="dms-items">
          <li v-for="item in layer.items" :key="item.value">
            <label :class="['dms-item', { active: selected.has(item.value) }]">
              <input
                type="checkbox"
                :value="item.value"
                :checked="selected.has(item.value)"
                :disabled="disabled"
                @change="toggle(item.value)"
                :data-testid="`sub-dim-${item.value}`"
              />
              <span>{{ item.label }}</span>
            </label>
          </li>
        </ul>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dimension-multi-select {
  display: grid;
  gap: 0.55rem;
  padding: 0.7rem 0.85rem;
  border-radius: var(--radius-md, 6px);
  background: color-mix(in srgb, var(--color-panel-solid, #fffdf7) 88%, transparent);
}
.dms-head { display: flex; justify-content: space-between; align-items: center; }
.dms-actions { display: flex; gap: 0.4rem; }
.dms-action, .dms-layer-select {
  font-size: 0.74rem;
  padding: 0.15rem 0.45rem;
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: var(--radius-sm, 4px);
  background: transparent;
  cursor: pointer;
}
.dms-action:disabled, .dms-layer-select:disabled { opacity: 0.55; cursor: not-allowed; }
.dms-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.55rem;
}
.dms-layer { display: grid; gap: 0.3rem; }
.dms-layer-head { display: flex; justify-content: space-between; align-items: center; font-size: 0.82rem; }
.dms-items { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.18rem; }
.dms-item {
  display: flex;
  gap: 0.35rem;
  align-items: center;
  padding: 0.15rem 0.35rem;
  border-radius: var(--radius-sm, 4px);
  font-size: 0.84rem;
  cursor: pointer;
}
.dms-item.active { background: color-mix(in srgb, var(--color-primary, #4a90e2) 10%, transparent); }
.dms-item input { margin: 0; }
.disabled { opacity: 0.55; }
/* PR-13 a11y — 键盘焦点可见 */
.dms-action:focus-visible,
.dms-layer-select:focus-visible,
.dms-item input:focus-visible {
  outline: 2px solid var(--color-primary, #2f6f62);
  outline-offset: 2px;
}
</style>
