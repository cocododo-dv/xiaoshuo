<script setup>
import { computed, onActivated, onDeactivated, ref, watch } from "vue";

import AttemptTimeline from "../components/AttemptTimeline.vue";
import BundleProvenanceCard from "../components/BundleProvenanceCard.vue";
import CursorPager from "../components/CursorPager.vue";
import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import GenerationSummaryCard from "../components/GenerationSummaryCard.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import LazySection from "../components/LazySection.vue";
import PanelShell from "../components/PanelShell.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import QcReportCard from "../components/QcReportCard.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useWorkbenchStore } from "../stores/workbench";

const emit = defineEmits(["notice"]);

const workbench = useWorkbenchStore();
const { focusTarget, openTarget, navigate } = useShellRouter();
const requestedSceneId = ref(workbench.sceneId);
const manualHoldReason = ref("");
const selectedStrategies = ref({});
const isViewActive = ref(false);
const DEFAULT_BACKFILL_STRATEGY = "create_tracker_now";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});
const WORKBENCH_MAIN_SCOPE = "workbench:main";
const WORKBENCH_CHAPTER_SCOPE = "workbench:chapter";

const hasData = computed(() => Boolean(workbench.data));
const chapterState = computed(() => workbench.data?.chapter_state || {});
const chapterId = computed(() => workbench.data?.chapter_goal?.chapter_id || "");
const runPreflight = computed(() => workbench.data?.run_preflight || {
  can_run: true,
  overall_status: "ready",
  blocking_items: [],
  warning_items: [],
  context_items: [],
});
const generationSummary = computed(() => workbench.data?.generation_summary || null);
const hardQcSummary = computed(() => workbench.data?.hard_qc_summary || null);
const softQcSummary = computed(() => workbench.data?.soft_qc_summary || null);
const rewriteCounters = computed(() => workbench.data?.rewrite_counters || null);
const humanReviewSummary = computed(() => workbench.data?.human_review_summary || null);
const pendingStagedBackfillItems = computed(() =>
  (chapterState.value.staged_backfill_items || []).filter((item) => item.status === "pending"),
);
const focusedSceneId = computed(() =>
  focusTarget.value?.target_type === "scene_card" ? focusTarget.value.target_id : "",
);
const focusedHumanReviewEventId = computed(() =>
  focusTarget.value?.target_type === "human_review_event" ? focusTarget.value.target_id : "",
);
const isFocusedRunReceipt = computed(
  () => focusTarget.value?.source_type === "scene_run_receipt" && focusTarget.value?.source_id === workbench.sceneId,
);
const currentFinalSceneRowId = computed(() =>
  workbench.data?.scene_run_state?.current_final_scene_row_id
  || workbench.lastRunResult?.current_final_scene_row_id
  || workbench.data?.final_scene?.row_id
  || "-",
);
const BLOCKING_QC_ISSUE_KEYS = new Set([
  "character_pronoun_drift",
  "instruction_residue",
  "mechanical_required_beat_listing",
  "scene_conflict_missing",
  "source_leak_risk",
]);
const archiveQualityLabel = computed(() => {
  if (!hasData.value) {
    return "-";
  }
  const sceneStatus = workbench.data?.scene_run_state?.scene_status || "";
  const hardIssueKeys = hardQcSummary.value?.issue_keys || [];
  const softIssueKeys = softQcSummary.value?.issue_keys || [];
  const hasBlockingIssue = [...hardIssueKeys, ...softIssueKeys].some((issueKey) => BLOCKING_QC_ISSUE_KEYS.has(issueKey));
  const triggerReason = humanReviewSummary.value?.trigger_reason || "";
  if (triggerReason === "blocking_soft_qc_issue" || (sceneStatus !== "archived" && hasBlockingIssue)) {
    return "Blocked by deterministic QC";
  }
  if (sceneStatus === "archived" && (softQcSummary.value?.resolution_code === "soft_waive" || softQcSummary.value?.next_action === "pass_with_notes")) {
    return "Archived with waived notes";
  }
  if (sceneStatus === "archived") {
    return "Clean archived";
  }
  return formatStatus(sceneStatus);
});
const attemptEvidenceLabel = computed(() => (workbench.attempts.length ? `${workbench.attempts.length} 条轨迹` : "暂无轨迹"));
const qcEvidenceLabel = computed(() => {
  if (!hasData.value) {
    return "-";
  }
  const hard = hardQcSummary.value?.status || hardQcSummary.value?.result || "";
  const soft = softQcSummary.value?.status || softQcSummary.value?.result || "";
  return [hard, soft].filter(Boolean).join(" / ") || "已显示";
});
const sceneMissingGuidance = computed(() => {
  const message = String(workbench.error || "").toLowerCase();
  if (!message) {
    return "";
  }
  if (message.includes("not found") || message.includes("404")) {
    return "没有找到这个场景。请检查场景 ID，或回到作者工作台从章节里的场景按钮打开。";
  }
  return "读取场景时遇到问题。请检查场景 ID，刷新后再试。";
});

