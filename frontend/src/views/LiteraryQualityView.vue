<script setup>
import { ArrowRight, FlaskConical, Play, RefreshCcw } from "lucide-vue-next";
import { computed, onActivated, onMounted, ref } from "vue";

import PanelShell from "../components/PanelShell.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useShellRouter } from "../router";
import { useLiteraryQualityStore } from "../stores/literaryQuality";

const emit = defineEmits(["notice"]);

const quality = useLiteraryQualityStore();
const { navigate } = useShellRouter();
const activeTab = ref("overview");

const summary = computed(() => quality.summary || {});
const items = computed(() => quality.overviewItems || []);
const report = computed(() => quality.latestReport || null);
const reportSummary = computed(() => quality.benchmarkSummary || {});
const benchmarkCases = computed(() => quality.benchmarkCases || []);

const DIMENSION_LABELS = {
  model_voice: "模型腔",
  image_homogeneity: "意象同质",
  expository_dialogue: "解释性对白",
  no_choice_scene: "无选择场景",
  summary_ending: "总结式结尾",
  choice_pressure: "选择压力",
  ending_drive: "结尾驱动",
};

function scoreLabel(value) {
  if (value === null || value === undefined) {
    return "未评分";
  }
  return `${Math.round(Number(value) * 100)} 分`;
}

function layerLabel(value) {
  return {
    author_draft: "作者稿",
    runtime_final_scene: "运行终稿",
    chapter_memory_final: "最终聚合稿",
    chapter_assembled: "实时拼接稿",
  }[value] || value || "-";
}

function severityLabel(value) {
  return {
    blocking: "阻断",
    revision: "修订",
    taste: "审美",
  }[value] || value || "-";
}

function riskEntries(item) {
  return Object.entries(item?.signals || {})
    .filter(([, signal]) => signal?.risk)
    .map(([dimension, signal]) => ({
      dimension,
      label: DIMENSION_LABELS[dimension] || dimension,
      evidence: signal.evidence || "",
    }));
}

function dimensionScoreEntries(dimensions = {}) {
  return Object.entries(dimensions).map(([dimension, score]) => ({
    dimension,
    label: DIMENSION_LABELS[dimension] || dimension,
    score,
  }));
}

function openDeepDesk() {
  navigate("deepdesk");
}

