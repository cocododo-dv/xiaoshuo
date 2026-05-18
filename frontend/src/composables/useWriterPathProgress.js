import { computed } from "vue";

import { useShellRouter } from "../router";
import { useReferenceLearningStore } from "../stores/referenceLearning";
import { useReviewInboxStore } from "../stores/reviewInbox";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";
import { useWriterFlowStore } from "../stores/writerFlow";
import { useWriterRoomStore } from "../stores/writerRoom";

export const WRITER_PATH_VIEW_IDS = ["snowflake-workbench", "writer-flow", "writer-room", "reference", "review"];

export const WRITER_PATH_STATUS_LABELS = {
  todo: "还没开始",
  active: "正在进行",
  running: "系统处理中",
  blocked: "需要你来",
  done: "已完成",
};

const REVIEW_DECISION_STATUSES = new Set(["pending", "waiting_review", "needs_author"]);
const HUMAN_REVIEW_DONE_STATUSES = new Set(["resolved", "dismissed", "completed", "approved"]);
const STRUCTURE_APPROVED_PROJECT_STATUSES = new Set([
  "chapter_ready",
  "chapter_running",
  "chapter_blocked",
  "chapter_final_review",
  "completed",
]);

function activeActionLabel(actionId) {
  return actionId ? "处理中" : "";
}

function currentStepLabel(snowflake) {
  return snowflake.currentStep?.label || snowflake.currentStep?.step_key || "当前雪花步骤";
}

function snowflakeWorkflowState(snowflake, writerFlow) {
  const gateStatus = String(snowflake.materializationGate?.status || "").toLowerCase();
  const planStatus = String(snowflake.latestPlan?.status || snowflake.workspace?.latest_plan?.status || "").toLowerCase();
  const projectStatus = String(
    snowflake.project?.status
      || snowflake.workspace?.project?.status
      || writerFlow.project?.status
      || writerFlow.dashboard?.project?.status
      || "",
  ).toLowerCase();

  if (planStatus === "approved" || STRUCTURE_APPROVED_PROJECT_STATUSES.has(projectStatus)) {
    return "structure_approved";
  }
  if (planStatus === "pending_review") {
    return "outline_pending_review";
  }
  if (snowflake.readyToMaterialize || ["ready", "approved", "done"].includes(gateStatus)) {
    return "can_materialize";
  }
  return "in_steps";
}

function snowflakeItem(meta, activeView, snowflake, writerFlow) {
  const hasProject = Boolean(snowflake.selectedProjectId || snowflake.project?.project_id);
  const stepCount = snowflake.steps?.length || 0;
  const doneCount = (snowflake.steps || []).filter((step) => step.gate_satisfied).length;
  const isLoaded = Boolean(snowflake.loaded || snowflake.workspace || hasProject);
  const workflowState = snowflakeWorkflowState(snowflake, writerFlow);

  let status = "active";
  let summary = `继续推进 ${currentStepLabel(snowflake)}。`;
  let nextAction = "继续推进当前这一步，把故事想清楚。";
  let countLabel = stepCount ? `${doneCount}/${stepCount}` : "待推进";
  let primaryTarget = meta.id;

  if (snowflake.actionId) {
    status = "running";
    summary = "雪花工作台正在处理当前操作。";
    nextAction = "等待操作完成后再继续下一步。";
    countLabel = activeActionLabel(snowflake.actionId);
  } else if (!hasProject) {
    status = "todo";
    summary = "先创建或选择一个雪花项目。";
    nextAction = "在雪花工作台创建项目，进入十步雪花。";
    countLabel = "待建项";
  } else if (snowflake.currentStepDirty) {
    status = "blocked";
    summary = `${currentStepLabel(snowflake)} 有未保存内容。`;
    nextAction = "先保存或确认当前步骤，再切到下一环。";
    countLabel = "未保存";
  } else if (workflowState === "structure_approved") {
    status = "done";
    summary = "章节结构已确认，写作主线已经交给写作总控。";
    nextAction = "进入写作总控，启动当前章节起草或查看终稿审阅。";
    countLabel = "结构已确认";
    primaryTarget = "writer-flow";
  } else if (workflowState === "outline_pending_review") {
    status = "active";
    summary = "章节结构草案已整理好，正在等待作者确认。";
    nextAction = "检查章节计划并确认结构，确认后进入写作总控。";
    countLabel = "待确认";
  } else if (workflowState === "can_materialize") {
    status = "active";
    summary = "雪花步骤已具备整理条件，还没有生成章节结构草案。";
    nextAction = "整理成章节结构，再检查并确认。";
    countLabel = "可整理";
  } else if (!isLoaded) {
    status = "todo";
    summary = "雪花工作台尚未加载项目状态。";
    nextAction = "打开雪花工作台查看当前步骤。";
    countLabel = "未加载";
  }

  return buildItem(meta, activeView, { status, summary, nextAction, countLabel, isLoaded, primaryTarget });
}

