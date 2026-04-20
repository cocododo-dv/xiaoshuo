<script setup>
import { computed, onActivated, ref } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import ProgressiveList from "../components/ProgressiveList.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useReferenceLearningStore } from "../stores/referenceLearning";

const emit = defineEmits(["notice"]);

const referenceLearning = useReferenceLearningStore();
const { navigate } = useShellRouter();
const rejectReasons = ref({});
const importExpanded = ref(false);
const profileVisibilityFilter = ref("ready");
const { receipt, running, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const REFERENCE_IMPORT_SCOPE = "reference:import";
const REFERENCE_RUN_SCOPE = "reference:run";
const REFERENCE_LIBRARY_SCOPE = "reference:library";

const selectedBook = computed(() => referenceLearning.detail?.book || referenceLearning.selectedBook || null);
const coverage = computed(() => referenceLearning.coverage || {});
const coveragePercent = computed(() => Math.round(Math.max(0, Math.min(1, Number(coverage.value.coverage_score || 0))) * 100));
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
const canAdvance = computed(() =>
  Boolean(
    referenceLearning.selectedBookId &&
      runId.value &&
      referenceLearning.pendingDecisionCount === 0 &&
      !readyProfiles.value.length &&
      !referenceLearning.actionId,
  ),
);
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
    { key: "apply", label: "手动应用", done: false },
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
  if (staleProfiles.value.length && !readyProfiles.value.length) {
    return "画像已过期：审核决策变化后，需要继续分析重新生成安全画像。";
  }
  if (readyProfiles.value.length) {
    return "画像已就绪；应用时只会创建审核项，不会直接污染全局。";
  }
  return "继续分析会推进到下一轮候选卡，覆盖度达标后生成画像。";
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
  if (staleProfiles.value.length && !readyProfiles.value.length) {
    return "点击「继续分析」重新生成画像；过期画像不会进入审核或生成链路。";
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

function profilePreviewItems(profile) {
  if (profile && Array.isArray(profile.preview_items)) {
    return profile.preview_items.filter(Boolean).slice(0, 4);
  }
  const displayJson = displayProfileJson(profile);
  const styleProfile = displayJson.style_profile || {};
  const features = styleProfile.features || {};
  const featureGuidance = Object.entries(features)
    .flatMap(([key, feature]) => {
      const guidance = feature?.guidance;
      const items = Array.isArray(guidance) ? guidance : guidance ? [guidance] : [];
      return items.map((item) => `${key}: ${item}`);
    })
    .slice(0, 3);
  const narrativePatterns = Array.isArray(displayJson.narrative_patterns)
    ? displayJson.narrative_patterns.map((item) => `narrative: ${item}`).slice(0, 2)
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
  return result?.reviews?.length || 1;
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
</script>

<template>
  <section class="reference-learning-view" data-testid="reference-learning-view">
    <header class="reference-hero panel">
      <div>
        <div class="eyebrow">Reference Learning</div>
        <h2>参考书学习</h2>
        <p class="panel-copy">丢入 TXT/MD，系统抽样整本书并把文笔与叙事结构结论送到审核卡。</p>
      </div>
      <div class="reference-coverage" data-testid="reference-coverage">
        <strong>{{ coveragePercent }}%</strong>
        <span>覆盖度</span>
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
              <div class="eyebrow">Import</div>
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
              <div class="eyebrow">Library</div>
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
              <div class="eyebrow">Learning Run</div>
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
                @click="advanceRun"
              >
                {{ referenceLearning.actionId === "advance-run" ? "分析中..." : "继续分析" }}
              </button>
            </div>
          </div>
          <FlowActionReceipt :receipt="receipt(REFERENCE_RUN_SCOPE)" />

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
              {{ dimension }}
            </span>
            <span v-for="type in coveredFindingTypes" :key="`type-${type}`" class="badge ghost">
              {{ labelForFindingType(type) }}
            </span>
          </div>
        </article>

        <article class="reference-section panel">
          <div class="reference-section-head">
            <div>
              <div class="eyebrow">Decision Cards</div>
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
                      <span class="badge ghost">{{ finding.dimension || "-" }}</span>
                    </div>
                    <span class="badge" :class="`status-${decisionStatus(finding)}`">
                      {{ labelForStatus(decisionStatus(finding)) }}
                    </span>
                  </div>

                  <p class="reference-source">
                    {{ finding.source_segment?.chapter_hint || finding.source_segment?.segment_kind || "片段" }}
                    <span v-if="finding.source_excerpt_hidden" class="source-hidden">source excerpt hidden</span>
                    <span v-else>· {{ finding.evidence_preview || "abstract summary" }}</span>
                  </p>
                  <p class="reference-summary">{{ finding.summary }}</p>
                  <p class="reference-risk">{{ findingRisk(finding) }}</p>

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
              <div class="eyebrow">Profiles</div>
              <h3>最终画像</h3>
            </div>
            <div class="actions">
              <button type="button" class="ghost" @click="openReviewInbox">Review Inbox</button>
              <button type="button" class="ghost" @click="openKnowledgeConsole">Knowledge Console</button>
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
              仅 safe/ready {{ readyProfiles.length }}
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
                  <strong>{{ profile.title || profile.profile_id }}</strong>
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
