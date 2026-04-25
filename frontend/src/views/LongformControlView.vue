<script setup>
import { computed, onActivated, onMounted, ref } from "vue";

import PanelShell from "../components/PanelShell.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useShellRouter } from "../router";
import { useLongformControlStore } from "../stores/longformControl";
import { useLongformEditorStore } from "../stores/longformEditor";

const emit = defineEmits(["notice"]);

const control = useLongformControlStore();
const editor = useLongformEditorStore();
const { navigate, openTarget } = useShellRouter();

const activeTab = ref("cards");
const guidanceDraft = ref({});
const scanText = ref("");

const summary = computed(() => control.summary);
const rhythmMap = computed(() => control.rhythmMap);
const characterArcs = computed(() => control.characterArcs);
const promisePayoff = computed(() => control.promisePayoff);
const informationReleaseCurve = computed(() => control.informationReleaseCurve);
const relationTensionMatrix = computed(() => control.relationTensionMatrix);
const motifTracking = computed(() => control.motifTracking);
const foreshadowDebts = computed(() => control.foreshadowDebts);
const continuityAlerts = computed(() => control.continuityAlerts);
const revisionPressure = computed(() => control.revisionPressure);
const cards = computed(() => editor.cardItems);

const tabs = [
  { id: "cards", label: "结构诊断卡" },
  { id: "characters", label: "人物弧线" },
  { id: "foreshadow", label: "伏笔债务" },
  { id: "information", label: "信息释放" },
  { id: "promise", label: "承诺兑现" },
  { id: "reference", label: "参考书安全" },
];

function statusLabel(value) {
  return {
    empty: "尚未生成",
    partial: "部分生成",
    complete: "完整",
    aggregate_missing: "未聚合",
    aggregate_matches_current: "聚合已同步",
    aggregate_differs_current: "聚合不同步",
    open: "待处理",
    resolved: "已解决",
    dismissed: "已忽略",
    published_guidance: "已发布指导",
  }[value] || value || "-";
}

function severityLabel(value) {
  return {
    info: "提示",
    minor: "轻微",
    major: "重要",
    critical: "关键",
  }[value] || value || "-";
}

function cardTitle(card) {
  return {
    character_arc_gap: "人物弧线断档",
    foreshadow_debt: "伏笔债务拖欠",
    promise_without_payoff: "承诺未兑现",
    information_congestion: "信息释放拥堵",
    theme_pressure_light: "主题压力过轻",
    relationship_turn_stall: "关系转向停滞",
    ending_drive_drop: "结尾驱动力下降",
    reference_leakage_risk: "参考书泄漏风险",
  }[card.card_type] || card.card_type;
}

function scoreLabel(value) {
  if (value === null || value === undefined) {
    return "未诊断";
  }
  return `${Math.round(Number(value) * 100)} 分`;
}

function openChapter(chapterId) {
  if (!chapterId) {
    return;
  }
  openTarget({
    target_type: "chapter_manuscript",
    target_id: chapterId,
    target_ref: `chapter_manuscript:${chapterId}`,
  });
}

function openDeepDesk(card) {
  if (!card?.scene_id && !card?.chapter_id) {
    return;
  }
  openTarget(
    {
      target_type: card.scene_id ? "scene_card" : "chapter_manuscript",
      target_id: card.scene_id || card.chapter_id,
      target_ref: `${card.scene_id ? "scene_card" : "chapter_manuscript"}:${card.scene_id || card.chapter_id}`,
      source_type: "longform_diagnostic_card",
      source_id: card.card_id,
    },
    { view_id: "deepdesk" },
  );
  navigate("deepdesk");
}

