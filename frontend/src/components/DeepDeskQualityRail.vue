<script setup>
import { computed } from "vue";

import BaseEmptyState from "./base/BaseEmptyState.vue";
import FlowActionReceipt from "./FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useWriterDeepDeskStore } from "../stores/writerDeepDesk";

const emit = defineEmits(["notice"]);

const desk = useWriterDeepDeskStore();
const REVIEW_SCOPE = "deepdesk:review";
const AUTO_REWRITE_SCOPE = "deepdesk:auto-rewrite";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const findings = computed(() => desk.findings || []);
const lensEvaluations = computed(() => desk.lensEvaluations || []);
const inlineQualitySpanFindings = computed(() => desk.inlineQualitySpanFindings || []);
const longformPressure = computed(() => desk.longformPressure || []);
const draftContent = computed(() => desk.draftContent);
const judgmentLayers = computed(() => desk.judgmentLayers || { blocking: [], revision: [], profile_mismatch: [], taste: [] });
const judgmentLayerBuckets = computed(() => [
  { key: "blocking", label: "blocking", items: judgmentLayers.value.blocking || [] },
  { key: "revision", label: "revision", items: judgmentLayers.value.revision || [] },
  { key: "profile_mismatch", label: "profile_mismatch", items: judgmentLayers.value.profile_mismatch || [] },
  { key: "taste", label: "taste", items: judgmentLayers.value.taste || [] },
]);
const qualityContract = computed(() => desk.qualityContract || null);
const qualityContractPayload = computed(() => qualityContract.value?.payload || {});
const qualityContractRows = computed(() => [
  { key: "scene_function", label: "场景功能", value: qualityContractPayload.value.scene_function },
  { key: "pov_or_actor", label: "POV/主行动者", value: qualityContractPayload.value.pov_or_actor },
  { key: "visible_desire", label: "可见欲望", value: qualityContractPayload.value.visible_desire },
  { key: "obstacle", label: "阻碍", value: qualityContractPayload.value.obstacle },
  { key: "forced_choice", label: "强迫选择", value: qualityContractPayload.value.forced_choice },
  { key: "price_paid", label: "代价", value: qualityContractPayload.value.price_paid },
  { key: "relationship_turn", label: "关系转向", value: qualityContractPayload.value.relationship_turn },
  { key: "information_release", label: "信息释放", value: qualityContractPayload.value.information_release },
  { key: "image_necessity", label: "意象必要性", value: qualityContractPayload.value.image_necessity },
  { key: "irreversible_change", label: "不可逆变化", value: qualityContractPayload.value.irreversible_change },
  { key: "ending_action", label: "结尾动作", value: qualityContractPayload.value.ending_action },
  { key: "next_scene_pull", label: "下一场牵引", value: qualityContractPayload.value.next_scene_pull },
]);
const autoRewriteRun = computed(() => desk.autoRewriteRun || null);
const qualityPromotion = computed(() => desk.qualityState?.promotion || {});
const qualityPromotionBlockers = computed(() => desk.qualityPromotionBlockers || []);
const scoreText = computed(() => {
  const score = desk.latestEvaluation?.overall_score;
  return score === null || score === undefined ? "未诊断" : `${Math.round(Number(score) * 100)} 分`;
});

function severityLabel(value) {
  return { blocking: "阻断", revision: "修订", taste: "审美", ignore_ok: "可忽略" }[value] || value || "未分级";
}
function lensLabel(value) {
  return { story: "故事", character: "人物", prose: "语言", reader: "读者", theme: "主题", aggregate: "总评" }[value] || value || "总评";
}
function scoreLabel(value) {
  return value === null || value === undefined ? "-" : `${Math.round(Number(value) * 100)} 分`;
}
function autoRewriteStatusLabel(value) {
  return { candidate_ready: "候选可审", promoted: "已晋级", rolled_back: "已回滚", human_review_required: "转人工", diagnose_only: "仅诊断", failed: "失败" }[value] || value || "未运行";
}
function longformCardTypeLabel(value) {
  return { character_arc_gap: "人物弧线断点", foreshadow_debt: "伏笔债务", foreshadowing_debt: "伏笔债务", promise_without_payoff: "章节承诺未兑现", chapter_promise_unpaid: "章节承诺未兑现", motif_reuse: "意象复用", information_release_gap: "信息释放断点" }[value] || value || "长篇压力";
}
function longformSeverityLabel(value) {
  return { critical: "高压", major: "中压", minor: "低压", info: "提示" }[value] || value || "未分级";
}
function longformRecommendation(card) {
  const r = card?.recommendation || {};
  if (typeof r === "string") return r;
  return r.summary || r.action || r.note || "等待人工判断下一步。";
}

