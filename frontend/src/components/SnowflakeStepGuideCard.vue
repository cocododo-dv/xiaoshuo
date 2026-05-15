<script setup>
import { computed, ref } from "vue";
import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Crosshair } from "lucide-vue-next";
import { diagnosticLabel, fieldLabel } from "../lib/snowflakeDisplay";

const props = defineProps({
  step: {
    type: Object,
    required: true,
  },
  steps: {
    type: Array,
    default: () => [],
  },
  currentStepIndex: {
    type: Number,
    default: 0,
  },
  completedStepCount: {
    type: Number,
    default: 0,
  },
  totalStepCount: {
    type: Number,
    default: 0,
  },
  currentStepDirty: {
    type: Boolean,
    default: false,
  },
});

const emit = defineEmits(["select-step", "go-triage"]);

const previousStep = computed(() => props.steps[props.currentStepIndex - 1] || null);
const nextStep = computed(() => props.steps[props.currentStepIndex + 1] || null);
const shouldOfferTriage = computed(() => ["scene_list", "scene_details"].includes(props.step?.step_key));
const missingFields = computed(() => props.step?.completeness?.missing_fields || []);
const expandedSections = ref({
  instruction: false,
  checklist: false,
  rubric: false,
  diagnostic: false,
});
const pressureDiagnostic = computed(() => {
  const health = props.step?.health || props.step?.artifact?.diagnosis_json || {};
  const score = typeof health.score === "number" ? health.score : health.pressure_score;
  const hasScore = typeof score === "number";
  const flags = Array.isArray(health.gaps) ? health.gaps : Array.isArray(health.pressure_flags) ? health.pressure_flags : [];
  const fixSteps = Array.isArray(health.next_actions) ? health.next_actions : Array.isArray(health.fix_steps) ? health.fix_steps : [];
  const hardBlockers = Array.isArray(health.hard_blockers) ? health.hard_blockers : [];
  const strengths = Array.isArray(health.strengths) ? health.strengths : [];
  if (!hasScore && !flags.length && !fixSteps.length && !hardBlockers.length && !strengths.length) {
    return null;
  }
  return {
    score: hasScore ? score : null,
    status: health.status || health.pressure_status || "",
    flags,
    fixSteps,
    hardBlockers,
    strengths,
  };
});
const rubricEntries = computed(() => Object.entries(props.step?.guidance?.rubric || {}));
const checklistItems = computed(() => props.step?.guidance?.checklist || []);
const instructionText = computed(() => (
  String(props.step?.guidance?.instruction || "").trim()
    || "先完成这一层的可用版本，再继续向下展开。"
));
const completenessLabel = computed(() => {
  const completeness = props.step?.completeness;
  if (!completeness) {
    return "等待草稿";
  }
  return `${completeness.filled_count} / ${completeness.total_count}`;
});
const diagnosticSummary = computed(() => {
  const diagnostic = pressureDiagnostic.value;
  if (!diagnostic) {
    return "";
  }
  const parts = [];
  if (diagnostic.flags.length) {
    parts.push(`${diagnostic.flags.length} 个缺口`);
  }
  if (diagnostic.hardBlockers.length) {
    parts.push(`${diagnostic.hardBlockers.length} 个阻断`);
  }
  if (diagnostic.fixSteps.length) {
    parts.push(`${diagnostic.fixSteps.length} 条修复建议`);
  }
  if (diagnostic.strengths.length) {
    parts.push(`${diagnostic.strengths.length} 个优势`);
  }
  return parts.join(" · ") || "暂无具体缺口，保留当前判断。";
});

function selectStep(step) {
  if (!step?.step_key) {
    return;
  }
  emit("select-step", step.step_key);
}

function pressureStatusLabel(status) {
  if (status === "pass") {
    return "可继续";
  }
  if (status === "rewrite") {
    return "需重构";
  }
  if (status === "maybe") {
    return "需加压";
  }
  return "待诊断";
}

function isExpanded(section) {
  return Boolean(expandedSections.value[section]);
}

