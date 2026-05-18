<script setup>
import { computed, ref } from "vue";

import BaseEmptyState from "./base/BaseEmptyState.vue";
import FlowActionReceipt from "./FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { compactEntityOptions, formatChapterChoice, formatSceneChoice } from "../lib/readableRefs";
import { useWriterDeepDeskStore } from "../stores/writerDeepDesk";

const emit = defineEmits(["notice"]);

const desk = useWriterDeepDeskStore();
const issueDimension = ref("");
const AI_DRAFT_SCOPE = "deepdesk:ai-draft";
const DRAFT_SCOPE = "deepdesk:draft";
const STRUCTURE_SCOPE = "deepdesk:structure";
const PATCH_SCOPE = "deepdesk:patch";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const chapters = computed(() => desk.chapters || []);
const scenes = computed(() => desk.availableScenes || []);
const chapterChoiceState = computed(() =>
  compactEntityOptions(chapters.value, {
    idKey: "chapter_id",
    titleKeys: ["chapter_title", "chapter_goal"],
    selectedId: desk.selectedChapterId,
    formatter: formatChapterChoice,
  }),
);
const sceneChoiceState = computed(() =>
  compactEntityOptions(scenes.value, {
    idKey: "scene_id",
    titleKeys: ["scene_title", "scene_goal"],
    selectedId: desk.selectedSceneId,
    formatter: formatSceneChoice,
  }),
);
const findings = computed(() => desk.findings || []);
const draftProposals = computed(() => desk.draftProposalRows || []);
const structureCandidates = computed(() => desk.structureCandidateRows || []);
const workProfile = computed(() => desk.workProfile || null);
const dailyFocus = computed(() => desk.dailyFocus || []);
const draftEvents = computed(() => desk.draftEvents || []);
const currentObjectLabel = computed(() => {
  if (desk.draftMode === "scene") {
    return sceneChoiceState.value.options.find((o) => o.value === desk.selectedSceneId)?.label || "未选择场景";
  }
  return chapterChoiceState.value.options.find((o) => o.value === desk.selectedChapterId)?.label || "未选择章节";
});
const finalAggregateLabel = computed(() =>
  desk.detail?.aggregate?.row_id ? `ChapterMemory ${desk.detail.aggregate.row_id}` : "尚未生成最终聚合稿",
);
const runtimeLayerLabel = computed(() => {
  if (desk.draftMode === "scene") return desk.runtimeLayerText || "该场景暂无运行终稿";
  return desk.currentSourceRef || "暂无运行终稿来源";
});
const draftStatusLabel = computed(() => {
  if (!desk.authorDraft) return "尚未创建";
  const dirty = desk.draftDirty ? "有未保存修改" : "已保存";
  return `${dirty} / 第 ${desk.draftRevisionNo} 版`;
});
const workProfileMeta = computed(() => {
  const profile = workProfile.value || {};
  const config = profile.profile_json || {};
  return [profile.profile_key, config.pacing_preference || config.pacing, config.language_density, config.ending_drive_policy].filter(Boolean).join(" / ") || "profile_default";
});
const selectedExcerpt = computed({
  get: () => desk.selectedExcerpt,
  set: (value) => desk.setSelectedExcerpt(value),
});
const draftContent = computed({
  get: () => desk.draftContent,
  set: (value) => desk.setDraftContent(value),
});
const selectedIssue = computed(() => issueDimension.value || findings.value[0]?.dimension || "dialogue_subtext");
const patchExcerpt = computed(() => desk.excerptForPatch || "");
const excerptPlaceholder = computed(() => "选中或粘贴一段作者稿正文，再生成局部候选。");