const STATUS_LABELS = {
  ready: "就绪",
  archived: "已归档",
  pending: "待处理",
  running: "进行中",
  completed: "已完成",
  none: "无",
  blocked_waiting_backfill: "等待补写",
  manual_hold: "人工挂起",
};

const ACTION_LABELS = {
  run_backfill: "执行补写",
  run_backfill_again: "重新执行补写",
  create_tracker_now: "立即创建跟踪",
  explicit_defer_with_tracker: "明确延后并跟踪",
  mark_staged_abandoned: "标记暂存为放弃",
  run_final_aggregate: "运行最终聚合",
  set_manual_hold: "设置人工挂起",
  clear_manual_hold: "清除人工挂起",
};

const PREFLIGHT_STATUS_LABELS = {
  ready: "可以运行",
  warning: "可以运行，但建议先补充信息",
  blocked: "暂时不可运行",
};

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function formatAction(action) {
  return ACTION_LABELS[action] || action || "-";
}

function formatPreflightStatus(status) {
  return PREFLIGHT_STATUS_LABELS[status] || status || "-";
}

function resolveSceneId() {
  return requestedSceneId.value.trim() || workbench.sceneId;
}

function openAuthorWorkspace() {
  navigate("author");
  emit("notice", "已打开作者工作台");
}

function sceneCardTarget(sceneId = resolveSceneId()) {
  if (!sceneId) {
    return null;
  }
  return {
    target_type: "scene_card",
    target_id: sceneId,
    target_ref: `scene_card:${sceneId}`,
  };
}

function selectedStrategyFor(stageId) {
  return selectedStrategies.value[stageId] || DEFAULT_BACKFILL_STRATEGY;
}

function syncSelectedStrategies(items) {
  const current = selectedStrategies.value;
  const next = {};

  items.forEach((item) => {
    if (item.stage_id) {
      next[item.stage_id] = current[item.stage_id] || DEFAULT_BACKFILL_STRATEGY;
    }
  });

  const currentKeys = Object.keys(current);
  const nextKeys = Object.keys(next);
  const changed =
    currentKeys.length !== nextKeys.length
    || nextKeys.some((stageId) => current[stageId] !== next[stageId]);

  if (changed) {
    selectedStrategies.value = next;
  }
}

async function loadWorkbench() {
  if (!resolveSceneId()) {
    emit("notice", "请先从作者工作台选择场景，或输入场景 ID。");
    return;
  }
  await runFlowAction({
    scopeKey: WORKBENCH_MAIN_SCOPE,
    actionLabel: "读取场景",
    runningMessage: "正在读取场景工作台数据...",
    successMessage: () => "场景工作台已刷新。",
    nextStep: () => "下一步：检查运行前提示，确认后运行完整场景。",
    action: () => workbench.refreshAll(resolveSceneId(), { force: true }),
  });
}

