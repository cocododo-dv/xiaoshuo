<script setup>
import { computed, onActivated, onMounted, ref } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import PanelShell from "../components/PanelShell.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useWriterDeepDeskStore } from "../stores/writerDeepDesk";

const emit = defineEmits(["notice"]);

const desk = useWriterDeepDeskStore();
const { navigate } = useShellRouter();
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const REVIEW_SCOPE = "deepdesk:review";
const PATCH_SCOPE = "deepdesk:patch";
const DECISION_SCOPE = "deepdesk:decision";
const DRAFT_SCOPE = "deepdesk:draft";
const STRUCTURE_SCOPE = "deepdesk:structure";
const AI_DRAFT_SCOPE = "deepdesk:ai-draft";
const AUTO_REWRITE_SCOPE = "deepdesk:auto-rewrite";

const issueDimension = ref("");

const chapters = computed(() => desk.chapters || []);
const scenes = computed(() => desk.availableScenes || []);
const findings = computed(() => desk.findings || []);
const lensEvaluations = computed(() => desk.lensEvaluations || []);
const candidates = computed(() => desk.candidateRows || []);
const structureCandidates = computed(() => desk.structureCandidateRows || []);
const draftProposals = computed(() => desk.draftProposalRows || []);
const inlineQualitySpanFindings = computed(() => desk.inlineQualitySpanFindings || []);
const longformPressure = computed(() => desk.longformPressure || []);
const workProfile = computed(() => desk.workProfile || null);
const dailyFocus = computed(() => desk.dailyFocus || []);
const judgmentLayers = computed(
  () =>
    desk.judgmentLayers || {
      blocking: [],
      revision: [],
      profile_mismatch: [],
      taste: [],
    },
);
const judgmentLayerBuckets = computed(() => [
  { key: "blocking", label: "blocking", items: judgmentLayers.value.blocking || [] },
  { key: "revision", label: "revision", items: judgmentLayers.value.revision || [] },
  { key: "profile_mismatch", label: "profile_mismatch", items: judgmentLayers.value.profile_mismatch || [] },
  { key: "taste", label: "taste", items: judgmentLayers.value.taste || [] },
]);
const draftEvents = computed(() => desk.draftEvents || []);
const preference = computed(() => desk.preferenceProfile || null);
const profileSummary = computed(() => preference.value?.summary || {});
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
  { key: "irreversible_change", label: "不可逆变化", value: qualityContractPayload.value.irreversible_change },
  { key: "ending_action", label: "结尾动作", value: qualityContractPayload.value.ending_action },
  { key: "next_scene_pull", label: "下一场牵引", value: qualityContractPayload.value.next_scene_pull },
]);
const autoRewriteRun = computed(() => desk.autoRewriteRun || null);
const qualityPromotion = computed(() => desk.qualityState?.promotion || {});
const qualityPromotionBlockers = computed(() => desk.qualityPromotionBlockers || []);
const workProfileMeta = computed(() => {
  const profile = workProfile.value || {};
  const config = profile.profile_json || {};
  return [
    profile.profile_key,
    config.pacing_preference || config.pacing,
    config.language_density,
    config.ending_drive_policy,
  ].filter(Boolean).join(" / ") || "profile_default";
});
const selectedExcerpt = computed({
  get: () => desk.selectedExcerpt,
  set: (value) => desk.setSelectedExcerpt(value),
});
const draftContent = computed({
  get: () => desk.draftContent,
  set: (value) => desk.setDraftContent(value),
});

const selectedIssue = computed(() => {
  if (issueDimension.value) {
    return issueDimension.value;
  }
  return findings.value[0]?.dimension || "dialogue_subtext";
});

const scoreText = computed(() => {
  const score = desk.latestEvaluation?.overall_score;
  return score === null || score === undefined ? "未诊断" : `${Math.round(Number(score) * 100)} 分`;
});

const patchExcerpt = computed(() => desk.excerptForPatch || "");
const excerptPlaceholder = computed(() => "选中或粘贴一段作者稿正文，再生成局部候选。");
const currentObjectLabel = computed(() => (desk.draftMode === "scene" ? desk.selectedSceneId || "未选择场景" : desk.selectedChapterId || "未选择章节"));
const finalAggregateLabel = computed(() =>
  desk.detail?.aggregate?.row_id ? `ChapterMemory ${desk.detail.aggregate.row_id}` : "尚未生成最终聚合稿",
);
const runtimeLayerLabel = computed(() => {
  if (desk.draftMode === "scene") {
    return desk.runtimeLayerText || "该场景暂无运行终稿";
  }
  return desk.currentSourceRef || "暂无运行终稿来源";
});
const draftStatusLabel = computed(() => {
  if (!desk.authorDraft) {
    return "尚未创建";
  }
  const dirty = desk.draftDirty ? "有未保存修改" : "已保存";
  return `${dirty} / 第 ${desk.draftRevisionNo} 版`;
});

function severityLabel(value) {
  return {
    blocking: "阻断",
    revision: "修订",
    taste: "审美",
    ignore_ok: "可忽略",
  }[value] || value || "未分级";
}

function lensLabel(value) {
  return {
    story: "故事",
    character: "人物",
    prose: "语言",
    reader: "读者",
    theme: "主题",
    aggregate: "总评",
  }[value] || value || "总评";
}

function statusLabel(value) {
  return {
    not_run: "未运行",
    reviewed: "已诊断",
    candidate: "候选",
    accepted: "已采纳",
    rejected: "已拒绝",
    pending: "待决定",
    draft: "草稿",
    approved: "已审核",
    current: "当前",
    superseded: "已替换",
  }[value] || value || "-";
}

function autoRewriteStatusLabel(value) {
  return {
    candidate_ready: "候选可审",
    promoted: "已晋级",
    rolled_back: "已回滚",
    human_review_required: "转人工",
    diagnose_only: "仅诊断",
    failed: "失败",
  }[value] || value || "未运行";
}

function proposalTypeLabel(value) {
  return {
    structure_candidate: "structure candidate",
    passage_candidate: "passage candidate",
    language_candidate: "language candidate",
    scene_draft: "scene draft",
    chapter_draft: "chapter draft",
  }[value] || value || "draft";
}

