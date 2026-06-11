<script setup>
import { computed, onActivated, onDeactivated, ref, watch } from "vue";
import { fetchChapterContract } from "../lib/api/longformTower";

import AttemptTimeline from "../components/AttemptTimeline.vue";
import BaseEmptyState from "../components/base/BaseEmptyState.vue";
import BundleProvenanceCard from "../components/BundleProvenanceCard.vue";
import CursorPager from "../components/CursorPager.vue";
import EvidenceDisclosure from "../components/EvidenceDisclosure.vue";
import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import GenerationSummaryCard from "../components/GenerationSummaryCard.vue";
import HumanReviewDrawer from "../components/HumanReviewDrawer.vue";
import LazySection from "../components/LazySection.vue";
import PanelShell from "../components/PanelShell.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import QcReportCard from "../components/QcReportCard.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import WriterReviewCard from "../components/WriterReviewCard.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useUiMode } from "../composables/useUiMode";
import { useShellRouter } from "../router";
import { useWorkbenchStore } from "../stores/workbench";

const emit = defineEmits(["notice"]);

const workbench = useWorkbenchStore();
const { focusTarget, openTarget, navigate } = useShellRouter();
const requestedSceneId = ref(workbench.sceneId);
const manualHoldReason = ref("");
const selectedStrategies = ref({});
const isViewActive = ref(false);
const { isAdvancedMode } = useUiMode();
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
  missing_dependencies: [],
  create_actions: [],
  constraint_conflicts: [],
});
const missingDependencies = computed(() => runPreflight.value.missing_dependencies || []);
const createActions = computed(() => runPreflight.value.create_actions || []);
const constraintConflicts = computed(() => runPreflight.value.constraint_conflicts || []);
const runJob = computed(() => workbench.runJob || null);

/* 设计稿六段流水线导轨:把后端 10 个 run 阶段折叠成作者可读的六段。
   阶段顺序与 backend scene_run_jobs.SCENE_RUN_STAGE_ORDER 对齐。 */
const PIPELINE_STAGE_ORDER = [
  "planning_running",
  "bundle_built",
  "neutral_running",
  "hard_qc_running",
  "style_running",
  "soft_qc_running",
  "rewrite_running",
  "acceptance_review_running",
  "near_final",
  "archived",
];

const PIPELINE_DISPLAY_STAGES = [
  { key: "preflight", label: "预检 · 打包", steps: ["planning_running", "bundle_built"] },
  { key: "draft", label: "起草", steps: ["neutral_running", "style_running"] },
  { key: "qc", label: "质检", steps: ["hard_qc_running", "soft_qc_running"] },
  { key: "rewrite", label: "二改", steps: ["rewrite_running"] },
  { key: "acceptance", label: "校核", steps: ["acceptance_review_running", "near_final"] },
  { key: "archive", label: "归档", steps: ["archived"] },
];

const pipelineStages = computed(() => {
  const sceneStatus = workbench.data?.scene_run_state?.scene_status || "";
  const jobStep = runJob.value?.current_step || runJob.value?.stage || "";
  const archived = sceneStatus === "archived" || jobStep === "archived";
  const currentIdx = archived ? PIPELINE_STAGE_ORDER.length - 1 : PIPELINE_STAGE_ORDER.indexOf(jobStep);
  return PIPELINE_DISPLAY_STAGES.map((stage) => {
    const stageIdxs = stage.steps.map((step) => PIPELINE_STAGE_ORDER.indexOf(step));
    const first = Math.min(...stageIdxs);
    const last = Math.max(...stageIdxs);
    let state = "todo";
    if (archived || currentIdx > last) {
      state = "done";
    } else if (currentIdx >= first && currentIdx <= last) {
      state = "active";
    }
    return { key: stage.key, label: stage.label, state };
  });
});

const pipelineVisible = computed(() => Boolean(workbench.data?.scene_card));