async function refresh() {
  try {
    await Promise.all([control.refresh(), editor.initialize({ force: true })]);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runDiagnose() {
  try {
    await editor.runDiagnose();
  } catch (error) {
    emit("notice", error.message);
  }
}

async function actOnCard(card, action) {
  try {
    await editor.actOnCard(card.card_id, { action });
  } catch (error) {
    emit("notice", error.message);
  }
}

async function publishGuidance(card) {
  const content = (guidanceDraft.value[card.card_id] || card.recommendation?.summary || "").trim();
  if (!content) {
    emit("notice", "请先填写要发布的结构指导。");
    return;
  }
  try {
    await editor.publishGuidance(card.card_id, {
      scope_type: card.scene_id ? "scene" : card.chapter_id ? "chapter" : "global",
      scope_ref_id: card.scene_id || card.chapter_id || "global",
      content,
    });
    navigate("review");
  } catch (error) {
    emit("notice", error.message);
  }
}

async function loadReferenceSafety() {
  try {
    await editor.loadReferenceSafety();
  } catch (error) {
    emit("notice", error.message);
  }
}

async function runSourceScan() {
  try {
    await editor.scanSourceSafety({ text: scanText.value });
  } catch (error) {
    emit("notice", error.message);
  }
}

async function ensureLoaded() {
  try {
    await Promise.all([control.initialize(), editor.initialize(), editor.loadReferenceSafety()]);
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
  <section class="panel-grid longform-control-view" data-testid="longform-control-view">
    <WorkflowPageHeader view-id="longform" />
    <PanelShell
      eyebrow="长篇编辑塔"
      title="结构诊断、伏笔债务、人物弧线与参考书安全"
      description="诊断卡只给出编辑判断和导航，不自动改正文，也不阻断运行终稿。"
    >
      <template #actions>
        <button data-testid="longform-refresh-button" :disabled="control.loading || editor.loading" @click="refresh">
          刷新
        </button>
        <button data-testid="longform-diagnose-button" :disabled="editor.actionLoading" @click="runDiagnose">
          生成诊断卡
        </button>
      </template>

      <div v-if="control.loading || editor.loading" class="empty">正在加载长篇编辑塔...</div>
      <div v-else-if="control.error || editor.error" class="empty">{{ control.error || editor.error }}</div>
      <div v-else class="longform-layout">
        <section class="longform-summary-grid">
          <article class="paper mini">
            <span>章节</span>
            <strong>{{ summary.chapter_count || 0 }}</strong>
          </article>
          <article class="paper mini">
            <span>场景</span>
            <strong>{{ summary.scene_count || 0 }}</strong>
          </article>
          <article class="paper mini">
            <span>开放卡</span>
            <strong>{{ editor.cardSummary.open_count || 0 }}</strong>
          </article>
          <article class="paper mini">
            <span>伏笔债务</span>
            <strong>{{ summary.open_foreshadow_count || 0 }}</strong>
          </article>
          <article class="paper mini">
            <span>已发布指导</span>
            <strong>{{ editor.cardSummary.published_guidance_count || 0 }}</strong>
          </article>
        </section>

        <nav class="toolbar compact" data-testid="longform-editor-tabs">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            type="button"
            :class="{ primary: activeTab === tab.id }"
            @click="activeTab = tab.id"
          >
            {{ tab.label }}
          </button>
        </nav>

        <section v-show="activeTab === 'cards'" class="paper longform-section" data-testid="longform-editor-cards">
          <div class="receipt-head">
            <div>
              <h3>结构诊断卡</h3>
              <p class="muted receipt-copy">把仪表盘指标转成可处理的编辑动作；发布指导后仍需在审核收件箱批准。</p>
            </div>
          </div>
          <div v-if="!cards.length" class="empty">暂无诊断卡。点击“生成诊断卡”开始结构巡检。</div>
          <div v-else class="longform-card-grid">
            <article v-for="card in cards" :key="card.card_id" class="longform-card">
              <div class="receipt-head compact">
                <div>
                  <strong>{{ cardTitle(card) }}</strong>
                  <p class="muted">{{ card.chapter_id || "全书" }}{{ card.scene_id ? ` / ${card.scene_id}` : "" }}</p>
                </div>
                <span class="badge">{{ severityLabel(card.severity) }} · {{ statusLabel(card.status) }}</span>
              </div>
              <p>{{ card.evidence?.issue || card.evidence?.text || card.evidence?.chapter_promise || "结构压力需要作者判断。" }}</p>
              <p class="muted">{{ card.recommendation?.summary || "-" }}</p>
              <textarea
                v-model="guidanceDraft[card.card_id]"
                rows="3"
                :placeholder="card.recommendation?.summary || '写下要进入审核的结构指导'"
              />
              <div class="toolbar compact">
                <button type="button" @click="openDeepDesk(card)">跳转深改台</button>
                <button type="button" @click="actOnCard(card, 'resolve')">解决</button>
                <button type="button" @click="actOnCard(card, 'dismiss')">忽略</button>
                <button type="button" @click="actOnCard(card, 'reopen')">重开</button>
                <button type="button" class="primary" @click="publishGuidance(card)">发布为指导</button>
              </div>
            </article>
          </div>
        </section>

        <section v-show="activeTab === 'characters'" class="paper longform-section" data-testid="longform-character-arcs">
          <div class="receipt-head">
            <div>
              <h3>人物弧线</h3>
              <p class="muted receipt-copy">查看 POV、出场、主动性和权力转移信号。</p>
            </div>
          </div>
          <div class="longform-card-grid">
            <article v-for="arc in characterArcs" :key="arc.character_id" class="longform-card">
              <strong>{{ arc.character_id }}</strong>
              <p>{{ (arc.chapters || []).join(", ") || "暂无章节" }}</p>
              <p class="muted">POV {{ arc.pov_scene_count }} · 出场 {{ arc.onstage_scene_count }} · 主动性低分 {{ arc.low_agency_finding_count }}</p>
            </article>
          </div>
        </section>

        <section v-show="activeTab === 'foreshadow'" class="paper longform-section" data-testid="longform-foreshadow-debts">
          <div class="receipt-head">
            <div>
              <h3>伏笔债务</h3>
              <p class="muted receipt-copy">来自 ForeshadowTracker 的开启、触碰和解决状态。</p>
            </div>
          </div>
          <div class="longform-card-grid">
            <article v-for="debt in foreshadowDebts" :key="debt.row_id" class="longform-card">
              <strong>{{ debt.foreshadow_id }}</strong>
              <p>{{ debt.text }}</p>
              <p class="muted">{{ debt.chapter_id }}{{ debt.scene_id ? ` / ${debt.scene_id}` : "" }} · {{ statusLabel(debt.debt_state) }}</p>
            </article>
          </div>
        </section>

        <section v-show="activeTab === 'information'" class="paper longform-section" data-testid="longform-literary-signals">
          <div class="receipt-head">
            <div>
              <h3>信息释放</h3>
              <p class="muted receipt-copy">集中看解释、行动、转折与信息节奏。</p>
            </div>
          </div>
          <div class="longform-table">
            <div class="longform-table-row head">
              <span>章节</span>
              <span>场景</span>
              <span>释放类型</span>
              <span>新信息</span>
            </div>
            <button
              v-for="row in informationReleaseCurve"
              :key="`${row.chapter_id}-${row.scene_id}`"
              type="button"
              class="longform-table-row clickable"
              @click="openChapter(row.chapter_id)"
            >
              <strong>{{ row.chapter_id }}</strong>
              <span>{{ row.scene_id || "-" }}</span>
              <span>{{ row.release_type || "-" }}</span>
              <span>{{ row.new_information || "-" }}</span>
            </button>
          </div>
          <div class="longform-card-grid">
            <article v-for="relation in relationTensionMatrix" :key="`rel-${relation.pair_key || relation.pair}`" class="longform-card">
              <strong>{{ relation.pair_key || (relation.pair || []).join("/") }}</strong>
              <p>{{ (relation.tension_sources || relation.unexploded_points || []).join(" / ") || relation.tension_note || "-" }}</p>
              <p class="muted">关系压力</p>
            </article>
            <article v-for="motif in motifTracking" :key="`motif-${motif.motif || motif.image_anchor}`" class="longform-card">
              <strong>{{ motif.motif || motif.image_anchor }}</strong>
              <p>{{ (motif.chapters || [motif.chapter_id]).filter(Boolean).join(", ") || "-" }}</p>
              <p class="muted">{{ motif.transformation_note || motif.risk || "-" }}</p>
            </article>
          </div>
        </section>

        <section v-show="activeTab === 'promise'" class="paper longform-section" data-testid="longform-promise-payoff">
          <div class="receipt-head">
            <div>
              <h3>承诺兑现</h3>
              <p class="muted receipt-copy">每章提出的问题、兑现目标和当前拖欠风险。</p>
            </div>
          </div>
          <div class="longform-table">
            <div class="longform-table-row head">
              <span>章节</span>
              <span>承诺</span>
              <span>兑现</span>
              <span>风险</span>
            </div>
            <button
              v-for="row in promisePayoff"
              :key="row.chapter_id"
              type="button"
              class="longform-table-row clickable"
              @click="openChapter(row.chapter_id)"
            >
              <strong>{{ row.chapter_id }}</strong>
              <span>{{ row.chapter_promise || row.ending_question || "-" }}</span>
              <span>{{ row.payoff_target || row.reveal_or_reversal || "-" }}</span>
              <span>{{ row.open_hook_count || 0 }}</span>
            </button>
          </div>
        </section>

        <section v-show="activeTab === 'reference'" class="paper longform-section" data-testid="longform-reference-safety">
          <div class="receipt-head">
            <div>
              <h3>参考书安全</h3>
              <p class="muted receipt-copy">查看安全画像覆盖，并对可疑文本做泄漏扫描。</p>
            </div>
            <button type="button" @click="loadReferenceSafety">刷新安全画像</button>
          </div>
          <div class="longform-summary-grid">
            <article class="paper mini">
              <span>画像</span>
              <strong>{{ editor.referenceSafety.summary.profile_count || 0 }}</strong>
            </article>
            <article class="paper mini">
              <span>已抽取安全画像</span>
              <strong>{{ editor.referenceSafety.summary.profile_with_safety_count || 0 }}</strong>
            </article>
            <article class="paper mini">
              <span>扫描风险</span>
              <strong>{{ editor.sourceSafetyScan?.risk_count || 0 }}</strong>
            </article>
          </div>
          <textarea v-model="scanText" rows="4" placeholder="粘贴要扫描的文本片段" />
          <div class="toolbar compact">
            <button type="button" class="primary" @click="runSourceScan">扫描文本</button>
          </div>
          <div v-if="editor.sourceSafetyScan?.risks?.length" class="longform-alert-list">
            <article v-for="risk in editor.sourceSafetyScan.risks" :key="`${risk.risk_type}-${risk.matched}`" class="longform-alert">
              <strong>{{ risk.risk_type }}</strong>
              <span>{{ Array.isArray(risk.matched) ? risk.matched.join(" / ") : risk.matched }}</span>
              <small>{{ risk.recommendation }}</small>
            </article>
          </div>
        </section>

        <section class="paper longform-section" data-testid="longform-rhythm-map">
          <div class="receipt-head">
            <div>
              <h3>章节节奏</h3>
              <p class="muted receipt-copy">保留原有长篇控制台的进度、字数、评分与 QC 压力。</p>
            </div>
          </div>
          <div class="longform-table">
            <div class="longform-table-row head">
              <span>章节</span>
              <span>进度</span>
              <span>字数</span>
              <span>评分</span>
              <span>QC</span>
            </div>
            <button
              v-for="row in rhythmMap"
              :key="row.chapter_id"
              type="button"
              class="longform-table-row clickable"
              @click="openChapter(row.chapter_id)"
            >
              <strong>{{ row.chapter_id }}</strong>
              <span>{{ row.generated_scene_count }}/{{ row.scene_count }} · {{ statusLabel(row.completion_status) }}</span>
              <span>{{ row.assembled_char_count }}</span>
              <span>{{ scoreLabel(row.average_writer_score) }}</span>
              <span>{{ row.qc_blocker_count }}</span>
            </button>
          </div>
        </section>

        <section class="paper longform-section" data-testid="longform-continuity-alerts">
          <div class="receipt-head">
            <div>
              <h3>连续性告警</h3>
              <p class="muted receipt-copy">缺终稿、聚合过期、人工复核和 LLM 异常集中查看。</p>
            </div>
          </div>
          <div v-if="!continuityAlerts.length" class="empty">当前没有连续性告警。</div>
          <div v-else class="longform-alert-list">
            <button
              v-for="alert in continuityAlerts"
              :key="`${alert.alert_type}-${alert.chapter_id}-${alert.scene_id || 'chapter'}`"
              type="button"
              class="longform-alert"
              @click="openChapter(alert.chapter_id)"
            >
              <strong>{{ alert.alert_type }}</strong>
              <span>{{ alert.chapter_id }}{{ alert.scene_id ? ` / ${alert.scene_id}` : "" }}</span>
              <small>{{ alert.message }}</small>
            </button>
          </div>
        </section>

        <section class="paper longform-section" data-testid="longform-revision-pressure">
          <div class="receipt-head">
            <div>
              <h3>修订压力</h3>
              <p class="muted receipt-copy">按章节汇总开放候选、人工复核和最低分维度。</p>
            </div>
          </div>
          <div class="longform-table">
            <div class="longform-table-row head">
              <span>章节</span>
              <span>候选</span>
              <span>人工</span>
              <span>低分维度</span>
            </div>
            <button
              v-for="row in revisionPressure"
              :key="row.chapter_id"
              type="button"
              class="longform-table-row clickable"
              @click="openChapter(row.chapter_id)"
            >
              <strong>{{ row.chapter_id }}</strong>
              <span>{{ row.open_candidate_count }}</span>
              <span>{{ row.requires_human_review_count }}</span>
              <span>{{ (row.top_low_dimensions || []).map((item) => `${item.dimension} ${Math.round(item.score * 100)}`).join(" / ") || "-" }}</span>
            </button>
          </div>
        </section>
      </div>
    </PanelShell>
  </section>
</template>