function focusTitle(item) {
  return item?.title || item?.issue || item?.dimension || item?.card_type || "focus";
}

function candidateCategoryLabel(value) {
  return {
    dialogue_rewrite: "对白改写",
    action_replace: "动作替换",
    ending_pressure: "结尾重压",
    information_reorder: "信息释放重排",
    de_model_voice: "去模型腔",
    local_patch: "局部深改",
  }[value] || "局部深改";
}

function candidateMetaLine(candidate) {
  const range = candidate?.target_range;
  const rangeText = range?.unit ? `${range.unit}:${range.start ?? "-"}-${range.end ?? "-"}` : "";
  return [
    candidateCategoryLabel(candidate?.candidate_category),
    candidate?.revision_strategy,
    rangeText,
  ].filter(Boolean).join(" · ");
}

function candidateTagLine(candidate) {
  const tags = Array.isArray(candidate?.preference_tags) ? candidate.preference_tags.filter(Boolean) : [];
  return tags.length ? `偏好标签：${tags.join(" / ")}` : "偏好标签：暂无";
}

function longformCardTypeLabel(value) {
  return {
    character_arc_gap: "人物弧线断点",
    foreshadow_debt: "伏笔债务",
    foreshadowing_debt: "伏笔债务",
    promise_without_payoff: "章节承诺未兑现",
    chapter_promise_unpaid: "章节承诺未兑现",
    motif_reuse: "意象复用",
    information_release_gap: "信息释放断点",
  }[value] || value || "长篇压力";
}

function longformSeverityLabel(value) {
  return {
    critical: "高压",
    major: "中压",
    minor: "低压",
    info: "提示",
  }[value] || value || "未分级";
}

function longformRecommendation(card) {
  const recommendation = card?.recommendation || {};
  if (typeof recommendation === "string") {
    return recommendation;
  }
  return recommendation.summary || recommendation.action || recommendation.note || "等待人工判断下一步。";
}

function eventTypeLabel(value) {
  return {
    created: "创建作者稿",
    edited: "保存版本",
    candidate_inserted: "候选放入稿件",
    candidate_saved: "候选保存确认",
    candidate_rejected: "拒绝候选",
    proposal_applied: "应用 AI 草稿提案",
    proposal_rejected: "拒绝 AI 草稿提案",
    structure_extracted: "结构提取",
  }[value] || value || "稿件事件";
}

function eventNote(event) {
  return event?.note || event?.patch_id || event?.option_id || event?.actor_ref || "";
}

function scoreLabel(value) {
  return value === null || value === undefined ? "-" : `${Math.round(Number(value) * 100)} 分`;
}

function structureBrief(candidate) {
  return candidate?.candidate_brief || candidate?.candidate_brief_json || {};
}

function uncertaintyNotes(candidate) {
  const notes = candidate?.uncertainty_notes || candidate?.uncertainty_notes_json || [];
  return Array.isArray(notes) ? notes.filter(Boolean) : [];
}

function structureFieldRows(candidate) {
  const brief = structureBrief(candidate);
  const fields =
    candidate?.object_type === "chapter"
      ? [
          ["core_promise", "核心承诺"],
          ["plot_movement", "主线推进"],
          ["character_shift", "人物变化"],
          ["chapter_question", "章节问题"],
          ["ending_aftertaste", "结尾余味"],
          ["escalation_path", "升级路径"],
          ["reveal_or_reversal", "揭示/反转"],
          ["ending_question", "结尾问题"],
        ]
      : [
          ["character_desire", "欲望"],
          ["obstacle", "阻碍"],
          ["stakes", "代价"],
          ["emotional_turn", "转折"],
          ["new_information", "信息释放"],
          ["irreversible_change", "结尾动作"],
          ["reader_question", "读者问题"],
          ["choice_under_pressure", "选择压力"],
        ];
  return fields.map(([key, label]) => ({
    key,
    label,
    value: brief[key] || "未确定",
  }));
}

function candidateNote(candidate) {
  const lines = structureFieldRows(candidate).map((field) => `${field.label}: ${field.value}`);
  const notes = uncertaintyNotes(candidate);
  if (notes.length) {
    lines.push(`不确定项: ${notes.join(" / ")}`);
  }
  if (candidate?.rationale) {
    lines.push(`判断依据: ${candidate.rationale}`);
  }
  return lines.join("\n");
}

async function ensureLoaded(force = false) {
  try {
    await desk.ensureLoaded({ force });
  } catch (error) {
    emit("notice", error.message);
  }
}

