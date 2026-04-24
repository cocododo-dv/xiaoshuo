<script setup>
import { computed, onActivated, onDeactivated, reactive, ref, watch } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import LazySection from "../components/LazySection.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import PanelShell from "../components/PanelShell.vue";
import StyleProfileDiffSummary from "../components/StyleProfileDiffSummary.vue";
import StyleProfileRiskWarning from "../components/StyleProfileRiskWarning.vue";
import StyleProfileSummary from "../components/StyleProfileSummary.vue";
import VirtualList from "../components/VirtualList.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useUiMode } from "../composables/useUiMode";
import { prioritizeMatchingItem } from "../lib/listPriority";
import {
  styleProfileDiffFromKnowledgeDetail,
  styleProfileRiskFromKnowledgeDetail,
  styleProfileRiskFromReviewItem,
  styleProfileSummaryFromKnowledgeDetail,
} from "../lib/styleProfileSummary";
import { useShellRouter } from "../router";
import { useKnowledgeConsoleStore } from "../stores/knowledgeConsole";

const emit = defineEmits(["notice"]);

const knowledgeConsole = useKnowledgeConsoleStore();
const { focusTarget, navigate, openTarget } = useShellRouter();
const isViewActive = ref(false);
const { isAdvancedMode } = useUiMode();
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});
const KNOWLEDGE_CREATE_SCOPE = "knowledge:create";
const KNOWLEDGE_WORKFLOW_SCOPE = "knowledge:workflow";

const filters = reactive({
  objectType: knowledgeConsole.filters?.objectType || "",
  scope: knowledgeConsole.filters?.scope || "",
  scopeRefId: knowledgeConsole.filters?.scopeRefId || "",
  status: knowledgeConsole.filters?.status || "",
});
const draft = reactive({
  reviewId: "",
  itemType: "style_rule_set",
  lineageKey: "",
  candidateText: "",
  scope: "global",
  scopeRefId: "global",
  chapterId: "CH001",
  sceneId: "CH001_SC01",
  characterId: "",
  displayName: "",
  pronouns: "",
  role: "",
  aliases: "",
  leftCharacterId: "",
  rightCharacterId: "",
  ruleTier: "",
  activeOnApprove: 1,
  extraPayload: "",
});
const riskAcknowledgements = reactive({});
const riskReasons = reactive({});

const selectedEntryKey = computed(() =>
  knowledgeConsole.selectedObjectType && knowledgeConsole.selectedLineageKey
    ? `${knowledgeConsole.selectedObjectType}:${knowledgeConsole.selectedLineageKey}`
    : "",
);

const pinnedCatalogKeys = computed(() => (selectedEntryKey.value ? [selectedEntryKey.value] : []));
const catalogRowMapVersion = computed(() => selectedEntryKey.value);
const catalogItems = computed(() => knowledgeConsole.items || []);
const prioritizedCatalogItems = computed(() =>
  prioritizeMatchingItem(catalogItems.value, (item) => knowledgeItemKey(item) === selectedEntryKey.value),
);
const detailReviewRefs = computed(() => knowledgeConsole.detail?.review_refs || []);
const detailBundleRefs = computed(() => knowledgeConsole.detail?.bundle_refs || []);
const detailWorkflow = computed(() => knowledgeConsole.detail?.workflow || {});
const workflowReviewItems = computed(() => detailWorkflow.value.review_items || []);
const workflowJobs = computed(() => detailWorkflow.value.jobs || []);
const workflowHumanReviewEvents = computed(() => detailWorkflow.value.human_review_events || []);
const workflowTargetActivityGroups = computed(() => detailWorkflow.value.target_activity_groups || []);
const primaryWorkflowAction = computed(() => detailWorkflow.value.recommended_primary_action || null);
const detailStyleProfileSummary = computed(() => styleProfileSummaryFromKnowledgeDetail(knowledgeConsole.detail));
const detailStyleProfileDiffSummary = computed(() => styleProfileDiffFromKnowledgeDetail(knowledgeConsole.detail));
const detailStyleProfileRisk = computed(() => styleProfileRiskFromKnowledgeDetail(knowledgeConsole.detail));
const emptyStyleProfileRisk = Object.freeze({
  available: false,
  severity: "",
  title: "",
  reasons: [],
  actionHint: "",
});
const workflowActionItems = computed(() => {
  const pendingReviews = [];
  const retryableJobs = [];
  const releasableReviews = [];
  const blockedReleaseReviewIds = new Set();
  const activeVersionRowId = knowledgeConsole.detail?.active_version?.row_id || "";

  workflowJobs.value.forEach((job) => {
    if (job.job_type !== "verify" || job.status === "succeeded") {
      return;
    }
    retryableJobs.push(job);
    if (job.review_id) {
      blockedReleaseReviewIds.add(job.review_id);
    }
  });

  workflowReviewItems.value.forEach((review) => {
    if (review.status === "pending") {
      pendingReviews.push(review);
      return;
    }
    if (
      review.status === "approved"
      && review.materialize_status === "succeeded"
      && review.approved_item_row_id
      && activeVersionRowId !== review.approved_item_row_id
      && !blockedReleaseReviewIds.has(review.review_id)
    ) {
      releasableReviews.push(review);
    }
  });

  return {
    pendingReviews,
    retryableJobs,
    releasableReviews,
  };
});
const workflowRiskConfirmationReviews = computed(() =>
  workflowActionItems.value.pendingReviews.filter((review) => reviewRequiresRiskConfirmation(review)),
);
const primaryWorkflowActionReview = computed(() => {
  const action = primaryWorkflowAction.value;
  if (action?.kind !== "review" || !action.review_id) {
    return null;
  }
  return workflowReviewForId(action.review_id);
});
const primaryWorkflowActionDisabled = computed(() => {
  const action = primaryWorkflowAction.value;
  if (!action) {
    return true;
  }
  if (knowledgeConsole.actionId) {
    return true;
  }
  if (action.kind === "review" && action.action === "approve_review" && primaryWorkflowActionReview.value) {
    return !canApproveReview(primaryWorkflowActionReview.value);
  }
  return false;
});
const ITEM_TYPE_LABELS = {
  style_rule: "风格规则",
  style_observation: "风格观察",
  narrative_pattern: "叙事结构",
  banned_rule_cluster: "禁忌规则簇",
  voice_card: "声线卡",
  relation_card: "关系卡",
  world_rule: "世界规则",
  calibration_line: "校准句",
  foreshadow: "伏笔",
  scene_summary: "场景摘要",
  chapter_summary: "章节摘要",
};