function statusLabel(value) {
  return { not_run: "未运行", reviewed: "已诊断", candidate: "候选", accepted: "已采纳", rejected: "已拒绝", pending: "待决定", draft: "草稿", approved: "已审核", current: "当前", superseded: "已替换" }[value] || value || "-";
}
function severityLabel(value) {
  return { blocking: "阻断", revision: "修订", taste: "审美", ignore_ok: "可忽略" }[value] || value || "未分级";
}
function proposalTypeLabel(value) {
  return { structure_candidate: "structure candidate", passage_candidate: "passage candidate", language_candidate: "language candidate", scene_draft: "scene draft", chapter_draft: "chapter draft" }[value] || value || "draft";
}
function focusTitle(item) {
  return item?.title || item?.issue || item?.dimension || item?.card_type || "focus";
}
function focusWhy(item) {
  return item?.why_it_matters || item?.summary || item?.issue || "这会影响人物代价、关系转向或下一场牵引。";
}
function focusAction(item) {
  return item?.proposed_action || item?.recommendation?.summary || "先做一处小刀式改动，再回看整场是否成立。";
}
function focusTradeoff(item) {
  return item?.tradeoff || "改得更锋利会牺牲一部分顺滑解释，需要保护作者声线。";
}
function eventTypeLabel(value) {
  return { created: "创建作者稿", edited: "保存版本", candidate_inserted: "候选放入稿件", candidate_saved: "候选保存确认", candidate_rejected: "拒绝候选", proposal_applied: "应用 AI 草稿提案", proposal_rejected: "拒绝 AI 草稿提案", structure_extracted: "结构提取" }[value] || value || "稿件事件";
}
function eventNote(event) {
  return event?.note || event?.patch_id || event?.option_id || event?.actor_ref || "";
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
  const fields = candidate?.object_type === "chapter"
    ? [["core_promise", "核心承诺"], ["plot_movement", "主线推进"], ["character_shift", "人物变化"], ["chapter_question", "章节问题"], ["ending_aftertaste", "结尾余味"], ["escalation_path", "升级路径"], ["reveal_or_reversal", "揭示/反转"], ["ending_question", "结尾问题"]]
    : [["character_desire", "欲望"], ["obstacle", "阻碍"], ["stakes", "代价"], ["emotional_turn", "转折"], ["new_information", "信息释放"], ["irreversible_change", "结尾动作"], ["reader_question", "读者问题"], ["choice_under_pressure", "选择压力"]];
  return fields.map(([key, label]) => ({ key, label, value: brief[key] || "未确定" }));
}
function candidateNote(candidate) {
  const lines = structureFieldRows(candidate).map((f) => `${f.label}: ${f.value}`);
  const notes = uncertaintyNotes(candidate);
  if (notes.length) lines.push(`不确定项: ${notes.join(" / ")}`);
  if (candidate?.rationale) lines.push(`判断依据: ${candidate.rationale}`);
  return lines.join("\n");
}

function selectDraftMode(mode) {
  desk.setDraftMode(mode).catch((e) => emit("notice", e.message));
}
function selectDeskMode(mode) { desk.setDeskMode(mode); }
function selectDeskStage(stage) { desk.setDeskStage(stage); }

