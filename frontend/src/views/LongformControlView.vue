<script setup>
import { computed, onActivated, onMounted } from "vue";

import PanelShell from "../components/PanelShell.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useShellRouter } from "../router";
import { useLongformControlStore } from "../stores/longformControl";

const emit = defineEmits(["notice"]);

const control = useLongformControlStore();
const { openTarget } = useShellRouter();

const summary = computed(() => control.summary);
const chapters = computed(() => control.chapters);
const rhythmMap = computed(() => control.rhythmMap);
const characterArcs = computed(() => control.characterArcs);
const foreshadowDebts = computed(() => control.foreshadowDebts);
const continuityAlerts = computed(() => control.continuityAlerts);
const revisionPressure = computed(() => control.revisionPressure);

function statusLabel(value) {
  return {
    empty: "尚未生成",
    partial: "部分生成",
    complete: "完整",
    aggregate_missing: "未聚合",
    aggregate_matches_current: "聚合已同步",
    aggregate_differs_current: "聚合不同步",
    open: "未偿还",
    resolved: "已解决",
  }[value] || value || "-";
}

function scoreLabel(value) {
  if (value === null || value === undefined) {
    return "未诊断";
  }
  return `${Math.round(Number(value) * 100)} 分`;
}

function openChapter(chapterId) {
  openTarget({
    target_type: "chapter_manuscript",
    target_id: chapterId,
    target_ref: `chapter_manuscript:${chapterId}`,
  });
}

async function refresh() {
  try {
    await control.refresh();
  } catch (error) {
    emit("notice", error.message);
  }
}

async function ensureLoaded() {
  try {
    await control.initialize();
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
      eyebrow="长篇控制塔"
      title="查看全书节奏、弧线、债务和连续性风险"
      description="这是只读控制台：帮助作者定位压力点，不自动修改正文、人物弧线或悬念状态。"
    >
      <template #actions>
        <button data-testid="longform-refresh-button" :disabled="control.loading" @click="refresh">
          {{ control.loading ? "刷新中..." : "刷新" }}
        </button>
      </template>

      <div v-if="control.loading" class="empty">正在加载长篇控制塔...</div>
      <div v-else-if="control.error" class="empty">{{ control.error }}</div>
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
            <span>候选</span>
            <strong>{{ summary.open_revision_candidate_count || 0 }}</strong>
          </article>
          <article class="paper mini">
            <span>悬念债务</span>
            <strong>{{ summary.open_foreshadow_count || 0 }}</strong>
          </article>
          <article class="paper mini">
            <span>连续性告警</span>
            <strong>{{ summary.continuity_alert_count || 0 }}</strong>
          </article>
        </section>

        <section class="paper longform-section" data-testid="longform-rhythm-map">
          <div class="receipt-head">
            <div>
              <h3>章节节奏</h3>
              <p class="muted receipt-copy">查看每章正文体量、完成度、聚合状态和 QC 压力。</p>
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

        <section class="paper longform-section" data-testid="longform-character-arcs">
          <div class="receipt-head">
            <div>
              <h3>人物弧线</h3>
              <p class="muted receipt-copy">从 POV、出场、人物主动性和权力转移信号派生。</p>
            </div>
          </div>
          <div class="longform-card-grid">
            <article v-for="arc in characterArcs" :key="arc.character_id" class="longform-card">
              <div class="receipt-head compact">
                <div>
                  <strong>{{ arc.character_id }}</strong>
                  <p class="muted">{{ (arc.chapters || []).join(", ") || "暂无章节" }}</p>
                </div>
                <span class="badge">POV {{ arc.pov_scene_count }}</span>
              </div>
              <p>出场 {{ arc.onstage_scene_count }} 场 · 声音 {{ arc.active_voice_profile_count }} · 关系 {{ arc.relation_profile_count }}</p>
              <p class="muted">主动性低分 {{ arc.low_agency_finding_count }} · 权力转移低分 {{ arc.power_shift_finding_count }}</p>
            </article>
          </div>
        </section>

        <section class="paper longform-section" data-testid="longform-foreshadow-debts">
          <div class="receipt-head">
            <div>
              <h3>悬念债务</h3>
              <p class="muted receipt-copy">来自 ForeshadowTracker 的开启、触碰和解决状态。</p>
            </div>
          </div>
          <div class="longform-card-grid">
            <article v-for="debt in foreshadowDebts" :key="debt.row_id" class="longform-card">
              <div class="receipt-head compact">
                <div>
                  <strong>{{ debt.foreshadow_id }}</strong>
                  <p class="muted">{{ debt.chapter_id }} · {{ debt.scene_id || "章节级" }}</p>
                </div>
                <span class="badge">{{ statusLabel(debt.debt_state) }}</span>
              </div>
              <p>{{ debt.text }}</p>
              <p class="muted">{{ debt.tracker_status }}</p>
            </article>
          </div>
        </section>

        <section class="paper longform-section" data-testid="longform-continuity-alerts">
          <div class="receipt-head">
            <div>
              <h3>连续性告警</h3>
              <p class="muted receipt-copy">缺终稿、聚合过期、人工复核和 LLM 异常会在这里集中出现。</p>
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
              <span>开放候选</span>
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
              <span>
                {{ (row.top_low_dimensions || []).map((item) => `${item.dimension} ${Math.round(item.score * 100)}`).join(" / ") || "-" }}
              </span>
            </button>
          </div>
        </section>
      </div>
    </PanelShell>
  </section>
</template>