async function selectChapter(chapterId) {
  try {
    await desk.selectChapter(chapterId);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function selectDraftMode(mode) {
  try {
    await desk.setDraftMode(mode);
  } catch (error) {
    emit("notice", error.message);
  }
}

function selectDeskMode(mode) {
  desk.setDeskMode(mode);
}

function selectDeskStage(stage) {
  desk.setDeskStage(stage);
}

async function runAiDraftToAuthorDraft() {
  await runFlowAction({
    scopeKey: AI_DRAFT_SCOPE,
    actionLabel: "AI 起草",
    runningMessage: "正在运行当前场景，并把运行终稿转成可改的作者稿。",
    successMessage: (message) => message,
    nextStep: "现在可以在作者稿里人工改写；运行终稿和聚合稿保持独立。",
    action: () => desk.runAiDraftToAuthorDraft(),
  });
}

async function generateDraftProposal() {
  await runFlowAction({
    scopeKey: AI_DRAFT_SCOPE,
    actionLabel: "AI 草稿提案",
    runningMessage: "正在生成可比较的 AI 草稿提案；作者稿、运行终稿和章节聚合稿都不会被覆盖。",
    successMessage: (message) => message,
    nextStep: "先比较提案，再选择整段替换、追加到当前稿、作为新版本，或拒绝并记录原因。",
    action: () =>
      desk.generateDraftProposal({
        proposal_type: desk.draftObjectType === "scene" ? "scene_draft" : "chapter_draft",
      }),
  });
}

async function generateDraftProposalSet() {
  await runFlowAction({
    scopeKey: AI_DRAFT_SCOPE,
    actionLabel: "proposal triad",
    runningMessage: "Generating structure, passage, and language candidates for author choice.",
    successMessage: (message) => message,
    nextStep: "Compare the three lanes, then apply, append, make a new version, or reject with a reason.",
    action: () => desk.generateDraftProposalSet({ instruction: "" }),
  });
}

async function applyDraftProposal(proposal, applyMode) {
  await runFlowAction({
    scopeKey: AI_DRAFT_SCOPE,
    actionLabel: "应用 AI 草稿提案",
    runningMessage: "正在把提案写成作者稿的新版本；运行终稿和章节聚合稿保持不变。",
    successMessage: (message) => message,
    nextStep: "继续人工改写并保存作者稿，或运行深改诊断检查新版本的风险。",
    action: () =>
      desk.applyDraftProposal(proposal, {
        apply_mode: applyMode,
        note: `apply proposal as ${applyMode}`,
      }),
  });
}

async function rejectDraftProposal(proposal) {
  await runFlowAction({
    scopeKey: AI_DRAFT_SCOPE,
    actionLabel: "拒绝 AI 草稿提案",
    runningMessage: "正在记录拒绝原因；这会沉淀为作者偏好草稿，但不会进入运行提示。",
    successMessage: (message) => message,
    nextStep: "可以重新生成提案，或回到作者稿里直接改写。",
    action: () =>
      desk.rejectDraftProposal(proposal, {
        note: "kept current author draft",
      }),
  });
}

async function selectScene(event) {
  try {
    await desk.selectSceneDraft(event.target.value);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function refreshDesk() {
  await ensureLoaded(true);
}

async function saveDraft() {
  await runFlowAction({
    scopeKey: DRAFT_SCOPE,
    actionLabel: "保存作者稿",
    runningMessage: "正在保存作者稿版本，并记录这次作者层改动。",
    successMessage: (message) => message,
    nextStep: "作者稿已保存；运行终稿与最终聚合稿保持不变。",
    action: () => desk.saveAuthorDraft(),
  });
}

async function ensureBlankDraft() {
  await runFlowAction({
    scopeKey: DRAFT_SCOPE,
    actionLabel: "创建空白作者稿",
    runningMessage: "正在准备一份独立作者稿；没有运行终稿时也可以直接开始写。",
    successMessage: () => "空白作者稿已准备好。",
    nextStep: "现在可以在正文编辑器里自由写作，后续再反向提取结构候选。",
    action: () => desk.ensureAuthorDraft(),
  });
}

async function extractAuthorStructure() {
  await runFlowAction({
    scopeKey: STRUCTURE_SCOPE,
    actionLabel: "反向提取戏剧卡",
    runningMessage: "正在从当前作者稿反向理解欲望、阻碍、代价、转折和读者问题。",
    successMessage: (message) => message,
    nextStep: "结构候选只进入候选栏；点击应用后才会更新章节或场景的 writer brief。",
    action: () => desk.extractAuthorStructure(),
  });
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

async function applyStructureCandidate(candidate) {
  await runFlowAction({
    scopeKey: STRUCTURE_SCOPE,
    actionLabel: "应用结构候选",
    runningMessage: "正在把结构候选写入对应戏剧卡的 writer brief，正文和运行终稿保持不变。",
    successMessage: (message) => message,
    nextStep: "作者工作台和长篇控制相关视图会在重新进入或刷新后读取新的戏剧卡候选内容。",
    action: () => desk.applyStructureCandidate(candidate),
  });
}

async function rejectStructureCandidate(candidate) {
  await runFlowAction({
    scopeKey: STRUCTURE_SCOPE,
    actionLabel: "拒绝结构候选",
    runningMessage: "正在记录这条结构候选的拒绝决定。",
    successMessage: (message) => message,
    nextStep: "被拒绝的候选不会进入章节或场景卡，也不会影响后续生成链路。",
    action: () => desk.rejectStructureCandidate(candidate),
  });
}

async function copyStructureCandidateNote(candidate) {
  const note = candidateNote(candidate);
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(note);
  }
  selectedExcerpt.value = note;
  emit("notice", "结构候选已复制为备注。");
}

async function createPatchCandidate() {
  await runFlowAction({
    scopeKey: PATCH_SCOPE,
    actionLabel: "生成局部候选",
    runningMessage: "正在为选中片段生成 2 到 3 个可比较版本。",
    successMessage: (message) => message,
    nextStep: "候选只进入右侧账本；点击放入稿件后也只改作者稿编辑器。",
    action: () =>
      desk.createPassagePatchCandidate({
        issue_dimension: selectedIssue.value,
        source_excerpt: patchExcerpt.value,
      }),
  });
}

async function insertCandidate(candidate, option = null) {
  await runFlowAction({
    scopeKey: DECISION_SCOPE,
    actionLabel: "放入稿件",
    runningMessage: "正在把候选放入作者稿编辑器，尚不覆盖运行终稿。",
    successMessage: (message) => message,
    nextStep: "确认全文上下文后点击保存作者稿，候选才会标记为已采纳。",
    action: () => desk.insertCandidateOption(candidate, option),
  });
}

async function rejectCandidate(candidate) {
  await runFlowAction({
    scopeKey: DECISION_SCOPE,
    actionLabel: "记录拒绝",
    runningMessage: "正在把拒绝决定写入作者偏好草稿。",
    successMessage: (message) => message,
    nextStep: "偏好仍为草稿，审核发布前不会进入后续生成提示。",
    action: () =>
      desk.rejectPassagePatchCandidate(candidate.patch_id, {
        note: "保留作者原句或等待人工重写。",
      }),
  });
}

function openManuscripts() {
  navigate("manuscripts");
}

onMounted(() => {
  ensureLoaded();
});

onActivated(() => {
  ensureLoaded();
});
</script>

<template>
  <section class="panel-grid writer-deep-desk" data-testid="writer-deep-desk">
    <WorkflowPageHeader view-id="deepdesk" />
    <PanelShell
      eyebrow="写作与深改台"
      title="先写正文，再让系统理解结构"
      description="作者稿是第一入口：AI 可以反向提取戏剧卡、诊断、生成候选、记录偏好，但不会自动覆盖 FinalScene 或 ChapterMemory。"
    >
      <template #actions>
        <div class="field-inline deep-desk-actions">
          <button data-testid="deep-desk-refresh" :disabled="desk.loading" @click="refreshDesk">
            {{ desk.loading ? "刷新中..." : "刷新" }}
          </button>
          <button class="ghost" @click="openManuscripts">返回成稿中心</button>
        </div>
      </template>

      <div v-if="desk.loading" class="empty">正在载入写作与深改台...</div>
      <div v-else-if="desk.error" class="empty">{{ desk.error }}</div>
      <div v-else class="deep-desk-shell">
        <aside class="paper deep-desk-index">
          <div class="receipt-head compact">
            <div>
              <h3>章节 / 场景</h3>
              <p class="muted receipt-copy">先定位章节，再切换章稿或场景稿。</p>
            </div>
            <span class="badge">{{ chapters.length }} 章</span>
          </div>
          <div v-if="!chapters.length" class="empty">还没有可阅读章节。</div>
          <div v-else class="deep-chapter-list">
            <button
              v-for="chapter in chapters"
              :key="chapter.chapter_id"
              type="button"
              class="deep-chapter-row"
              :class="{ active: desk.selectedChapterId === chapter.chapter_id }"
              @click="selectChapter(chapter.chapter_id)"
            >
              <strong>{{ chapter.chapter_id }}</strong>
              <span>{{ chapter.chapter_goal || "未填写章节目标" }}</span>
              <small>{{ statusLabel(chapter.completion_status) }} / {{ statusLabel(chapter.comparison_status) }}</small>
            </button>
          </div>

          <section class="scene-switcher">
            <div class="receipt-head compact">
              <div>
                <h4>场景稿</h4>
                <p class="muted receipt-copy">场景稿可从场景卡 / 章节目标生成空白骨架。</p>
              </div>
              <span class="badge">{{ scenes.length }} 场</span>
            </div>
            <select
              class="control-input"
              :value="desk.selectedSceneId"
              :disabled="!scenes.length"
              aria-label="选择场景稿"
              @change="selectScene"
            >
              <option v-for="scene in scenes" :key="scene.scene_id" :value="scene.scene_id">
                {{ scene.scene_id }} / {{ scene.scene_goal || "未填写场景目标" }}
              </option>
            </select>
          </section>
        </aside>

        <main class="paper deep-desk-reader" data-testid="deep-desk-reader">
          <div class="receipt-head compact">
            <div>
              <h3>{{ currentObjectLabel }}</h3>
              <p class="muted receipt-copy">{{ desk.draftSourceRef || "等待创建作者稿" }}</p>
            </div>
            <div class="draft-mode-tabs" aria-label="稿件层级切换">
              <button
                type="button"
                data-testid="draft-mode-chapter"
                :class="{ active: desk.draftMode === 'chapter' }"
                @click="selectDraftMode('chapter')"
              >
                章稿
              </button>
              <button
                type="button"
                data-testid="draft-mode-scene"
                :class="{ active: desk.draftMode === 'scene' }"
                :disabled="!desk.selectedSceneId"
                @click="selectDraftMode('scene')"
              >
                场景稿
              </button>
            </div>
          </div>

          <div class="desk-mode-strip" aria-label="作家书桌模式">
            <div class="desk-stage-tabs" role="group" aria-label="作者书桌状态">
              <button
                type="button"
                data-testid="desk-stage-write"
                :class="{ active: desk.deskStage === 'write' }"
                @click="selectDeskStage('write')"
              >
                我先写
              </button>
              <button
                type="button"
                data-testid="desk-stage-ai"
                :class="{ active: desk.deskStage === 'ai' }"
                @click="selectDeskStage('ai')"
              >
                AI 起草
              </button>
              <button
                type="button"
                data-testid="desk-stage-review"
                :class="{ active: desk.deskStage === 'review' }"
                @click="selectDeskStage('review')"
              >
                深改诊断
              </button>
              <button
                type="button"
                data-testid="desk-stage-longform"
                :class="{ active: desk.deskStage === 'longform' }"
                @click="selectDeskStage('longform')"
              >
                长篇压力
              </button>
            </div>
            <div class="desk-mode-buttons" role="group" aria-label="起草模式">
              <button
                type="button"
                data-testid="desk-mode-write-first"
                :class="{ active: desk.deskMode === 'write_first' }"
                @click="selectDeskMode('write_first')"
              >
                我先写
              </button>
              <button
                type="button"
                data-testid="desk-mode-ai-draft"
                :class="{ active: desk.deskMode === 'ai_draft' }"
                @click="selectDeskMode('ai_draft')"
              >
                AI 起草
              </button>
            </div>
          </div>
          <FlowActionReceipt :receipt="receipt(AI_DRAFT_SCOPE)" />

          <section class="author-radar-strip" aria-label="author daily signals">
            <article class="author-radar-card" data-testid="author-work-profile">
              <div class="receipt-head compact">
                <div>
                  <h4>作品档案</h4>
                  <p class="muted receipt-copy">{{ workProfileMeta }}</p>
                </div>
                <span class="badge">{{ workProfile?.display_name || "default" }}</span>
              </div>
            </article>
            <article class="author-radar-card" data-testid="author-daily-focus">
              <div class="receipt-head compact">
                <div>
                  <h4>今日焦点</h4>
                  <p class="muted receipt-copy">Top issues for the current author draft.</p>
                </div>
                <span class="badge">{{ dailyFocus.length }} items</span>
              </div>
              <ol v-if="dailyFocus.length" class="author-focus-list">
                <li v-for="item in dailyFocus" :key="`${item.source}-${item.dimension}-${focusTitle(item)}`">
                  <strong>{{ focusTitle(item) }}</strong>
                  <span class="muted">{{ item.dimension || item.card_type || item.source }}</span>
                </li>
              </ol>
              <div v-else class="empty">No daily focus yet.</div>
            </article>
          </section>

          <section class="draft-proposal-panel" data-testid="draft-proposals">
            <div class="receipt-head compact">
              <div>
                <h4>AI 草稿提案</h4>
                <p class="muted receipt-copy">AI 只生成可比较、可采纳、可拒绝的提案；不会直接覆盖作者稿、运行终稿或章节聚合稿。</p>
              </div>
              <span class="badge">三类候选 / {{ draftProposals.length }} 条</span>
            </div>
            <div class="field-inline draft-proposal-controls">
              <button
                type="button"
                data-testid="draft-proposal-generate"
                :disabled="!desk.authorDraft || desk.actionId === 'proposal-generate'"
                @click="generateDraftProposal"
              >
                {{ desk.actionId === "proposal-generate" ? "生成中..." : "生成 AI 草稿提案" }}
              </button>
              <button
                type="button"
                class="ghost"
                data-testid="draft-proposal-generate-set"
                :disabled="!desk.authorDraft || desk.actionId === 'proposal-generate-set'"
                @click="generateDraftProposalSet"
              >
                {{ desk.actionId === "proposal-generate-set" ? "生成中..." : "生成三类候选" }}
              </button>
              <span class="muted">提案进入右侧账本，只有应用后才成为作者稿新版本。</span>
            </div>
            <div v-if="!draftProposals.length" class="empty">还没有 AI 草稿提案。</div>
            <article v-for="proposal in draftProposals" :key="proposal.proposal_id" class="draft-proposal-row">
              <div class="receipt-head compact">
                <div>
                  <strong>{{ proposalTypeLabel(proposal.proposal_type) }}</strong>
                  <p class="muted">{{ proposal.rationale || proposal.proposal_id }}</p>
                </div>
                <span class="badge">{{ statusLabel(proposal.status) }}</span>
              </div>
              <p class="proposal-text">{{ proposal.content }}</p>
              <div class="card-actions">
                <button
                  type="button"
                  data-testid="draft-proposal-apply-replace"
                  :disabled="desk.actionId.startsWith('proposal-') || proposal.status !== 'candidate'"
                  @click="applyDraftProposal(proposal, 'replace')"
                >
                  整段替换
                </button>
                <button
                  type="button"
                  data-testid="draft-proposal-apply-append"
                  :disabled="desk.actionId.startsWith('proposal-') || proposal.status !== 'candidate'"
                  @click="applyDraftProposal(proposal, 'append')"
                >
                  追加到当前稿
                </button>
                <button
                  type="button"
                  data-testid="draft-proposal-apply-new-version"
                  :disabled="desk.actionId.startsWith('proposal-') || proposal.status !== 'candidate'"
                  @click="applyDraftProposal(proposal, 'new_version')"
                >
                  作为新版本
                </button>
                <button
                  type="button"
                  class="ghost"
                  data-testid="draft-proposal-reject"
                  :disabled="desk.actionId.startsWith('proposal-') || proposal.status !== 'candidate'"
                  @click="rejectDraftProposal(proposal)"
                >
                  拒绝提案
                </button>
              </div>
            </article>
          </section>

          <div class="draft-layer-strip">
            <article>
              <strong>作者稿</strong>
              <span>{{ draftStatusLabel }}</span>
              <small>保存版本，不回写运行终稿。</small>
            </article>
            <article>
              <strong>运行终稿</strong>
              <span>{{ runtimeLayerLabel }}</span>
              <small>FinalScene 或实时拼接稿。</small>
            </article>
            <article>
              <strong>最终聚合稿</strong>
              <span>{{ finalAggregateLabel }}</span>
              <small>ChapterMemory(final)，发布层仍独立。</small>
            </article>
          </div>

          <textarea
            v-model="draftContent"
            class="control-input author-draft-editor"
            data-testid="author-draft-editor"
            spellcheck="false"
            placeholder="这里是作者稿。可以从空白开始写；场景稿会带一个最小骨架，运行终稿只作为对照层。"
          />
          <div class="draft-save-row">
            <span class="badge" :class="{ active: desk.draftDirty }">
              {{ desk.draftDirty ? "未保存" : "已保存" }}
            </span>
            <span class="muted">{{ draftContent.length }} 字</span>
            <button
              class="ghost"
              data-testid="author-draft-ensure-blank"
              :disabled="!desk.draftObjectId || !!desk.authorDraft"
              @click="ensureBlankDraft"
            >
              创建空白作者稿
            </button>
            <button
              data-testid="author-draft-save"
              :disabled="!desk.authorDraft || !desk.draftDirty || desk.actionId === 'draft-save'"
              @click="saveDraft"
            >
              {{ desk.actionId === "draft-save" ? "保存中..." : "保存作者稿" }}
            </button>
          </div>
          <FlowActionReceipt :receipt="receipt(DRAFT_SCOPE)" />

          <section class="draft-event-timeline" data-testid="author-draft-events">
            <div class="receipt-head compact">
              <div>
                <h4>作者稿时间线</h4>
                <p class="muted receipt-copy">版本、候选插入、拒绝和结构提取会留在作者稿账本里。</p>
              </div>
              <span class="badge">{{ draftEvents.length }} 条</span>
            </div>
            <div v-if="!draftEvents.length" class="empty">暂无作者稿事件。</div>
            <ol v-else class="draft-event-list">
              <li v-for="event in draftEvents" :key="event.event_id || `${event.event_type}-${event.created_at}`">
                <strong>{{ eventTypeLabel(event.event_type) }}</strong>
                <span v-if="eventNote(event)" class="muted">{{ eventNote(event) }}</span>
              </li>
            </ol>
          </section>

          <section class="deep-structure" data-testid="author-structure-candidates">
            <div class="receipt-head compact">
              <div>
                <h4>反向提取戏剧卡</h4>
                <p class="muted receipt-copy">从当前作者稿生成结构候选；应用后只更新戏剧卡，不改正文、不改运行终稿。</p>
              </div>
              <span class="badge">{{ structureCandidates.length }} 条</span>
            </div>
            <div class="field-inline deep-structure-controls">
              <button
                data-testid="structure-extract-run"
                :disabled="!desk.authorDraft || !draftContent.trim() || desk.actionId === 'structure-extract'"
                @click="extractAuthorStructure"
              >
                {{ desk.actionId === "structure-extract" ? "提取中..." : "反向提取戏剧卡" }}
              </button>
              <span class="muted">AI 理解只进入候选审核，不自动成为权威设定。</span>
            </div>
            <FlowActionReceipt :receipt="receipt(STRUCTURE_SCOPE)" />
            <div v-if="!structureCandidates.length" class="empty">还没有结构候选。写一段作者稿后，可以先让系统反向理解它。</div>
            <article
              v-for="candidate in structureCandidates"
              :key="candidate.candidate_id"
              class="deep-structure-row"
            >
              <div class="receipt-head compact">
                <div>
                  <strong>结构候选</strong>
                  <p class="muted">{{ candidate.source_text_ref }}</p>
                </div>
                <span class="badge">{{ statusLabel(candidate.status) }}</span>
              </div>
              <dl class="structure-field-grid">
                <template v-for="field in structureFieldRows(candidate)" :key="field.key">
                  <dt>{{ field.label }}</dt>
                  <dd>{{ field.value }}</dd>
                </template>
              </dl>
              <p v-if="candidate.rationale" class="muted">{{ candidate.rationale }}</p>
              <ul v-if="uncertaintyNotes(candidate).length" class="uncertainty-list">
                <li v-for="note in uncertaintyNotes(candidate)" :key="note">{{ note }}</li>
              </ul>
              <div class="card-actions">
                <button
                  type="button"
                  data-testid="author-structure-apply"
                  :disabled="desk.actionId.startsWith('structure-') || candidate.status !== 'candidate'"
                  @click="applyStructureCandidate(candidate)"
                >
                  应用到戏剧卡
                </button>
                <button
                  type="button"
                  class="ghost"
                  data-testid="author-structure-reject"
                  :disabled="desk.actionId.startsWith('structure-') || candidate.status !== 'candidate'"
                  @click="rejectStructureCandidate(candidate)"
                >
                  拒绝候选
                </button>
                <button type="button" class="ghost" @click="copyStructureCandidateNote(candidate)">复制为备注</button>
              </div>
            </article>
          </section>

          <section class="deep-selection">
            <div class="receipt-head compact">
              <div>
                <h4>局部选段</h4>
                <p class="muted receipt-copy">粘贴或保留一段作者稿正文，候选只针对这个片段生成。</p>
              </div>
              <span class="badge">author_draft_only</span>
            </div>
            <textarea
              v-model="selectedExcerpt"
              class="control-input deep-selection-input"
              :placeholder="excerptPlaceholder"
            />
            <div class="field-inline deep-selection-controls">
              <select v-model="issueDimension" class="control-input" aria-label="问题维度">
                <option value="">使用首个诊断维度</option>
                <option v-for="finding in findings" :key="`${finding.lens}-${finding.dimension}-${finding.issue}`" :value="finding.dimension">
                  {{ finding.dimension }} / {{ severityLabel(finding.severity) }}
                </option>
              </select>
              <button
                data-testid="patch-candidate-create"
                :disabled="!desk.authorDraft || !patchExcerpt.trim() || desk.actionId === 'patch-create'"
                @click="createPatchCandidate"
              >
                生成局部候选
              </button>
            </div>
          </section>
          <FlowActionReceipt :receipt="receipt(PATCH_SCOPE)" />
        </main>

        <aside class="paper deep-desk-rail">
          <div class="receipt-head compact">
            <div>
              <h3>深改诊断</h3>
              <p class="muted receipt-copy">诊断跟随当前章稿 / 场景稿目标。</p>
            </div>
            <span class="badge">{{ scoreText }}</span>
          </div>
          <button
            data-testid="deep-review-run"
            :disabled="!desk.draftObjectId || desk.actionId === 'deep-review'"
            @click="runDeepReview"
          >
            运行深改诊断
          </button>
          <button
            type="button"
            class="ghost"
            data-testid="inline-quality-run"
            :disabled="!desk.authorDraft || !draftContent.trim() || desk.actionId === 'inline-quality'"
            @click="runInlineQuality"
          >
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
            <button
              type="button"
              class="ghost"
              data-testid="scene-quality-contract-generate"
              :disabled="desk.draftObjectType !== 'scene' || !desk.selectedSceneId || desk.actionId === 'quality-contract'"
              @click="generateQualityContract"
            >
              刷新契约
            </button>
            <dl v-if="qualityContract" class="quality-contract-grid">
              <template v-for="row in qualityContractRows" :key="row.key">
                <dt>{{ row.label }}</dt>
                <dd>{{ row.value || "待补足" }}</dd>
              </template>
            </dl>
            <div v-else class="empty">当前场景还没有质量契约。</div>
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
              <button
                type="button"
                data-testid="scene-auto-rewrite-run-button"
                :disabled="desk.draftObjectType !== 'scene' || !desk.selectedSceneId || desk.actionId === 'auto-rewrite'"
                @click="runAutoRewrite"
              >
                自动重写
              </button>
              <button
                type="button"
                class="ghost"
                data-testid="scene-auto-rewrite-promote"
                :disabled="!autoRewriteRun?.run_id || !qualityPromotion?.eligible || desk.actionId.startsWith('auto-rewrite-')"
                @click="promoteAutoRewrite"
              >
                晋级为运行终稿
              </button>
              <button
                type="button"
                class="ghost"
                data-testid="scene-auto-rewrite-rollback"
                :disabled="!autoRewriteRun?.run_id || desk.actionId.startsWith('auto-rewrite-')"
                @click="rollbackAutoRewrite"
              >
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
            <div v-if="!inlineQualitySpanFindings.length" class="empty">暂未扫描当前作者稿。</div>
            <article
              v-for="span in inlineQualitySpanFindings"
              :key="`${span.dimension}-${span.start}-${span.end}`"
              class="deep-finding"
            >
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
            <div v-if="!longformPressure.length" class="empty">暂无高优先级长篇压力。</div>
            <article
              v-for="card in longformPressure"
              :key="card.card_id"
              class="deep-pressure-row"
            >
              <div class="receipt-head compact">
                <strong>{{ longformCardTypeLabel(card.card_type) }}</strong>
                <span class="badge">{{ longformSeverityLabel(card.severity) }}</span>
              </div>
              <p>{{ longformRecommendation(card) }}</p>
            </article>
          </section>

          <section class="deep-review-findings" data-testid="deep-review-findings">
            <div v-if="!findings.length" class="empty">还没有深改批注。</div>
            <article
              v-for="finding in findings"
              :key="`${finding.lens}-${finding.dimension}-${finding.issue}`"
              class="deep-finding"
              :class="`severity-${finding.severity}`"
            >
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
            <div v-if="!lensEvaluations.length" class="empty">暂无 lens 结果。</div>
            <article v-for="lens in lensEvaluations" :key="lens.evaluation_id" class="deep-lens-row">
              <span>{{ lensLabel(lens.lens) }}</span>
              <strong>{{ scoreLabel(lens.overall_score) }}</strong>
            </article>
          </section>
        </aside>
      </div>

      <section class="paper deep-candidates" data-testid="passage-patch-candidates">
        <div class="receipt-head">
          <div>
            <h3>局部候选账本</h3>
            <p class="muted receipt-copy">“放入稿件”只修改作者稿编辑器；保存作者稿后，候选才会标记为已采纳。</p>
          </div>
          <span class="badge">{{ candidates.length }} 条</span>
        </div>
        <div v-if="!candidates.length" class="empty">还没有局部候选。</div>
        <article v-for="candidate in candidates" :key="candidate.patch_id" class="deep-candidate-row">
          <div class="receipt-head compact">
            <div>
              <strong>{{ candidateCategoryLabel(candidate.candidate_category) }} / {{ candidate.issue_dimension }}</strong>
              <p class="muted">{{ candidateMetaLine(candidate) }}</p>
              <p class="muted">{{ candidateTagLine(candidate) }}</p>
              <p class="muted">{{ candidate.source_excerpt }}</p>
              <small v-if="candidate.rationale" class="muted">{{ candidate.rationale }}</small>
            </div>
            <div class="candidate-badges">
              <span class="badge">{{ statusLabel(candidate.status) }}</span>
              <span v-if="candidate.inserted_into_author_draft" class="badge">已放入稿件</span>
            </div>
          </div>
          <div class="deep-option-grid">
            <section v-for="option in candidate.replacement_options" :key="option.option_id" class="deep-option">
              <div class="receipt-head compact">
                <strong>{{ option.label || option.tone }}</strong>
                <span class="badge">{{ option.tone }}</span>
              </div>
              <p class="option-text">{{ option.replacement_text }}</p>
              <small>{{ option.why_it_helps }}</small>
              <button
                type="button"
                :disabled="desk.actionId.startsWith('patch-') || candidate.status !== 'candidate'"
                @click="insertCandidate(candidate, option)"
              >
                放入稿件
              </button>
            </section>
          </div>
          <div class="card-actions">
            <button
              type="button"
              class="ghost"
              :disabled="desk.actionId.startsWith('patch-') || candidate.status !== 'candidate'"
              @click="rejectCandidate(candidate)"
            >
              拒绝候选
            </button>
            <span class="muted">作者决定：{{ statusLabel(candidate.author_decision) }}</span>
          </div>
        </article>
        <FlowActionReceipt :receipt="receipt(DECISION_SCOPE)" />
      </section>

      <section class="paper deep-preference" data-testid="author-preference-profile">
        <div class="receipt-head">
          <div>
            <h3>作者偏好草稿</h3>
            <p class="muted receipt-copy">采纳 / 拒绝会沉淀偏好，但审核发布前不会进入后续生成提示。</p>
          </div>
          <span class="badge">{{ statusLabel(preference?.status) }}</span>
        </div>
        <div class="deep-preference-grid">
          <article>
            <h4>偏好的改法</h4>
            <p>{{ (profileSummary.preferred_revision_moves || []).join(" / ") || "暂无采纳样本。" }}</p>
          </article>
          <article>
            <h4>常拒绝的痕迹</h4>
            <p>{{ (profileSummary.rejected_revision_moves || []).join(" / ") || "暂无拒绝样本。" }}</p>
          </article>
          <article>
            <h4>AI 痕迹监测</h4>
            <p>{{ (profileSummary.ai_trace_terms_to_watch || []).join(" / ") || "暂无监测词。" }}</p>
          </article>
          <article>
            <h4>偏好候选类型</h4>
            <p>{{ (profileSummary.preferred_patch_categories || []).join(" / ") || "暂无类型样本。" }}</p>
          </article>
          <article>
            <h4>偏好标签</h4>
            <p>{{ (profileSummary.preference_tags || []).join(" / ") || "暂无标签样本。" }}</p>
          </article>
          <article>
            <h4>运行资格</h4>
            <p>{{ preference?.runtime_eligible ? "已允许进入运行 bundle" : "草稿状态，不进运行 bundle" }}</p>
          </article>
        </div>
      </section>
    </PanelShell>
  </section>
</template>

<style scoped>
.deep-desk-shell {
  display: grid;
  grid-template-columns: minmax(13rem, 0.82fr) minmax(26rem, 1.85fr) minmax(18rem, 1fr);
  gap: 1rem;
  align-items: start;
}

.deep-desk-index,
.deep-desk-reader,
.deep-desk-rail,
.deep-candidates,
.deep-structure,
.author-radar-strip,
.draft-proposal-panel,
.judgment-layers-panel,
.scene-quality-panel,
.scene-auto-rewrite-panel,
.deep-preference {
  display: grid;
  gap: 1rem;
}

.deep-chapter-list,
.scene-switcher {
  display: grid;
  gap: 0.6rem;
}

.deep-chapter-row {
  display: grid;
  gap: 0.25rem;
  width: 100%;
  text-align: left;
  background: rgba(255, 255, 255, 0.54);
  color: var(--ink);
  border: 1px solid var(--line);
}

.deep-chapter-row.active {
  border-color: rgba(132, 45, 29, 0.35);
  background: rgba(163, 63, 47, 0.1);
}

.deep-chapter-row span,
.deep-chapter-row small {
  overflow-wrap: anywhere;
}

.draft-mode-tabs {
  display: inline-flex;
  gap: 0.35rem;
  padding: 0.25rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
}

.draft-mode-tabs button {
  min-width: 4.5rem;
  padding: 0.45rem 0.7rem;
  border-color: transparent;
  background: transparent;
  color: var(--muted);
}

.draft-mode-tabs button.active {
  background: rgba(36, 71, 86, 0.12);
  border-color: rgba(36, 71, 86, 0.18);
  color: var(--ink);
}

.desk-mode-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.65rem;
  border: 1px solid rgba(37, 51, 66, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.52);
}

.desk-stage-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.35rem;
  min-width: min(32rem, 100%);
  padding: 0.25rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.62);
}

.desk-stage-tabs button {
  min-width: 0;
  padding: 0.5rem 0.65rem;
  border-color: transparent;
  background: transparent;
  color: var(--muted);
  white-space: nowrap;
}

.desk-stage-tabs button.active {
  border-color: rgba(36, 71, 86, 0.2);
  background: rgba(36, 71, 86, 0.12);
  color: var(--ink);
}

.desk-mode-buttons {
  display: inline-flex;
  gap: 0.35rem;
  padding: 0.25rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.55);
}