async function runAiDraftToAuthorDraft() {
  await runFlowAction({ scopeKey: AI_DRAFT_SCOPE, actionLabel: "AI 起草", runningMessage: "正在运行当前场景，并把运行终稿转成可改的作者稿。", successMessage: (m) => m, nextStep: "现在可以在作者稿里人工改写；运行终稿和聚合稿保持独立。", action: () => desk.runAiDraftToAuthorDraft() });
}
async function generateDraftProposal() {
  await runFlowAction({ scopeKey: AI_DRAFT_SCOPE, actionLabel: "AI 草稿提案", runningMessage: "正在生成可比较的 AI 草稿提案；作者稿、运行终稿和章节聚合稿都不会被覆盖。", successMessage: (m) => m, nextStep: "先比较提案，再选择整段替换、追加到当前稿、作为新版本，或拒绝并记录原因。", action: () => desk.generateDraftProposal({ proposal_type: desk.draftObjectType === "scene" ? "scene_draft" : "chapter_draft" }) });
}
async function generateDraftProposalSet() {
  await runFlowAction({ scopeKey: AI_DRAFT_SCOPE, actionLabel: "proposal triad", runningMessage: "Generating structure, passage, and language candidates for author choice.", successMessage: (m) => m, nextStep: "Compare the three lanes, then apply, append, make a new version, or reject with a reason.", action: () => desk.generateDraftProposalSet({ instruction: "" }) });
}
async function applyDraftProposal(proposal, applyMode) {
  await runFlowAction({ scopeKey: AI_DRAFT_SCOPE, actionLabel: "应用 AI 草稿提案", runningMessage: "正在把提案写成作者稿的新版本；运行终稿和章节聚合稿保持不变。", successMessage: (m) => m, nextStep: "继续人工改写并保存作者稿，或运行深改诊断检查新版本的风险。", action: () => desk.applyDraftProposal(proposal, { apply_mode: applyMode, note: `apply proposal as ${applyMode}` }) });
}
async function rejectDraftProposal(proposal) {
  await runFlowAction({ scopeKey: AI_DRAFT_SCOPE, actionLabel: "拒绝 AI 草稿提案", runningMessage: "正在记录拒绝原因；这会沉淀为作者偏好草稿，但不会进入运行提示。", successMessage: (m) => m, nextStep: "可以重新生成提案，或回到作者稿里直接改写。", action: () => desk.rejectDraftProposal(proposal, { note: "kept current author draft" }) });
}
async function saveDraft() {
  await runFlowAction({ scopeKey: DRAFT_SCOPE, actionLabel: "保存作者稿", runningMessage: "正在保存作者稿版本，并记录这次作者层改动。", successMessage: (m) => m, nextStep: "作者稿已保存；运行终稿与最终聚合稿保持不变。", action: () => desk.saveAuthorDraft() });
}
async function ensureBlankDraft() {
  await runFlowAction({ scopeKey: DRAFT_SCOPE, actionLabel: "创建空白作者稿", runningMessage: "正在准备一份独立作者稿；没有运行终稿时也可以直接开始写。", successMessage: () => "空白作者稿已准备好。", nextStep: "现在可以在正文编辑器里自由写作，后续再反向提取结构候选。", action: () => desk.ensureAuthorDraft() });
}
async function extractAuthorStructure() {
  await runFlowAction({ scopeKey: STRUCTURE_SCOPE, actionLabel: "反向提取戏剧卡", runningMessage: "正在从当前作者稿反向理解欲望、阻碍、代价、转折和读者问题。", successMessage: (m) => m, nextStep: "结构候选只进入候选栏；点击应用后才会更新章节或场景的 writer brief。", action: () => desk.extractAuthorStructure() });
}
async function applyStructureCandidate(candidate) {
  await runFlowAction({ scopeKey: STRUCTURE_SCOPE, actionLabel: "应用结构候选", runningMessage: "正在把结构候选写入对应戏剧卡的 writer brief，正文和运行终稿保持不变。", successMessage: (m) => m, nextStep: "作者工作台和长篇控制相关视图会在重新进入或刷新后读取新的戏剧卡候选内容。", action: () => desk.applyStructureCandidate(candidate) });
}
async function rejectStructureCandidate(candidate) {
  await runFlowAction({ scopeKey: STRUCTURE_SCOPE, actionLabel: "拒绝结构候选", runningMessage: "正在记录这条结构候选的拒绝决定。", successMessage: (m) => m, nextStep: "被拒绝的候选不会进入章节或场景卡，也不会影响后续生成链路。", action: () => desk.rejectStructureCandidate(candidate) });
}
async function copyStructureCandidateNote(candidate) {
  const note = candidateNote(candidate);
  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) await navigator.clipboard.writeText(note);
  selectedExcerpt.value = note;
  emit("notice", "结构候选已复制为备注。");
}
async function createPatchCandidate() {
  await runFlowAction({ scopeKey: PATCH_SCOPE, actionLabel: "生成局部候选", runningMessage: "正在为选中片段生成 2 到 3 个可比较版本。", successMessage: (m) => m, nextStep: "候选只进入右侧账本；点击放入稿件后也只改作者稿编辑器。", action: () => desk.createPassagePatchCandidate({ issue_dimension: selectedIssue.value, source_excerpt: patchExcerpt.value }) });
}
</script>