async function runDeepReview() {
  await runFlowAction({
    scopeKey: REVIEW_SCOPE,
    actionLabel: "深改诊断",
    runningMessage: "正在按当前稿件层级运行文学深改诊断。",
    successMessage: (message) => message,
    nextStep: "查看阻断、修订和审美问题，再挑一段生成局部候选。",
    action: () => desk.runCurrentDeepReview(),
  });
}

async function runInlineQuality() {
  await runFlowAction({
    scopeKey: REVIEW_SCOPE,
    actionLabel: "文学质检内联扫描",
    runningMessage: "正在把当前作者稿扫描为可定位的 span findings。",
    successMessage: () => "文学质检内联扫描已完成。",
    nextStep: "优先处理模型腔、动作模板复用、意象场复用、假清晰和解释性对白。",
    action: () => desk.analyzeCurrentDraftQuality(),
  });
}

async function generateQualityContract() {
  await runFlowAction({
    scopeKey: AUTO_REWRITE_SCOPE,
    actionLabel: "场景质量契约",
    runningMessage: "正在把当前场景整理成可验收的文学契约。",
    successMessage: (message) => message,
    nextStep: "契约会作为自动重写和近终稿验收的同一份判断依据。",
    action: () => desk.generateSceneQualityContract(),
  });
}

async function runAutoRewrite() {
  await runFlowAction({
    scopeKey: AUTO_REWRITE_SCOPE,
    actionLabel: "自动重写",
    runningMessage: "正在按场景质量契约生成重写候选。",
    successMessage: (message) => message,
    nextStep: "先比较候选与当前运行终稿，再决定是否晋级。",
    action: () => desk.runSceneAutoRewrite({ mode: "auto" }),
  });
}

async function promoteAutoRewrite() {
  await runFlowAction({
    scopeKey: AUTO_REWRITE_SCOPE,
    actionLabel: "晋级为运行终稿",
    runningMessage: "正在把通过验收的重写候选晋级为新的 FinalScene。",
    successMessage: (message) => message,
    nextStep: "晋级只影响运行层终稿；旧版本和证据仍可回滚。",
    action: () => desk.promoteAutoRewriteRun(),
  });
}

async function rollbackAutoRewrite() {
  await runFlowAction({
    scopeKey: AUTO_REWRITE_SCOPE,
    actionLabel: "回滚",
    runningMessage: "正在恢复自动重写晋级前的运行终稿。",
    successMessage: (message) => message,
    nextStep: "回滚不会删除自动重写证据，后续仍可审计。",
    action: () => desk.rollbackAutoRewriteRun(),
  });
}
</script>