const STATUS_LABELS = {
  active: "生效中",
  candidate: "候选中",
  resolved: "已解决",
  pending: "待处理",
  approved: "已批准",
  rejected: "已拒绝",
  clear: "正常",
  not_required: "无需校验",
  unknown: "未知",
  succeeded: "成功",
  failed: "失败",
  running: "进行中",
  tracked: "已跟踪",
  released: "已发布",
};

const JOB_TYPE_LABELS = {
  verify: "校验任务",
  reindex: "重建索引任务",
};

const ACTION_LABELS = {
  approve_review: "批准审核",
  retry_verify: "重试校验",
  release_review: "发布审核",
  retry_request: "重试请求",
  inspect: "查看详情",
};
const REFERENCE_SOURCES = new Set(["reference_book_learning", "reference_profile_apply"]);

function formatItemType(itemType) {
  return ITEM_TYPE_LABELS[itemType] || itemType || "-";
}

function formatStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function formatJobType(jobType) {
  return JOB_TYPE_LABELS[jobType] || jobType || "-";
}

function formatAction(action) {
  return ACTION_LABELS[action] || action || "-";
}

function knowledgeItemKey(item) {
  return `${item.object_type}:${item.lineage_key}`;
}

const workflowStatusItems = computed(() => {
  const reviewStatus = workflowReviewItems.value[0]?.status || "clear";
  const verifyJob = workflowJobs.value.find((job) => job.job_type === "verify");
  const verifyStatus = verifyJob?.status || knowledgeConsole.detail?.runtime_refs?.verify_status || "not_required";
  const unresolvedHumanReview = workflowHumanReviewEvents.value.find((item) => item.status !== "resolved");
  return [
    { label: "知识", value: formatStatus(knowledgeConsole.detail?.status || "unknown") },
    { label: "审核", value: formatStatus(reviewStatus) },
    { label: "校验", value: formatStatus(verifyStatus) },
    {
      label: "人工审核",
      value: formatStatus(
        unresolvedHumanReview?.status || (workflowHumanReviewEvents.value.length ? "resolved" : "clear"),
      ),
    },
  ];
});

function previewText(version) {
  if (!version?.text) {
    return "暂无文本";
  }
  return version.text;
}

function previewSummaryText(version) {
  const text = previewText(version);
  if (text === "暂无文本" || text.length <= 120) {
    return text;
  }
  return `${text.slice(0, 120)}...`;
}

function actionLabel(action) {
  return formatAction(action);
}

