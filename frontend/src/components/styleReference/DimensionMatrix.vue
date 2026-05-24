<script setup>
import { computed } from "vue";
import DimensionConfidenceBar from "./DimensionConfidenceBar.vue";

const props = defineProps({
  findings: {
    type: Object,
    required: true,
  },
  inputAssessment: {
    type: Object,
    default: () => ({}),
  },
  highlightDim: {
    type: String,
    default: "",
  },
});

const emit = defineEmits(["select-sub-dim"]);

const LAYERS = [
  {
    key: "language",
    label: "语言层",
    subDims: [
      { path: "language.sentence_structure", label: "句法" },
      { path: "language.vocabulary", label: "词汇" },
      { path: "language.rhetoric", label: "修辞" },
      { path: "language.punctuation", label: "标点" },
    ],
  },
  {
    key: "narrative",
    label: "叙事层",
    subDims: [
      { path: "narrative.perspective", label: "视角" },
      { path: "narrative.pacing", label: "节奏" },
      { path: "narrative.time_handling", label: "时间" },
      { path: "narrative.information_density", label: "信息密度" },
    ],
  },
  {
    key: "scene",
    label: "场景层",
    subDims: [
      { path: "scene.environment", label: "环境" },
      { path: "scene.character_portrayal", label: "人物" },
      { path: "scene.dialogue", label: "对话" },
      { path: "scene.sensory_priority", label: "感官" },
    ],
  },
  {
    key: "theme",
    label: "主题层",
    subDims: [
      { path: "theme.emotional_tone", label: "情绪" },
      { path: "theme.values", label: "价值" },
      { path: "theme.motifs", label: "母题" },
      { path: "theme.narrative_philosophy", label: "哲思" },
    ],
  },
];

function statsFor(dimPath) {
  const bucket = props.findings?.[dimPath];
  if (!bucket) {
    return { obs: 0, forbid: 0, quotes: 0, confidence: "skip", isSkipped: true };
  }
  const obs = bucket.observations?.length ?? 0;
  const forbid = bucket.forbidden_patterns?.length ?? 0;
  let quotes = 0;
  for (const f of bucket.observations ?? []) quotes += (f.evidence_count ?? 0);
  for (const f of bucket.forbidden_patterns ?? []) quotes += (f.evidence_count ?? 0);
  let confidence = "skip";
  if (obs >= 5 || forbid >= 2) confidence = "high";
  else if (obs >= 2) confidence = "medium";
  else if (obs >= 1) confidence = "low";
  return { obs, forbid, quotes, confidence, isSkipped: obs === 0 && forbid === 0 };
}

function layerSkipped(layerKey) {
  const level = props.inputAssessment?.[layerKey];
  return level === "skip" || (layerKey !== "language" && layerKey !== "narrative");
}

function handleClick(dimPath, stats) {
  if (stats.isSkipped) return;
  emit("select-sub-dim", dimPath);
}

const totalCells = computed(() => LAYERS.length * 4);
</script>

<template>
  <section class="dimension-matrix" aria-label="风格维度矩阵 4×16">
    <header class="matrix-head">
      <p class="matrix-title">维度矩阵({{ totalCells }} sub_dim)</p>
      <p class="matrix-hint">PR-5 阶段:仅 language + narrative 8 维有数据;scene / theme 待 PR-6 落地。</p>
    </header>
    <div class="matrix-grid">
      <template v-for="layer in LAYERS" :key="layer.key">
        <div class="layer-row" :class="{ 'layer-skipped': layerSkipped(layer.key) }">
          <div class="layer-label">{{ layer.label }}</div>
          <div class="layer-cells">
            <button
              v-for="sub in layer.subDims"
              :key="sub.path"
              type="button"
              class="matrix-cell"
              :class="[
                `cell-${statsFor(sub.path).confidence}`,
                { 'cell-highlight': highlightDim === sub.path, 'cell-disabled': statsFor(sub.path).isSkipped },
              ]"
              :title="`${sub.label}|${statsFor(sub.path).obs} obs / ${statsFor(sub.path).forbid} forbid`"
              :disabled="statsFor(sub.path).isSkipped"
              @click="handleClick(sub.path, statsFor(sub.path))"
            >
              <div class="cell-label">{{ sub.label }}</div>
              <DimensionConfidenceBar :confidence="statsFor(sub.path).confidence" />
              <div class="cell-stats">
                <span>{{ statsFor(sub.path).obs }} obs</span>
                <span>·</span>
                <span>{{ statsFor(sub.path).forbid }} forbid</span>
              </div>
            </button>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.dimension-matrix {
  display: grid;
  gap: 0.8rem;
  padding: 1rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.15));
  border-radius: var(--radius-panel, 8px);
  background: var(--color-panel-solid, #fffdf7);
}

.matrix-title { margin: 0; font-weight: 700; font-size: 0.96rem; }
.matrix-hint { margin: 0; font-size: 0.78rem; color: var(--text-muted, rgba(33, 26, 21, 0.58)); }

.matrix-grid { display: grid; gap: 0.5rem; }
.layer-row { display: grid; grid-template-columns: 6.5rem 1fr; gap: 0.6rem; align-items: stretch; }
.layer-label { font-weight: 700; font-size: 0.85rem; display: flex; align-items: center; }
.layer-cells { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.5rem; }
.layer-skipped .layer-label { color: var(--text-muted, rgba(33, 26, 21, 0.45)); }

.matrix-cell {
  display: grid;
  gap: 0.35rem;
  padding: 0.55rem 0.65rem;
  border: 1px solid var(--surface-line, rgba(33, 26, 21, 0.15));
  border-radius: var(--radius-md, 6px);
  background: var(--color-panel-solid, #fffdf7);
  cursor: pointer;
  text-align: left;
  transition: transform var(--transition-fast, 120ms);
}
.matrix-cell:hover:not(:disabled) { transform: translateY(-1px); border-color: rgba(33, 26, 21, 0.35); }
.matrix-cell:disabled { cursor: not-allowed; opacity: 0.55; }

.cell-label { font-weight: 600; font-size: 0.84rem; }
.cell-stats { font-size: 0.72rem; color: var(--text-muted, rgba(33, 26, 21, 0.62)); display: flex; gap: 0.25rem; }
.cell-high { background: #f2faf5; border-color: #b8dec3; }
.cell-medium { background: #fafdfa; border-color: #d4e9da; }
.cell-low { background: #fcf8eb; border-color: #ead9aa; }
.cell-skip { background: rgba(0, 0, 0, 0.04); }
.cell-highlight { box-shadow: 0 0 0 2px var(--color-primary, #4a90e2); }
</style>