async function refreshOverview() {
  try {
    await quality.refreshOverview();
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runBaselineEval() {
  try {
    await quality.runBaselineEval();
    emit("notice", "基准评测已完成");
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runLiveEval() {
  try {
    await quality.runLiveEval();
    emit("notice", "Live 评测已完成");
  } catch (error) {
    emit("notice", error.message);
  }
}

async function ensureLoaded(force = false) {
  try {
    await quality.initialize({ force });
  } catch (error) {
    emit("notice", error.message);
  }
}

onMounted(() => {
  ensureLoaded();
});

onActivated(() => {
  ensureLoaded();
});
</script>

<template>
  <section class="panel-grid literary-quality-view" data-testid="literary-quality-view">
    <WorkflowPageHeader view-id="quality" />
    <PanelShell
      eyebrow="文学质量引擎"
      title="巡检稿件风险，校准生成基准"
      description="默认优先读取作者稿；没有作者稿时再回退运行终稿或最终聚合稿。所有文学质量风险只提示和导航，不改变运行状态。"
    >
      <template #actions>
        <div class="field-inline quality-actions">
          <button type="button" data-testid="quality-refresh" :disabled="quality.loading" @click="refreshOverview">
            <RefreshCcw :size="16" aria-hidden="true" />
            <span>{{ quality.loading ? "刷新中..." : "刷新巡检" }}</span>
          </button>
        </div>
      </template>

      <div class="quality-tabs" aria-label="文学质量页签">
        <button
          type="button"
          data-testid="quality-tab-overview"
          :class="{ active: activeTab === 'overview' }"
          @click="activeTab = 'overview'"
        >
          稿件巡检
        </button>
        <button
          type="button"
          data-testid="quality-tab-benchmark"
          :class="{ active: activeTab === 'benchmark' }"
          @click="activeTab = 'benchmark'"
        >
          基准评测
        </button>
      </div>

      <div v-if="activeTab === 'overview'" class="quality-overview">
        <section class="quality-summary-grid">
          <article class="paper mini">
            <span>巡检对象</span>
            <strong>{{ summary.object_count || 0 }}</strong>
          </article>
          <article class="paper mini">
            <span>平均分</span>
            <strong>{{ scoreLabel(summary.mean_score) }}</strong>
          </article>
          <article class="paper mini">
            <span>高风险</span>
            <strong>{{ summary.high_risk_count || 0 }}</strong>
          </article>
          <article class="paper mini">
            <span>模型腔</span>
            <strong>{{ summary.model_voice_count || 0 }}</strong>
          </article>
        </section>

        <div v-if="quality.loading" class="empty">正在巡检稿件...</div>
        <div v-else-if="quality.error" class="empty">{{ quality.error }}</div>
        <div v-else-if="!items.length" class="empty">暂无可巡检稿件。</div>
        <section v-else class="quality-card-list" data-testid="quality-overview-items">
          <article
            v-for="item in items"
            :key="`${item.object_type}-${item.object_id}`"
            class="quality-card"
            :class="{ risky: item.score < 0.72 }"
          >
            <div class="receipt-head compact">
              <div>
                <h3>{{ item.object_id }}</h3>
                <p class="muted receipt-copy">
                  {{ item.object_type }} / {{ layerLabel(item.text_layer) }} / {{ item.source_ref }}
                </p>
              </div>
              <span class="badge">{{ scoreLabel(item.score) }}</span>
            </div>

            <div class="risk-strip">
              <span v-for="risk in riskEntries(item)" :key="risk.dimension" class="risk-pill">
                {{ risk.label }}
              </span>
              <span v-if="!riskEntries(item).length" class="risk-pill calm">暂无明显风险</span>
            </div>

            <div class="quality-findings">
              <article
                v-for="finding in item.findings"
                :key="`${finding.dimension}-${finding.issue}`"
                class="quality-finding"
              >
                <div class="receipt-head compact">
                  <strong>{{ DIMENSION_LABELS[finding.dimension] || finding.dimension }}</strong>
                  <span class="badge">{{ severityLabel(finding.severity) }}</span>
                </div>
                <p>{{ finding.issue }}</p>
                <blockquote v-if="finding.evidence_excerpt">{{ finding.evidence_excerpt }}</blockquote>
                <small>{{ finding.recommendation }}</small>
              </article>
            </div>

            <button type="button" class="ghost quality-open" @click="openDeepDesk">
              <ArrowRight :size="16" aria-hidden="true" />
              <span>去深改台</span>
            </button>
          </article>
        </section>
      </div>

      <div v-else class="quality-benchmark" data-testid="quality-eval-report">
        <section class="paper quality-eval-toolbar">
          <div>
            <h3>Literary Eval</h3>
            <p class="muted receipt-copy">
              Baseline 用离线样本文本守住基准；Live 使用当前模型路由跑同一套用例。
            </p>
          </div>
          <div class="field-inline">
            <button type="button" :disabled="quality.evalLoading" @click="runBaselineEval">
              <FlaskConical :size="16" aria-hidden="true" />
              <span>运行 baseline</span>
            </button>
            <button type="button" class="ghost" :disabled="quality.evalLoading" @click="runLiveEval">
              <Play :size="16" aria-hidden="true" />
              <span>运行 live</span>
            </button>
          </div>
        </section>

        <div v-if="quality.evalLoading" class="empty">正在运行文学基准评测...</div>
        <div v-else-if="quality.evalError" class="empty">{{ quality.evalError }}</div>
        <div v-else-if="!report" class="empty">暂无评测报告。</div>
        <section v-else class="quality-eval-layout">
          <div class="quality-summary-grid">
            <article class="paper mini">
              <span>用例</span>
              <strong>{{ reportSummary.case_count || 0 }}</strong>
            </article>
            <article class="paper mini">
              <span>通过</span>
              <strong>{{ reportSummary.passed_count || 0 }}</strong>
            </article>
            <article class="paper mini">
              <span>失败</span>
              <strong>{{ reportSummary.failed_count || 0 }}</strong>
            </article>
            <article class="paper mini">
              <span>均分</span>
              <strong>{{ scoreLabel(reportSummary.mean_score) }}</strong>
            </article>
          </div>

          <div class="quality-eval-cases">
            <article
              v-for="caseItem in benchmarkCases"
              :key="caseItem.case_id"
              class="quality-case-row"
              :class="{ failed: !caseItem.passed }"
            >
              <div class="receipt-head compact">
                <div>
                  <h3>{{ caseItem.title || caseItem.case_id }}</h3>
                  <p class="muted receipt-copy">{{ caseItem.case_id }}</p>
                </div>
                <span class="badge">{{ scoreLabel(caseItem.score) }}</span>
              </div>
              <div class="dimension-grid">
                <span
                  v-for="dimension in dimensionScoreEntries(caseItem.dimensions)"
                  :key="`${caseItem.case_id}-${dimension.dimension}`"
                >
                  {{ dimension.label }} {{ scoreLabel(dimension.score) }}
                </span>
              </div>
              <ul v-if="caseItem.issues?.length" class="quality-issues">
                <li v-for="issue in caseItem.issues" :key="issue">{{ issue }}</li>
              </ul>
            </article>
          </div>
        </section>
      </div>
    </PanelShell>
  </section>
</template>

<style scoped>
.literary-quality-view {
  --quality-accent: #2f6271;
  --quality-warn: #9a3f33;
  --quality-ink-soft: rgba(37, 51, 66, 0.72);
}

.quality-actions button,
.quality-eval-toolbar button,
.quality-open {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
}

.quality-tabs {
  display: inline-flex;
  width: fit-content;
  gap: 0.35rem;
  padding: 0.25rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.55);
}

.quality-tabs button {
  min-width: 6.5rem;
  padding: 0.55rem 0.8rem;
  border-color: transparent;
  background: transparent;
  color: var(--muted);
}

.quality-tabs button.active {
  border-color: rgba(47, 98, 113, 0.2);
  background: rgba(47, 98, 113, 0.12);
  color: var(--ink);
}

.quality-overview,
.quality-benchmark,
.quality-eval-layout,
.quality-card-list,
.quality-findings,
.quality-eval-cases {
  display: grid;
  gap: 1rem;
}

.quality-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.85rem;
}

.quality-card,
.quality-case-row,
.quality-eval-toolbar {
  display: grid;
  gap: 0.9rem;
  padding: 1rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.58);
}

.quality-card.risky,
.quality-case-row.failed {
  border-color: rgba(154, 63, 51, 0.32);
  box-shadow: inset 4px 0 0 rgba(154, 63, 51, 0.22);
}

.risk-strip,
.dimension-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
}

