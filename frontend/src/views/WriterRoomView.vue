<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ArrowRight, Check, Eye, FileText, RefreshCw, Save, Sparkles, X } from "lucide-vue-next";

import CompactEntitySelect from "../components/CompactEntitySelect.vue";
import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import PanelShell from "../components/PanelShell.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { compactEntityOptions, formatChapterChoice, formatSceneChoice } from "../lib/readableRefs";
import { useShellRouter } from "../router";
import { useWriterRoomStore } from "../stores/writerRoom";

const emit = defineEmits(["notice"]);

const room = useWriterRoomStore();
const { focusTarget, navigate, routeContext, settleFocusView } = useShellRouter();
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const WRITER_DRAFT_SCOPE = "writer-room:draft";
const WRITER_PROPOSAL_SCOPE = "writer-room:proposal";

const proposalModeOptions = [
  { value: "structure", label: "结构" },
  { value: "dialogue", label: "对白" },
  { value: "language", label: "语言" },
  { value: "continuation", label: "续写" },
  { value: "near_final", label: "近终稿" },
];
const proposalInstruction = ref("");
const autoSaveState = ref("idle");
const chapters = computed(() => room.navigation?.chapters || []);
const scenes = computed(() => room.navigation?.scenes || []);
const chapterChoiceState = computed(() =>
  compactEntityOptions(chapters.value, {
    idKey: "chapter_id",
    titleKeys: ["chapter_title", "chapter_goal"],
    selectedId: room.selectedChapterId,
    formatter: formatChapterChoice,
  }),
);
const sceneChoiceState = computed(() =>
  compactEntityOptions(scenes.value, {
    idKey: "scene_id",
    titleKeys: ["scene_title", "scene_goal"],
    selectedId: room.selectedSceneId,
    formatter: formatSceneChoice,
  }),
);
const chapterOptions = computed(() => chapterChoiceState.value.options);
const sceneOptions = computed(() => sceneChoiceState.value.options);
const selectedProposalMode = computed({
  get: () => room.proposalMode || "near_final",
  set: (value) => {
    room.proposalMode = value;
  },
});
const draftContent = computed({
  get: () => room.draftContent,
  set: (value) => room.setDraftContent(value),
});
const title = computed(() => {
  if (room.sceneCard?.scene_goal) {
    return room.sceneCard.scene_goal;
  }
  if (room.chapter?.chapter_goal) {
    return room.chapter.chapter_goal;
  }
  return "先选一章或一场，开始写正文";
});
const draftStatus = computed(() => {
  if (!room.draft?.draft_id) {
    return "尚未建立作者草稿";
  }
  const dirty = room.draftDirty ? "有未保存修改" : "已保存";
  return `${dirty} / 第 ${room.draft.revision_no || 0} 版`;
});
const keepAdvice = computed(() => room.keepAdvice || room.diagnosis?.keep || "先保留最有张力的一处，再动刀。");
const proposalCards = computed(() => room.proposalCards.length ? room.proposalCards : room.proposals);
const longformCards = computed(() => room.longformCards.length ? room.longformCards : room.contextPressure);
const proposalCount = computed(() => proposalCards.value.filter((proposal) => proposal.status !== "rejected").length);
const diffPreview = computed(() => room.proposalDiff || null);
const returnContext = computed(() => routeContext.value?.returnTo ? routeContext.value : null);
const draftStatusLabel = computed(() => {
  if (autoSaveState.value === "saving") return "保存中...";
  if (autoSaveState.value === "saved" && !room.draftDirty) return "已自动保存";
  if (autoSaveState.value === "error") return "保存失败";
  return draftStatus.value;
});
let autoSaveTimer = null;
let autoSavePromise = null;

function clearAutoSaveTimer() {
  if (autoSaveTimer) {
    window.clearTimeout(autoSaveTimer);
    autoSaveTimer = null;
  }
}