<template>
  <main class="paper deep-desk-reader" data-testid="deep-desk-reader">
    <div class="receipt-head compact">
      <div>
        <h3 class="line-clamp-2">{{ currentObjectLabel }}</h3>
        <p class="muted receipt-copy technical-ref">{{ desk.draftSourceRef || "等待创建作者稿" }}</p>
      </div>
      <div class="draft-mode-tabs" aria-label="稿件层级切换">
        <button type="button" data-testid="draft-mode-chapter" :class="{ active: desk.draftMode === 'chapter' }" @click="selectDraftMode('chapter')">章稿</button>
        <button type="button" data-testid="draft-mode-scene" :class="{ active: desk.draftMode === 'scene' }" :disabled="!desk.selectedSceneId" @click="selectDraftMode('scene')">场景稿</button>
      </div>
    </div>

    <div class="desk-mode-strip" aria-label="作家书桌模式">
      <div class="desk-stage-tabs" role="group" aria-label="作者书桌状态">
        <button type="button" data-testid="desk-stage-write" :class="{ active: desk.deskStage === 'write' }" @click="selectDeskStage('write')">我先写</button>
        <button type="button" data-testid="desk-stage-ai" :class="{ active: desk.deskStage === 'ai' }" @click="selectDeskStage('ai')">AI 起草</button>
        <button type="button" data-testid="desk-stage-review" :class="{ active: desk.deskStage === 'review' }" @click="selectDeskStage('review')">深改诊断</button>
        <button type="button" data-testid="desk-stage-longform" :class="{ active: desk.deskStage === 'longform' }" @click="selectDeskStage('longform')">长篇压力</button>
      </div>
      <div class="desk-mode-buttons" role="group" aria-label="起草模式">
        <button type="button" data-testid="desk-mode-write-first" :class="{ active: desk.deskMode === 'write_first' }" @click="selectDeskMode('write_first')">我先写</button>
        <button type="button" data-testid="desk-mode-ai-draft" :class="{ active: desk.deskMode === 'ai_draft' }" @click="selectDeskMode('ai_draft')">AI 起草</button>
      </div>
    </div>
    <FlowActionReceipt :receipt="receipt(AI_DRAFT_SCOPE)" />

    <section class="author-radar-strip" aria-label="author daily signals">
      <article class="author-radar-card" data-testid="author-work-profile">
        <div class="receipt-head compact">
          <div><h4>作品档案</h4><p class="muted receipt-copy">{{ workProfileMeta }}</p></div>
          <span class="badge">{{ workProfile?.display_name || "default" }}</span>
        </div>
      </article>
      <article class="author-radar-card" data-testid="author-daily-focus">
        <div class="receipt-head compact">
          <div><h4>今日焦点</h4><p class="muted receipt-copy">Top issues for the current author draft.</p></div>
          <span class="badge">{{ dailyFocus.length }} items</span>
        </div>
        <ol v-if="dailyFocus.length" class="author-focus-list">
          <li v-for="item in dailyFocus" :key="`${item.source}-${item.dimension}-${focusTitle(item)}`">
            <strong>{{ focusTitle(item) }}</strong>
            <span class="muted">{{ item.dimension || item.card_type || item.source }}</span>
          </li>
        </ol>
        <BaseEmptyState v-else description="No daily focus yet." />
      </article>
    </section>

    <section class="author-next-actions" data-testid="author-next-actions">
      <div class="receipt-head compact">
        <div><h4>下一步改稿动作</h4><p class="muted receipt-copy">把诊断翻译成作者今天能下手的一处局部动作。</p></div>
        <span class="badge">{{ dailyFocus.length }} actions</span>
      </div>
      <BaseEmptyState v-if="!dailyFocus.length" description="还没有可执行动作。" />
      <div v-else class="author-action-grid">
        <article v-for="item in dailyFocus" :key="`action-${item.source}-${item.dimension}-${focusTitle(item)}`" class="author-action-card">
          <strong>{{ focusTitle(item) }}</strong>
          <dl>
            <dt>为什么要改</dt><dd>{{ focusWhy(item) }}</dd>
            <dt>建议动作</dt><dd>{{ focusAction(item) }}</dd>
            <dt>取舍</dt><dd>{{ focusTradeoff(item) }}</dd>
          </dl>
        </article>
      </div>
    </section>

    <section class="draft-proposal-panel" data-testid="draft-proposals">
      <div class="receipt-head compact">
        <div><h4>AI 草稿提案</h4><p class="muted receipt-copy">AI 只生成可比较、可采纳、可拒绝的提案；不会直接覆盖作者稿、运行终稿或章节聚合稿。</p></div>
        <span class="badge">三类候选 / {{ draftProposals.length }} 条</span>
      </div>
      <div class="field-inline draft-proposal-controls">
        <button type="button" data-testid="draft-proposal-generate" :disabled="!desk.authorDraft || desk.actionId === 'proposal-generate'" @click="generateDraftProposal">
          {{ desk.actionId === "proposal-generate" ? "生成中..." : "生成 AI 草稿提案" }}
        </button>
        <button type="button" class="ghost" data-testid="draft-proposal-generate-set" :disabled="!desk.authorDraft || desk.actionId === 'proposal-generate-set'" @click="generateDraftProposalSet">
          {{ desk.actionId === "proposal-generate-set" ? "生成中..." : "生成三类候选" }}
        </button>
        <span class="muted">提案进入右侧账本，只有应用后才成为作者稿新版本。</span>
      </div>
      <BaseEmptyState v-if="!draftProposals.length" description="还没有 AI 草稿提案。" />
      <article v-for="proposal in draftProposals" :key="proposal.proposal_id" class="draft-proposal-row">
        <div class="receipt-head compact">
          <div><strong>{{ proposalTypeLabel(proposal.proposal_type) }}</strong><p class="muted">{{ proposal.rationale || proposal.proposal_id }}</p></div>
          <span class="badge">{{ statusLabel(proposal.status) }}</span>
        </div>
        <p class="proposal-text">{{ proposal.content }}</p>
        <div class="card-actions">
          <button type="button" data-testid="draft-proposal-apply-replace" :disabled="desk.actionId.startsWith('proposal-') || proposal.status !== 'candidate'" @click="applyDraftProposal(proposal, 'replace')">整段替换</button>
          <button type="button" data-testid="draft-proposal-apply-append" :disabled="desk.actionId.startsWith('proposal-') || proposal.status !== 'candidate'" @click="applyDraftProposal(proposal, 'append')">追加到当前稿</button>
          <button type="button" data-testid="draft-proposal-apply-new-version" :disabled="desk.actionId.startsWith('proposal-') || proposal.status !== 'candidate'" @click="applyDraftProposal(proposal, 'new_version')">作为新版本</button>
          <button type="button" class="ghost" data-testid="draft-proposal-reject" :disabled="desk.actionId.startsWith('proposal-') || proposal.status !== 'candidate'" @click="rejectDraftProposal(proposal)">拒绝提案</button>
        </div>
      </article>
    </section>

    <div class="draft-layer-strip">
      <article><strong>作者稿</strong><span>{{ draftStatusLabel }}</span><small>保存版本，不回写运行终稿。</small></article>
      <article><strong>运行终稿</strong><span>{{ runtimeLayerLabel }}</span><small>FinalScene 或实时拼接稿。</small></article>
      <article><strong>最终聚合稿</strong><span>{{ finalAggregateLabel }}</span><small>ChapterMemory(final)，发布层仍独立。</small></article>
    </div>

    <textarea
      v-model="draftContent"
      class="control-input author-draft-editor"
      data-testid="author-draft-editor"
      spellcheck="false"
      placeholder="这里是作者稿。可以从空白开始写；场景稿会带一个最小骨架，运行终稿只作为对照层。"
    />
    <div class="draft-save-row">
      <span class="badge" :class="{ active: desk.draftDirty }">{{ desk.draftDirty ? "未保存" : "已保存" }}</span>
      <span class="muted">{{ draftContent.length }} 字</span>
      <button class="ghost" data-testid="author-draft-ensure-blank" :disabled="!desk.draftObjectId || !!desk.authorDraft" @click="ensureBlankDraft">创建空白作者稿</button>
      <button data-testid="author-draft-save" :disabled="!desk.authorDraft || !desk.draftDirty || desk.actionId === 'draft-save'" @click="saveDraft">
        {{ desk.actionId === "draft-save" ? "保存中..." : "保存作者稿" }}
      </button>
    </div>
    <FlowActionReceipt :receipt="receipt(DRAFT_SCOPE)" />

    <section class="draft-event-timeline" data-testid="author-draft-events">
      <div class="receipt-head compact">
        <div><h4>作者稿时间线</h4><p class="muted receipt-copy">版本、候选插入、拒绝和结构提取会留在作者稿账本里。</p></div>
        <span class="badge">{{ draftEvents.length }} 条</span>
      </div>
      <BaseEmptyState v-if="!draftEvents.length" description="暂无作者稿事件。" />
      <ol v-else class="draft-event-list">
        <li v-for="event in draftEvents" :key="event.event_id || `${event.event_type}-${event.created_at}`">
          <strong>{{ eventTypeLabel(event.event_type) }}</strong>
          <span v-if="eventNote(event)" class="muted">{{ eventNote(event) }}</span>
        </li>
      </ol>
    </section>

    <section class="deep-structure" data-testid="author-structure-candidates">
      <div class="receipt-head compact">
        <div><h4>反向提取戏剧卡</h4><p class="muted receipt-copy">从当前作者稿生成结构候选；应用后只更新戏剧卡，不改正文、不改运行终稿。</p></div>
        <span class="badge">{{ structureCandidates.length }} 条</span>
      </div>
      <div class="field-inline deep-structure-controls">
        <button data-testid="structure-extract-run" :disabled="!desk.authorDraft || !draftContent.trim() || desk.actionId === 'structure-extract'" @click="extractAuthorStructure">
          {{ desk.actionId === "structure-extract" ? "提取中..." : "反向提取戏剧卡" }}
        </button>
        <span class="muted">AI 理解只进入候选审核，不自动成为权威设定。</span>
      </div>
      <FlowActionReceipt :receipt="receipt(STRUCTURE_SCOPE)" />
      <BaseEmptyState v-if="!structureCandidates.length" description="还没有结构候选。写一段作者稿后，可以先让系统反向理解它。" />
      <article v-for="candidate in structureCandidates" :key="candidate.candidate_id" class="deep-structure-row">
        <div class="receipt-head compact">
          <div><strong>结构候选</strong><p class="muted">{{ candidate.source_text_ref }}</p></div>
          <span class="badge">{{ statusLabel(candidate.status) }}</span>
        </div>
        <dl class="structure-field-grid">
          <template v-for="field in structureFieldRows(candidate)" :key="field.key">
            <dt>{{ field.label }}</dt><dd>{{ field.value }}</dd>
          </template>
        </dl>
        <p v-if="candidate.rationale" class="muted">{{ candidate.rationale }}</p>
        <ul v-if="uncertaintyNotes(candidate).length" class="uncertainty-list">
          <li v-for="note in uncertaintyNotes(candidate)" :key="note">{{ note }}</li>
        </ul>
        <div class="card-actions">
          <button type="button" data-testid="author-structure-apply" :disabled="desk.actionId.startsWith('structure-') || candidate.status !== 'candidate'" @click="applyStructureCandidate(candidate)">应用到戏剧卡</button>
          <button type="button" class="ghost" data-testid="author-structure-reject" :disabled="desk.actionId.startsWith('structure-') || candidate.status !== 'candidate'" @click="rejectStructureCandidate(candidate)">拒绝候选</button>
          <button type="button" class="ghost" @click="copyStructureCandidateNote(candidate)">复制为备注</button>
        </div>
      </article>
    </section>

    <section class="deep-selection">
      <div class="receipt-head compact">
        <div><h4>局部选段</h4><p class="muted receipt-copy">粘贴或保留一段作者稿正文，候选只针对这个片段生成。</p></div>
        <span class="badge">author_draft_only</span>
      </div>
      <textarea v-model="selectedExcerpt" class="control-input deep-selection-input" :placeholder="excerptPlaceholder" />
      <div class="field-inline deep-selection-controls">
        <select v-model="issueDimension" class="control-input" aria-label="问题维度">
          <option value="">使用首个诊断维度</option>
          <option v-for="finding in findings" :key="`${finding.lens}-${finding.dimension}-${finding.issue}`" :value="finding.dimension">
            {{ finding.dimension }} / {{ severityLabel(finding.severity) }}
          </option>
        </select>
        <button data-testid="patch-candidate-create" :disabled="!desk.authorDraft || !patchExcerpt.trim() || desk.actionId === 'patch-create'" @click="createPatchCandidate">生成局部候选</button>
      </div>
    </section>
    <FlowActionReceipt :receipt="receipt(PATCH_SCOPE)" />
  </main>