.risk-pill,
.dimension-grid span {
  display: inline-flex;
  align-items: center;
  min-height: 1.85rem;
  padding: 0.25rem 0.55rem;
  border: 1px solid rgba(47, 98, 113, 0.18);
  border-radius: 999px;
  background: rgba(47, 98, 113, 0.08);
  color: var(--quality-ink-soft);
  font-size: 0.84rem;
}

.risk-pill.calm {
  border-color: rgba(42, 102, 74, 0.2);
  background: rgba(42, 102, 74, 0.08);
}

.quality-finding {
  display: grid;
  gap: 0.6rem;
  padding: 0.85rem;
  border: 1px solid rgba(37, 51, 66, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
}

.quality-finding p,
.quality-finding blockquote,
.quality-finding small,
.quality-case-row p {
  margin: 0;
}

.quality-finding blockquote {
  padding: 0.65rem 0.75rem;
  border-left: 3px solid rgba(47, 98, 113, 0.42);
  background: rgba(47, 98, 113, 0.07);
  color: #304854;
  line-height: 1.6;
}

.quality-finding small {
  color: var(--muted);
  line-height: 1.55;
}

.quality-open {
  justify-self: start;
}

.quality-eval-toolbar {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
}

.quality-issues {
  display: grid;
  gap: 0.35rem;
  margin: 0;
  padding-left: 1.1rem;
  color: var(--quality-warn);
  line-height: 1.55;
}

@media (max-width: 980px) {
  .quality-summary-grid,
  .quality-eval-toolbar {
    grid-template-columns: 1fr;
  }

  .quality-tabs {
    width: 100%;
  }

  .quality-tabs button {
    flex: 1;
    min-width: 0;
  }
}
</style>