<template>
  <aside class="paper deep-desk-rail">
    <div class="receipt-head compact">
      <div>
        <h3>深改诊断</h3>
        <p class="muted receipt-copy">诊断跟随当前章稿 / 场景稿目标。</p>
      </div>
      <span class="badge">{{ scoreText }}</span>
    </div>
    <button data-testid="deep-review-run" :disabled="!desk.draftObjectId || desk.actionId === 'deep-review'" @click="runDeepReview">
      运行深改诊断
    </button>
    <button type="button" class="ghost" data-testid="inline-quality-run" :disabled="!desk.authorDraft || !draftContent.trim() || desk.actionId === 'inline-quality'" @click="runInlineQuality">
      {{ desk.actionId === "inline-quality" ? "扫描中..." : "文学质检内联扫描" }}
    </button>
    <FlowActionReceipt :receipt="receipt(REVIEW_SCOPE)" />

    <section class="scene-quality-panel" data-testid="scene-quality-contract">
      <div class="receipt-head compact">
        <div>
          <h4>场景质量契约</h4>
          <p class="muted receipt-copy">欲望、阻碍、选择、代价和结尾动作共用同一份验收口径。</p>
        </div>
        <span class="badge">{{ qualityContract?.contract_version || "未生成" }}</span>
      </div>
      <button type="button" class="ghost" data-testid="scene-quality-contract-generate" :disabled="desk.draftObjectType !== 'scene' || !desk.selectedSceneId || desk.actionId === 'quality-contract'" @click="generateQualityContract">
        刷新契约
      </button>
      <dl v-if="qualityContract" class="quality-contract-grid">
        <template v-for="row in qualityContractRows" :key="row.key">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value || "待补足" }}</dd>
        </template>
      </dl>
      <BaseEmptyState v-else description="当前场景还没有质量契约。" />
    </section>

    <section class="scene-auto-rewrite-panel" data-testid="scene-auto-rewrite-run">
      <div class="receipt-head compact">
        <div>
          <h4>自动重写</h4>
          <p class="muted receipt-copy">只生成运行层候选；作者稿不会被覆盖。</p>
        </div>
        <span class="badge">{{ autoRewriteStatusLabel(autoRewriteRun?.status) }}</span>
      </div>
      <div v-if="autoRewriteRun" class="auto-rewrite-summary">
        <span>branch: {{ autoRewriteRun.branch || "-" }}</span>
        <span>failure: {{ autoRewriteRun.failure_class || "-" }}</span>
        <span>candidate: {{ autoRewriteRun.candidate_draft_row_id || "-" }}</span>
      </div>
      <div v-if="qualityPromotionBlockers.length" class="quality-blockers">
        <strong>阻塞原因</strong>
        <span v-for="blocker in qualityPromotionBlockers" :key="blocker">{{ blocker }}</span>
      </div>
      <div class="card-actions">
        <button type="button" data-testid="scene-auto-rewrite-run-button" :disabled="desk.draftObjectType !== 'scene' || !desk.selectedSceneId || desk.actionId === 'auto-rewrite'" @click="runAutoRewrite">
          自动重写
        </button>
        <button type="button" class="ghost" data-testid="scene-auto-rewrite-promote" :disabled="!autoRewriteRun?.run_id || !qualityPromotion?.eligible || desk.actionId.startsWith('auto-rewrite-')" @click="promoteAutoRewrite">
          晋级为运行终稿
        </button>
        <button type="button" class="ghost" data-testid="scene-auto-rewrite-rollback" :disabled="!autoRewriteRun?.run_id || desk.actionId.startsWith('auto-rewrite-')" @click="rollbackAutoRewrite">
          回滚
        </button>
      </div>
      <FlowActionReceipt :receipt="receipt(AUTO_REWRITE_SCOPE)" />
    </section>

    <section class="judgment-layers-panel" data-testid="judgment-layers">
      <div class="receipt-head compact">
        <div>
          <h4>判断分层</h4>
          <p class="muted receipt-copy">Blocking is separated from revision and taste signals.</p>
        </div>
        <span class="badge">{{ desk.snapshotDeepReviewSummary?.non_blocking_count || 0 }} advisory</span>
      </div>
      <div class="judgment-layer-grid">
        <article v-for="bucket in judgmentLayerBuckets" :key="bucket.key" class="judgment-layer-card">
          <div class="receipt-head compact">
            <strong>{{ bucket.label }}</strong>
            <span class="badge">{{ bucket.items.length }}</span>
          </div>
          <p v-if="bucket.items[0]" class="muted">{{ bucket.items[0].issue || bucket.items[0].dimension }}</p>
          <p v-else class="muted">clear</p>
        </article>
      </div>
    </section>

    <section class="inline-quality-panel" data-testid="inline-quality-span-findings">
      <div class="receipt-head compact">
        <div>
          <h4>文学质检内联风险</h4>
          <p class="muted receipt-copy">span_findings 直接定位在作者稿上，先处理会破坏类型长篇阅读推进的风险。</p>
        </div>
        <span class="badge">{{ inlineQualitySpanFindings.length }} 条</span>
      </div>
      <BaseEmptyState v-if="!inlineQualitySpanFindings.length" description="暂未扫描当前作者稿。" />
      <article v-for="span in inlineQualitySpanFindings" :key="`${span.dimension}-${span.start}-${span.end}`" class="deep-finding">
        <div class="receipt-head compact">
          <strong>{{ severityLabel(span.severity) }} / {{ span.dimension }}</strong>
          <span class="badge">{{ span.start }}-{{ span.end }}</span>
        </div>
        <blockquote>{{ span.evidence }}</blockquote>
        <p class="muted">{{ span.recommended_action }}</p>
      </article>
    </section>

    <section class="deep-longform-pressure" data-testid="desk-longform-pressure">
      <div class="receipt-head compact">
        <div>
          <h4>长篇压力</h4>
          <p class="muted receipt-copy">只推当前稿件最需要处理的连续性压力。</p>
        </div>
        <span class="badge">{{ longformPressure.length }} 条</span>
      </div>
      <BaseEmptyState v-if="!longformPressure.length" description="暂无高优先级长篇压力。" />
      <article v-for="card in longformPressure" :key="card.card_id" class="deep-pressure-row">
        <div class="receipt-head compact">
          <strong>{{ longformCardTypeLabel(card.card_type) }}</strong>
          <span class="badge">{{ longformSeverityLabel(card.severity) }}</span>
        </div>
        <p>{{ longformRecommendation(card) }}</p>
      </article>
    </section>

    <section class="deep-review-findings" data-testid="deep-review-findings">
      <BaseEmptyState v-if="!findings.length" description="还没有深改批注。" />
      <article v-for="finding in findings" :key="`${finding.lens}-${finding.dimension}-${finding.issue}`" class="deep-finding" :class="`severity-${finding.severity}`">
        <div class="receipt-head compact">
          <strong>{{ severityLabel(finding.severity) }} / {{ finding.dimension }}</strong>
          <span class="badge">{{ lensLabel(finding.lens) }}</span>
        </div>
        <p>{{ finding.issue }}</p>
        <p class="muted">{{ finding.recommendation }}</p>
        <p v-if="finding.why_it_matters" class="muted">影响读者：{{ finding.why_it_matters }}</p>
        <blockquote v-if="finding.evidence_excerpt">{{ finding.evidence_excerpt }}</blockquote>
      </article>
    </section>

    <section class="deep-lenses">
      <h4>Lens</h4>
      <BaseEmptyState v-if="!lensEvaluations.length" description="暂无 lens 结果。" />
      <article v-for="lens in lensEvaluations" :key="lens.evaluation_id" class="deep-lens-row">
        <span>{{ lensLabel(lens.lens) }}</span>
        <strong>{{ scoreLabel(lens.overall_score) }}</strong>
      </article>
    </section>
  </aside>