async function ensureWorkbenchLoaded() {
  if (!resolveSceneId()) {
    return;
  }
  await workbench.ensureLoaded({ sceneId: resolveSceneId() });
  if (workbench.error) {
    emit("notice", workbench.error);
  }
}

async function nextAttemptsPage() {
  await workbench.nextAttemptsPage();
  if (workbench.error) {
    emit("notice", workbench.error);
  }
}

async function previousAttemptsPage() {
  await workbench.previousAttemptsPage();
  if (workbench.error) {
    emit("notice", workbench.error);
  }
}

async function runScene() {
  const sceneId = resolveSceneId();
  if (!sceneId) {
    emit("notice", "请先从作者工作台选择场景，或输入场景 ID。");
    return;
  }
  const result = await runFlowAction({
    scopeKey: WORKBENCH_MAIN_SCOPE,
    actionLabel: "运行完整场景",
    runningMessage: "正在运行完整场景流水线...",
    successMessage: (message) => message || "完整场景运行已完成。",
    nextStep: () => "下一步：查看下方运行回执、质量报告和 bundle 来源。",
    action: () => workbench.runScene(sceneId),
  });
  if (result) {
    openTarget(sceneCardTarget(sceneId), {
      view_id: "workbench",
      source_type: "scene_run_receipt",
      source_id: sceneId,
    });
  }
}

async function runChapterBackfill(stageId) {
  await runFlowAction({
    scopeKey: WORKBENCH_CHAPTER_SCOPE,
    actionLabel: "执行章节补写",
    runningMessage: "正在执行章节补写动作...",
    successMessage: (message) => message || "章节补写已完成。",
    nextStep: () => "下一步：查看章节运行状态，必要时继续运行完整场景。",
    action: () => workbench.runChapterBackfill(
      chapterId.value,
      stageId,
      selectedStrategyFor(stageId),
      resolveSceneId(),
    ),
  });
}

async function runChapterFinalAggregate() {
  await runFlowAction({
    scopeKey: WORKBENCH_CHAPTER_SCOPE,
    actionLabel: "运行最终聚合",
    runningMessage: "正在聚合章节最终状态...",
    successMessage: (message) => message || "章节最终聚合已完成。",
    nextStep: () => "下一步：回到场景状态或运行完整场景确认结果。",
    action: () => workbench.runChapterFinalAggregate(chapterId.value, resolveSceneId()),
  });
}

async function setManualHold() {
  await runFlowAction({
    scopeKey: WORKBENCH_CHAPTER_SCOPE,
    actionLabel: "设置人工挂起",
    runningMessage: "正在设置章节人工挂起...",
    successMessage: (message) => message || "已设置人工挂起。",
    nextStep: () => "下一步：处理挂起原因；准备好后可解除挂起。",
    action: () => workbench.setChapterManualHold(chapterId.value, manualHoldReason.value, resolveSceneId()),
  });
}

async function clearManualHold() {
  await runFlowAction({
    scopeKey: WORKBENCH_CHAPTER_SCOPE,
    actionLabel: "解除人工挂起",
    runningMessage: "正在解除章节人工挂起...",
    successMessage: (message) => message || "已解除人工挂起。",
    nextStep: () => "下一步：继续章节运行或运行完整场景。",
    action: () => workbench.clearChapterManualHold(chapterId.value, resolveSceneId()),
  });
}

function handleOpenTarget(target) {
  openTarget(target);
  emit("notice", `已打开 ${target.target_ref}`);
}

async function syncWorkbenchFocus() {
  if (!isViewActive.value) {
    return false;
  }
  if (
    focusTarget.value?.target_type === "scene_card"
    && focusTarget.value.target_id
    && focusTarget.value.target_id !== workbench.sceneId
  ) {
    requestedSceneId.value = focusTarget.value.target_id;
    await loadWorkbench();
    return true;
  }
  return false;
}

