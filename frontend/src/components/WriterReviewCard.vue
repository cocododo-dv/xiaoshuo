<script setup>
import { computed } from "vue";
import { Check, RefreshCw, X } from "lucide-vue-next";

const props = defineProps({
  summary: {
    type: Object,
    default: null,
  },
  title: {
    type: String,
    default: "这一场是否成立",
  },
  runLabel: {
    type: String,
    default: "运行作家诊断",
  },
  busy: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["run", "accept", "reject"]);

const evaluation = computed(() => props.summary?.latest_evaluation || props.summary?.evaluation || null);
const candidates = computed(() => props.summary?.candidates || []);
const findings = computed(() => evaluation.value?.findings || []);
const revisionBrief = computed(() => evaluation.value?.revision_brief || []);
const scores = computed(() => evaluation.value?.scores || {});
const scoreItems = computed(() =>
  Object.entries(scores.value).map(([key, value]) => ({
    key,
    value: Number(value || 0),
  })),
);
const scoreLabel = computed(() => {
  if (!evaluation.value || evaluation.value.overall_score === null || evaluation.value.overall_score === undefined) {
    return "未诊断";
  }
  return `${Math.round(Number(evaluation.value.overall_score) * 100)} 分`;
});

function formatDimension(key) {
  return {
    desire: "欲望",
    obstacle: "阻碍",
    stakes: "代价",
    turn: "转折",
    subtext: "潜台词",
    irreversible_change: "不可逆变化",
    scene_necessity: "必要性",
    reader_hook: "读者钩子",
    continuity: "连续性",
    character_agency: "人物主动性",
    dialogue_edge: "对白锋利度",
    information_rhythm: "信息节奏",
    imagery_freshness: "意象新鲜度",
    expression_repetition: "重复表达",
    power_shift: "权力转移",
    ending_drive: "结尾推进力",
    writer_diagnosis_payload: "诊断载荷",
  }[key] || key;
}

function candidateStatusLabel(status) {
  return {
    candidate: "候选",
    accepted: "已采纳",
    rejected: "已拒绝",
    superseded: "已被新候选替代",
  }[status] || status || "候选";
}

function candidateKindLabel(kind) {
  return {
    full_scene_rewrite: "完整场景改写",
    chapter_passage_rewrite: "章节局部改写",
    revision_plan: "章节修订计划",
  }[kind] || kind || "修订候选";
}

function formatChangedDimensions(candidate) {
  return (candidate.diff_summary?.changed_dimensions || [])
    .map((dimension) => formatDimension(dimension))
    .filter(Boolean)
    .join(" / ");
}
</script>

<template>
  <article class="paper writer-review-card" data-testid="writer-review-card">
    <div class="receipt-head">
      <div>
        <h3>{{ title }}</h3>
        <p class="muted receipt-copy">
          {{ evaluation ? "按戏剧有效性查看问题和候选修订。" : "还没有作家诊断。AI 只给建议和候选稿，不会覆盖终稿。" }}
        </p>
      </div>
      <span class="badge">{{ scoreLabel }}</span>
    </div>

    <div class="card-actions writer-review-actions">
      <button type="button" :disabled="busy" data-testid="writer-review-run" @click="emit('run')">
        <RefreshCw :size="15" aria-hidden="true" />
        {{ busy ? "诊断中..." : runLabel }}
      </button>
      <span v-if="evaluation?.requires_human_review" class="badge danger">建议人工介入</span>
    </div>

    <div v-if="evaluation" class="writer-review-body">
      <div v-if="scoreItems.length" class="writer-score-grid">
        <div v-for="item in scoreItems" :key="item.key" class="writer-score-item">
          <span>{{ formatDimension(item.key) }}</span>
          <strong>{{ Math.round(item.value * 100) }}</strong>
        </div>
      </div>

      <section v-if="findings.length" class="writer-review-section">
        <h4>问题列表</h4>
        <ul>
          <li v-for="item in findings" :key="`${item.dimension}-${item.issue}`">
            <strong>{{ formatDimension(item.dimension) }}</strong>
            <span>{{ item.issue }}</span>
            <small>{{ item.recommendation }}</small>
            <small v-if="item.evidence_excerpt" class="writer-evidence">
              证据：{{ item.evidence_excerpt }}
            </small>
            <small v-if="item.evidence_location" class="writer-evidence">
              位置：{{ item.evidence_location }}
            </small>
            <small v-if="item.why_it_matters" class="writer-evidence">
              判断：{{ item.why_it_matters }}
            </small>
          </li>
        </ul>
      </section>

      <section v-if="revisionBrief.length" class="writer-review-section">
        <h4>可执行修订 brief</h4>
        <ul>
          <li v-for="item in revisionBrief" :key="`${item.dimension}-${item.action}`">
            <strong>{{ formatDimension(item.dimension) }}</strong>
            <span>{{ item.action }}</span>
          </li>
        </ul>
      </section>
    </div>

    <section v-if="candidates.length" class="writer-review-section">
      <h4>修订候选</h4>
      <article v-for="candidate in candidates" :key="candidate.revision_id" class="revision-candidate-card">
        <div class="receipt-head compact">
          <div>
            <strong>{{ candidateStatusLabel(candidate.status) }}</strong>
            <p class="muted">{{ candidate.diff_summary?.summary || "候选稿保留在修订账本中。" }}</p>
          </div>
          <span class="badge">{{ candidateKindLabel(candidate.diff_summary?.candidate_kind) }}</span>
        </div>
        <div class="writer-candidate-meta">
          <span v-if="candidate.diff_summary?.rewrite_strategy" class="badge">
            {{ candidate.diff_summary.rewrite_strategy }}
          </span>
          <span v-if="formatChangedDimensions(candidate)" class="muted">
            {{ formatChangedDimensions(candidate) }}
          </span>
        </div>
        <pre>{{ candidate.proposed_text }}</pre>
        <div class="card-actions">
          <button
            type="button"
            :disabled="busy || candidate.status !== 'candidate'"
            :data-testid="`writer-revision-accept-${candidate.revision_id}`"
            @click="emit('accept', candidate.revision_id)"
          >
            <Check :size="15" aria-hidden="true" />
            采纳
          </button>
          <button
            type="button"
            class="ghost"
            :disabled="busy || candidate.status !== 'candidate'"
            :data-testid="`writer-revision-reject-${candidate.revision_id}`"
            @click="emit('reject', candidate.revision_id)"
          >
            <X :size="15" aria-hidden="true" />
            拒绝
          </button>
        </div>
      </article>
    </section>
  </article>
</template>
