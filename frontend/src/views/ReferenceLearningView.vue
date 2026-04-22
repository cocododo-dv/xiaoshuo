<script setup>
import { computed, onActivated, onBeforeUnmount, ref } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useReferenceLearningStore } from "../stores/referenceLearning";

const emit = defineEmits(["notice"]);

const referenceLearning = useReferenceLearningStore();
const { navigate } = useShellRouter();
const rejectReasons = ref({});
const expandedExcerptSegmentIds = ref({});
const importExpanded = ref(false);
const profileVisibilityFilter = ref("ready");
const referenceLongTaskSeconds = ref(0);
const referenceLongTaskTimer = ref(null);
const { receipt, running, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const REFERENCE_IMPORT_SCOPE = "reference:import";
const REFERENCE_RUN_SCOPE = "reference:run";
const REFERENCE_LIBRARY_SCOPE = "reference:library";
const SEGMENT_KIND_LABELS = {
  opening: "开篇片段",
  dialogue: "对话片段",
  imagery: "意象片段",
  action: "动作片段",
  emotion: "情绪片段",
  structure: "结构片段",
  closing: "结尾片段",
  boilerplate: "站点声明片段",
  reference: "参考片段",
};
const DIMENSION_LABELS = {
  rhythm: "节奏",
  imagery: "意象",
  "chapter hook": "章节钩子",
  "banned move": "禁复刻点",
  calibration: "校准",
  syntax: "句法",
  "conflict escalation": "冲突升级",
  "dialogue ratio": "对话比例",
  "narrative distance": "叙事距离",
  "emotion curve": "情绪曲线",
  "paragraph density": "段落密度",
};

function startReferenceLongTaskTimer() {
  stopReferenceLongTaskTimer();
  referenceLongTaskSeconds.value = 0;
  referenceLongTaskTimer.value = window.setInterval(() => {
    referenceLongTaskSeconds.value += 1;
  }, 1000);
}

function stopReferenceLongTaskTimer() {
  if (referenceLongTaskTimer.value) {
    window.clearInterval(referenceLongTaskTimer.value);
    referenceLongTaskTimer.value = null;
  }
  referenceLongTaskSeconds.value = 0;
}

const selectedBook = computed(() => referenceLearning.detail?.book || referenceLearning.selectedBook || null);
const coverage = computed(() => referenceLearning.coverage || {});
const coveragePercent = computed(() => Math.round(Math.max(0, Math.min(1, Number(coverage.value.coverage_score || 0))) * 100));
const sampledSegments = computed(() => Number(coverage.value.sampled_segments || 0));
const eligibleSegments = computed(() => Number(coverage.value.eligible_segments || selectedBook.value?.total_segments || 0));
const remainingSegments = computed(() => Number(coverage.value.remaining_segments || 0));
const sampleCoveragePercent = computed(() =>
  Math.round(Math.max(0, Math.min(1, Number(coverage.value.sample_coverage_score || 0))) * 100),
);
const dimensionCoveragePercent = computed(() =>
  Math.round(Math.max(0, Math.min(1, Number(coverage.value.dimension_coverage_score ?? coverage.value.coverage_score ?? 0))) * 100),
);
const sampleProgressLabel = computed(() => `已抽样 ${sampledSegments.value}/${eligibleSegments.value || 0}`);
const sampleRemainingLabel = computed(() =>
  coverage.value.learning_complete ? "全书可学习片段已完成" : `剩余 ${remainingSegments.value} 段可继续学习`,
);
const cloudPolicy = computed(() => selectedBook.value?.cloud_policy || referenceLearning.pathDraft.cloud_policy);
const consentLabel = computed(() => CLOUD_POLICY_LABELS[cloudPolicy.value] || cloudPolicy.value || "-");
const runId = computed(() => referenceLearning.currentRun?.run_id || referenceLearning.detail?.latest_run?.run_id || "");
const findings = computed(() => referenceLearning.findings || []);
const profiles = computed(() => referenceLearning.profiles || []);
const readyProfiles = computed(() =>
  profiles.value.filter((profile) => !isProfileStale(profile) && profileSafety(profile).safe !== false),
);
const staleProfiles = computed(() => profiles.value.filter((profile) => isProfileStale(profile)));
const visibleProfiles = computed(() =>
  profileVisibilityFilter.value === "all" ? profiles.value : readyProfiles.value,
);
const coveredDimensions = computed(() => coverage.value.covered_dimensions || []);
const coveredFindingTypes = computed(() => coverage.value.covered_finding_types || []);
const canContinueLearningMore = computed(() => Boolean(coverage.value.next_round_available));
const activeApplicationStatus = computed(() => {
  const status = {
    total: 0,
    pending: 0,
    approved: 0,
    rejected: 0,
    review_ids: [],
  };
  for (const profile of profiles.value) {
    const item = profile?.application_status || {};
    status.total += Number(item.total || 0);
    status.pending += Number(item.pending || 0);
    status.approved += Number(item.approved || 0);
    status.rejected += Number(item.rejected || 0);
    status.review_ids.push(...(Array.isArray(item.review_ids) ? item.review_ids : []));
  }
  return status;
});
const hasPendingApplicationReviews = computed(() => activeApplicationStatus.value.pending > 0);
const canReplayProfileAdvance = computed(() =>
  Boolean(readyProfiles.value.length && referenceLearning.pendingDecisionCount === 0 && !canContinueLearningMore.value),
);
const canAdvance = computed(() =>
  Boolean(
    referenceLearning.selectedBookId &&
      runId.value &&
      referenceLearning.pendingDecisionCount === 0 &&
      !referenceLearning.actionId,
  ),
);
const advanceRunDisabledReason = computed(() => {
  if (!selectedBook.value || !referenceLearning.selectedBookId) {
    return "先导入或选择一本参考书。";
  }
  if (!runId.value) {
    return "先启动学习任务。";
  }
  if (referenceLearning.actionId) {
    return "系统正在处理当前操作。";
  }
  if (referenceLearning.pendingDecisionCount > 0) {
    return `还有 ${referenceLearning.pendingDecisionCount} 张候选卡待决策`;
  }
  if (canContinueLearningMore.value) {
    return "阶段画像可用；仍有未抽样片段，可继续学习更多片段。";
  }
  if (coverage.value.learning_complete) {
    return "全书可学习片段已完成，可应用画像。";
  }
  if (readyProfiles.value.length) {
    return "画像已生成，可点击刷新状态或直接应用。";
  }
  return "";
});
const advanceRunLabel = computed(() => {
  if (referenceLearning.actionId === "advance-run") {
    return "分析中...";
  }
  if (canContinueLearningMore.value) {
    return "继续学习更多片段";
  }
  if (canReplayProfileAdvance.value) {
    return "刷新画像状态";
  }
  if (hasRoundFindings.value && referenceLearning.pendingDecisionCount === 0 && !readyProfiles.value.length) {
    return "继续生成画像";
  }
  return "继续分析";
});
const canStart = computed(() => Boolean(referenceLearning.selectedBookId && !runId.value && !referenceLearning.actionId));
const startRunDisabledReason = computed(() => {
  if (!selectedBook.value) {
    return "先导入或选择一本参考书。";
  }
  if (referenceLearning.actionId) {
    return "系统正在处理当前操作。";
  }
  if (runId.value) {
    return "这本书已经有学习任务；请按右侧状态继续。";
  }
  return "";
});
const startRunLabel = computed(() => {
  if (!selectedBook.value) {
    return "先选书";
  }
  if (runId.value) {
    return "已启动";
  }
  return "启动学习";
});
const hasRoundFindings = computed(() => findings.value.length > 0);
const shouldShowImportForm = computed(() => importExpanded.value || !selectedBook.value || !referenceLearning.books.length);
const approvedMetric = computed(() =>
  hasRoundFindings.value ? referenceLearning.approvedDecisionCount : coverage.value.approved_findings || 0,
);
const pendingMetric = computed(() =>
  hasRoundFindings.value ? referenceLearning.pendingDecisionCount : coverage.value.pending_findings || 0,
);
const rejectedMetric = computed(() =>
  hasRoundFindings.value ? referenceLearning.rejectedDecisionCount : coverage.value.rejected_findings || 0,
);
const flowStage = computed(() => {
  if (!selectedBook.value) {
    return "import";
  }
  if (hasPendingApplicationReviews.value) {
    return "apply";
  }
  if (profiles.value.length || referenceLearning.currentRun?.status === "completed") {
    return "profile";
  }
  if (referenceLearning.pendingDecisionCount > 0) {
    return "decision";
  }
  if (runId.value) {
    return "sampling";
  }
  return "import";
});
const flowSteps = computed(() => {
  const hasDecisions =
    referenceLearning.approvedDecisionCount > 0 ||
    referenceLearning.rejectedDecisionCount > 0 ||
    Number(coverage.value.approved_findings || 0) > 0 ||
    Number(coverage.value.rejected_findings || 0) > 0;
  return [
    { key: "import", label: "导入书籍", done: Boolean(selectedBook.value) },
    { key: "sampling", label: "抽样分析", done: Boolean(hasRoundFindings.value || hasDecisions || profiles.value.length) },
    { key: "decision", label: "审核候选", done: Boolean(hasRoundFindings.value && referenceLearning.pendingDecisionCount === 0) },
    { key: "profile", label: "生成画像", done: Boolean(readyProfiles.value.length) },
    { key: "apply", label: "手动应用", done: Boolean(activeApplicationStatus.value.total && !activeApplicationStatus.value.pending) },
  ];
});
const flowHint = computed(() => {
  if (!selectedBook.value) {
    return "先导入或选择一本参考书。";
  }
  if (!runId.value) {
    return "下一步：启动学习，让系统挑第一轮片段。";
  }
  if (referenceLearning.pendingDecisionCount > 0) {
    return "当前暂停在审核点：批准有价值的卡片，或把不合格卡片拒绝掉。";
  }
  if (hasPendingApplicationReviews.value) {
    return `已创建 ${activeApplicationStatus.value.total} 个应用审核项，等待审核收件箱批准。`;
  }
  if (staleProfiles.value.length && !readyProfiles.value.length) {
    return "画像已过期：审核决策变化后，需要继续分析重新生成安全画像。";
  }
  if (readyProfiles.value.length && canContinueLearningMore.value) {
    return "阶段画像已就绪；可以先应用，也可以继续学习未抽样片段。";
  }
  if (readyProfiles.value.length) {
    return "画像已就绪；应用时只会创建审核项，不会直接污染全局。";
  }
  return "继续分析会推进到下一轮候选卡；全书进度按已抽样片段计算。";
});
const currentTask = computed(() => {
  if (!selectedBook.value) {
    return "还没有参考书。";
  }
  if (!runId.value) {
    return "已选中参考书，但还没有开始学习。";
  }
  if (referenceLearning.pendingDecisionCount > 0) {
    return `卡在审核候选：还有 ${referenceLearning.pendingDecisionCount} 张候选卡待决策。`;
  }
  if (hasPendingApplicationReviews.value) {
    return `已创建 ${activeApplicationStatus.value.total} 个应用审核项，等待审核收件箱批准。`;
  }
  if (staleProfiles.value.length && !readyProfiles.value.length) {
    return "画像已过期，等待重新生成。";
  }
  if (readyProfiles.value.length) {
    return "画像已生成，等待你决定应用范围。";
  }
  if (hasRoundFindings.value) {
    return "本轮候选卡已经全部决策完。";
  }
  return "学习任务已启动，正在等待生成第一轮候选卡。";
});
const nextAction = computed(() => {
  if (!selectedBook.value) {
    return "展开左侧导入参考书，或从书籍列表选择一本。";
  }
  if (!runId.value) {
    return "点击「启动学习」创建任务，然后点击「继续分析」生成候选卡。";
  }
  if (referenceLearning.pendingDecisionCount > 0) {
    return "去下方候选卡逐张点击「批准」或「拒绝」；待审核清零后，「继续分析」才会亮起。";
  }
  if (hasPendingApplicationReviews.value) {
    return "去审核收件箱批准这些应用项；批准后才会进入知识库和生成链路。";
  }
  if (staleProfiles.value.length && !readyProfiles.value.length) {
    return "点击「继续分析」重新生成画像；过期画像不会进入审核或生成链路。";
  }
  if (readyProfiles.value.length && canContinueLearningMore.value) {
    return "可以点击「继续学习更多片段」生成下一轮候选卡，或先把当前画像应用到审核。";
  }
  if (readyProfiles.value.length) {
    return "在最终画像区选择全局、章节或场景，再点击「应用到审核」。";
  }
  if (hasRoundFindings.value) {
    return "点击「继续分析」，系统会进入下一轮抽样，或在覆盖度达标后生成画像。";
  }
  return "点击「继续分析」生成第一轮候选卡。";
});

const CLOUD_POLICY_LABELS = {
  allow_full_cloud: "允许云端处理全文",
  segments_only: "仅允许云端处理抽样片段",
  local_only: "仅本地处理",
};

const FINDING_TYPE_LABELS = {
  style_rule_set: "文笔规则",
  style_observation: "风格观察",
  narrative_pattern: "叙事结构",
  banned_rule_cluster: "禁用复刻规则",
  calibration_candidate: "校准参考",
};

const STATUS_LABELS = {
  imported: "已导入",
  learning: "学习中",
  running: "运行中",
  waiting_review: "等待审核",
  completed: "已完成",
  ready: "可应用",
  stale: "需重新生成",
  pending: "待决策",
  approved: "已批准",
  rejected: "已拒绝",
};

function labelForStatus(status) {
  return STATUS_LABELS[status] || status || "-";
}

function bookProgressLabel(book) {
  const latestCoverage = book?.latest_run?.coverage || book?.coverage || {};
  const eligible = Number(latestCoverage.eligible_segments || book?.total_segments || 0);
  const sampled = Number(latestCoverage.sampled_segments || 0);
  const remaining = Number(latestCoverage.remaining_segments || Math.max(0, eligible - sampled));
  if (eligible > 0) {
    const base = `已抽样 ${sampled}/${eligible} · 剩余 ${remaining}`;
    if (latestCoverage.learning_complete) {
      return `${base} · 全书完成`;
    }
    if (latestCoverage.next_round_available) {
      return `${base} · 可继续学习`;
    }
    return base;
  }
  if (book?.profile_status === "ready" || latestCoverage.profile_ready) {
    return `画像已就绪 · ${book.total_segments || 0} 段`;
  }
  if (book?.profile_status === "stale" || book?.profile_stale || latestCoverage.profile_stale) {
    return `需重新生成 · ${book.total_segments || 0} 段`;
  }
  return `${labelForStatus(book?.status)} · ${book?.total_segments || 0} 段`;
}

function labelForFindingType(type) {
  return FINDING_TYPE_LABELS[type] || type || "-";
}

function decisionStatus(finding) {
  return finding?.review?.status || finding?.status || "pending";
}

function canApproveFinding(finding) {
  return Boolean(reviewIdForFinding(finding)) && decisionStatus(finding) !== "approved" && !referenceLearning.actionId;
}

function canRejectFinding(finding) {
  return Boolean(reviewIdForFinding(finding)) && decisionStatus(finding) !== "rejected" && !referenceLearning.actionId;
}

function approveLabel(finding) {
  return decisionStatus(finding) === "rejected" ? "改为批准" : "批准";
}

function rejectLabel(finding) {
  return decisionStatus(finding) === "approved" ? "改为拒绝" : "拒绝";
}

function rejectionHint(finding) {
  const status = decisionStatus(finding);
  if (status === "approved") {
    return "可填写原因后改为拒绝。";
  }
  if (status === "rejected") {
    return "已拒绝；如误判可改为批准。";
  }
  return "可选：写明为什么拒绝，便于之后回看。";
}

function reviewIdForFinding(finding) {
  return finding?.review?.review_id || "";
}

function findingRisk(finding) {
  if (finding?.finding_type === "banned_rule_cluster") {
    return "会作为禁用规则保存，用来阻断角色、设定、专名或可识别桥段的复刻。";
  }
  if (finding?.finding_type === "calibration_candidate") {
    return "只保留抽象校准，不把原书长句作为生成素材。";
  }
  return "只进入抽象技法层，不直接带入原书表达。";
}

function hasChineseText(value) {
  return /[\u4e00-\u9fff]/.test(String(value || ""));
}

function normalizedReferenceCode(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+segment$/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ");
}

function labelForSegmentKind(segmentKind) {
  const normalized = normalizedReferenceCode(segmentKind).replace(/\s+/g, "_");
  return SEGMENT_KIND_LABELS[normalized] || "";
}

function labelForDimension(dimension) {
  const normalized = normalizedReferenceCode(dimension);
  if (!normalized) {
    return "-";
  }
  if (DIMENSION_LABELS[normalized]) {
    return DIMENSION_LABELS[normalized];
  }
  const matched = Object.entries(DIMENSION_LABELS).find(([key]) => normalized.includes(key));
  if (matched) {
    return matched[1];
  }
  return hasChineseText(dimension) ? dimension : "技法";
}

function findingSourceLabel(finding) {
  const kindLabel = labelForSegmentKind(finding?.source_segment?.segment_kind);
  if (kindLabel) {
    return kindLabel;
  }
  const displayLabel = finding?.source_segment?.display_label;
  if (hasChineseText(displayLabel)) {
    return displayLabel;
  }
  const displayKindLabel = labelForSegmentKind(displayLabel);
  return displayKindLabel || "参考片段";
}

function isSourceExcerptHidden(finding) {
  return finding?.source_excerpt_hidden !== false;
}

function sourceVisibilityLabel(finding) {
  return isSourceExcerptHidden(finding) ? "源文片段已隐藏" : "仅显示抽象摘要";
}

function displayFindingSummary(finding) {
  const summary = String(finding?.summary || "").trim();
  if (!summary || hasChineseText(summary)) {
    return summary;
  }
  return localizeReferenceGuidance(summary);
}

function findingSafetyLabel(finding) {
  const notes =
    finding?.review?.candidate_payload_json?.safety_notes ||
    finding?.candidate_payload_json?.safety_notes ||
    {};
  if (Number(notes.stripped_count || 0) > 0) {
    return "已移除源书专名";
  }
  if (notes.source_excerpt_hidden || isSourceExcerptHidden(finding)) {
    return "已抽象化";
  }
  return "";
}

function segmentIdForFinding(finding) {
  return finding?.source_segment?.segment_id || finding?.reference_segment_id || "";
}

function isExcerptExpanded(finding) {
  const segmentId = segmentIdForFinding(finding);
  return Boolean(segmentId && expandedExcerptSegmentIds.value[segmentId]);
}

function excerptForFinding(finding) {
  const segmentId = segmentIdForFinding(finding);
  return segmentId ? referenceLearning.segmentExcerpts[segmentId] : null;
}

function isExcerptLoading(finding) {
  const segmentId = segmentIdForFinding(finding);
  return Boolean(segmentId && referenceLearning.segmentExcerptLoading[segmentId]);
}

async function toggleFindingExcerpt(finding) {
  const segmentId = segmentIdForFinding(finding);
  if (!segmentId) {
    return;
  }
  if (expandedExcerptSegmentIds.value[segmentId]) {
    expandedExcerptSegmentIds.value = {
      ...expandedExcerptSegmentIds.value,
      [segmentId]: false,
    };
    return;
  }
  expandedExcerptSegmentIds.value = {
    ...expandedExcerptSegmentIds.value,
    [segmentId]: true,
  };
  try {
    await referenceLearning.fetchSegmentExcerpt(segmentId);
  } catch (error) {
    expandedExcerptSegmentIds.value = {
      ...expandedExcerptSegmentIds.value,
      [segmentId]: false,
    };
    emit("notice", error.message);
  }
}

function modelTraceLabel(trace) {
  if (!trace || trace.mode === "local_heuristic" || trace.provider === "local") {
    return "本地启发式提取";
  }
  return [trace.provider, trace.model].filter(Boolean).join(" · ") || "模型调用";
}

function modelTraceQuality(trace) {
  const value = Number(trace?.quality_score);
  if (!Number.isFinite(value)) {
    return "";
  }
  return `质量分 ${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function modelTraceNode(trace) {
  const nodeIds = Array.isArray(trace?.node_ids) ? trace.node_ids : [trace?.node_id].filter(Boolean);
  return nodeIds.length ? `参考学习节点：${nodeIds.join(" / ")}` : "";
}

function modelCapabilityHint(trace) {
  if (!trace || trace.mode === "local_heuristic" || trace.provider === "local") {
    return "未调用 LLM；使用本地启发式提取。";
  }
  return "模型越强通常抽象更精准；最终入库仍以抽样覆盖、prompt 和人工审核结果为准。";
}

function findingReceiptScope(finding) {
  return `reference:finding:${reviewIdForFinding(finding) || finding?.finding_id || "unknown"}`;
}

function referenceProfileScope(profile) {
  return `reference:profile:${profile?.profile_id || "unknown"}`;
}

function referenceProfileReceipt(profile) {
  return receipt(referenceProfileScope(profile));
}

function profileSafety(profile) {
  return profile?.safety_summary || profile?.coverage?.safety_summary || { safe: true, stripped_count: 0, blocked_markers: [] };
}

function isProfileStale(profile) {
  return (
    profile?.status === "stale" ||
    profile?.coverage?.profile_stale === true ||
    profileSafety(profile).safe === false
  );
}

function canApplyProfile(profile) {
  return !isProfileStale(profile) && !referenceLearning.actionId && !running(referenceProfileScope(profile));
}

function profileStatusLabel(profile) {
  if (isProfileStale(profile)) {
    return "需重新生成";
  }
  if (profileSafety(profile).safe) {
    return "安全可应用";
  }
  return labelForStatus(profile?.status);
}

function profileApplicationStatus(profile) {
  return profile?.application_status || {
    total: 0,
    pending: 0,
    approved: 0,
    rejected: 0,
    review_ids: [],
  };
}

function displayProfileJson(profile) {
  return profile?.display_profile_json || {};
}

function profileSummary(profile) {
  const displayJson = displayProfileJson(profile);
  const styleProfile = displayJson.style_profile || {};
  const features = styleProfile.features || {};
  const guidedFeatures = Object.values(features).filter((feature) => {
    const guidance = feature?.guidance;
    return Array.isArray(guidance) ? guidance.length : Boolean(guidance);
  }).length;
  const narrativeCount = Array.isArray(displayJson.narrative_patterns) ? displayJson.narrative_patterns.length : 0;
  const bannedCount = Array.isArray(styleProfile.banned_moves) ? styleProfile.banned_moves.length : 0;
  return `${guidedFeatures} 条文笔特征 · ${narrativeCount} 条叙事模式 · ${bannedCount} 条禁复刻规则`;
}

function profileTitle(profile) {
  const rawTitle = String(profile?.title || profile?.profile_id || "").trim();
  if (/reference profile$/i.test(rawTitle)) {
    return rawTitle.replace(/\s*reference profile$/i, " · 参考画像");
  }
  if (/\sprofile$/i.test(rawTitle)) {
    return rawTitle.replace(/\s*profile$/i, " · 参考画像");
  }
  return rawTitle;
}

function localizeReferenceGuidance(value) {
  const text = String(value || "").trim();
  if (!text || hasChineseText(text)) {
    return text;
  }
  const normalized = text.toLowerCase();
  if (normalized.includes("layered syntax")) {
    return "用分层句法承载对话与内心张力，但只保留抽象句法方法。";
  }
  if (
    normalized.includes("specific phenomenon") ||
    normalized.includes("visible consequence") ||
    normalized.includes("delay explanation")
  ) {
    return "先给具体现象，延后解释，再用可见后果推动场景转向。";
  }
  if (normalized.includes("catalog-like") || normalized.includes("informational exposition")) {
    return "开篇避免目录式介绍，优先用沉浸式叙事建立节奏。";
  }
  if (normalized.includes("chapter hook")) {
    return "用章节钩子制造期待，延后解释并推动场景转向。";
  }
  if (normalized.includes("pressure") || normalized.includes("rhythm")) {
    return "用紧凑压力节拍推进，再安排较长情绪句释放。";
  }
  if (normalized.includes("imagery") || normalized.includes("sensory")) {
    return "用感官意象制造反差，但不复用源文表达。";
  }
  if (normalized.includes("protected expression") || normalized.includes("source") || normalized.includes("names")) {
    return "保留禁复刻边界，避免专名、设定、原句和可识别桥段。";
  }
  return "保留抽象写作技法，不展示英文源描述。";
}

function labelForProfilePreviewKey(key) {
  const normalized = normalizedReferenceCode(key);
  if (normalized === "narrative") {
    return "叙事模式";
  }
  return labelForDimension(normalized);
}

function formatProfilePreviewItem(item) {
  const raw = String(item || "").trim();
  const separatorIndex = raw.indexOf(":");
  if (separatorIndex > 0) {
    const key = raw.slice(0, separatorIndex).trim();
    const value = raw.slice(separatorIndex + 1).trim();
    return `${labelForProfilePreviewKey(key)}：${localizeReferenceGuidance(value)}`;
  }
  return localizeReferenceGuidance(raw);
}

function profilePreviewItems(profile) {
  if (profile && Array.isArray(profile.preview_items)) {
    return profile.preview_items.filter(Boolean).map(formatProfilePreviewItem).slice(0, 4);
  }
  const displayJson = displayProfileJson(profile);
  const styleProfile = displayJson.style_profile || {};
  const features = styleProfile.features || {};
  const featureGuidance = Object.entries(features)
    .flatMap(([key, feature]) => {
      const guidance = feature?.guidance;
      const items = Array.isArray(guidance) ? guidance : guidance ? [guidance] : [];
      return items.map((item) => `${labelForProfilePreviewKey(key)}：${localizeReferenceGuidance(item)}`);
    })
    .slice(0, 3);
  const narrativePatterns = Array.isArray(displayJson.narrative_patterns)
    ? displayJson.narrative_patterns.map((item) => `叙事模式：${localizeReferenceGuidance(item)}`).slice(0, 2)
    : [];
  return [...featureGuidance, ...narrativePatterns].slice(0, 4);
}

function nextDecisionStep() {
  if (referenceLearning.pendingDecisionCount === 0) {
    return "下一步：本轮候选已经清零，点击「继续分析」进入下一轮或生成画像。";
  }
  return `下一步：继续审核剩余 ${referenceLearning.pendingDecisionCount} 张候选卡。`;
}

function applyReviewCount(result) {
  return result?.application_status?.total || result?.reviews?.length || 1;
}

function handleReceiptNavigate(target) {
  if (target?.view) {
    navigate(target.view);
  }
}

async function ensureLoaded() {
  await runFlowAction({
    scopeKey: REFERENCE_LIBRARY_SCOPE,
    actionLabel: "刷新书籍列表",
    runningMessage: "正在刷新参考书列表...",
    successMessage: () => "参考书列表已刷新。",
    nextStep: () => "下一步：选择一本书，或展开导入区添加新书。",
    action: () => referenceLearning.initialize({ force: true }),
  });
}

async function importPath() {
  const result = await runFlowAction({
    scopeKey: REFERENCE_IMPORT_SCOPE,
    actionLabel: "导入参考书",
    runningMessage: "正在读取文件、解析章节并切分片段...",
    successMessage: () => referenceLearning.lastActionMessage || "参考书已导入。",
    nextStep: () => "下一步：点击「启动学习」，让系统创建学习任务。",
    action: () => referenceLearning.importPath(),
  });
  if (result) {
    importExpanded.value = false;
  }
}

async function importUpload() {
  const result = await runFlowAction({
    scopeKey: REFERENCE_IMPORT_SCOPE,
    actionLabel: "上传参考书",
    runningMessage: "正在上传文件、解析章节并切分片段...",
    successMessage: () => referenceLearning.lastActionMessage || "参考书已上传导入。",
    nextStep: () => "下一步：点击「启动学习」，让系统创建学习任务。",
    action: () => referenceLearning.importUpload(),
  });
  if (result) {
    importExpanded.value = false;
  }
}

async function startRun() {
  await runFlowAction({
    scopeKey: REFERENCE_RUN_SCOPE,
    actionLabel: "启动学习",
    runningMessage: "正在创建参考书学习任务...",
    successMessage: () => referenceLearning.lastActionMessage || "学习任务已启动。",
    nextStep: () => "下一步：点击「继续分析」生成第一轮候选卡。",
    action: () => referenceLearning.startRun({ batch_size: 8 }),
  });
}

async function advanceRun() {
  startReferenceLongTaskTimer();
  try {
    await runFlowAction({
      scopeKey: REFERENCE_RUN_SCOPE,
      actionLabel: "继续分析",
      runningMessage: "正在抽样片段并生成候选结论...",
      successMessage: () => referenceLearning.lastActionMessage || "参考书学习已推进。",
      nextStep: (result) => {
        if (result?.profile) {
          return "下一步：在最终画像区选择应用范围，再创建审核项。";
        }
        if (result?.round) {
          return "下一步：审核下方候选卡，批准有价值的结论或拒绝低质量结论。";
        }
        return "下一步：根据当前卡住点继续处理。";
      },
      action: () => referenceLearning.advanceRun(),
    });
  } finally {
    stopReferenceLongTaskTimer();
  }
}

async function approveFinding(finding) {
  const reviewId = reviewIdForFinding(finding);
  await runFlowAction({
    scopeKey: findingReceiptScope(finding),
    actionLabel: approveLabel(finding),
    runningMessage: "正在提交候选卡决策...",
    successMessage: () => referenceLearning.lastActionMessage || "已批准 1 张候选卡。",
    nextStep: nextDecisionStep,
    action: () => referenceLearning.approveFinding(reviewId),
  });
}

async function rejectFinding(finding) {
  const reviewId = reviewIdForFinding(finding);
  await runFlowAction({
    scopeKey: findingReceiptScope(finding),
    actionLabel: rejectLabel(finding),
    runningMessage: "正在提交候选卡决策...",
    successMessage: () => referenceLearning.lastActionMessage || "已拒绝 1 张候选卡。",
    nextStep: nextDecisionStep,
    action: () => referenceLearning.rejectFinding(reviewId, rejectReasons.value[reviewId] || ""),
  });
}

async function applyProfile(profile) {
  await runFlowAction({
    scopeKey: referenceProfileScope(profile),
    actionLabel: "应用到审核",
    runningMessage: "正在创建画像应用审核项...",
    successMessage: (result) => `已创建 ${applyReviewCount(result)} 个应用审核项。`,
    nextStep: () => "下一步：去审核收件箱批准这些应用项，批准后才会进入生成链路。",
    target: { label: "去审核收件箱", view: "review" },
    action: () => referenceLearning.applyProfile(profile.profile_id),
  });
}

function setUploadFile(event) {
  referenceLearning.uploadDraft.file = event.target.files?.[0] || null;
}

function selectBook(bookId) {
  referenceLearning.selectBook(bookId).catch((error) => emit("notice", error.message));
}

function openReviewInbox() {
  navigate("review");
}

function openKnowledgeConsole() {
  navigate("knowledge");
}

onActivated(() => {
  referenceLearning.initialize().catch((error) => emit("notice", error.message));
});

onBeforeUnmount(() => {
  stopReferenceLongTaskTimer();
});
</script>

<template>
  <section class="reference-learning-view" data-testid="reference-learning-view">
    <header class="reference-hero panel">
      <div>
        <div class="eyebrow">参考学习</div>
        <h2>参考书学习</h2>
        <p class="panel-copy">丢入 TXT/MD，系统抽样整本书并把文笔与叙事结构结论送到审核卡。</p>
      </div>
      <div class="reference-coverage" data-testid="reference-coverage">
        <strong data-testid="reference-sample-progress">{{ sampleProgressLabel }}</strong>
        <span>全书抽样进度 · {{ sampleCoveragePercent }}%</span>
        <small>{{ sampleRemainingLabel }} · 技法维度 {{ dimensionCoveragePercent }}%</small>
      </div>
    </header>

    <div v-if="referenceLearning.error" class="panel inline-error">
      <strong>请求失败</strong>
      <p>{{ referenceLearning.error }}</p>
    </div>

    <div class="reference-layout">
      <section class="reference-side reference-secondary">
        <article class="reference-section panel">
          <div class="reference-section-head">
            <div>
              <div class="eyebrow">导入</div>
              <h3>导入参考书</h3>
            </div>
            <div class="reference-import-head-actions">
              <span class="badge">{{ consentLabel }}</span>
              <button
                type="button"
                class="ghost"
                data-testid="reference-import-toggle"
                @click="importExpanded = !importExpanded"
              >
                {{ shouldShowImportForm ? "收起" : "导入新书" }}
              </button>
            </div>
          </div>

          <p v-if="!shouldShowImportForm" class="reference-import-summary">
            导入是低频动作；当前书籍已在下方列表中。需要换书时再展开。
          </p>

          <template v-else>
            <div class="reference-import-tabs" role="tablist" aria-label="参考书导入方式">
              <button
                type="button"
                class="ghost"
                :class="{ active: referenceLearning.importMode === 'path' }"
                @click="referenceLearning.importMode = 'path'"
              >
                本机路径
              </button>
              <button
                type="button"
                class="ghost"
                :class="{ active: referenceLearning.importMode === 'upload' }"
                @click="referenceLearning.importMode = 'upload'"
              >
                TXT/MD 文件
              </button>
            </div>

            <form v-if="referenceLearning.importMode === 'path'" class="reference-form" @submit.prevent="importPath">
              <label>
                <span>文件路径</span>
                <input
                  v-model="referenceLearning.pathDraft.file_path"
                  class="control-input"
                  data-testid="reference-import-path"
                  placeholder="E:/books/reference.md"
                />
              </label>
              <label>
                <span>标题</span>
                <input v-model="referenceLearning.pathDraft.title" class="control-input" />
              </label>
              <label>
                <span>作者标记</span>
                <input v-model="referenceLearning.pathDraft.author_label" class="control-input" />
              </label>
              <label>
                <span>云端处理确认</span>
                <select v-model="referenceLearning.pathDraft.cloud_policy" class="control-input">
                  <option value="allow_full_cloud">允许云端处理全文</option>
                  <option value="segments_only">仅允许云端处理抽样片段</option>
                  <option value="local_only">仅本地处理</option>
                </select>
              </label>
              <button
                type="submit"
                data-testid="reference-import-submit"
                :disabled="referenceLearning.actionId === 'import-path'"
              >
                {{ running(REFERENCE_IMPORT_SCOPE) ? "导入中..." : "导入路径" }}
              </button>
            </form>

            <form v-else class="reference-form" @submit.prevent="importUpload">
              <label>
                <span>文件</span>
                <input class="control-input" type="file" accept=".txt,.md,text/plain,text/markdown" @change="setUploadFile" />
              </label>
              <label>
                <span>标题</span>
                <input v-model="referenceLearning.uploadDraft.title" class="control-input" />
              </label>
              <label>
                <span>作者标记</span>
                <input v-model="referenceLearning.uploadDraft.author_label" class="control-input" />
              </label>
              <label>
                <span>云端处理确认</span>
                <select v-model="referenceLearning.uploadDraft.cloud_policy" class="control-input">
                  <option value="allow_full_cloud">允许云端处理全文</option>
                  <option value="segments_only">仅允许云端处理抽样片段</option>
                  <option value="local_only">仅本地处理</option>
                </select>
              </label>
              <button type="submit" :disabled="referenceLearning.actionId === 'import-upload'">
                {{ running(REFERENCE_IMPORT_SCOPE) ? "上传中..." : "上传导入" }}
              </button>
            </form>
          </template>
          <FlowActionReceipt compact :receipt="receipt(REFERENCE_IMPORT_SCOPE)" />
        </article>

        <article class="reference-section panel">
          <div class="reference-section-head">
            <div>
              <div class="eyebrow">书库</div>
              <h3>书籍列表</h3>
            </div>
            <button type="button" class="ghost" :disabled="running(REFERENCE_LIBRARY_SCOPE)" @click="ensureLoaded">
              {{ running(REFERENCE_LIBRARY_SCOPE) ? "刷新中..." : "刷新" }}
            </button>
          </div>
          <FlowActionReceipt compact :receipt="receipt(REFERENCE_LIBRARY_SCOPE)" />

          <div v-if="referenceLearning.books.length" class="reference-book-list" data-testid="reference-book-list">
            <button
              v-for="book in referenceLearning.books"
              :key="book.book_id"
              type="button"
              class="reference-book-row"
              :class="{ active: book.book_id === referenceLearning.selectedBookId }"
              @click="selectBook(book.book_id)"
            >
              <strong>{{ book.title || book.book_id }}</strong>
              <span>{{ bookProgressLabel(book) }}</span>
            </button>
          </div>
          <p v-else class="muted">暂无参考书。</p>
        </article>
      </section>

      <section class="reference-main">
        <article class="reference-section panel">
          <div class="reference-workbench-head">
            <div>
              <div class="eyebrow">学习任务</div>
              <h3>{{ selectedBook?.title || "未选择参考书" }}</h3>
              <p class="muted">
                {{ selectedBook?.total_chars || 0 }} 字 · {{ selectedBook?.total_segments || 0 }} 段 · {{ consentLabel }}
              </p>
            </div>
            <div class="actions">
              <button
                type="button"
                data-testid="reference-start-run"
                :disabled="!canStart"
                :title="startRunDisabledReason"
                @click="startRun"
              >
                {{ referenceLearning.actionId === "start-run" ? "启动中..." : startRunLabel }}
              </button>
              <button
                type="button"
                class="ghost"
                data-testid="reference-advance-run"
                :disabled="!canAdvance"
                :title="advanceRunDisabledReason"
                @click="advanceRun"
              >
                {{ advanceRunLabel }}
              </button>
            </div>
          </div>
          <p v-if="advanceRunDisabledReason" class="muted reference-control-hint">
            {{ advanceRunDisabledReason }}
          </p>
          <FlowActionReceipt :receipt="receipt(REFERENCE_RUN_SCOPE)" />
          <p
            v-if="referenceLongTaskSeconds > 0 || referenceLearning.actionId === 'advance-run'"
            class="reference-long-task muted"
            data-testid="reference-long-task"
          >
            真实模型分析可能需要数分钟，已等待 {{ referenceLongTaskSeconds }} 秒；请不要重复点击继续分析。
          </p>

          <div class="reference-flow" aria-label="reference learning workflow">
            <span
              v-for="step in flowSteps"
              :key="step.key"
              class="reference-flow-step"
              :class="{ active: flowStage === step.key, done: step.done }"
            >
              {{ step.label }}
            </span>
            <p class="reference-action-hint">{{ flowHint }}</p>
          </div>

          <div class="reference-next-action" data-testid="reference-next-action">
            <div>
              <span>当前卡住点</span>
              <strong>{{ currentTask }}</strong>
            </div>
            <div>
              <span>下一步</span>
              <strong>{{ nextAction }}</strong>
            </div>
          </div>

          <div class="reference-metrics">
            <div>
              <strong>{{ approvedMetric }}</strong>
              <span>已批准</span>
            </div>
            <div>
              <strong>{{ pendingMetric }}</strong>
              <span>待审核</span>
            </div>
            <div>
              <strong>{{ rejectedMetric }}</strong>
              <span>已拒绝</span>
            </div>
            <div>
              <strong>{{ profiles.length }}</strong>
              <span>画像</span>
            </div>
          </div>

          <div class="reference-chip-row" v-if="coveredDimensions.length || coveredFindingTypes.length">
            <span v-for="dimension in coveredDimensions" :key="`dimension-${dimension}`" class="badge ghost">
              {{ labelForDimension(dimension) }}
            </span>
            <span v-for="type in coveredFindingTypes" :key="`type-${type}`" class="badge ghost">
              {{ labelForFindingType(type) }}
            </span>
          </div>
        </article>

        <article class="reference-section panel">
          <div class="reference-section-head">
            <div>
              <div class="eyebrow">审核卡</div>
              <h3>候选审核卡</h3>
            </div>
            <span class="badge">{{ referenceLearning.pendingDecisionCount }} 待决策</span>
          </div>

          <ProgressiveList
            :items="findings"
            :initial-count="8"
            :batch-size="8"
            :threshold="8"
            test-id="reference-finding-list"
          >
            <template #default="{ items }">
              <div v-if="items.length" class="reference-finding-grid">
                <article
                  v-for="finding in items"
                  :key="finding.finding_id"
                  class="reference-finding-card"
                  :data-testid="`reference-finding-${finding.finding_id}`"
                >
                  <div class="reference-card-top">
                    <div>
                      <span class="badge">{{ labelForFindingType(finding.finding_type) }}</span>
                      <span class="badge ghost">{{ labelForDimension(finding.dimension) }}</span>
                    </div>
                    <span class="badge" :class="`status-${decisionStatus(finding)}`">
                      {{ labelForStatus(decisionStatus(finding)) }}
                    </span>
                  </div>

                  <p class="reference-source">
                    {{ findingSourceLabel(finding) }}
                    <span class="source-hidden">{{ sourceVisibilityLabel(finding) }}</span>
                    <span v-if="findingSafetyLabel(finding)" class="source-hidden">{{ findingSafetyLabel(finding) }}</span>
                  </p>
                  <p class="reference-model-trace">
                    <span>模型来源：{{ modelTraceLabel(finding.model_trace) }}</span>
                    <span v-if="modelTraceQuality(finding.model_trace)">{{ modelTraceQuality(finding.model_trace) }}</span>
                  </p>
                  <p class="reference-summary">{{ displayFindingSummary(finding) }}</p>
                  <p class="reference-risk">{{ findingRisk(finding) }}</p>
                  <button
                    v-if="segmentIdForFinding(finding)"
                    type="button"
                    class="ghost reference-excerpt-toggle"
                    :data-testid="`reference-toggle-excerpt-${segmentIdForFinding(finding)}`"
                    @click="toggleFindingExcerpt(finding)"
                  >
                    {{ isExcerptExpanded(finding) ? "收起原文片段" : "查看原文片段" }}
                  </button>
                  <div
                    v-if="isExcerptExpanded(finding)"
                    class="reference-source-excerpt"
                    :data-testid="`reference-source-excerpt-${segmentIdForFinding(finding)}`"
                  >
                    <p v-if="isExcerptLoading(finding)" class="muted">正在读取本地原文片段...</p>
                    <template v-else-if="excerptForFinding(finding)">
                      <strong>{{ excerptForFinding(finding).display_label }}</strong>
                      <p>{{ excerptForFinding(finding).excerpt }}</p>
                      <small>{{ excerptForFinding(finding).safety_note }}</small>
                    </template>
                  </div>

                  <div class="reference-card-actions">
                    <label class="reference-reject-field">
                      <input
                        v-model="rejectReasons[reviewIdForFinding(finding)]"
                        class="control-input"
                        placeholder="可选原因"
                        :disabled="!canRejectFinding(finding)"
                      />
                      <small>{{ rejectionHint(finding) }}</small>
                    </label>
                    <button
                      type="button"
                      class="reference-reject-button"
                      :class="{ 'is-reversal': decisionStatus(finding) === 'approved' }"
                      :data-testid="`reference-reject-${reviewIdForFinding(finding)}`"
                      :disabled="!canRejectFinding(finding)"
                      @click="rejectFinding(finding)"
                    >
                      {{ rejectLabel(finding) }}
                    </button>
                    <button
                      type="button"
                      :data-testid="`reference-approve-${reviewIdForFinding(finding)}`"
                      :disabled="!canApproveFinding(finding)"
                      @click="approveFinding(finding)"
                    >
                      {{ approveLabel(finding) }}
                    </button>
                  </div>
                  <FlowActionReceipt compact :receipt="receipt(findingReceiptScope(finding))" />
                </article>
              </div>
              <p v-else class="muted">当前没有候选卡。</p>
            </template>
          </ProgressiveList>
        </article>

        <article class="reference-section panel">
          <div class="reference-section-head">
            <div>
              <div class="eyebrow">画像</div>
              <h3>最终画像</h3>
            </div>
            <div class="actions">
              <button type="button" class="ghost" @click="openReviewInbox">审核收件箱</button>
              <button type="button" class="ghost" @click="openKnowledgeConsole">知识控制台</button>
            </div>
          </div>

          <div class="reference-apply-controls">
            <label>
              <span>应用范围</span>
              <select v-model="referenceLearning.applyDraft.scope" class="control-input" data-testid="reference-apply-scope">
                <option value="global">全局</option>
                <option value="chapter">章节</option>
                <option value="scene">场景</option>
              </select>
            </label>
            <label>
              <span>范围 ID</span>
              <input
                v-model="referenceLearning.applyDraft.scope_ref_id"
                class="control-input"
                data-testid="reference-apply-scope-ref"
                :placeholder="referenceLearning.applyDraft.scope === 'global' ? 'global' : 'CH001 或 CH001_SC01'"
                :disabled="referenceLearning.applyDraft.scope === 'global'"
              />
            </label>
          </div>

          <div v-if="profiles.length" class="reference-profile-filter" data-testid="reference-profile-filter">
            <button
              type="button"
              class="ghost"
              data-testid="reference-profile-filter-ready"
              :class="{ active: profileVisibilityFilter === 'ready' }"
              @click="profileVisibilityFilter = 'ready'"
            >
              仅安全可用 {{ readyProfiles.length }}
            </button>
            <button
              type="button"
              class="ghost"
              data-testid="reference-profile-filter-all"
              :class="{ active: profileVisibilityFilter === 'all' }"
              @click="profileVisibilityFilter = 'all'"
            >
              全部画像 {{ profiles.length }}
            </button>
          </div>

          <div v-if="visibleProfiles.length" class="reference-profile-list">
            <article
              v-for="profile in visibleProfiles"
              :key="profile.profile_id"
              class="reference-profile-card"
              :data-testid="`reference-profile-${profile.profile_id}`"
            >
              <div class="reference-card-top">
                <div>
                  <strong>{{ profileTitle(profile) }}</strong>
                  <p class="muted">
                    {{ profileStatusLabel(profile) }} · {{ profile.source_finding_ids?.length || 0 }} 条来源结论
                  </p>
                </div>
                <button
                  type="button"
                  :data-testid="`reference-apply-${profile.profile_id}`"
                  :disabled="!canApplyProfile(profile)"
                  :title="isProfileStale(profile) ? '审核决策已变化，请继续分析重新生成画像。' : ''"
                  @click="applyProfile(profile)"
                >
                  {{ running(referenceProfileScope(profile)) ? "应用中..." : "应用到审核" }}
                </button>
              </div>
              <div class="reference-profile-summary">
                <span class="badge" :class="{ 'status-rejected': isProfileStale(profile), 'status-approved': !isProfileStale(profile) }">
                  {{ profileStatusLabel(profile) }}
                </span>
                <span class="badge ghost">已清洗 {{ profileSafety(profile).stripped_count || 0 }} 处来源证据</span>
                <span v-if="profileSafety(profile).blocked_markers?.length" class="badge status-rejected">
                  阻断 {{ profileSafety(profile).blocked_markers.length }} 个来源标记
                </span>
                <div class="reference-model-trace">
                  <strong>模型来源：{{ modelTraceLabel(profile.model_trace) }}</strong>
                  <span v-if="modelTraceQuality(profile.model_trace)">{{ modelTraceQuality(profile.model_trace) }}</span>
                  <span v-if="modelTraceNode(profile.model_trace)">{{ modelTraceNode(profile.model_trace) }}</span>
                  <small>{{ modelCapabilityHint(profile.model_trace) }}</small>
                </div>
                <div
                  v-if="profileApplicationStatus(profile).total"
                  class="reference-application-status"
                  data-testid="reference-profile-application-status"
                >
                  <strong>
                    已创建 {{ profileApplicationStatus(profile).total }} 个应用审核项，等待审核收件箱批准
                  </strong>
                  <span>
                    待审 {{ profileApplicationStatus(profile).pending }} · 已批准 {{ profileApplicationStatus(profile).approved }} · 已拒绝 {{ profileApplicationStatus(profile).rejected }}
                  </span>
                  <button type="button" class="ghost" @click="openReviewInbox">去审核收件箱</button>
                </div>
                <p>{{ profileSummary(profile) }}</p>
                <p v-if="isProfileStale(profile)" class="reference-risk">
                  审核决策已变化，请继续分析重新生成画像；过期画像不会进入审核或生成链路。
                </p>
                <ul v-if="profilePreviewItems(profile).length" class="reference-profile-preview">
                  <li v-for="item in profilePreviewItems(profile)" :key="item">{{ item }}</li>
                </ul>
              </div>
              <FlowActionReceipt
                data-testid="reference-profile-apply-receipt"
                :receipt="referenceProfileReceipt(profile)"
                :on-navigate="handleReceiptNavigate"
              />
              <pre v-if="false" class="reference-profile-json">{{ JSON.stringify(profile.profile_json || {}, null, 2) }}</pre>
            </article>
          </div>
          <p v-else-if="profiles.length" class="muted">
            当前没有 ready + safe 画像；切到“全部画像”可查看过期或被阻断的画像诊断。
          </p>
          <p v-else class="muted">覆盖度达标后会生成独立参考画像。</p>
        </article>
      </section>
    </div>
  </section>
</template>