.desk-mode-buttons button {
  min-width: 5.25rem;
  padding: 0.45rem 0.8rem;
  border-color: transparent;
  background: transparent;
  color: var(--muted);
}

.desk-mode-buttons button.active {
  background: rgba(132, 45, 29, 0.12);
  border-color: rgba(132, 45, 29, 0.22);
  color: var(--ink);
}

.draft-layer-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.7rem;
}

.draft-layer-strip article {
  display: grid;
  gap: 0.3rem;
  min-width: 0;
  padding: 0.75rem;
  border: 1px solid rgba(37, 51, 66, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.46);
}

.draft-layer-strip span,
.draft-layer-strip small {
  overflow-wrap: anywhere;
}

.draft-layer-strip small {
  color: var(--muted);
  line-height: 1.45;
}

.author-draft-editor {
  min-height: 34rem;
  max-height: 62vh;
  resize: vertical;
  padding: 1.15rem;
  color: #24221e;
  line-height: 1.9;
  white-space: pre-wrap;
}

.draft-save-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.7rem;
  align-items: center;
  justify-content: flex-end;
}

.draft-save-row .badge.active {
  border-color: rgba(143, 47, 38, 0.24);
  background: rgba(143, 47, 38, 0.1);
}

.deep-selection {
  display: grid;
  gap: 0.7rem;
  padding-top: 0.4rem;
  border-top: 1px dashed var(--line);
}