function writerRoomItem(meta, activeView, room) {
  const candidateCount = (room.proposalCards?.length ? room.proposalCards : room.proposals || [])
    .filter((proposal) => proposal?.status !== "rejected").length;
  const hasAdvice = Boolean(room.topIssue || room.keepAdvice);
  const isLoaded = Boolean(room.loaded || room.writerRoomPayload);

  let status = "todo";
  let summary = "写作房间尚未打开。";
  let nextAction = "打开写作房间，保存正文并比较候选。";
  let countLabel = "未加载";

  if (room.actionId) {
    status = "running";
    summary = "写作房间正在处理正文或候选改法。";
    nextAction = "等待操作完成，避免重复应用候选。";
    countLabel = activeActionLabel(room.actionId);
  } else if (!isLoaded) {
    status = "todo";
  } else if (room.draftDirty) {
    status = "blocked";
    summary = "当前正文有未保存修改。";
    nextAction = "先保存正文，再比较候选或继续写。";
    countLabel = "未保存";
  } else if (candidateCount > 0) {
    status = "active";
    summary = "已有候选改法等待作者比较。";
    nextAction = "预览、采纳或放弃候选改法。";
    countLabel = `${candidateCount} 候选`;
  } else if (hasAdvice) {
    status = "active";
    summary = "当前正文有一条优先建议可处理。";
    nextAction = "围绕最重要建议做一轮小修。";
    countLabel = "有建议";
  } else {
    status = "done";
    summary = "正文已保存，暂无阻塞候选。";
    nextAction = "继续写下一段，或回雪花工作台校准结构。";
    countLabel = "已保存";
  }

  return buildItem(meta, activeView, { status, summary, nextAction, countLabel, isLoaded });
}

function writerFlowItem(meta, activeView, flow) {
  const isLoaded = Boolean(flow.loaded || flow.dashboard || flow.project);
  const nextAction = flow.nextAction || "";
  const runStatus = flow.runStatus || {};

  let status = "todo";
  let summary = "写作总控尚未打开。";
  let nextActionText = "打开写作总控，继续当前项目的下一步。";
  let countLabel = "未加载";

  if (flow.actionId) {
    status = "running";
    summary = "写作总控正在处理当前动作。";
    nextActionText = "等待动作完成后再继续推进章节。";
    countLabel = activeActionLabel(flow.actionId);
  } else if (!isLoaded) {
    status = "todo";
  } else if (nextAction === "view_chapter_progress" || ["pending", "running", "queued"].includes(String(runStatus.status || "").toLowerCase())) {
    status = "running";
    summary = "当前章节正在起草。";
    nextActionText = "查看进度，完成后进入终稿审阅。";
    countLabel = `${Number(runStatus.progress_pct ?? flow.progressPercent ?? 0)}%`;
  } else if (nextAction === "approve_chapter_final") {
    status = "active";
    summary = "当前章节已进入终稿审阅。";
    nextActionText = "阅读正文来源和风险提示，确认后批准本章。";
    countLabel = flow.reviewPacket?.body ? "待批准" : "缺正文";
  } else if (nextAction === "resolve_blocker" || nextAction === "resolve_backtrack_items") {
    status = "blocked";
    summary = "当前章节有阻塞或返工项。";
    nextActionText = "先处理阻塞原因，再继续起草。";
    const pendingCount = Array.isArray(flow.backtrackItems)
      ? flow.backtrackItems.filter((item) => item.status === "pending").length
      : 0;
    countLabel = `${pendingCount || 1} 待处理`;
  } else if (nextAction === "completed") {
    status = "done";
    summary = "项目章节主线已完成。";
    nextActionText = "可以查看成稿或继续做文本小修。";
    countLabel = "已完成";
  } else if (nextAction === "run_current_chapter") {
    status = "active";
    summary = "当前章节可以开始起草。";
    nextActionText = "启动当前章起草，随后在这里查看进度。";
    countLabel = "可起草";
  }

  return buildItem(meta, activeView, { status, summary, nextAction: nextActionText, countLabel, isLoaded });
}