</template>

<style scoped>
.deep-desk-rail {
  display: grid;
  gap: 1rem;
}

.inline-quality-panel,
.judgment-layers-panel,
.scene-quality-panel,
.scene-auto-rewrite-panel,
.deep-longform-pressure {
  display: grid;
  gap: 0.7rem;
  padding-top: 0.4rem;
  border-top: 1px dashed var(--line);
}

.quality-contract-grid {
  display: grid;
  grid-template-columns: 6.5rem minmax(0, 1fr);
  gap: 0.45rem 0.75rem;
  margin: 0;
}

.quality-contract-grid dt {
  color: var(--muted);
}

.quality-contract-grid dd {
  margin: 0;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.auto-rewrite-summary,
.quality-blockers {
  display: grid;
  gap: 0.4rem;
  padding: 0.65rem;
  border: 1px solid rgba(37, 51, 66, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.52);
}

.auto-rewrite-summary span,
.quality-blockers span {
  overflow-wrap: anywhere;
}

.deep-review-findings,
.deep-lenses,
.judgment-layer-grid {
  display: grid;
  gap: 0.8rem;
}

.judgment-layer-card {
  display: grid;
  gap: 0.55rem;
  min-width: 0;
  padding: 0.75rem;
  border: 1px solid rgba(37, 51, 66, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.52);
}

.deep-finding,
.deep-pressure-row {
  display: grid;
  gap: 0.65rem;
  padding: 0.85rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.58);
}

.deep-finding p,
.deep-pressure-row p {
  margin: 0;
}

.deep-finding blockquote {
  margin: 0;
  padding: 0.65rem 0.8rem;
  border-left: 3px solid rgba(36, 71, 86, 0.42);
  background: rgba(36, 71, 86, 0.07);
  color: #314552;
  line-height: 1.6;
}

.severity-blocking {
  border-color: rgba(143, 47, 38, 0.34);
  box-shadow: inset 4px 0 0 rgba(143, 47, 38, 0.24);
}

.severity-revision {
  box-shadow: inset 4px 0 0 rgba(47, 98, 113, 0.22);
}

.severity-taste {
  box-shadow: inset 4px 0 0 rgba(107, 92, 54, 0.2);
}

.severity-ignore_ok {
  box-shadow: inset 4px 0 0 rgba(82, 104, 91, 0.18);
  background: rgba(82, 104, 91, 0.06);
}

.deep-lens-row {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  padding: 0.55rem 0;
  border-bottom: 1px solid rgba(37, 51, 66, 0.1);
}
</style>