/* —— 长程约束(控制塔交接契约):预检时在场 ——
   设计语义:契约下发后,起草台预检读同一份约束,生成链路合一。 */
const towerContract = ref(null);

async function loadSceneContract() {
  const card = workbench.data?.scene_card || {};
  const projectId = card.project_id || workbench.data?.chapter?.project_id || "";
  const chapterId = card.chapter_id || "";
  if (!projectId || !chapterId) {
    towerContract.value = null;
    return;
  }
  try {
    towerContract.value = await fetchChapterContract(projectId, chapterId);
  } catch {
    towerContract.value = null;
  }
}

watch(
  () => [workbench.data?.scene_card?.scene_id, workbench.data?.scene_card?.chapter_id],
  () => {
    loadSceneContract();
  },
  { immediate: true },
);

const contractConstraints = computed(() => {
  const sceneId = workbench.data?.scene_card?.scene_id || "";
  return (towerContract.value?.constraints || []).map((constraint) => ({
    ...constraint,
    assigned: Boolean(constraint.scene_id && constraint.scene_id === sceneId),
  }));
});

const generationSummary = computed(() => {
  const summary = workbench.data?.generation_summary || null;
  if (!summary || !workbench.data?.near_final_summary) {
    return summary;
  }
  return {
    ...summary,
    near_final_summary: workbench.data.near_final_summary,
  };
});
const hardQcSummary = computed(() => workbench.data?.hard_qc_summary || null);
const softQcSummary = computed(() => workbench.data?.soft_qc_summary || null);
const rewriteCounters = computed(() => workbench.data?.rewrite_counters || null);
const humanReviewSummary = computed(() => workbench.data?.human_review_summary || null);
const writerReviewSummary = computed(() => workbench.data?.writer_review_summary || null);
const literaryBlueprint = computed(() => workbench.data?.literary_blueprint || null);
const executionContract = computed(() => workbench.data?.execution_contract || null);
const triagePreview = computed(() => workbench.data?.triage_preview || null);
const blueprintItems = computed(() => Object.entries(literaryBlueprint.value?.blueprint_json || {}));
const sourceSafetyScan = computed(() => workbench.data?.source_safety_scan || {
  safe: true,
  blocked_terms: [],
  source_profile_ids: [],
  checked_at: "",
});
const sourceSafetyBlockedTerms = computed(() => sourceSafetyScan.value.blocked_terms || []);
const sourceSafetyProfileIds = computed(() => sourceSafetyScan.value.source_profile_ids || []);
const sourceSafetyStatusLabel = computed(() =>
  sourceSafetyScan.value.safe
    ? "未命中保护标记"
    : `命中 ${sourceSafetyBlockedTerms.value.length} 个保护标记`,
);
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
const receiptBundleId = computed(() =>
  workbench.lastRunResult?.current_bundle_id
  || workbench.data?.bundle?.bundle_id
  || workbench.data?.scene_run_state?.current_bundle_id
  || "-",
);
const receiptBundleHash = computed(() =>
  workbench.lastRunResult?.current_bundle_hash
  || workbench.data?.bundle?.bundle_snapshot_hash
  || workbench.data?.scene_run_state?.current_bundle_hash
  || "-",
);
const receiptFinalSceneRowId = computed(() =>
  workbench.lastRunResult?.current_final_scene_row_id
  || workbench.data?.scene_run_state?.current_final_scene_row_id
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

function formatRunJobStatus(job) {
  if (!job) {
    return "未启动";
  }
  return [job.status, job.current_step || job.stage].filter(Boolean).join(" / ") || "-";
}

function formatDependencyLabel(item) {
  return item.title || item.label || item.dependency_type || item.kind || item.code || "缺失依赖";
}

function formatDependencyDetail(item) {
  return item.detail || item.message || item.reason || item.lineage_key || item.target_ref || "-";
}

function formatCreateActionLabel(item) {
  return item.label || item.title || item.action || item.action_type || "可创建依赖";
}

function formatConflictLabel(item) {
  return item.title || item.label || item.term || item.code || "约束冲突";
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

async function runWriterReview() {
  const sceneId = resolveSceneId();
  if (!sceneId) {
    emit("notice", "请先选择场景，再运行作家诊断。");
    return;
  }
  await runFlowAction({
    scopeKey: WORKBENCH_MAIN_SCOPE,
    actionLabel: "运行作家诊断",
    runningMessage: "正在诊断这一场是否成立...",
    successMessage: (message) => message || "作家诊断已完成。",
    nextStep: () => "下一步：阅读问题列表，决定是否采纳候选修订。",
    action: () => workbench.runWriterReview(sceneId),
  });
}

async function generateBlueprint() {
  const sceneId = resolveSceneId();
  if (!sceneId) {
    emit("notice", "Please choose a scene before generating a literary blueprint.");
    return;
  }
  await runFlowAction({
    scopeKey: WORKBENCH_MAIN_SCOPE,
    actionLabel: "Generate literary blueprint",
    runningMessage: "Building the scene intent blueprint...",
    successMessage: (message) => message || "Literary blueprint is ready.",
    nextStep: () => "Next: review the blueprint, then run the scene or writer diagnosis.",
    action: () => workbench.generateBlueprint(sceneId),
  });
}

async function generateExecutionContract() {
  const sceneId = resolveSceneId();
  if (!sceneId) {
    emit("notice", "Please choose a scene before generating an execution contract.");
    return;
  }
  await runFlowAction({
    scopeKey: WORKBENCH_MAIN_SCOPE,
    actionLabel: "Generate execution contract",
    runningMessage: "Building the scene execution contract...",
    successMessage: (message) => message || "Execution contract is ready.",
    nextStep: () => "Next: review the contract and triage state before drafting.",
    action: () => workbench.generateExecutionContract(sceneId),
  });
}

async function runSceneTriage() {
  const sceneId = resolveSceneId();
  if (!sceneId) {
    emit("notice", "Please choose a scene before running triage.");
    return;
  }
  await runFlowAction({
    scopeKey: WORKBENCH_MAIN_SCOPE,
    actionLabel: "Run scene triage",
    runningMessage: "Evaluating whether the scene should advance, rewrite, or replan...",
    successMessage: (message) => message || "Scene triage completed.",
    nextStep: () => "Next: follow the triage decision shown below.",
    action: () => workbench.runTriage(sceneId),
  });
}

async function acceptWriterRevision(revisionId) {
  await runFlowAction({
    scopeKey: WORKBENCH_MAIN_SCOPE,
    actionLabel: "采纳修订候选",
    runningMessage: "正在记录作者采纳...",
    successMessage: (message) => message || "修订候选已采纳；终稿未被覆盖。",
    nextStep: () => "下一步：人工合并需要的句段，或继续运行章节诊断。",
    action: () => workbench.acceptRevision(revisionId, resolveSceneId()),
  });
}

async function rejectWriterRevision(revisionId) {
  await runFlowAction({
    scopeKey: WORKBENCH_MAIN_SCOPE,
    actionLabel: "拒绝修订候选",
    runningMessage: "正在记录作者拒绝...",
    successMessage: (message) => message || "修订候选已拒绝。",
    nextStep: () => "下一步：可调整戏剧卡后重新运行诊断。",
    action: () => workbench.rejectRevision(revisionId, resolveSceneId()),
  });
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
    <WorkflowPageHeader view-id="workbench" />
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
            :disabled="workbench.actionId === 'scene-execution-contract' || !resolveSceneId()"
            data-testid="scene-execution-contract-button"
            @click="generateExecutionContract"
          >
            {{ workbench.actionId === "scene-execution-contract" ? "生成中..." : "生成执行合同" }}
          </button>
          <button
            :disabled="workbench.actionId === 'scene-triage' || !resolveSceneId()"
            data-testid="scene-triage-button"
            @click="runSceneTriage"
          >
            {{ workbench.actionId === "scene-triage" ? "评估中..." : "运行 Triage" }}
          </button>
          <button
            :disabled="workbench.actionId === 'run-scene' || workbench.runJobPolling || !runPreflight.can_run || !resolveSceneId()"
            data-testid="run-full-scene-button"
            @click="runScene"
          >
            {{ workbench.actionId === "run-scene" || workbench.runJobPolling ? "运行中..." : "启动场景运行" }}
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
          <span>{{ isAdvancedMode ? "终稿行" : "成稿" }}</span>
          <strong>{{ currentFinalSceneRowId }}</strong>
        </div>
        <div class="stat">
          <span>QC</span>
          <strong>{{ qcEvidenceLabel }}</strong>
        </div>
        <div class="stat" data-testid="scene-archive-quality-label">
          <span>{{ isAdvancedMode ? "Archive Quality" : "归档质量" }}</span>
          <strong>{{ archiveQualityLabel }}</strong>
        </div>
        <div class="stat">
          <span>{{ isAdvancedMode ? "运行轨迹" : "运行记录" }}</span>
          <strong>{{ attemptEvidenceLabel }}</strong>
        </div>
        <div class="stat" data-testid="scene-run-job-summary">
          <span>运行任务</span>
          <strong>{{ formatRunJobStatus(runJob) }}</strong>
        </div>
      </div>

      <div v-if="workbench.loading" class="empty loading-pulse">正在加载场景工作台...</div>
      <template v-else-if="hasData">
        <article v-if="workbench.error" class="paper inline-error">
          <h3>最新错误</h3>
          <p>{{ workbench.error }}</p>
        </article>

        <div class="stats">
          <div class="stat">
            <span>运行快照</span>
            <strong>{{ workbench.data.bundle?.bundle_id ? "已生成" : "尚未生成" }}</strong>
          </div>
          <div v-if="isAdvancedMode" class="stat" data-testid="scene-bundle-technical-stats">
            <span>构包</span>
            <strong>{{ workbench.data.bundle?.bundle_id || "-" }}</strong>
          </div>
          <div v-if="isAdvancedMode" class="stat">
            <span>哈希</span>
            <strong>{{ workbench.data.bundle?.bundle_snapshot_hash || "-" }}</strong>
          </div>
          <div class="stat">
            <span>状态</span>
            <strong>{{ formatStatus(workbench.data.scene_run_state.scene_status) }}</strong>
          </div>
        </div>

        <div v-if="pipelineVisible" class="scene-pipeline-rail" data-testid="scene-pipeline-rail" aria-label="起草流水线进度">
          <template v-for="(stage, index) in pipelineStages" :key="stage.key">
            <div class="scene-pipeline-stage" :class="`s-${stage.state}`">
              <span class="scene-pipeline-dot" aria-hidden="true">
                <template v-if="stage.state === 'done'">✓</template>
                <template v-else>{{ index + 1 }}</template>
              </span>
              <span class="scene-pipeline-label">{{ stage.label }}</span>
            </div>
            <span
              v-if="index < pipelineStages.length - 1"
              class="scene-pipeline-link"
              :class="{ 'is-done': stage.state === 'done' }"
              aria-hidden="true"
            />
          </template>
        </div>

        <article class="paper scene-blueprint-card" data-testid="scene-literary-blueprint-card">
          <div class="receipt-head">
            <div>
              <h3>文学蓝图</h3>
              <p class="muted receipt-copy">本次生成或改稿依据的场景意图：选择、阻碍、信息释放、权力变化和结尾问题。</p>
            </div>
            <span class="badge">{{ literaryBlueprint?.status || "missing" }}</span>
          </div>
          <div class="card-actions">
            <button
              type="button"
              :disabled="workbench.actionId === 'scene-blueprint'"
              data-testid="scene-blueprint-run"
              @click="generateBlueprint"
            >
              {{ workbench.actionId === "scene-blueprint" ? "生成中..." : "生成文学蓝图" }}
            </button>
          </div>
          <div v-if="blueprintItems.length" class="writer-score-grid">
            <div v-for="[key, value] in blueprintItems" :key="key" class="writer-score-item">
              <span>{{ key }}</span>
              <strong>{{ value }}</strong>
            </div>
          </div>
          <p v-else class="muted">还没有蓝图；完整运行会自动生成，但建议先在这里审一眼创作意图。</p>
          <p v-if="literaryBlueprint?.row_id" class="muted">
            {{ literaryBlueprint.row_id }} / {{ literaryBlueprint.source_bundle_hash || "-" }}
          </p>
        </article>

        <WriterReviewCard
          :summary="writerReviewSummary"
          :busy="workbench.actionId === 'writer-review' || workbench.actionId.startsWith('revision-')"
          title="这一场是否成立"
          run-label="运行戏剧诊断"
          @run="runWriterReview"
          @accept="acceptWriterRevision"
          @reject="rejectWriterRevision"
        />

        <article class="paper preflight-card" data-testid="scene-run-preflight-card">
          <div v-if="contractConstraints.length" class="scene-contract-strip" data-testid="scene-contract-strip">
            <div class="scene-contract-head">
              <strong>长程约束 · 来自控制塔交接契约</strong>
              <span class="badge" :class="{ active: towerContract?.status === 'dispatched' }">
                {{ { drafting: "起草中", ready: "就绪", dispatched: "已下发", archived: "已归档" }[towerContract?.status] || towerContract?.status }}
              </span>
            </div>
            <p v-for="(constraint, index) in contractConstraints" :key="`ctr-${index}`" class="scene-contract-item" :class="{ 'is-assigned': constraint.assigned }">
              {{ constraint.text }}<span v-if="constraint.assigned" class="badge">本场指派</span>
            </p>
          </div>
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

          <div
            v-if="missingDependencies.length"
            class="preflight-group"
            data-testid="scene-run-preflight-missing-dependencies"
          >
            <h4>缺失依赖</h4>
            <ProgressiveList
              :items="missingDependencies"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-missing-dependencies-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.lineage_key || item.code || item.dependency_type"
                  class="preflight-item preflight-item-blocking"
                >
                  <div class="preflight-item-head">
                    <strong>{{ formatDependencyLabel(item) }}</strong>
                    <span class="badge ghost">{{ item.lineage_key || item.code || item.dependency_type }}</span>
                  </div>
                  <p>{{ formatDependencyDetail(item) }}</p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <div
            v-if="createActions.length"
            class="preflight-group"
            data-testid="scene-run-preflight-create-actions"
          >
            <h4>可一键补齐</h4>
            <ProgressiveList
              :items="createActions"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-create-actions-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.action_id || item.action || item.lineage_key"
                  class="preflight-item"
                >
                  <div class="preflight-item-head">
                    <strong>{{ formatCreateActionLabel(item) }}</strong>
                    <span class="badge ghost">{{ item.action || item.action_type || "create" }}</span>
                  </div>
                  <p>{{ item.detail || item.description || item.lineage_key || item.target_ref || "系统可根据当前场景生成最小可运行知识卡。" }}</p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <div
            v-if="constraintConflicts.length"
            class="preflight-group"
            data-testid="scene-run-preflight-constraint-conflicts"
          >
            <h4>约束冲突</h4>
            <ProgressiveList
              :items="constraintConflicts"
              :initial-count="6"
              :batch-size="6"
              :threshold="6"
              test-id="scene-run-preflight-constraint-conflicts-progressive-list"
            >
              <template #default="{ items }">
                <article
                  v-for="item in items"
                  :key="item.conflict_id || item.term || item.code"
                  class="preflight-item preflight-item-blocking"
                >
                  <div class="preflight-item-head">
                    <strong>{{ formatConflictLabel(item) }}</strong>
                    <span class="badge ghost">{{ item.severity || item.code || "conflict" }}</span>
                  </div>
                  <p>{{ item.human_readable_reason || item.detail || item.message || item.conflicts_with || "-" }}</p>
                  <p v-if="item.constraint_source" class="muted"><code>{{ item.constraint_source }}</code></p>
                </article>
              </template>
            </ProgressiveList>
          </div>

          <p
            v-if="!runPreflight.blocking_items.length && !runPreflight.warning_items.length && !runPreflight.context_items.length && !missingDependencies.length && !createActions.length && !constraintConflicts.length"
            class="muted"
          >
            当前没有预检提示，可以直接执行完整场景运行。
          </p>
        </article>

        <article class="paper receipt-card" data-testid="scene-execution-contract-card">
          <div class="receipt-head">
            <div>
              <h3>场景执行合同</h3>
              <p class="muted receipt-copy">统一显示 SceneExecutionContract 与 triage 结果，决定是起草、重写还是回流返工。</p>
            </div>
            <span class="badge">{{ executionContract?.status || "未生成" }}</span>
          </div>
          <div v-if="executionContract" class="receipt-grid">
            <p><strong>形态</strong><br />{{ executionContract.payload?.scene_mode || "-" }}</p>
            <p><strong>POV</strong><br />{{ executionContract.payload?.pov_character_id || "-" }}</p>
            <p><strong>Crucible</strong><br />{{ executionContract.payload?.scene_crucible || "-" }}</p>
            <p><strong>下一步</strong><br />{{ triagePreview?.next_action || "-" }}</p>
          </div>
          <p v-if="executionContract?.missing_fields?.length" class="muted">
            缺失字段：{{ executionContract.missing_fields.join(" / ") }}
          </p>
          <p v-if="triagePreview" class="muted" data-testid="scene-triage-preview">
            Triage：{{ triagePreview.decision }} / {{ triagePreview.next_action }}
            <span v-if="triagePreview.reason_codes?.length"> / {{ triagePreview.reason_codes.join(" / ") }}</span>
          </p>
          <div v-if="executionContract?.payload?.reference_rules?.safety_rules?.length" class="review-safety">
            <span
              v-for="rule in executionContract.payload.reference_rules.safety_rules"
              :key="rule"
            >
              {{ rule }}
            </span>
          </div>
          <p v-else class="muted">先生成执行合同，再查看结构门禁和安全规则。</p>
        </article>

        <article
          v-if="runJob"
          class="paper receipt-card"
          data-testid="scene-run-job-status"
        >
          <div class="receipt-head">
            <div>
              <h3>后台运行任务</h3>
              <p class="muted receipt-copy">场景运行已交给后台 Job，当前页面通过轮询刷新阶段和结果。</p>
            </div>
            <span class="badge">{{ workbench.runJobPolling ? "轮询中" : "已同步" }}</span>
          </div>
          <div class="receipt-grid">
            <p><strong>任务</strong><br />{{ runJob.job_id || "-" }}</p>
            <p><strong>状态</strong><br />{{ runJob.status || "-" }}</p>
            <p><strong>阶段</strong><br />{{ runJob.current_step || runJob.stage || "-" }}</p>
            <p><strong>人工处理</strong><br />{{ runJob.needs_human_review ? "需要" : "无需" }}</p>
          </div>
          <p v-if="runJob.error_text || runJob.error_code" class="muted">
            {{ runJob.error_code || "error" }}：{{ runJob.error_text || "-" }}
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
            <p><strong>{{ isAdvancedMode ? "构包" : "运行快照" }}</strong><br />{{ receiptBundleId }}</p>
            <p v-if="isAdvancedMode"><strong>哈希</strong><br />{{ receiptBundleHash }}</p>
            <p><strong>最终场景</strong><br />{{ receiptFinalSceneRowId }}</p>
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

        <EvidenceDisclosure
          title="生成与验收证据"
          summary="生成调用、QC、源书安全扫描默认收起；高级模式会自动展开。"
          test-id="scene-workbench-evidence-disclosure"
        >
          <div class="workbench-columns" data-testid="scene-workbench-summary-row">
            <GenerationSummaryCard
              v-if="isAdvancedMode"
              data-testid="scene-generation-summary-card"
              :summary="generationSummary"
            />
            <QcReportCard
              v-if="isAdvancedMode"
              data-testid="scene-qc-report-card"
              :hard-summary="hardQcSummary"
              :soft-summary="softQcSummary"
              :rewrite-counters="rewriteCounters"
              :human-review-summary="humanReviewSummary"
            />
            <article class="paper" data-testid="scene-source-safety-card">
              <h3>源书安全扫描</h3>
              <p><strong>{{ sourceSafetyStatusLabel }}</strong></p>
              <p class="muted">
                {{ sourceSafetyBlockedTerms.length ? sourceSafetyBlockedTerms.join("、") : "没有命中源书专名、设定或受保护桥段标记。" }}
              </p>
              <p class="muted">
                {{ sourceSafetyProfileIds.length ? sourceSafetyProfileIds.join(", ") : "暂无参考画像来源 ID" }}
              </p>
            </article>
          </div>
        </EvidenceDisclosure>

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
      <BaseEmptyState
        v-else
        data-testid="scene-workbench-empty"
        description="从作者工作台选择场景，或输入场景 ID 加载。"
      />
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

<style scoped>
/* 设计稿六段流水线导轨(预检·打包 → 起草 → 质检 → 二改 → 校核 → 归档) */
.scene-pipeline-rail {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding: 12px 16px;
  border: 1px solid var(--line-1);
  border-radius: var(--r-lg);
  background: var(--paper-1);
}

.scene-pipeline-stage {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}

.scene-pipeline-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  background: var(--paper-3);
  color: var(--ink-3);
  border: 2px solid transparent;
  transition: background var(--t-fast), color var(--t-fast), border-color var(--t-fast);
}

.scene-pipeline-stage.s-done .scene-pipeline-dot {
  background: var(--sage);
  color: #fff;
}

.scene-pipeline-stage.s-active .scene-pipeline-dot {
  background: var(--paper-0);
  color: var(--crimson);
  border-color: var(--crimson);
  box-shadow: 0 0 0 3px var(--crimson-wash);
}

.scene-pipeline-label {
  font-size: 12.5px;
  color: var(--ink-3);
}

.scene-pipeline-stage.s-active .scene-pipeline-label {
  color: var(--ink-1);
  font-weight: 600;
}

.scene-pipeline-stage.s-done .scene-pipeline-label {
  color: var(--ink-2);
}

.scene-pipeline-link {
  flex: 1 1 14px;
  min-width: 14px;
  height: 2px;
  border-radius: 2px;
  background: var(--line-2);
}

.scene-pipeline-link.is-done {
  background: var(--sage);
}

/* 长程约束(契约下发)块 */
.scene-contract-strip {
  display: grid;
  gap: 6px;
  border: 1px solid color-mix(in srgb, var(--crimson) 24%, transparent);
  border-left: 3px solid var(--crimson);
  border-radius: var(--r-md);
  background: color-mix(in srgb, var(--crimson-wash) 20%, var(--paper-1));
  padding: 10px 12px;
  margin-bottom: 10px;
}

.scene-contract-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.scene-contract-head strong {
  font-size: 12px;
  letter-spacing: 0.06em;
  color: var(--ink-2);
}

.scene-contract-item {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-2);
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.scene-contract-item.is-assigned {
  color: var(--ink-1);
  font-weight: 500;
}
</style>