function scheduleAutoSave() {
  clearAutoSaveTimer();
  if (!room.draft?.draft_id || !room.draftDirty) {
    if (!room.draftDirty && autoSaveState.value !== "saving") {
      autoSaveState.value = "idle";
    }
    return;
  }
  autoSaveState.value = "dirty";
  autoSaveTimer = window.setTimeout(() => {
    runAutoSave().catch(() => {});
  }, 1500);
}

async function runAutoSave() {
  if (!room.draft?.draft_id || !room.draftDirty) {
    return room.draft;
  }
  if (autoSavePromise) {
    return autoSavePromise;
  }
  autoSaveState.value = "saving";
  autoSavePromise = room.saveDraft({ note: "auto-saved from writer room" })
    .then((draft) => {
      autoSaveState.value = "saved";
      return draft;
    })
    .catch((error) => {
      autoSaveState.value = "error";
      emit("notice", "保存失败");
      throw error;
    })
    .finally(() => {
      autoSavePromise = null;
      if (room.draftDirty) {
        scheduleAutoSave();
      }
    });
  return autoSavePromise;
}

function handleBeforeUnload(event) {
  if (!room.draftDirty) {
    return;
  }
  event.preventDefault();
  event.returnValue = "";
}

function proposalTitle(proposal) {
  return proposal.display_kind || proposal.title || proposal.summary || proposal.proposal_type || proposal.proposal_kind || "可采纳改法";
}

function proposalExcerpt(proposal) {
  return proposal.excerpt || proposal.replacement_text || proposal.content || proposal.description || "";
}

function pressureTitle(card) {
  return card.title || card.card_type || "长篇压力";
}

function pressureSummary(card) {
  const recommendation = card.recommendation || {};
  if (typeof recommendation === "string") {
    return recommendation;
  }
  return recommendation.summary || recommendation.action || card.summary || card.issue || "先确认这一处是否会影响后续章节。";
}

function focusTargetLoad() {
  const target = focusTarget.value || {};
  if (!target.target_type || !target.target_id) {
    return null;
  }
  if (["scene_card", "scene_memory", "final_scene", "scene_attempt", "author_draft_scene"].includes(target.target_type)) {
    return { objectType: "scene", objectId: target.target_id };
  }
  if (["chapter_goal", "chapter_manuscript", "author_draft_chapter"].includes(target.target_type)) {
    return { objectType: "chapter", objectId: target.target_id };
  }
  return null;
}

async function loadInitial({ force = false } = {}) {
  if (room.loading) {
    return;
  }
  try {
    const focused = focusTargetLoad();
    if (focused) {
      await room.load(focused.objectType, focused.objectId);
      settleFocusView("writer-room");
      return;
    }
    if (room.loaded && room.objectId && !force) {
      return;
    }
    if (room.objectId && force) {
      await room.load(room.objectType, room.objectId);
      return;
    }
    await room.loadDefault();
  } catch (error) {
    emit("notice", error.message);
  }
}