function toggleSection(section) {
  expandedSections.value = {
    ...expandedSections.value,
    [section]: !expandedSections.value[section],
  };
}
</script>

<template>
  <article class="snowflake-step-guide-card" data-testid="snowflake-step-guide-card">
    <div class="step-guide-head">
      <div>
        <span class="eyebrow">步骤说明卡</span>
        <h3>{{ step.label }}</h3>
        <p class="muted">
          {{ step.phase }}
          <span v-if="currentStepDirty"> / 有未保存修改</span>
        </p>
      </div>
      <div class="step-guide-counter">
        <strong>{{ completedStepCount }}</strong>
        <span>/ {{ totalStepCount }} 步</span>
      </div>
    </div>

    <section class="step-guide-task">
      <div>
        <span class="eyebrow">当前任务</span>
        <p class="step-guide-description">{{ step.description }}</p>
      </div>
      <strong v-if="step.guidance?.required_for_materialization" class="required-chip">整理前必需</strong>
    </section>

    <div class="step-guide-status">
      <strong>{{ completenessLabel }}</strong>
      <span v-if="missingFields.length">待补：{{ missingFields.slice(0, 5).map(fieldLabel).join("、") }}</span>
      <span v-else>这一层字段已补齐，可以继续向下扩展。</span>
    </div>

    <section class="step-guide-disclosure">
      <button
        type="button"
        class="step-guide-disclosure-toggle"
        data-testid="snowflake-guide-toggle-instruction"
        :aria-expanded="isExpanded('instruction')"
        @click="toggleSection('instruction')"
      >
        <span>
          <strong>写作指引</strong>
          <small>展开当前层的操作提示</small>
        </span>
        <ChevronDown v-if="isExpanded('instruction')" :size="16" />
        <ChevronRight v-else :size="16" />
      </button>
      <div
        v-if="isExpanded('instruction')"
        class="step-guide-instruction"
        data-testid="snowflake-guide-instruction-body"
      >
        <p>{{ instructionText }}</p>
      </div>
    </section>

    <section v-if="checklistItems.length" class="step-guide-disclosure">
      <button
        type="button"
        class="step-guide-disclosure-toggle"
        data-testid="snowflake-guide-toggle-checklist"
        :aria-expanded="isExpanded('checklist')"
        @click="toggleSection('checklist')"
      >
        <span>
          <strong>检查清单</strong>
          <small>{{ checklistItems.length }} 项提交前自检</small>
        </span>
        <ChevronDown v-if="isExpanded('checklist')" :size="16" />
        <ChevronRight v-else :size="16" />
      </button>
      <ul
        v-if="isExpanded('checklist')"
        class="step-guide-list"
        data-testid="snowflake-guide-checklist-body"
      >
        <li v-for="item in checklistItems" :key="item">{{ item }}</li>
      </ul>
    </section>

    <section v-if="rubricEntries.length" class="step-guide-disclosure">
      <button
        type="button"
        class="step-guide-disclosure-toggle"
        data-testid="snowflake-guide-toggle-rubric"
        :aria-expanded="isExpanded('rubric')"
        @click="toggleSection('rubric')"
      >
        <span>
          <strong>质量标尺</strong>
          <small>{{ rubricEntries.length }} 个判断维度</small>
        </span>
        <ChevronDown v-if="isExpanded('rubric')" :size="16" />
        <ChevronRight v-else :size="16" />
      </button>
      <dl
        v-if="isExpanded('rubric')"
        class="step-guide-rubric"
        data-testid="snowflake-guide-rubric-body"
      >
        <template v-for="[key, value] in rubricEntries" :key="key">
          <dt>{{ key }}</dt>
          <dd>{{ value }}</dd>
        </template>
      </dl>
    </section>

    <section
      v-if="pressureDiagnostic"
      class="step-guide-pressure step-guide-disclosure"
      :class="pressureDiagnostic.status || 'empty'"
      data-testid="snowflake-pressure-diagnostic"
    >
      <div class="step-guide-pressure-head">
        <div>
          <span class="eyebrow">结构压力诊断</span>
          <strong>
            结构压力
            <template v-if="pressureDiagnostic.score !== null">{{ pressureDiagnostic.score }}</template>
            <small>{{ pressureStatusLabel(pressureDiagnostic.status) }}</small>
          </strong>
          <p class="muted">{{ diagnosticSummary }}</p>
        </div>
        <button
          type="button"
          class="step-guide-disclosure-toggle compact-toggle"
          data-testid="snowflake-guide-toggle-diagnostic"
          :aria-expanded="isExpanded('diagnostic')"
          @click="toggleSection('diagnostic')"
        >
          <span>{{ isExpanded("diagnostic") ? "收起诊断" : "查看诊断" }}</span>
          <ChevronDown v-if="isExpanded('diagnostic')" :size="16" />
          <ChevronRight v-else :size="16" />
        </button>
      </div>
      <div
        v-if="isExpanded('diagnostic')"
        class="step-guide-pressure-body"
        data-testid="snowflake-guide-diagnostic-body"
      >
        <p v-if="pressureDiagnostic.flags.length">
          缺口：{{ pressureDiagnostic.flags.slice(0, 3).map(diagnosticLabel).join("、") }}
        </p>
        <p v-if="pressureDiagnostic.hardBlockers.length">
          硬阻断：{{ pressureDiagnostic.hardBlockers.slice(0, 3).map(diagnosticLabel).join("、") }}
        </p>
        <ol v-if="pressureDiagnostic.fixSteps.length">
          <li v-for="item in pressureDiagnostic.fixSteps.slice(0, 2)" :key="item">{{ item }}</li>
        </ol>
        <ul v-if="pressureDiagnostic.strengths.length" class="pressure-strengths">
          <li v-for="item in pressureDiagnostic.strengths.slice(0, 2)" :key="item">{{ item }}</li>
        </ul>
      </div>
    </section>

    <div class="step-guide-actions">
      <button
        type="button"
        class="ghost mini-btn"
        data-testid="snowflake-step-prev"
        :disabled="!previousStep"
        @click="selectStep(previousStep)"
      >
        <ArrowLeft :size="14" />
        <span>上一步</span>
      </button>
      <button
        v-if="shouldOfferTriage"
        type="button"
        class="primary mini-btn"
        data-testid="snowflake-step-triage"
        @click="emit('go-triage')"
      >
        <Crosshair :size="14" />
        <span>进入场景急救</span>
      </button>
      <button
        v-else
        type="button"
        class="ghost mini-btn"
        data-testid="snowflake-step-next"
        :disabled="!nextStep"
        @click="selectStep(nextStep)"
      >
        <span>下一步</span>
        <ArrowRight :size="14" />
      </button>
    </div>
  </article>