.draft-event-timeline,
.draft-proposal-panel,
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

.author-radar-strip {
  grid-template-columns: minmax(0, 0.82fr) minmax(0, 1.18fr);
  gap: 0.7rem;
}

.author-radar-card,
.judgment-layer-card {
  display: grid;
  gap: 0.55rem;
  min-width: 0;
  padding: 0.75rem;
  border: 1px solid rgba(37, 51, 66, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.52);
}

.author-focus-list {
  display: grid;
  gap: 0.45rem;
  margin: 0;
  padding-left: 1.1rem;
}

.author-focus-list li {
  line-height: 1.45;
}

.author-focus-list span {
  display: block;
}

.draft-event-list {
  display: grid;
  gap: 0.55rem;
  margin: 0;
  padding-left: 1.15rem;
}

.draft-event-list li {
  line-height: 1.55;
}

.draft-event-list span {
  display: block;
  overflow-wrap: anywhere;
}

.deep-selection-input {
  min-height: 8.5rem;
  resize: vertical;
  line-height: 1.7;
}

.deep-selection-controls {
  align-items: stretch;
}

.deep-review-findings,
.deep-lenses,
.deep-option-grid,
.judgment-layer-grid,
.structure-field-grid,
.deep-preference-grid {
  display: grid;
  gap: 0.8rem;
}