watch(
  () => focusTarget.value?.target_ref,
  async () => {
    await syncWorkbenchFocus();
  },
);

watch(
  () => workbench.data?.chapter_state?.manual_hold_reason,
  (value) => {
    manualHoldReason.value = value || "";
  },
  { immediate: true },
);

watch(pendingStagedBackfillItems, syncSelectedStrategies, { immediate: true });

onActivated(async () => {
  isViewActive.value = true;
  const focusedLoaded = await syncWorkbenchFocus();
  if (!focusedLoaded) {
    await ensureWorkbenchLoaded();
  }
});

onDeactivated(() => {
  isViewActive.value = false;
});
</script>

<template>
  <section class="panel-grid" data-testid="scene-workbench-view">
    <PanelShell
      eyebrow="场景工作台"
      title="场景循环与归档"
      description="本页用于生成与验收单场景；平时从作者工作台打开场景后再运行。"
    >
      <template #actions>
        <div class="field-inline">
          <input
            v-model="requestedSceneId"
            class="control-input"
            data-testid="scene-id-input"
            placeholder="从作者工作台选择场景，或输入场景 ID"
          />
          <button data-testid="scene-load-button" @click="loadWorkbench">读取</button>
          <button
            :disabled="workbench.actionId === 'run-scene' || !runPreflight.can_run || !resolveSceneId()"
            data-testid="run-full-scene-button"
            @click="runScene"
          >
            {{ workbench.actionId === "run-scene" ? "运行中..." : "运行完整场景" }}
          </button>
        </div>
      </template>
      <FlowActionReceipt :receipt="receipt(WORKBENCH_MAIN_SCOPE)" />

      <div class="stats workbench-purpose-strip" data-testid="workbench-purpose-strip">
        <div class="stat">
          <span>用途</span>
          <strong>本页用于生成与验收单场景</strong>
        </div>
        <div class="stat">
          <span>当前场景</span>
          <strong>{{ workbench.sceneId || "未选择" }}</strong>
        </div>
        <div class="stat">
          <span>预检</span>
          <strong>{{ hasData ? formatPreflightStatus(runPreflight.overall_status) : "等待加载" }}</strong>
        </div>
        <div class="stat">
          <span>终稿行</span>
          <strong>{{ currentFinalSceneRowId }}</strong>
        </div>
        <div class="stat">
          <span>QC</span>
          <strong>{{ qcEvidenceLabel }}</strong>
        </div>
        <div class="stat" data-testid="scene-archive-quality-label">
          <span>Archive Quality</span>
          <strong>{{ archiveQualityLabel }}</strong>
        </div>
        <div class="stat">
          <span>运行轨迹</span>
          <strong>{{ attemptEvidenceLabel }}</strong>
        </div>
      </div>

      <div v-if="workbench.loading" class="empty">正在加载场景工作台...</div>
      <template v-else-if="hasData">
        <article v-if="workbench.error" class="paper inline-error">
          <h3>最新错误</h3>
          <p>{{ workbench.error }}</p>
        </article>

        <div class="stats">
          <div class="stat">
            <span>构包</span>
            <strong>{{ workbench.data.bundle?.bundle_id || "-" }}</strong>
          </div>
          <div class="stat">
            <span>哈希</span>
            <strong>{{ workbench.data.bundle?.bundle_snapshot_hash || "-" }}</strong>
          </div>
          <div class="stat">
            <span>状态</span>
            <strong>{{ formatStatus(workbench.data.scene_run_state.scene_status) }}</strong>
          </div>
        </div>

        <article class="paper preflight-card" data-testid="scene-run-preflight-card">
          <div class="receipt-head">
            <div>
              <h3>运行前检查</h3>
              <p class="muted receipt-copy">在点击完整运行前，先确认当前场景依赖和输入状态是否到位。</p>
            </div>
            <span class="badge" data-testid="scene-run-preflight-status">
              {{ formatPreflightStatus(runPreflight.overall_status) }}
            </span>
          </div>

          <p class="muted">
            {{ runPreflight.can_run ? "当前允许执行完整场景运行。" : "当前存在真实阻塞项，完整场景运行已被禁用。" }}
          </p>

          <div
            v-if="runPreflight.blocking_items.length"
            class="preflight-group"
            data-testid="scene-run-preflight-blocking"
          >
            <h4>阻塞项</h4>
            <ProgressiveList
              :items="runPreflight.blocking_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-blocking-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item preflight-item-blocking"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <div
            v-if="runPreflight.warning_items.length"
            class="preflight-group"
            data-testid="scene-run-preflight-warning"
          >
            <h4>建议补充</h4>
            <ProgressiveList
              :items="runPreflight.warning_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-warning-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <div
            v-if="runPreflight.context_items.length"
            class="preflight-group"
            data-testid="scene-run-preflight-context"
          >
            <h4>章节上下文</h4>
            <ProgressiveList
              :items="runPreflight.context_items"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-context-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.code"
                  class="preflight-item"
                  :data-testid="`scene-run-preflight-item-${item.code}`"
                >
                  <div class="preflight-item-head">
                    <strong>{{ item.title }}</strong>
                    <span class="badge ghost">{{ item.code }}</span>
                  </div>
                  <p>{{ item.detail }}</p>
                  <p v-if="item.technical_hint" class="muted"><code>{{ item.technical_hint }}</code></p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <p
            v-if="!runPreflight.blocking_items.length && !runPreflight.warning_items.length && !runPreflight.context_items.length"
            class="muted"
          >
            当前没有预检提示，可以直接执行完整场景运行。
          </p>
        </article>

        <article
          v-if="workbench.lastRunResult"
          class="paper receipt-card"
          data-testid="scene-run-receipt"
          :class="{ 'focused-card': isFocusedRunReceipt }"
        >
          <div class="receipt-head">
            <div>
              <h3>运行回执</h3>
              <p class="muted receipt-copy">面板刷新前捕获的最近一次流水线返回结果。</p>
            </div>
            <span class="badge">完整运行</span>
          </div>
          <div class="receipt-grid">
            <p><strong>状态</strong><br />{{ formatStatus(workbench.lastRunResult.scene_status) }}</p>
            <p><strong>构包</strong><br />{{ workbench.lastRunResult.current_bundle_id || "-" }}</p>
            <p><strong>哈希</strong><br />{{ workbench.lastRunResult.current_bundle_hash || "-" }}</p>
            <p><strong>最终场景</strong><br />{{ workbench.lastRunResult.current_final_scene_row_id || "-" }}</p>
          </div>
          <div class="card-actions">
            <button
              class="ghost"
              @click="handleOpenTarget({
                ...sceneCardTarget(),
                source_type: 'scene_run_receipt',
                source_id: workbench.sceneId,
                view_id: 'workbench',
              })"
            >
              打开场景卡片
            </button>
          </div>
        </article>
        <FlowActionReceipt :receipt="receipt(WORKBENCH_CHAPTER_SCOPE)" />

        <div class="workbench-columns" data-testid="scene-workbench-summary-row">
          <GenerationSummaryCard
            data-testid="scene-generation-summary-card"
            :summary="generationSummary"
          />
          <QcReportCard
            data-testid="scene-qc-report-card"
            :hard-summary="hardQcSummary"
            :soft-summary="softQcSummary"
            :rewrite-counters="rewriteCounters"
            :human-review-summary="humanReviewSummary"
          />
        </div>

        <div class="workbench-columns">
          <article
            class="paper"
            data-testid="scene-workbench-scene-card"
            :class="{ 'focused-card': (focusedSceneId && workbench.data.scene_card.scene_id === focusedSceneId) || isFocusedRunReceipt }"
          >
            <h3>章节 / 场景</h3>
            <p><strong>{{ workbench.data.chapter_goal.chapter_goal }}</strong></p>
            <p>{{ workbench.data.scene_card.scene_goal }}</p>
            <p class="muted">地点：{{ workbench.data.scene_card.location || "-" }}</p>
            <p class="muted">必须包含：{{ workbench.data.scene_card.must_include_text || "-" }}</p>
          </article>
          <article class="paper">
            <h3>草稿谱系</h3>
            <p><strong>中性稿</strong><br />{{ workbench.data.neutral_draft?.content || "-" }}</p>
            <p><strong>风格稿</strong><br />{{ workbench.data.style_draft?.content || "-" }}</p>
            <p><strong>定稿</strong><br />{{ workbench.data.final_scene?.content || "-" }}</p>
          </article>
          <article class="paper">
            <h3>归档 / 门控</h3>
            <p><strong>场景记忆</strong><br />{{ workbench.data.scene_memory?.content || "-" }}</p>
            <p class="muted">待补写：{{ workbench.data.chapter_state.chapter_backfill_pending_count }}</p>
            <p class="muted">聚合门控：{{ formatStatus(workbench.data.chapter_state.aggregate_block_reason) }}</p>
            <p class="muted">人工挂起：{{ workbench.data.chapter_state.manual_hold_reason || "-" }}</p>
            <p class="muted">最终记忆行：{{ workbench.data.chapter_state.last_final_memory_row_id || "-" }}</p>

            <div class="chapter-runtime-section">
              <h4>待处理补写</h4>
              <ProgressiveList
                v-if="pendingStagedBackfillItems.length"
                class="chapter-backfill-list"
                :items="pendingStagedBackfillItems"
                :initial-count="4"
                :batch-size="4"
                :threshold="4"
                test-id="chapter-backfill-progressive-list"
              >
                <template #default="{ items }">
                  <article
                    v-for="item in items"
                    :key="item.stage_id"
                    class="chapter-backfill-item"
                    :data-testid="`chapter-backfill-item-${item.stage_id}`"
                  >
                  <p><strong>{{ item.marker_text }}</strong></p>
                  <p class="muted">标记 {{ item.marker_id }} / 阶段 {{ item.stage_id }}</p>
                  <div class="field-inline">
                    <select
                      :data-testid="`chapter-backfill-strategy-${item.stage_id}`"
                      :value="selectedStrategies[item.stage_id] || DEFAULT_BACKFILL_STRATEGY"
                      @change="selectedStrategies[item.stage_id] = $event.target.value"
                    >
                      <option value="create_tracker_now">立即创建跟踪</option>
                      <option value="run_backfill_again">重新执行补写</option>
                      <option value="explicit_defer_with_tracker">明确延后并跟踪</option>
                      <option value="mark_staged_abandoned">标记暂存为放弃</option>
                    </select>
                    <button
                      :disabled="workbench.actionId === `chapter-backfill:${item.stage_id}`"
                      :data-testid="`chapter-backfill-run-${item.stage_id}`"
                      @click="runChapterBackfill(item.stage_id)"
                    >
                      {{ workbench.actionId === `chapter-backfill:${item.stage_id}` ? "执行中..." : "执行" }}
                    </button>
                  </div>
                  </article>
                </template>
              </ProgressiveList>
              <p v-else class="muted" data-testid="chapter-backfill-empty">当前没有待处理的暂存补写。</p>
            </div>

            <div class="chapter-runtime-section">
              <h4>章节操作</h4>
              <div class="field-inline">
                <button
                  :disabled="workbench.actionId === 'chapter-final-aggregate'"
                  data-testid="chapter-final-aggregate-button"
                  @click="runChapterFinalAggregate"
                >
                  {{ workbench.actionId === "chapter-final-aggregate" ? "聚合中..." : "运行最终聚合" }}
                </button>
              </div>
              <div class="field-inline chapter-manual-hold-controls">
                <input
                  v-model="manualHoldReason"
                  class="control-input"
                  data-testid="chapter-manual-hold-reason-input"
                  placeholder="人工挂起原因"
                />
                <button
                  :disabled="workbench.actionId === 'chapter-manual-hold-set'"
                  data-testid="chapter-manual-hold-set-button"
                  @click="setManualHold"
                >
                  {{ workbench.actionId === "chapter-manual-hold-set" ? "保存中..." : "设置挂起" }}
                </button>
                <button
                  class="ghost"
                  :disabled="workbench.actionId === 'chapter-manual-hold-clear'"
                  data-testid="chapter-manual-hold-clear-button"
                  @click="clearManualHold"
                >
                  {{ workbench.actionId === "chapter-manual-hold-clear" ? "清除中..." : "清除挂起" }}
                </button>
              </div>
            </div>

            <article
              v-if="workbench.lastChapterActionResult"
              class="paper mini receipt-card chapter-receipt"
              data-testid="chapter-action-receipt"
            >
              <div class="receipt-head">
                <div>
                  <h4>章节操作回执</h4>
                  <p class="muted receipt-copy">最近一次章节运行时操作及返回回执。</p>
                </div>
                <span class="badge">{{ formatAction(workbench.lastChapterActionResult.action) }}</span>
              </div>
              <p class="muted">章节 {{ workbench.lastChapterActionResult.chapter_id }}</p>
              <p v-if="workbench.lastChapterActionResult.stage_id" class="muted">
                阶段 {{ workbench.lastChapterActionResult.stage_id }}
              </p>
              <p v-if="workbench.lastChapterActionResult.strategy" class="muted">
                策略 {{ formatAction(workbench.lastChapterActionResult.strategy) }}
              </p>
              <p v-if="workbench.lastChapterActionResult.reason" class="muted">
                原因 {{ workbench.lastChapterActionResult.reason }}
              </p>
              <p v-if="workbench.lastChapterActionResult.chapter_memory_row_id" class="muted">
                最终记忆 {{ workbench.lastChapterActionResult.chapter_memory_row_id }}
              </p>
              <p v-if="workbench.lastChapterActionResult.status" class="muted">
                状态 {{ formatStatus(workbench.lastChapterActionResult.status) }}
              </p>
            </article>
          </article>
        </div>

        <LazySection
          :key="`bundle-provenance-${workbench.data.bundle?.bundle_id || workbench.sceneId}`"
          title="包谱系"
          toggle-test-id="scene-toggle-bundle-provenance"
        >
          <BundleProvenanceCard :snapshot="workbench.data.bundle?.snapshot" />
        </LazySection>
      </template>
      <div v-else-if="workbench.error" class="empty scene-missing-guidance" data-testid="scene-missing-guidance">
        <p>{{ sceneMissingGuidance }}</p>
        <p class="muted">错误信息：{{ workbench.error }}</p>
        <div class="card-actions">
          <button class="ghost" type="button" @click="openAuthorWorkspace">回到作者工作台</button>
        </div>
      </div>
      <div v-else class="empty" data-testid="scene-workbench-empty">
        从作者工作台选择场景，或输入场景 ID 加载。
      </div>
    </PanelShell>

    <PanelShell eyebrow="尝试时间线" title="执行轨迹">
      <AttemptTimeline :items="workbench.attempts" />
      <CursorPager
        test-id-prefix="attempts-pager"
        :pagination="workbench.attemptPagination"
        :can-previous="Boolean(workbench.attemptCursorStack.length)"
        :can-next="Boolean(workbench.attemptPagination?.has_next)"
        :disabled="workbench.attemptLoading"
        @previous="previousAttemptsPage"
        @next="nextAttemptsPage"
      />
    </PanelShell>

    <PanelShell eyebrow="人工审核抽屉" title="人工回流">
      <HumanReviewDrawer
        :items="workbench.humanReviewItems"
        :focus-event-id="focusedHumanReviewEventId"
        @open-target="handleOpenTarget"
      />
    </PanelShell>
  </section>
</template>