function referenceItem(meta, activeView, reference) {
  const isLoaded = Boolean(reference.loaded || reference.books?.length || reference.detail || reference.currentRun);
  const readyProfiles = (reference.profiles || []).filter((profile) =>
    ["ready", "active", "applied"].includes(String(profile?.status || "").toLowerCase()),
  );
  const pendingCount = reference.pendingDecisionCount || 0;

  let status = "todo";
  let summary = "还没有导入参考书。";
  let nextAction = "导入或继续分析参考书。";
  let countLabel = "未导入";
  let primaryTarget;

  if (reference.actionId) {
    status = "running";
    summary = "参考书学习正在处理导入、分析或应用。";
    nextAction = "等待长任务完成后再继续分析。";
    countLabel = activeActionLabel(reference.actionId);
  } else if (!reference.books?.length) {
    status = "todo";
  } else if (pendingCount > 0) {
    status = "blocked";
    summary = "参考学习产生了待审核候选卡。";
    nextAction = "先审核候选卡，避免未经确认的风格进入正文。";
    countLabel = `${pendingCount} 待审`;
  } else if (reference.lastApplicationGuidance) {
    status = "active";
    summary = "参考画像已创建应用审核项。";
    nextAction = "去待处理建议确认应用结果。";
    countLabel = "已送审";
    primaryTarget = "review";
  } else if (readyProfiles.length > 0) {
    status = "done";
    summary = "已有安全可用的参考画像。";
    nextAction = "选择应用范围，或进入待处理建议确认。";
    countLabel = `${readyProfiles.length} 画像`;
  } else if (isLoaded) {
    status = "active";
    summary = "参考书已就绪，可以启动或继续分析。";
    nextAction = "启动学习或继续分析下一轮。";
    countLabel = reference.currentRun ? "分析中" : "可学习";
  }

  return buildItem(meta, activeView, { status, summary, nextAction, countLabel, isLoaded, primaryTarget });
}

function reviewItem(meta, activeView, review) {
  const authorDecisionCount = (review.items || []).filter((item) =>
    REVIEW_DECISION_STATUSES.has(String(item?.status || "").toLowerCase()),
  ).length;
  const humanDecisionCount = (review.humanReviewItems || []).filter((item) =>
    !HUMAN_REVIEW_DONE_STATUSES.has(String(item?.status || "").toLowerCase()),
  ).length;
  const blockerCount = authorDecisionCount + humanDecisionCount;
  const isLoaded = Boolean(review.loaded);

  let status = "todo";
  let summary = "待处理建议尚未加载。";
  let nextAction = "打开待处理建议处理待决策项。";
  let countLabel = "未加载";
  let primaryTarget;

  if (review.actionId) {
    status = "running";
    summary = "待处理建议正在处理当前决策。";
    nextAction = "等待审核操作完成后再处理下一项。";
    countLabel = activeActionLabel(review.actionId);
  } else if (!isLoaded) {
    status = "todo";
  } else if (blockerCount > 0) {
    status = "blocked";
    summary = "有需要作者决策的建议或人工事件。";
    nextAction = "先处理待作者决策的卡片。";
    countLabel = `${blockerCount} 待决策`;
  } else {
    status = "done";
    summary = "当前没有阻塞作家主路径的审核项。";
    nextAction = "回到写作房间继续正文。";
    countLabel = "已清空";
    primaryTarget = "writer-room";
  }

  return buildItem(meta, activeView, { status, summary, nextAction, countLabel, isLoaded, primaryTarget });
}

function buildItem(meta, activeView, state) {
  const { primaryTarget, ...rest } = state;
  return {
    viewId: meta.id,
    label: meta.writerLabel || meta.stepLabel || meta.label,
    isActive: activeView === meta.id,
    primaryTarget: primaryTarget || meta.id,
    ...rest,
  };
}

export function useWriterPathProgress() {
  const router = useShellRouter();
  const snowflake = useSnowflakeWorkbenchStore();
  const writerFlow = useWriterFlowStore();
  const room = useWriterRoomStore();
  const reference = useReferenceLearningStore();
  const review = useReviewInboxStore();

  const items = computed(() => {
    const activeView = router.activeView.value;
    return [
      snowflakeItem(router.viewMeta("snowflake-workbench"), activeView, snowflake, writerFlow),
      writerFlowItem(router.viewMeta("writer-flow"), activeView, writerFlow),
      writerRoomItem(router.viewMeta("writer-room"), activeView, room),
      referenceItem(router.viewMeta("reference"), activeView, reference),
      reviewItem(router.viewMeta("review"), activeView, review),
    ];
  });

  const activeItem = computed(() =>
    items.value.find((item) => item.isActive)
    || items.value.find((item) => item.status === "blocked")
    || items.value[0]
    || null,
  );

  // First not-done phase. Linear by construction so the breadcrumb can never
  // show a later phase "done" while an earlier one is still active.
  const journeyPhase = computed(() => {
    const snowflakeDone = items.value[0]?.status === "done";
    const flowDone = items.value[1]?.status === "done";
    const roomDone = items.value[2]?.status === "done";
    if (!snowflakeDone) return "构思";
    if (!flowDone) return "起草";
    if (!roomDone) return "打磨";
    return "打磨";
  });

  function navigateToItem(itemOrViewId) {
    const viewId = typeof itemOrViewId === "string" ? itemOrViewId : itemOrViewId?.primaryTarget || itemOrViewId?.viewId;
    if (viewId) {
      router.navigate(viewId);
    }
  }

  return {
    items,
    activeItem,
    journeyPhase,
    navigateToItem,
  };
}
