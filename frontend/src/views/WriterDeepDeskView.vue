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

const issueDimension = ref("");

const chapters = computed(() => desk.chapters || []);
const scenes = computed(() => desk.availableScenes || []);
const findings = computed(() => desk.findings || []);
const lensEvaluations = computed(() => desk.lensEvaluations || []);
const candidates = computed(() => desk.candidateRows || []);
const preference = computed(() => desk.preferenceProfile || null);
const profileSummary = computed(() => preference.value?.summary || {});
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
  }[value] || value || "-";
}

function scoreLabel(value) {
  return value === null || value === undefined ? "-" : `${Math.round(Number(value) * 100)} 分`;
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
      eyebrow="作家改稿台"
      title="诊断归诊断，改稿归作者"
      description="作者稿是独立创作层：AI 可以诊断、生成候选、记录偏好，但不会自动覆盖 FinalScene 或 ChapterMemory。"
    >
      <template #actions>
        <div class="field-inline deep-desk-actions">
          <button data-testid="deep-desk-refresh" :disabled="desk.loading" @click="refreshDesk">
            {{ desk.loading ? "刷新中..." : "刷新" }}
          </button>
          <button class="ghost" @click="openManuscripts">返回成稿中心</button>
        </div>
      </template>

      <div v-if="desk.loading" class="empty">正在载入深改台...</div>
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
                <p class="muted receipt-copy">场景稿从当前 FinalScene 创建。</p>
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
            placeholder="这里会载入作者稿。若还没有作者稿，系统会从运行终稿创建一份独立副本。"
          />
          <div class="draft-save-row">
            <span class="badge" :class="{ active: desk.draftDirty }">
              {{ desk.draftDirty ? "未保存" : "已保存" }}
            </span>
            <span class="muted">{{ draftContent.length }} 字</span>
            <button
              data-testid="author-draft-save"
              :disabled="!desk.authorDraft || !desk.draftDirty || desk.actionId === 'draft-save'"
              @click="saveDraft"
            >
              {{ desk.actionId === "draft-save" ? "保存中..." : "保存作者稿" }}
            </button>
          </div>
          <FlowActionReceipt :receipt="receipt(DRAFT_SCOPE)" />

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
          <FlowActionReceipt :receipt="receipt(REVIEW_SCOPE)" />

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
              <strong>{{ candidate.issue_dimension }}</strong>
              <p class="muted">{{ candidate.source_excerpt }}</p>
              <small v-if="candidate.rationale" class="muted">{{ candidate.rationale }}</small>
            </div>
            <span class="badge">{{ statusLabel(candidate.status) }}</span>
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
.deep-preference-grid {
  display: grid;
  gap: 0.8rem;
}

.deep-finding,
.deep-option,
.deep-candidate-row,
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
.deep-preference p {
  margin: 0;
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

.deep-lens-row {
  display: flex;
  justify-content: space-between;
  gap: 0.8rem;
  padding: 0.55rem 0;
  border-bottom: 1px solid rgba(37, 51, 66, 0.1);
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

.deep-option button {
  justify-self: start;
}

.deep-candidates,
.deep-preference {
  margin-top: 1rem;
}

.deep-preference-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

@media (max-width: 1200px) {
  .deep-desk-shell,
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
}
</style>