</template>

<style scoped>
.snowflake-step-guide-card {
  display: grid;
  gap: 12px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: linear-gradient(135deg, var(--snowflake-paper-strong), var(--snowflake-paper));
  color: var(--snowflake-ink);
  padding: 14px;
}

.step-guide-head,
.step-guide-actions,
.step-guide-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.step-guide-head h3 {
  margin: 3px 0;
  color: var(--snowflake-heading);
}

.step-guide-description,
.step-guide-instruction p,
.step-guide-disclosure-toggle small,
.muted {
  margin: 0;
}

.step-guide-description {
  line-height: 1.7;
}

.step-guide-task {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.step-guide-task > div {
  min-width: 0;
}

.step-guide-disclosure {
  display: grid;
  gap: 8px;
  min-width: 0;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: rgba(255, 254, 248, 0.72);
  padding: 10px;
}

.step-guide-disclosure-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
  min-height: 38px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--snowflake-moss-deep);
  cursor: pointer;
  padding: 0;
  text-align: left;
}

.step-guide-disclosure-toggle span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.step-guide-disclosure-toggle strong {
  color: var(--snowflake-heading);
}

.step-guide-disclosure-toggle small {
  color: var(--snowflake-muted);
  font-size: 0.78rem;
  line-height: 1.35;
}

.step-guide-disclosure-toggle svg {
  flex: 0 0 auto;
}