</template>

<style scoped>
.deep-desk-reader {
  display: grid;
  gap: 1rem;
}

.deep-structure,
.author-next-actions,
.draft-proposal-panel {
  display: grid;
  gap: 1rem;
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
.draft-proposal-panel {
  display: grid;
  gap: 0.7rem;
  padding-top: 0.4rem;
  border-top: 1px dashed var(--line);
}

.author-radar-strip {
  display: grid;
  grid-template-columns: minmax(0, 0.82fr) minmax(0, 1.18fr);
  gap: 0.7rem;
}

.author-radar-card,
.author-action-card {
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

.author-action-grid {
  display: grid;
  gap: 0.7rem;
}

.author-action-card dl {
  display: grid;
  grid-template-columns: 5.5rem minmax(0, 1fr);
  gap: 0.4rem 0.7rem;
  margin: 0;
}

.author-action-card dt {
  color: var(--muted);
}

.author-action-card dd {
  margin: 0;
  line-height: 1.55;
  overflow-wrap: anywhere;
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

.draft-proposal-row,
.deep-structure-row {
  display: grid;
  gap: 0.65rem;
  padding: 0.85rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.58);
}

.draft-proposal-row p,
.deep-structure-row p {
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
  display: grid;
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

.uncertainty-list {
  display: grid;
  gap: 0.35rem;
  margin: 0;
  padding-left: 1.1rem;
  color: var(--muted);
  line-height: 1.5;
}

.proposal-text {
  max-height: 16rem;
  overflow: auto;
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.75;
}

@media (max-width: 1360px) {
  .author-radar-strip,
  .draft-layer-strip {
    grid-template-columns: 1fr;
  }

  .author-draft-editor {
    max-height: none;
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