.deep-finding,
.deep-option,
.deep-candidate-row,
.deep-structure-row,
.draft-proposal-row,
.deep-pressure-row,
.deep-preference-grid > article {
  display: grid;
  gap: 0.65rem;
  padding: 0.85rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.58);
}

.deep-finding p,
.deep-option p,
.deep-candidate-row p,
.deep-structure-row p,
.deep-pressure-row p,
.deep-preference p {
  margin: 0;
}

.deep-structure {
  padding-top: 0.4rem;
  border-top: 1px dashed var(--line);
}

.deep-structure-controls {
  align-items: center;
}

.structure-field-grid {
  grid-template-columns: 5.5rem minmax(0, 1fr);
  gap: 0.45rem 0.8rem;
  margin: 0;
}

.structure-field-grid dt {
  color: var(--muted);
}

.structure-field-grid dd {
  margin: 0;
  line-height: 1.55;
  overflow-wrap: anywhere;
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

.uncertainty-list {
  display: grid;
  gap: 0.35rem;
  margin: 0;
  padding-left: 1.1rem;
  color: var(--muted);
  line-height: 1.5;
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

.candidate-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  justify-content: flex-end;
}

.deep-option-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.deep-option small,
.deep-candidate-row small {
  color: var(--muted);
  line-height: 1.5;
}

.option-text {
  white-space: pre-wrap;
  line-height: 1.75;
}

.proposal-text {
  max-height: 16rem;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.75;
}

.deep-option button {
  justify-self: start;
}

.deep-candidates,
.deep-preference {
  margin-top: 1rem;
}

.deep-preference-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

@media (max-width: 1360px) {
  .deep-desk-shell,
  .author-radar-strip,
  .draft-layer-strip {
    grid-template-columns: 1fr;
  }

  .author-draft-editor {
    max-height: none;
  }

  .deep-option-grid,
  .deep-preference-grid {
    grid-template-columns: 1fr;
  }

  .desk-mode-strip {
    align-items: stretch;
    flex-direction: column;
  }

  .desk-stage-tabs {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    min-width: 0;
  }
}
</style>