.compact-toggle {
  width: auto;
  min-width: 104px;
  border: 1px solid var(--snowflake-line);
  background: var(--snowflake-paper-strong);
  padding: 7px 10px;
}

.step-guide-instruction {
  display: grid;
  gap: 8px;
  border-left: 4px solid var(--snowflake-moss);
  border-radius: 0 8px 8px 0;
  background: rgba(47, 111, 98, 0.07);
  padding: 12px 14px;
}

.step-guide-list {
  margin: 0;
  padding-left: 18px;
  color: var(--snowflake-ink);
  line-height: 1.65;
}

.required-chip {
  width: fit-content;
  border-radius: 6px;
  background: rgba(47, 111, 98, 0.12);
  color: var(--snowflake-moss-deep);
  font-size: 0.72rem;
  letter-spacing: 0;
  padding: 3px 6px;
}

.step-guide-rubric {
  display: grid;
  gap: 4px;
  margin: 0;
  border-left: 4px solid var(--snowflake-teal);
  border-radius: 0 8px 8px 0;
  background: rgba(63, 125, 134, 0.07);
  padding: 12px 14px;
}

.step-guide-rubric dt {
  color: var(--snowflake-heading);
  font-weight: 700;
}

.step-guide-rubric dd {
  margin: 0;
  color: var(--snowflake-muted);
}

.step-guide-instruction p {
  white-space: pre-line;
}

.step-guide-counter {
  display: grid;
  min-width: 82px;
  justify-items: center;
  border-radius: 8px;
  background: var(--snowflake-moss-soft);
  color: var(--snowflake-moss-deep);
  padding: 9px 10px;
}

.step-guide-counter strong {
  font-size: 1.45rem;
  line-height: 1;
}

.step-guide-status {
  flex-wrap: wrap;
  border-top: 1px solid var(--snowflake-line);
  padding-top: 10px;
  color: var(--snowflake-muted);
}

.step-guide-status strong {
  color: var(--snowflake-heading);
}

.step-guide-pressure {
  border: 1px solid var(--snowflake-line);
  background: var(--snowflake-paper);
}

.step-guide-pressure.maybe {
  border-color: rgba(140, 103, 43, 0.28);
  background: var(--snowflake-warning-soft);
}

.step-guide-pressure.rewrite {
  border-color: rgba(159, 63, 50, 0.25);
  background: var(--snowflake-danger-soft);
}

.step-guide-pressure.pass {
  border-color: rgba(47, 111, 98, 0.28);
  background: var(--snowflake-moss-soft);
}

.step-guide-pressure-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.step-guide-pressure-head > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.step-guide-pressure-head strong {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
  color: var(--snowflake-heading);
}

.step-guide-pressure-head small {
  color: var(--snowflake-muted);
  font-size: 0.78rem;
  font-weight: 600;
}

.step-guide-pressure p,
.step-guide-pressure ol,
.step-guide-pressure ul {
  margin: 0;
}

.step-guide-pressure p {
  color: var(--snowflake-muted);
  line-height: 1.5;
}

.step-guide-pressure ol {
  padding-left: 18px;
  color: var(--snowflake-ink);
}

.step-guide-pressure-body {
  display: grid;
  gap: 8px;
  border-top: 1px solid var(--snowflake-line);
  padding-top: 10px;
}

.pressure-strengths {
  padding-left: 18px;
  color: var(--snowflake-moss-deep);
}

.step-guide-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.mini-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 34px;
  border: 1px solid var(--snowflake-line);
  border-radius: 999px;
  color: var(--snowflake-moss-deep);
  cursor: pointer;
  padding: 7px 12px;
}

.mini-btn:disabled {
  cursor: default;
  opacity: 0.45;
}

.ghost {
  background: var(--snowflake-paper-strong);
}

.primary {
  background: var(--snowflake-moss);
  border-color: var(--snowflake-moss);
  color: #fff;
}

@media (max-width: 760px) {
  .step-guide-head,
  .step-guide-task,
  .step-guide-status,
  .step-guide-pressure-head,
  .step-guide-actions {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
