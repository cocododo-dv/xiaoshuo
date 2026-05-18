<script setup>
import { computed } from "vue";

import BaseEmptyState from "./base/BaseEmptyState.vue";
import FlowActionReceipt from "./FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useWriterDeepDeskStore } from "../stores/writerDeepDesk";

const emit = defineEmits(["notice"]);

const desk = useWriterDeepDeskStore();
const DECISION_SCOPE = "deepdesk:decision";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const candidates = computed(() => desk.candidateRows || []);
const preference = computed(() => desk.preferenceProfile || null);
const profileSummary = computed(() => preference.value?.summary || {});

function statusLabel(value) {
  return { not_run: "未运行", reviewed: "已诊断", candidate: "候选", accepted: "已采纳", rejected: "已拒绝", pending: "待决定", draft: "草稿", approved: "已审核", current: "当前", superseded: "已替换" }[value] || value || "-";
}

function candidateCategoryLabel(value) {
  return { dialogue_rewrite: "对白改写", action_replace: "动作替换", ending_pressure: "结尾重压", information_reorder: "信息释放重排", de_model_voice: "去模型腔", local_patch: "局部深改" }[value] || "局部深改";
}

function candidateMetaLine(candidate) {
  const range = candidate?.target_range;
  const rangeText = range?.unit ? `${range.unit}:${range.start ?? "-"}-${range.end ?? "-"}` : "";
  return [candidateCategoryLabel(candidate?.candidate_category), candidate?.revision_strategy, rangeText].filter(Boolean).join(" · ");
}

function candidateTagLine(candidate) {
  const tags = Array.isArray(candidate?.preference_tags) ? candidate.preference_tags.filter(Boolean) : [];
  return tags.length ? `偏好标签：${tags.join(" / ")}` : "偏好标签：暂无";
}

async function insertCandidate(candidate, option = null) {
  await runFlowAction({
    scopeKey: DECISION_SCOPE,
    actionLabel: "放入稿件",
    runningMessage: "正在把候选放入作者稿编辑器，尚不覆盖运行终稿。",
    successMessage: (message) => message,
    nextStep: "确认全文上下文后点击保存作者稿，候选才会标记为已采纳。",
    action: () => desk.insertCandidateOption(candidate, option),
  });
}

async function rejectCandidate(candidate) {
  await runFlowAction({
    scopeKey: DECISION_SCOPE,
    actionLabel: "记录拒绝",
    runningMessage: "正在把拒绝决定写入作者偏好草稿。",
    successMessage: (message) => message,
    nextStep: "偏好仍为草稿，审核发布前不会进入后续生成提示。",
    action: () => desk.rejectPassagePatchCandidate(candidate.patch_id, { note: "保留作者原句或等待人工重写。" }),
  });
}
</script>