function formatJsonPayload(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function formatSources(sources, fallback = "活动") {
  return sources?.length ? sources.join(", ") : fallback;
}

function candidatePayloadForItem(item) {
  return (
    item?.candidate_version?.candidate_payload_json ||
    item?.candidate_version?.payload_json ||
    item?.candidate_payload_json ||
    item?.payload_json ||
    {}
  );
}

function referenceSourceForItem(item) {
  const payload = candidatePayloadForItem(item);
  if (REFERENCE_SOURCES.has(payload?.source)) {
    return "参考书学习";
  }
  const lineageKey = String(item?.lineage_key || "");
  const reviewId = String(item?.candidate_version?.review_id || item?.review_refs?.[0] || "");
  if (lineageKey.startsWith("refbook_") || reviewId.includes("reffind") || reviewId.includes("refprofile")) {
    return "参考书学习";
  }
  return "";
}

function referenceKnowledgeSummary(label, fallback) {
  return label ? "参考书候选已抽象化，源书片段隐藏。" : fallback;
}

function knowledgeCatalogRow(item) {
  const itemKey = knowledgeItemKey(item);
  const referenceSourceLabel = referenceSourceForItem(item);

  return {
    item,
    itemKey,
    objectType: item?.object_type || "",
    lineageKey: item?.lineage_key || "",
    itemTypeLabel: formatItemType(item?.object_type),
    statusLabel: formatStatus(item?.status || "tracked"),
    activeSummary: referenceKnowledgeSummary(
      referenceSourceLabel && item?.active_version?.text,
      previewSummaryText(item?.active_version),
    ),
    candidateSummary: referenceKnowledgeSummary(
      referenceSourceLabel && item?.candidate_version,
      previewSummaryText(item?.candidate_version),
    ),
    runtimeRefLabel: item?.runtime_refs?.alias_scope || item?.runtime_refs?.mode || "-",
    referenceSourceLabel,
    focused: selectedEntryKey.value === itemKey,
  };
}

function knowledgeVersionRow(version) {
  return {
    version,
    rowId: version.row_id,
    versionLabel: `v${version.version || "候选"}`,
    text: version.text || "-",
  };
}

function knowledgeWorkflowReviewRow(review) {
  return {
    review,
    reviewId: review.review_id,
    statusLabel: formatStatus(review.status),
    materializeStatusLabel: formatStatus(review.materialize_status || "pending"),
  };
}

function knowledgeWorkflowJobRow(job) {
  return {
    job,
    jobId: job.job_id,
    statusLabel: formatStatus(job.status),
    summary: `${formatJobType(job.job_type)} / ${job.alias_scope || "直接读取"}`,
  };
}

function knowledgeHumanReviewRow(event) {
  const eventId = event.event_id;
  return {
    event,
    eventId,
    statusLabel: formatStatus(event.status),
    defaultActionLabel: formatAction(event.default_action || "inspect"),
    actions: (event.allowed_actions_json || []).map((action) => ({
      action,
      key: `${eventId}-${action}`,
      label: actionLabel(action),
    })),
  };
}

function knowledgeActivityRow(group) {
  const targetRef = group.target?.target_ref || "";
  return {
    group,
    targetRef,
    activityCount: group.activity_count ?? 0,
    sourcesLabel: formatSources(group.sources),
  };
}

function knowledgeReviewRefRow(reviewRef) {
  return {
    reviewRef,
    targetType: "review_item",
  };
}

function knowledgeBundleRefRow(bundleRef) {
  return {
    bundleRef,
    bundleId: bundleRef.bundle_id,
    sceneId: bundleRef.scene_id,
    chapterId: bundleRef.chapter_id || "-",
  };
}

function jobTarget(job) {
  if (!job?.job_id || !job?.job_type) {
    return null;
  }
  const targetType = job.job_type === "reindex" ? "reindex_job" : "verify_job";
  return {
    target_type: targetType,
    target_id: job.job_id,
    target_ref: `${targetType}:${job.job_id}`,
  };
}

function selectEntry(item) {
  knowledgeConsole.selectItem(item.object_type, item.lineage_key).catch((error) => {
    emit("notice", error.message);
  });
}

async function refreshKnowledge() {
  const hadSelection = Boolean(knowledgeConsole.selectedObjectType && knowledgeConsole.selectedLineageKey);
  await knowledgeConsole.load(filters, { force: true });
  if (!hadSelection && !knowledgeConsole.selectedObjectType && !knowledgeConsole.selectedLineageKey && !knowledgeConsole.detail && knowledgeConsole.items.length) {
    await knowledgeConsole.selectItem(knowledgeConsole.items[0].object_type, knowledgeConsole.items[0].lineage_key);
  }
  if (knowledgeConsole.error) {
    emit("notice", knowledgeConsole.error);
  }
}

async function ensureKnowledgeLoaded() {
  const hadSelection = Boolean(knowledgeConsole.selectedObjectType && knowledgeConsole.selectedLineageKey);
  await knowledgeConsole.ensureLoaded({ filters });
  if (!hadSelection && !knowledgeConsole.selectedObjectType && !knowledgeConsole.selectedLineageKey && !knowledgeConsole.detail && knowledgeConsole.items.length) {
    await knowledgeConsole.selectItem(knowledgeConsole.items[0].object_type, knowledgeConsole.items[0].lineage_key);
  }
  if (knowledgeConsole.error) {
    emit("notice", knowledgeConsole.error);
  }
}

async function submitCandidate() {
  await runFlowAction({
    scopeKey: KNOWLEDGE_CREATE_SCOPE,
    actionLabel: "创建候选",
    runningMessage: "正在创建知识审核候选...",
    successMessage: (message) => message || "知识候选已创建。",
    nextStep: () => "下一步：在详情抽屉或审核收件箱里批准候选。",
    action: () => knowledgeConsole.createCandidate(draft),
  });
}

function openReviewInbox(item) {
  const reviewId = item?.candidate_version?.review_id || item?.review_refs?.[0];
  if (!reviewId) {
    navigate("review");
    emit("notice", "已打开审核收件箱");
    return;
  }
  openTarget(
    {
      target_type: "review_item",
      target_id: reviewId,
      target_ref: `review_item:${reviewId}`,
    },
    {
      view_id: "review",
      source_type: "knowledge_console",
      source_id: reviewId,
    },
  );
  emit("notice", `已打开审核收件箱：review_item:${reviewId}`);
}

function openReferenceLearning() {
  navigate("reference");
  emit("notice", "已打开参考书学习");
}

function openIndexConsole(item) {
  navigate("index");
  emit("notice", `已打开索引控制台：${item.object_type}:${item.lineage_key}`);
}

function parseKnowledgeTarget(targetRef) {
  if (!targetRef?.startsWith("knowledge_entry:")) {
    return null;
  }
  const [, objectType, ...rest] = targetRef.split(":");
  const lineageKey = rest.join(":");
  if (!objectType || !lineageKey) {
    return null;
  }
  return { objectType, lineageKey };
}

function openReviewRef(reviewId) {
  if (!reviewId) {
    return;
  }
  openTarget(
    {
      target_type: "review_item",
      target_id: reviewId,
      target_ref: `review_item:${reviewId}`,
    },
    {
      view_id: "review",
      source_type: "knowledge_detail_review_ref",
      source_id: reviewId,
    },
  );
  emit("notice", `已打开审核收件箱：review_item:${reviewId}`);
}

function openBundleWorkbench(bundleRef) {
  if (!bundleRef?.scene_id) {
    return;
  }
  openTarget(
    {
      target_type: "scene_card",
      target_id: bundleRef.scene_id,
      target_ref: `scene_card:${bundleRef.scene_id}`,
    },
    {
      view_id: "workbench",
      source_type: "knowledge_bundle_ref",
      source_id: bundleRef.bundle_id,
    },
  );
  emit("notice", `已打开场景工作台：scene_card:${bundleRef.scene_id}`);
}

function openJobTarget(job) {
  const target = jobTarget(job);
  if (!target) {
    return;
  }
  openTarget(target, {
    source_type: "knowledge_workflow_job",
    source_id: job.job_id,
  });
  emit("notice", `已打开索引任务：${target.target_ref}`);
}

function openHumanReviewEvent(event) {
  if (!event?.event_id) {
    return;
  }
  openTarget(
    {
      target_type: "human_review_event",
      target_id: event.event_id,
      target_ref: `human_review_event:${event.event_id}`,
    },
    {
      view_id: "review",
      source_type: "knowledge_workflow_event",
      source_id: event.event_id,
    },
  );
  emit("notice", `已打开人工审核事件：human_review_event:${event.event_id}`);
}

function openActivityTarget(group) {
  if (!group?.target) {
    return;
  }
  openTarget(group.target, {
    source_type: "knowledge_target_activity",
    source_id: group.target.target_ref,
  });
  emit("notice", `已打开目标：${group.target.target_ref}`);
}

function workflowReviewForId(reviewId) {
  return workflowReviewItems.value.find((review) => review.review_id === reviewId) || null;
}

function knowledgeReviewRisk(review) {
  const reviewRisk = styleProfileRiskFromReviewItem(review);
  if (reviewRisk?.available) {
    return reviewRisk;
  }

  const selectedCandidateReviewId = knowledgeConsole.detail?.candidate_version?.review_id || "";
  const matchesSelectedCandidate =
    Boolean(review?.review_id)
    && (
      review.review_id === selectedCandidateReviewId
      || detailReviewRefs.value.includes(review.review_id)
    );
  if (matchesSelectedCandidate && detailStyleProfileRisk.value?.available) {
    return detailStyleProfileRisk.value;
  }
  return emptyStyleProfileRisk;
}

function reviewRequiresRiskConfirmation(review) {
  return knowledgeReviewRisk(review).severity === "high";
}

function riskReasonForReview(reviewId) {
  return (riskReasons[reviewId] || "").trim();
}

function canApproveReview(review) {
  if (!reviewRequiresRiskConfirmation(review)) {
    return true;
  }
  return Boolean(riskAcknowledgements[review.review_id] && riskReasonForReview(review.review_id));
}

function approvalPayloadForReview(review) {
  if (!reviewRequiresRiskConfirmation(review)) {
    return {};
  }
  return {
    risk_confirmation: {
      acknowledged: Boolean(riskAcknowledgements[review.review_id]),
      reason: riskReasonForReview(review.review_id),
      severity: "high",
    },
  };
}

async function runApprove(reviewId, payload = {}) {
  await runFlowAction({
    scopeKey: KNOWLEDGE_WORKFLOW_SCOPE,
    actionLabel: "批准审核",
    runningMessage: "正在批准知识候选...",
    successMessage: (message) => message || "知识候选已批准。",
    nextStep: () => "下一步：如果需要发布，继续点击「发布审核」。",
    action: () => knowledgeConsole.approveReview(reviewId, payload),
  });
}

async function runRetryVerify(jobId) {
  await runFlowAction({
    scopeKey: KNOWLEDGE_WORKFLOW_SCOPE,
    actionLabel: "重试校验",
    runningMessage: "正在重试知识校验任务...",
    successMessage: (message) => message || "校验任务已重试。",
    nextStep: () => "下一步：查看关联任务状态，成功后继续发布。",
    action: () => knowledgeConsole.retryVerifyJob(jobId),
  });
}

async function runRelease(reviewId) {
  await runFlowAction({
    scopeKey: KNOWLEDGE_WORKFLOW_SCOPE,
    actionLabel: "发布审核",
    runningMessage: "正在发布知识审核结果...",
    successMessage: (message) => message || "知识审核已发布。",
    nextStep: () => "下一步：查看目标活动，确认运行时引用已经更新。",
    action: () => knowledgeConsole.releaseReview(reviewId),
  });
}

async function runHumanReviewAction(eventId, action) {
  await runFlowAction({
    scopeKey: KNOWLEDGE_WORKFLOW_SCOPE,
    actionLabel: "处理人工审核",
    runningMessage: "正在执行人工审核后续动作...",
    successMessage: (message) => message || "人工审核动作已完成。",
    nextStep: () => "下一步：打开目标活动或继续处理关联审核。",
    action: () => knowledgeConsole.actOnHumanReviewEvent(eventId, action),
  });
}

async function runPrimaryWorkflowAction() {
  const action = primaryWorkflowAction.value;
  if (!action) {
    return;
  }
  if (action.kind === "review" && action.action === "approve_review") {
    const review = workflowReviewForId(action.review_id);
    if (review && !canApproveReview(review)) {
      emit("notice", "请先确认高风险风格变更并填写批准理由。");
      return;
    }
    await runApprove(action.review_id, review ? approvalPayloadForReview(review) : {});
    return;
  }
  if (action.kind === "review" && action.action === "release_review") {
    await runRelease(action.review_id);
    return;
  }
  if (action.kind === "verify_job" && action.action === "retry_verify") {
    await runRetryVerify(action.job_id);
    return;
  }
  if (action.kind === "human_review_event") {
    await runHumanReviewAction(action.event_id, action.action);
  }
}

async function syncKnowledgeFocus(targetRef = focusTarget.value?.target_ref || "") {
  if (!isViewActive.value) {
    return;
  }
  const target = parseKnowledgeTarget(targetRef);
  if (!target) {
    return;
  }
  if (!knowledgeConsole.items.length) {
    await refreshKnowledge();
  }
  try {
    await knowledgeConsole.selectItem(target.objectType, target.lineageKey);
  } catch (error) {
    emit("notice", error.message);
  }
}

onActivated(async () => {
  isViewActive.value = true;
  await ensureKnowledgeLoaded();
  await syncKnowledgeFocus();
});

onDeactivated(() => {
  isViewActive.value = false;
});

watch(
  () => focusTarget.value?.target_ref || "",
  async (targetRef) => {
    await syncKnowledgeFocus(targetRef);
  },
);
</script>

<template>
  <section class="panel-grid" data-testid="knowledge-console-view">
    <WorkflowPageHeader view-id="knowledge" />
    <PanelShell
      eyebrow="知识控制台"
      title="新建候选并查看生效知识"
      description="这是长期设定与风格知识库，会影响后续生成，不是写正文的页面。"
    >
      <template #actions>
        <div class="knowledge-filter-grid">
          <label>
            <span>对象类型</span>
            <select v-model="filters.objectType" class="control-input" data-testid="knowledge-filter-select">
              <option value="">全部家族</option>
              <option v-for="objectType in knowledgeConsole.supportedObjectTypes" :key="objectType" :value="objectType">
                {{ formatItemType(objectType) }}
              </option>
            </select>
          </label>
          <label>
            <span>作用域</span>
            <input v-model="filters.scope" class="control-input" data-testid="knowledge-scope-filter" placeholder="global" />
          </label>
          <label>
            <span>作用域引用</span>
            <input
              v-model="filters.scopeRefId"
              class="control-input"
              data-testid="knowledge-scope-ref-filter"
              placeholder="global / chapter / scene"
            />
          </label>
          <label>
            <span>状态</span>
            <select v-model="filters.status" class="control-input" data-testid="knowledge-status-filter">
              <option value="">全部状态</option>
              <option value="active">生效中</option>
              <option value="candidate">候选中</option>
              <option value="resolved">已解决</option>
            </select>
          </label>
          <button data-testid="knowledge-refresh-button" @click="refreshKnowledge">刷新</button>
        </div>
      </template>

      <div class="stats knowledge-purpose-strip" data-testid="knowledge-purpose-strip">
        <div class="stat">
          <span>用途</span>
          <strong>长期设定与风格知识库</strong>
        </div>
        <div class="stat">
          <span>流程</span>
          <strong>创建候选 -> 批准 -> 必要时校验 -> 发布/生效</strong>
        </div>
        <div class="stat">
          <span>影响</span>
          <strong>生效知识会进入后续生成上下文</strong>
        </div>
      </div>

      <div class="knowledge-layout">
        <article class="paper knowledge-form-card">
          <div class="receipt-head">
            <div>
              <h3>新建候选</h3>
              <p class="muted receipt-copy">创建候选 -> 批准 -> 必要时校验 -> 发布/生效。先写入长期知识草稿，再在右侧详情抽屉里处理。</p>
            </div>
            <span class="badge">创建接口</span>
          </div>
          <div class="knowledge-form-grid">
            <label>
              <span>{{ isAdvancedMode ? "审核 ID" : "来源审核" }}</span>
              <input v-model="draft.reviewId" class="control-input" data-testid="knowledge-review-id" />
            </label>
            <label>
              <span>条目类型</span>
              <select v-model="draft.itemType" class="control-input" data-testid="knowledge-item-type">
                <option value="style_rule_set">风格规则集</option>
                <option value="narrative_pattern">叙事结构画像</option>
                <option value="banned_rule_cluster">禁忌规则簇</option>
                <option value="voice_card_candidate">声线卡候选</option>
                <option value="relation_card_candidate">关系卡候选</option>
                <option value="world_rule">世界规则</option>
                <option value="calibration_candidate">校准句候选</option>
                <option value="foreshadow_open">伏笔开启</option>
                <option value="foreshadow_touch">伏笔触发</option>
                <option value="foreshadow_resolve">伏笔回收</option>
                <option value="scene_summary">场景摘要</option>
                <option value="chapter_summary">章节摘要</option>
                <option value="style_observation">风格观察</option>
              </select>
            </label>
            <label>
              <span>{{ isAdvancedMode ? "血缘 key" : "知识名称" }}</span>
              <input v-model="draft.lineageKey" class="control-input" data-testid="knowledge-lineage-key" />
              <small>同一条长期知识的稳定名字，例如某个角色声线、关系或全局风格。</small>
            </label>
            <label>
              <span>批准后生效</span>
              <select v-model.number="draft.activeOnApprove" class="control-input" data-testid="knowledge-active-on-approve">
                <option :value="1">是</option>
                <option :value="0">否</option>
              </select>
              <small>选择“否”时，需要先完成校验，再发布到运行时。</small>
            </label>
            <label>
              <span>{{ isAdvancedMode ? "作用域" : "应用范围" }}</span>
              <input v-model="draft.scope" class="control-input" />
            </label>
            <label>
              <span>{{ isAdvancedMode ? "作用域引用" : "范围对象" }}</span>
              <input v-model="draft.scopeRefId" class="control-input" />
            </label>
            <label>
              <span>{{ isAdvancedMode ? "章节 ID" : "章节" }}</span>
              <input v-model="draft.chapterId" class="control-input" />
            </label>
            <label>
              <span>{{ isAdvancedMode ? "场景 ID" : "场景" }}</span>
              <input v-model="draft.sceneId" class="control-input" />
            </label>
            <label>
              <span>{{ isAdvancedMode ? "角色 ID" : "角色" }}</span>
              <input v-model="draft.characterId" class="control-input" />
            </label>
            <label>
              <span>角色名</span>
              <input v-model="draft.displayName" class="control-input" />
            </label>
            <label>
              <span>代词</span>
              <input v-model="draft.pronouns" class="control-input" placeholder="她 / 他 / TA" />
            </label>
            <label>
              <span>角色职责</span>
              <input v-model="draft.role" class="control-input" />
            </label>
            <label>
              <span>别名</span>
              <input v-model="draft.aliases" class="control-input" placeholder="用逗号分隔" />
            </label>
            <label>
              <span>左角色</span>
              <input v-model="draft.leftCharacterId" class="control-input" />
            </label>
            <label>
              <span>右角色</span>
              <input v-model="draft.rightCharacterId" class="control-input" />
            </label>
            <label>
              <span>规则层级</span>
              <input v-model="draft.ruleTier" class="control-input" />
            </label>
            <label class="knowledge-wide">
              <span>候选文本</span>
              <textarea v-model="draft.candidateText" class="control-input control-textarea" data-testid="knowledge-candidate-text" />
            </label>
            <label v-if="isAdvancedMode" class="knowledge-wide" data-testid="knowledge-extra-payload-field">
              <span>附加载荷 JSON</span>
              <textarea v-model="draft.extraPayload" class="control-input control-textarea" placeholder='{"expires_at":"2099-01-01T00:00:00+00:00"}' />
            </label>
          </div>
          <div class="card-actions">
            <button :disabled="knowledgeConsole.actionId === 'create'" data-testid="knowledge-create-button" @click="submitCandidate">
              {{ knowledgeConsole.actionId === "create" ? "创建中..." : "创建候选" }}
            </button>
          </div>
          <FlowActionReceipt :receipt="receipt(KNOWLEDGE_CREATE_SCOPE)" />
        </article>

        <article class="paper knowledge-catalog-card">
          <div class="receipt-head">
            <div>
              <h3>目录</h3>
              <p class="muted receipt-copy">把生效行和暂存候选合并成一份按血缘优先排序的视图。</p>
            </div>
            <span class="badge">{{ catalogItems.length }} 条血缘</span>
          </div>

          <div v-if="knowledgeConsole.loading" class="empty">正在加载知识目录...</div>
          <div v-else-if="knowledgeConsole.error" class="empty">{{ knowledgeConsole.error }}</div>
          <div v-else-if="!catalogItems.length" class="empty">当前筛选下没有匹配的知识行或候选项。</div>
          <VirtualList
            v-else
            class="knowledge-list"
            :items="prioritizedCatalogItems"
            :item-key="knowledgeItemKey"
            :estimated-item-height="220"
            :threshold="8"
            :viewport-height="640"
            :pinned-keys="pinnedCatalogKeys"
            :map-item="knowledgeCatalogRow"
            :map-version="catalogRowMapVersion"
            test-id="knowledge-catalog-virtual-list"
          >
            <template #default="{ row }">
              <article
                class="review-card knowledge-card"
                :class="{ 'focused-card': row.focused }"
                :data-testid="`knowledge-card-${row.objectType}-${row.lineageKey}`"
              >
                <div class="source-top">
                  <div>
                    <div class="eyebrow">{{ row.itemTypeLabel }}</div>
                    <h3>{{ row.lineageKey }}</h3>
                  </div>
                  <div class="card-actions">
                    <span v-if="row.referenceSourceLabel" class="badge ghost">来自参考书学习</span>
                    <span class="badge">{{ row.statusLabel }}</span>
                  </div>
                </div>
                <p><strong>生效文本</strong><br />{{ row.activeSummary }}</p>
                <p><strong>候选文本</strong><br />{{ row.candidateSummary }}</p>
                <p class="muted">运行时引用：{{ row.runtimeRefLabel }}</p>
                <div class="card-actions">
                  <button
                    v-if="row.referenceSourceLabel"
                    class="ghost"
                    :data-testid="`knowledge-open-reference-${row.objectType}-${row.lineageKey}`"
                    @click="openReferenceLearning"
                  >
                    回到参考书学习
                  </button>
                  <button
                    class="ghost"
                    :data-testid="`knowledge-view-detail-${row.objectType}-${row.lineageKey}`"
                    @click="selectEntry(row.item)"
                  >
                    查看详情
                  </button>
                  <button class="ghost" @click="openReviewInbox(row.item)">查看审核收件箱</button>
                  <button class="ghost" @click="openIndexConsole(row.item)">打开索引控制台</button>
                </div>
              </article>
            </template>
          </VirtualList>
        </article>

        <article class="paper knowledge-detail-card" data-testid="knowledge-detail-drawer">
          <div class="receipt-head">
            <div>
              <h3>详情抽屉</h3>
              <p class="muted receipt-copy">在不离开知识控制台的前提下查看生效态、候选态，并继续做审核、校验、发布和后续处理。</p>
            </div>
            <span v-if="knowledgeConsole.detail" class="badge">{{ formatItemType(knowledgeConsole.detail.object_type) }}</span>
          </div>

          <div v-if="!knowledgeConsole.detail" class="empty" data-testid="knowledge-detail-empty">
            先选择一条血缘，再查看版本历史和运行时引用。
          </div>
          <template v-else>
            <div class="history-stack" data-testid="knowledge-impact-summary">
              <p class="history-title">生效范围与证据</p>
              <p><strong>这条知识现在是否生效</strong><br />{{ formatStatus(knowledgeConsole.detail.status || "unknown") }}</p>
              <p><strong>会影响哪里</strong><br />{{ knowledgeConsole.detail.runtime_refs?.alias_scope || knowledgeConsole.detail.runtime_refs?.mode || "直接读取" }}</p>
              <p><strong>来自哪个审核</strong><br />{{ workflowReviewItems[0]?.review_id || detailReviewRefs[0] || "暂无关联审核" }}</p>
            </div>
            <p data-testid="knowledge-detail-lineage"><strong>{{ isAdvancedMode ? "血缘" : "知识名称" }}</strong><br />{{ knowledgeConsole.detail.lineage_key }}</p>
            <p><strong>生效版本</strong><br />{{ previewText(knowledgeConsole.detail.active_version) }}</p>
            <p><strong>候选版本</strong><br />{{ previewText(knowledgeConsole.detail.candidate_version) }}</p>
            <StyleProfileSummary
              :summary="detailStyleProfileSummary"
              test-id="knowledge-style-profile-summary"
            />
            <StyleProfileDiffSummary
              :summary="detailStyleProfileDiffSummary"
              test-id="knowledge-style-profile-diff-summary"
            />
            <StyleProfileRiskWarning
              :risk="detailStyleProfileRisk"
              test-id="knowledge-style-profile-risk-warning"
            />
            <div class="history-stack">
              <p class="history-title">流程状态</p>
              <div class="card-actions">
                <span v-for="item in workflowStatusItems" :key="item.label" class="badge">{{ item.label }}: {{ item.value }}</span>
              </div>
            </div>
            <div class="history-stack">
              <p class="history-title">流程动作</p>
              <div class="card-actions">
                <button
                  v-if="primaryWorkflowAction"
                  class="ghost"
                  data-testid="knowledge-workflow-primary-action"
                  :disabled="primaryWorkflowActionDisabled"
                  @click="runPrimaryWorkflowAction"
                >
                  {{ actionLabel(primaryWorkflowAction.action) }}
                </button>
                <button
                  v-for="review in workflowActionItems.pendingReviews"
                  :key="`approve-${review.review_id}`"
                  class="ghost"
                  :data-testid="`knowledge-approve-review-${review.review_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId) || !canApproveReview(review)"
                  @click="runApprove(review.review_id, approvalPayloadForReview(review))"
                >
                  批准审核
                </button>
                <button
                  v-for="job in workflowActionItems.retryableJobs"
                  :key="`verify-${job.job_id}`"
                  class="ghost"
                  :data-testid="`knowledge-retry-verify-${job.job_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runRetryVerify(job.job_id)"
                >
                  重试校验
                </button>
                <button
                  v-for="review in workflowActionItems.releasableReviews"
                  :key="`release-${review.review_id}`"
                  class="ghost"
                  :data-testid="`knowledge-release-review-${review.review_id}`"
                  :disabled="Boolean(knowledgeConsole.actionId)"
                  @click="runRelease(review.review_id)"
                >
                  发布审核
                </button>
              </div>
              <FlowActionReceipt :receipt="receipt(KNOWLEDGE_WORKFLOW_SCOPE)" />
              <div
                v-for="review in workflowRiskConfirmationReviews"
                :key="`risk-confirmation-${review.review_id}`"
                class="risk-confirmation knowledge-risk-confirmation"
                :data-testid="`knowledge-risk-confirmation-${review.review_id}`"
              >
                <label class="checkbox-inline risk-confirmation-check">
                  <input
                    v-model="riskAcknowledgements[review.review_id]"
                    type="checkbox"
                    :data-testid="`knowledge-risk-confirm-${review.review_id}`"
                  />
                  <span>我已复核高风险风格变更，确认可以从知识控制台覆盖当前生效画像。</span>
                </label>
                <textarea
                  v-model="riskReasons[review.review_id]"
                  class="risk-confirmation-reason"
                  rows="3"
                  :data-testid="`knowledge-risk-reason-${review.review_id}`"
                  placeholder="填写批准理由，会写入操作日志"
                ></textarea>
                <small>需要明确理由后才能批准，之后可在索引控制台目标活动中回放。</small>
              </div>
            </div>
            <div class="history-stack" data-testid="knowledge-advanced-refs">
              <p class="history-title">高级引用</p>
              <p class="muted">审核引用、关联任务、包引用和目标活动默认折叠在下方，需要排查时再展开。</p>
            </div>
            <LazySection
              :key="`runtime-${selectedEntryKey}`"
              title="运行时引用"
              toggle-test-id="knowledge-toggle-runtime-refs"
            >
              <pre class="json-block" data-testid="knowledge-runtime-refs-json">{{
                formatJsonPayload(knowledgeConsole.detail.runtime_refs)
              }}</pre>
            </LazySection>
            <LazySection :key="`versions-${selectedEntryKey}`" title="版本历史" toggle-test-id="knowledge-toggle-versions">
              <ProgressiveList
                :items="knowledgeConsole.detail.versions || []"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeVersionRow"
                test-id="knowledge-versions-progressive-list"
              >
                <template #default="{ items }">
                  <ol class="history-list">
                    <li v-for="row in items" :key="row.rowId" class="history-entry" :data-testid="`knowledge-version-row-${row.rowId}`">
                      <p class="history-meta">
                        <strong>{{ row.rowId }}</strong>
                        <span>{{ row.versionLabel }}</span>
                      </p>
                      <p>{{ row.text }}</p>
                    </li>
                  </ol>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection :key="`reviews-${selectedEntryKey}`" title="关联审核" toggle-test-id="knowledge-toggle-reviews">
              <ProgressiveList
                :items="workflowReviewItems"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeWorkflowReviewRow"
                test-id="knowledge-reviews-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.reviewId" class="history-entry" :data-testid="`knowledge-review-row-${row.reviewId}`">
                      <p class="history-meta">
                        <strong>{{ row.reviewId }}</strong>
                        <span>{{ row.statusLabel }}</span>
                      </p>
                      <p class="muted">{{ row.materializeStatusLabel }}</p>
                      <div class="card-actions">
                        <button
                          class="ghost"
                          :data-testid="`knowledge-open-related-review-${row.reviewId}`"
                          @click="openReviewRef(row.reviewId)"
                        >
                          打开审核收件箱
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联审核。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection :key="`jobs-${selectedEntryKey}`" title="关联任务" toggle-test-id="knowledge-toggle-jobs">
              <ProgressiveList
                :items="workflowJobs"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeWorkflowJobRow"
                test-id="knowledge-jobs-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.jobId" class="history-entry" :data-testid="`knowledge-job-row-${row.jobId}`">
                      <p class="history-meta">
                        <strong>{{ row.jobId }}</strong>
                        <span>{{ row.statusLabel }}</span>
                      </p>
                      <p class="muted">{{ row.summary }}</p>
                      <div class="card-actions">
                        <button class="ghost" @click="openJobTarget(row.job)">
                          打开索引控制台
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联任务。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection :key="`human-review-${selectedEntryKey}`" title="关联人工审核" toggle-test-id="knowledge-toggle-human-review">
              <ProgressiveList
                :items="workflowHumanReviewEvents"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeHumanReviewRow"
                test-id="knowledge-human-review-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.eventId" class="history-entry" :data-testid="`knowledge-human-review-row-${row.eventId}`">
                      <p class="history-meta">
                        <strong>{{ row.eventId }}</strong>
                        <span>{{ row.statusLabel }}</span>
                      </p>
                      <p class="muted">{{ row.defaultActionLabel }}</p>
                      <div class="card-actions">
                        <button class="ghost" @click="openHumanReviewEvent(row.event)">
                          打开审核收件箱
                        </button>
                        <button
                          v-for="action in row.actions"
                          :key="action.key"
                          class="ghost"
                          :data-testid="`knowledge-human-review-action-${row.eventId}-${action.action}`"
                          :disabled="Boolean(knowledgeConsole.actionId)"
                          @click="runHumanReviewAction(row.eventId, action.action)"
                        >
                          {{ action.label }}
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联的人工审核后续项。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection :key="`activity-${selectedEntryKey}`" title="目标活动" toggle-test-id="knowledge-toggle-activity">
              <ProgressiveList
                :items="workflowTargetActivityGroups"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeActivityRow"
                test-id="knowledge-activity-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.targetRef" class="history-entry" :data-testid="`knowledge-activity-row-${row.targetRef}`">
                      <p class="history-meta">
                        <strong>{{ row.targetRef }}</strong>
                        <span>{{ row.activityCount }} 条活动</span>
                      </p>
                      <p class="muted">{{ row.sourcesLabel }}</p>
                      <div class="card-actions">
                        <button class="ghost" @click="openActivityTarget(row.group)">
                          打开目标
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联目标活动。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection
              :key="`review-refs-${selectedEntryKey}`"
              title="审核引用"
              toggle-test-id="knowledge-toggle-review-refs"
            >
              <ProgressiveList
                :items="detailReviewRefs"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeReviewRefRow"
                test-id="knowledge-review-refs-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.reviewRef" class="history-entry" :data-testid="`knowledge-review-ref-row-${row.reviewRef}`">
                      <p class="history-meta">
                        <strong>{{ row.reviewRef }}</strong>
                        <span>{{ row.targetType }}</span>
                      </p>
                      <div class="card-actions">
                        <button
                          class="ghost"
                          :data-testid="`knowledge-open-review-ref-${row.reviewRef}`"
                          @click="openReviewRef(row.reviewRef)"
                        >
                          打开审核收件箱
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有关联审核引用。</p>
                </template>
              </ProgressiveList>
            </LazySection>
            <LazySection
              :key="`bundle-refs-${selectedEntryKey}`"
              title="包引用"
              toggle-test-id="knowledge-toggle-bundle-refs"
            >
              <ProgressiveList
                :items="detailBundleRefs"
                :initial-count="6"
                :batch-size="6"
                :threshold="8"
                :map-item="knowledgeBundleRefRow"
                test-id="knowledge-bundle-refs-progressive-list"
              >
                <template #default="{ items }">
                  <ol v-if="items.length" class="history-list">
                    <li v-for="row in items" :key="row.bundleId" class="history-entry" :data-testid="`knowledge-bundle-ref-row-${row.bundleId}`">
                      <p class="history-meta">
                        <strong>{{ row.bundleId }}</strong>
                        <span>{{ row.sceneId }}</span>
                      </p>
                      <p class="muted">章节 {{ row.chapterId }}</p>
                      <div class="card-actions">
                        <button
                          class="ghost"
                          :data-testid="`knowledge-open-bundle-ref-${row.bundleId}`"
                          @click="openBundleWorkbench(row.bundleRef)"
                        >
                          打开场景工作台
                        </button>
                      </div>
                    </li>
                  </ol>
                  <p v-else class="muted">还没有包引用。</p>
                </template>
              </ProgressiveList>
            </LazySection>
          </template>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