async function selectChapter(value) {
  const chapterId = typeof value === "string" ? value : value?.target?.value;
  if (!chapterId) {
    return;
  }
  try {
    await room.load("chapter", chapterId);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function selectScene(value) {
  const sceneId = typeof value === "string" ? value : value?.target?.value;
  if (!sceneId) {
    return;
  }
  try {
    await room.load("scene", sceneId);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function saveDraft() {
  clearAutoSaveTimer();
  await runFlowAction({
    scopeKey: WRITER_DRAFT_SCOPE,
    actionLabel: "保存正文",
    runningMessage: "正在保存作者正文...",
    successMessage: () => "正文已保存为作者草稿的新版本。",
    nextStep: () => "下一步：比较候选或继续小修正文。",
    action: () => room.saveDraft(),
  });
  autoSaveState.value = "saved";
}

async function previewProposal(proposal) {
  await runFlowAction({
    scopeKey: WRITER_PROPOSAL_SCOPE,
    actionLabel: "预览改法",
    runningMessage: "正在生成差异预览...",
    successMessage: () => "差异预览已生成。",
    nextStep: () => "下一步：确认是否采纳这条改法。",
    action: () => room.previewProposal(proposal),
  });
}

async function applyProposal(proposal) {
  await runFlowAction({
    scopeKey: WRITER_PROPOSAL_SCOPE,
    actionLabel: "采纳改法",
    runningMessage: "正在把改法写入作者草稿...",
    successMessage: () => "改法已写入作者草稿的新版本。",
    nextStep: () => "下一步：保存并继续小修正文，或回到审核收件箱处理风险。",
    action: () => room.applyProposal(proposal, {
      apply_mode: proposal.proposal_kind || "replace",
    }),
  });
}

async function generateProposalSet() {
  const issueExcerpt = room.topIssue?.evidence_excerpt;
  await runFlowAction({
    scopeKey: WRITER_PROPOSAL_SCOPE,
    actionLabel: "生成改法",
    runningMessage: "正在生成可比较改法...",
    successMessage: () => "已生成三种可比较改法。",
    nextStep: () => "下一步：先预览差异，再采纳或放弃。",
    action: () => room.generateProposalSet({
      mode: selectedProposalMode.value,
      instruction: proposalInstruction.value,
      target_range: issueExcerpt ? { unit: "text", source_excerpt: issueExcerpt } : undefined,
    }),
  });
}

async function rejectProposal(proposal) {
  const note = typeof window === "undefined"
    ? ""
    : (window.prompt("为什么不采用这个改法？可留空，系统会把原因当作写作偏好参考。", "") || "");
  const preference_remembered = note.trim();
  await runFlowAction({
    scopeKey: WRITER_PROPOSAL_SCOPE,
    actionLabel: "放弃改法",
    runningMessage: "正在记录作者决定...",
    successMessage: () => preference_remembered ? "已标记为不采纳，写作偏好已记录。 preference_remembered" : "已标记为不采纳。",
    nextStep: () => "下一步：继续比较其它候选或回到正文。",
    action: () => room.rejectProposal(proposal, { note }),
  });
}

watch(() => room.draftContent, scheduleAutoSave);
watch(() => room.draftDirty, (dirty) => {
  if (dirty) {
    scheduleAutoSave();
  } else if (autoSaveState.value !== "saving") {
    clearAutoSaveTimer();
  }
});

onMounted(() => {
  loadInitial();
  if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", handleBeforeUnload);
  }
});
onActivated(() => loadInitial());
onBeforeUnmount(() => {
  clearAutoSaveTimer();
  if (typeof window !== "undefined") {
    window.removeEventListener("beforeunload", handleBeforeUnload);
  }
});
</script>

<template>
  <section class="writer-room-view" data-testid="writer-room-view">
    <WorkflowPageHeader view-id="writer-room" kicker="正文优先" />

    <PanelShell
      eyebrow="Writing Room"
      title="写作房间"
      description="先写正文，再看诊断和改法；运行证据留在高级页面里。"
    >
      <template #actions>
        <button type="button" class="ghost" :disabled="room.loading" @click="loadInitial({ force: true })">
          <RefreshCw :size="16" />
          刷新
        </button>
        <button type="button" :disabled="!room.draft?.draft_id || !room.draftDirty || room.actionId === 'draft-save'" @click="saveDraft">
          <Save :size="16" />
          保存
        </button>
      </template>

      <FlowActionReceipt :receipt="receipt(WRITER_DRAFT_SCOPE)" />
      <button
        v-if="returnContext"
        type="button"
        class="ghost writer-room-return"
        data-testid="writer-room-return-to-flow"
        @click="navigate(returnContext.returnTo, { target: { target: returnContext.returnTarget || room.target?.project_id || room.chapter?.project_id || '' } })"
      >
        {{ returnContext.returnLabel || "返回" }}
      </button>
      <div class="writer-room-context-strip" data-testid="writer-room-context-strip" aria-live="polite">
        <span class="badge">{{ room.selectedSceneId ? "场景小修" : "章节小修" }}</span>
        <strong>{{ title }}</strong>
        <span class="badge" :class="{ active: room.draftDirty || autoSaveState === 'saving', danger: autoSaveState === 'error' }">{{ draftStatusLabel }}</span>
      </div>

      <div class="writer-room-grid">
        <aside class="writer-room-nav" aria-label="章节与场景">
          <CompactEntitySelect
            label="章节"
            :model-value="room.selectedChapterId"
            :options="chapterOptions"
            :folded-count="chapterChoiceState.hiddenCount"
            placeholder="选择章节"
            test-id="writer-room-chapter-select"
            @change="selectChapter"
          />

          <CompactEntitySelect
            label="场景"
            :model-value="room.selectedSceneId"
            :options="sceneOptions"
            :folded-count="sceneChoiceState.hiddenCount"
            placeholder="整章草稿"
            test-id="writer-room-scene-select"
            @change="selectScene"
          />

          <section class="writer-room-brief">
            <h3>{{ title }}</h3>
            <dl>
              <dt>欲望</dt>
              <dd>{{ room.sceneCard?.writer_brief_json?.character_desire || room.sceneCard?.visible_desire || "待补" }}</dd>
              <dt>阻力</dt>
              <dd>{{ room.sceneCard?.writer_brief_json?.obstacle || room.sceneCard?.obstacle || "待补" }}</dd>
              <dt>代价</dt>
              <dd>{{ room.sceneCard?.writer_brief_json?.stakes || room.sceneCard?.price_paid || "待补" }}</dd>
            </dl>
          </section>

          <div class="writer-room-jumps">
            <button type="button" class="ghost" @click="navigate('author')">
              编排
              <ArrowRight :size="15" />
            </button>
            <button type="button" class="ghost" @click="navigate('workbench')">
              运行
              <ArrowRight :size="15" />
            </button>
            <button type="button" class="ghost" @click="navigate('deepdesk')">
              深改
              <ArrowRight :size="15" />
            </button>
          </div>
        </aside>

        <main class="writer-room-editor">
          <div class="writer-room-editor-head">
            <div>
              <span class="eyebrow">Author Draft</span>
              <h3>正文</h3>
            </div>
            <span class="badge" :class="{ active: room.draftDirty || autoSaveState === 'saving', danger: autoSaveState === 'error' }">{{ draftStatusLabel }}</span>
          </div>

          <textarea
            v-model="draftContent"
            class="writer-room-textarea"
            spellcheck="false"
            placeholder="在这里写作者草稿。运行稿只是来源，终稿由你确认。"
          />
        </main>

        <aside class="writer-room-side" aria-label="诊断与改法">
          <section class="writer-room-focus">
            <div class="writer-room-section-head">
              <div>
                <span class="eyebrow">Focus</span>
                <h3>最该改的一处</h3>
              </div>
            </div>
            <p v-if="room.topIssue" class="writer-room-main-advice">{{ room.topIssue.issue }}</p>
            <p v-else class="muted">暂无诊断。先写一版，再让系统只指出最影响阅读的一处。</p>
            <p v-if="room.topIssue?.recommendation" class="muted">{{ room.topIssue.recommendation }}</p>
            <div class="writer-room-keep">
              <FileText :size="16" />
              <span>{{ keepAdvice }}</span>
            </div>
          </section>

          <section class="writer-room-proposals">
            <div class="writer-room-section-head">
              <div>
                <span class="eyebrow">Proposals</span>
                <h3>可采纳改法</h3>
              </div>
              <span class="badge">{{ proposalCount }} 条</span>
            </div>

            <div class="writer-room-mode-strip" role="group" aria-label="写作任务模式">
              <button
                v-for="option in proposalModeOptions"
                :key="option.value"
                type="button"
                class="ghost"
                :class="{ active: selectedProposalMode === option.value }"
                :data-testid="option.value === 'near_final' ? 'writer-room-proposal-mode-near_final' : `writer-room-proposal-mode-${option.value}`"
                @click="selectedProposalMode = option.value"
              >
                {{ option.label }}
              </button>
            </div>
            <div class="writer-room-generate-row">
              <input
                v-model="proposalInstruction"
                type="text"
                placeholder="本轮改法重点"
                aria-label="本轮改法重点"
              />
              <button type="button" :disabled="room.actionId === 'proposal-generate-set'" @click="generateProposalSet">
                <Sparkles :size="15" />
                生成
              </button>
            </div>
            <FlowActionReceipt compact :receipt="receipt(WRITER_PROPOSAL_SCOPE)" />

            <div v-if="!proposalCards.length" class="empty">还没有候选改法。</div>
            <article v-for="proposal in proposalCards" :key="proposal.proposal_id" class="writer-room-proposal">
              <div class="writer-room-proposal-head">
                <strong>{{ proposalTitle(proposal) }}</strong>
                <span class="badge">{{ proposal.merge_status || proposal.status || "待比较" }}</span>
              </div>
              <p>{{ proposalExcerpt(proposal) || "先预览差异，再决定是否写入作者草稿。" }}</p>
              <div class="card-actions">
                <button type="button" class="ghost" :disabled="room.actionId.includes(proposal.proposal_id)" @click="previewProposal(proposal)">
                  <Eye :size="15" />
                  预览
                </button>
                <button
                  type="button"
                  :disabled="proposal.status === 'rejected' || proposal.merge_status === 'applied' || room.actionId.includes(proposal.proposal_id)"
                  @click="applyProposal(proposal)"
                >
                  <Check :size="15" />
                  采纳
                </button>
                <button
                  type="button"
                  class="ghost"
                  :disabled="proposal.status === 'rejected' || proposal.merge_status === 'applied' || room.actionId.includes(proposal.proposal_id)"
                  @click="rejectProposal(proposal)"
                >
                  <X :size="15" />
                  放弃
                </button>
              </div>
            </article>
          </section>

          <section v-if="diffPreview" class="writer-room-diff" data-testid="writer-room-proposal-diff">
            <div class="writer-room-section-head">
              <h3>差异预览</h3>
              <span class="badge">{{ diffPreview.merge_status || "clean" }}</span>
            </div>
            <div class="writer-room-diff-grid">
              <pre>{{ diffPreview.before_text || "" }}</pre>
              <pre>{{ diffPreview.after_text || "" }}</pre>
            </div>
          </section>

          <section class="writer-room-pressure">
            <div class="writer-room-section-head">
              <div>
                <span class="eyebrow">Longform</span>
                <h3>后续压力</h3>
              </div>
            </div>
            <div v-if="!longformCards.length" class="empty">暂无高优先级长篇提醒。</div>
            <article v-for="card in longformCards" :key="card.card_id || card.title" class="writer-room-pressure-row">
              <strong>{{ pressureTitle(card) }}</strong>
              <p>{{ pressureSummary(card) }}</p>
            </article>
          </section>
        </aside>
      </div>
    </PanelShell>
  </section>
</template>

<style scoped>
.writer-room-view {
  display: grid;
  gap: 1rem;
}

.writer-room-grid {
  display: grid;
  grid-template-columns: minmax(16rem, 20rem) minmax(0, 1fr) minmax(18rem, 22rem);
  gap: 1rem;
  align-items: start;
}

.writer-room-context-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  align-items: center;
  min-width: 0;
  padding: 0.75rem 0.85rem;
  border: 1px solid rgba(47, 111, 98, 0.16);
  border-radius: 8px;
  background: rgba(237, 247, 242, 0.76);
}

.writer-room-return {
  justify-self: start;
}

.writer-room-context-strip strong {
  min-width: min(100%, 14rem);
  flex: 1 1 18rem;
  overflow-wrap: anywhere;
  line-height: 1.45;
}

.writer-room-nav,
.writer-room-editor,
.writer-room-side,
.writer-room-focus,
.writer-room-proposals,
.writer-room-diff,
.writer-room-pressure,
.writer-room-brief {
  display: grid;
  gap: 0.85rem;
  min-width: 0;
}

.writer-room-field {
  display: grid;
  gap: 0.35rem;
}

.writer-room-field span {
  color: var(--muted);
  font-size: 0.82rem;
}

.writer-room-brief {
  padding-top: 0.35rem;
  border-top: 1px dashed var(--line);
}

.writer-room-brief h3,
.writer-room-editor h3,
.writer-room-side h3 {
  margin: 0;
}

.writer-room-brief dl {
  display: grid;
  grid-template-columns: 3rem minmax(0, 1fr);
  gap: 0.45rem 0.65rem;
  margin: 0;
}

.writer-room-brief dt {
  color: var(--muted);
}

.writer-room-brief dd {
  margin: 0;
  overflow-wrap: anywhere;
  line-height: 1.55;
}

.writer-room-jumps {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.writer-room-jumps button,
.writer-room-editor-head,
.writer-room-section-head,
.writer-room-proposal-head,
.writer-room-keep {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.writer-room-editor-head,
.writer-room-section-head,
.writer-room-proposal-head {
  justify-content: space-between;
  min-width: 0;
}

.writer-room-editor-head > div,
.writer-room-section-head > div,
.writer-room-proposal-head > strong {
  min-width: 0;
}

.writer-room-textarea {
  width: 100%;
  min-width: 0;
  min-height: 58vh;
  max-height: 72vh;
  resize: vertical;
  padding: 1.1rem;
  color: #24221e;
  line-height: 1.9;
  white-space: pre-wrap;
}

.writer-room-main-advice {
  margin: 0;
  font-size: 1.02rem;
  line-height: 1.7;
}

.writer-room-keep {
  align-items: flex-start;
  padding: 0.7rem;
  border: 1px solid rgba(37, 51, 66, 0.12);
  border-radius: 8px;
  background: rgba(82, 104, 91, 0.08);
  line-height: 1.55;
}

.writer-room-proposal,
.writer-room-pressure-row {
  display: grid;
  gap: 0.65rem;
  padding: 0.8rem;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.58);
}

.writer-room-mode-strip,
.writer-room-generate-row {
  display: flex;
  gap: 0.5rem;
  min-width: 0;
}

.writer-room-mode-strip {
  flex-wrap: wrap;
}

.writer-room-mode-strip button {
  min-height: 2.15rem;
}

.writer-room-mode-strip button.active {
  border-color: rgba(41, 82, 96, 0.32);
  background: rgba(41, 82, 96, 0.12);
  color: #1f4753;
}

.writer-room-generate-row input {
  min-width: 0;
  flex: 1;
}

.writer-room-proposal p,
.writer-room-pressure-row p {
  margin: 0;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.writer-room-diff-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.6rem;
}

.writer-room-diff-grid pre {
  max-height: 14rem;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  line-height: 1.55;
}

.badge.active {
  border-color: rgba(143, 47, 38, 0.24);
  background: rgba(143, 47, 38, 0.1);
}

@media (max-width: 1320px) {
  .writer-room-grid {
    grid-template-columns: 1fr;
  }

  .writer-room-textarea {
    max-height: none;
  }

  .writer-room-diff-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .writer-room-view,
  .writer-room-grid,
  .writer-room-nav,
  .writer-room-editor,
  .writer-room-side {
    min-width: 0;
  }

  .writer-room-context-strip,
  .writer-room-editor-head,
  .writer-room-section-head,
  .writer-room-proposal-head,
  .writer-room-generate-row {
    align-items: stretch;
    flex-direction: column;
  }

  .writer-room-context-strip strong,
  .writer-room-generate-row input {
    flex-basis: auto;
    width: 100%;
  }

  .writer-room-mode-strip button,
  .writer-room-generate-row button,
  .writer-room-jumps button,
  .writer-room-editor-head button,
  .writer-room-section-head button,
  .writer-room-proposal-head button {
    min-height: 44px;
  }

  .writer-room-mode-strip button,
  .writer-room-generate-row button {
    flex: 1 1 100%;
  }

  .writer-room-textarea {
    min-height: 46vh;
    padding: 0.9rem;
  }
}
</style>