<template>
  <section class="paper deep-candidates" data-testid="passage-patch-candidates">
    <div class="receipt-head">
      <div>
        <h3>局部候选账本</h3>
        <p class="muted receipt-copy">"放入稿件"只修改作者稿编辑器；保存作者稿后，候选才会标记为已采纳。</p>
      </div>
      <span class="badge">{{ candidates.length }} 条</span>
    </div>
    <BaseEmptyState v-if="!candidates.length" description="还没有局部候选。" />
    <article v-for="candidate in candidates" :key="candidate.patch_id" class="deep-candidate-row">
      <div class="receipt-head compact">
        <div>
          <strong>{{ candidateCategoryLabel(candidate.candidate_category) }} / {{ candidate.issue_dimension }}</strong>
          <p class="muted">{{ candidateMetaLine(candidate) }}</p>
          <p class="muted">{{ candidateTagLine(candidate) }}</p>
          <p class="muted">{{ candidate.source_excerpt }}</p>
          <small v-if="candidate.rationale" class="muted">{{ candidate.rationale }}</small>
        </div>
        <div class="candidate-badges">
          <span class="badge">{{ statusLabel(candidate.status) }}</span>
          <span v-if="candidate.inserted_into_author_draft" class="badge">已放入稿件</span>
        </div>
      </div>
      <div class="deep-option-grid">
        <section v-for="option in candidate.replacement_options" :key="option.option_id" class="deep-option">
          <div class="receipt-head compact">
            <strong>{{ option.label || option.tone }}</strong>
            <span class="badge">{{ option.tone }}</span>
          </div>
          <p class="option-text">{{ option.replacement_text }}</p>
          <small>{{ option.why_it_helps }}</small>
          <button type="button" :disabled="desk.actionId.startsWith('patch-') || candidate.status !== 'candidate'" @click="insertCandidate(candidate, option)">
            放入稿件
          </button>
        </section>
      </div>
      <div class="card-actions">
        <button type="button" class="ghost" :disabled="desk.actionId.startsWith('patch-') || candidate.status !== 'candidate'" @click="rejectCandidate(candidate)">
          拒绝候选
        </button>
        <span class="muted">作者决定：{{ statusLabel(candidate.author_decision) }}</span>
      </div>
    </article>
    <FlowActionReceipt :receipt="receipt(DECISION_SCOPE)" />
  </section>

  <section class="paper deep-preference" data-testid="author-preference-profile">
    <div class="receipt-head">
      <div>
        <h3>作者偏好草稿</h3>
        <p class="muted receipt-copy">采纳 / 拒绝会沉淀偏好，但审核发布前不会进入后续生成提示。</p>
      </div>
      <span class="badge">{{ statusLabel(preference?.status) }}</span>
    </div>
    <div class="deep-preference-grid">
      <article>
        <h4>偏好的改法</h4>
        <p>{{ (profileSummary.preferred_revision_moves || []).join(" / ") || "暂无采纳样本。" }}</p>
      </article>
      <article>
        <h4>常拒绝的痕迹</h4>
        <p>{{ (profileSummary.rejected_revision_moves || []).join(" / ") || "暂无拒绝样本。" }}</p>
      </article>
      <article>
        <h4>AI 痕迹监测</h4>
        <p>{{ (profileSummary.ai_trace_terms_to_watch || []).join(" / ") || "暂无监测词。" }}</p>
      </article>
      <article>
        <h4>偏好候选类型</h4>
        <p>{{ (profileSummary.preferred_patch_categories || []).join(" / ") || "暂无类型样本。" }}</p>
      </article>
      <article>
        <h4>偏好标签</h4>
        <p>{{ (profileSummary.preference_tags || []).join(" / ") || "暂无标签样本。" }}</p>
      </article>
      <article>
        <h4>运行资格</h4>
        <p>{{ preference?.runtime_eligible ? "已允许进入运行 bundle" : "草稿状态，不进运行 bundle" }}</p>
      </article>
    </div>
  </section>
</template>

<style scoped>
.deep-candidates,
.deep-preference {
  display: grid;
  gap: 1rem;
  margin-top: 1rem;
}

.deep-preference-grid {
  display: grid;
  gap: 0.8rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.deep-preference-grid > article,
.deep-candidate-row,
.deep-option {
  display: grid;
  gap: 0.65rem;
  padding: 0.85rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.58);
}

.deep-option p,
.deep-candidate-row p,
.deep-preference p {
  margin: 0;
}

.candidate-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  justify-content: flex-end;
}

.deep-option-grid {
  display: grid;
  gap: 0.8rem;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.deep-option small,
.deep-candidate-row small {
  color: var(--muted);
  line-height: 1.5;
}

.deep-option button {
  justify-self: start;
}

.option-text {
  white-space: pre-wrap;
  line-height: 1.75;
}

@media (max-width: 1360px) {
  .deep-option-grid,
  .deep-preference-grid {
    grid-template-columns: 1fr;
  }
}
</style>
