<script setup>
import { computed, onActivated, onMounted, ref } from "vue";
import {
  BookOpenCheck,
  Check,
  FileText,
  FolderOpen,
  Link,
  PenLine,
  Play,
  Plus,
  RefreshCw,
  WandSparkles,
} from "lucide-vue-next";

import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useShellRouter } from "../router";
import { useProjectDashboardStore } from "../stores/projectDashboard";

const emit = defineEmits(["notice"]);

const dashboard = useProjectDashboardStore();
const { navigate, openTarget } = useShellRouter();

const project = computed(() => dashboard.project);
const latestPlan = computed(() => dashboard.latestPlan);
const chapters = computed(() => dashboard.planChapters);
const snowflake = computed(() => dashboard.snowflakeState);
const snowflakeSteps = computed(() => dashboard.snowflakeSteps);
const currentSnowflakeStep = computed(() => dashboard.currentSnowflakeStep);
const currentSnowflakeArtifact = computed(() => currentSnowflakeStep.value?.artifact || null);
const isSnowflakeProject = computed(() => project.value?.planning_mode === "snowflake");
const currentChapterId = computed(() => project.value?.current_chapter_id || dashboard.currentChapter?.chapter_id || "");
const currentChapter = computed(() =>
  (dashboard.dashboard?.chapters || []).find((chapter) => chapter.chapter_id === currentChapterId.value)
  || dashboard.currentChapter
  || chapters.value.find((chapter) => chapter.chapter_id === currentChapterId.value)
  || null,
);
const reviewPacket = computed(() => dashboard.reviewPacket);
const referenceProfiles = computed(() => dashboard.referenceProfiles);
const backtrackItems = computed(() => dashboard.pendingBacktrackItems);
const backtrackNotes = ref({});

const stageCards = computed(() => [
  {
    key: "outline",
    label: isSnowflakeProject.value ? "雪花规划" : "大纲",
    status: project.value ? "done" : "active",
  },
  {
    key: "plan",
    label: "结构确认",
    status: latestPlan.value?.status === "approved" ? "done" : latestPlan.value ? "active" : "waiting",
  },
  {
    key: "chapter",
    label: "逐章运行",
    status: ["chapter_ready", "chapter_running", "chapter_blocked"].includes(project.value?.status) ? "active" : project.value?.status === "completed" ? "done" : "waiting",
  },
  {
    key: "final",
    label: "终稿确认",
    status: project.value?.status === "chapter_final_review" ? "active" : project.value?.status === "completed" ? "done" : "waiting",
  },
]);

function statusLabel(status) {
  const labels = {
    outline_draft: "待拆解",
    outline_review: "待确认结构",
    chapter_ready: "可运行章节",
    chapter_running: "运行中",
    chapter_blocked: "有阻塞",
    chapter_final_review: "待终稿确认",
    completed: "已完成",
    pending_review: "待确认",
    approved: "已确认",
  };
  return labels[status] || status || "未开始";
}

function actionDisabled(actionId) {
  return Boolean(dashboard.actionId && dashboard.actionId !== actionId);
}

function snowflakeStatusLabel(status) {
  const labels = {
    pending_review: "待确认",
    approved: "已确认",
    skipped: "已跳过",
    stale: "需重做",
    superseded: "已替换",
  };
  return labels[status] || status || "未生成";
}

function snowflakeStepStatus(step) {
  if (step.gate_satisfied) {
    return "done";
  }
  if (step.artifact?.status === "stale") {
    return "stale";
  }
  if (step.step_key === snowflake.value?.current_step_key) {
    return "active";
  }
  return "waiting";
}

function currentArtifactJson() {
  if (!dashboard.snowflakeEditDraft.trim()) {
    return null;
  }
  return JSON.parse(dashboard.snowflakeEditDraft);
}

async function guarded(task) {
  try {
    return await task();
  } catch (error) {
    emit("notice", error.message);
    return null;
  }
}

async function initialize(force = false) {
  await guarded(() => dashboard.initialize({ force }));
}

async function createProject() {
  const projectPayload = await guarded(() => dashboard.createFromDraft());
  if (projectPayload) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function generatePlan() {
  const plan = await guarded(() => dashboard.generateOutlinePlan());
  if (plan) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function generateSnowflake() {
  const artifact = await guarded(() => dashboard.generateCurrentSnowflakeStep());
  if (artifact) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function saveSnowflakeArtifact() {
  const artifactId = currentSnowflakeArtifact.value?.artifact_id;
  if (!artifactId) {
    emit("notice", "请先生成当前雪花候选。");
    return;
  }
  const result = await guarded(() => dashboard.updateSnowflakeArtifact(artifactId, currentArtifactJson()));
  if (result) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function approveSnowflake() {
  const artifactId = currentSnowflakeArtifact.value?.artifact_id;
  if (!artifactId) {
    emit("notice", "请先生成当前雪花候选。");
    return;
  }
  const result = await guarded(() => dashboard.approveSnowflakeArtifact(artifactId));
  if (result) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function materializeSnowflake() {
  const plan = await guarded(() => dashboard.materializeSnowflakePlan());
  if (plan) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function approvePlan() {
  const result = await guarded(() => dashboard.approveOutlinePlan());
  if (result) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function runChapter() {
  const result = await guarded(() => dashboard.runCurrentChapter());
  if (result) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function approveFinal() {
  const result = await guarded(() => dashboard.approveCurrentChapterFinal());
  if (result) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function bindProfile() {
  const result = await guarded(() => dashboard.bindReferenceProfile());
  if (result) {
    emit("notice", dashboard.lastActionMessage);
  }
}

async function resolveBacktrack(item) {
  const note = String(backtrackNotes.value[item.item_id] || "").trim();
  const result = await guarded(() => dashboard.resolveBacktrackItem(item.item_id, note));
  if (result) {
    backtrackNotes.value[item.item_id] = "";
    emit("notice", dashboard.lastActionMessage);
  }
}

function openSmallRevision(objectType = "chapter", objectId = currentChapterId.value) {
  if (!objectId) {
    navigate("writer-room");
    return;
  }
  openTarget({
    target_type: objectType === "scene" ? "author_draft_scene" : "author_draft_chapter",
    target_id: objectId,
    target_ref: `${objectType}:${objectId}`,
    view_id: "writer-room",
  });
}

function firstSceneId(chapter) {
  return chapter?.scenes?.[0]?.scene_id || "";
}

function openBacktrackTarget(item) {
  if (item?.scene_id) {
    openSmallRevision("scene", item.scene_id);
    return;
  }
  if (item?.chapter_id) {
    openSmallRevision("chapter", item.chapter_id);
  }
}

onMounted(() => initialize(false));
onActivated(() => initialize(false));
</script>

<template>
  <section class="project-dashboard-view" data-testid="project-dashboard-view">
    <WorkflowPageHeader view-id="project-dashboard" kicker="大纲驱动" />

    <div class="project-dashboard-grid">
      <aside class="project-sidebar" aria-label="项目列表">
        <div class="project-section-head">
          <div>
            <span class="eyebrow">Projects</span>
            <h2>项目</h2>
          </div>
          <button type="button" class="icon-btn" title="刷新项目" :disabled="dashboard.loading" @click="initialize(true)">
            <RefreshCw :size="16" />
          </button>
        </div>

        <div class="project-list" data-testid="project-list">
          <button
            v-for="item in dashboard.projects"
            :key="item.project_id"
            type="button"
            class="project-row"
            :class="{ active: item.project_id === dashboard.selectedProjectId }"
            @click="dashboard.selectProject(item.project_id)"
          >
            <FolderOpen :size="16" />
            <span>
              <strong>{{ item.title }}</strong>
              <small>{{ statusLabel(item.status) }}</small>
            </span>
          </button>
          <p v-if="!dashboard.projects.length" class="muted">暂无项目。</p>
        </div>

        <form class="project-create-form" data-testid="project-create-form" @submit.prevent="createProject">
          <label>
            <span>标题</span>
            <input v-model="dashboard.draft.title" class="control-input" placeholder="未命名小说" />
          </label>
          <label>
            <span>题材</span>
            <input v-model="dashboard.draft.genre" class="control-input" placeholder="都市 / 玄幻 / 悬疑" />
          </label>
          <div class="project-number-grid">
            <label>
              <span>章节数</span>
              <input v-model="dashboard.draft.target_chapter_count" class="control-input" inputmode="numeric" />
            </label>
            <label>
              <span>目标字数</span>
              <input v-model="dashboard.draft.target_word_count" class="control-input" inputmode="numeric" />
            </label>
          </div>
          <label>
            <span>小说大纲</span>
            <textarea
              v-model="dashboard.draft.outline_text"
              class="control-input outline-editor"
              data-testid="project-outline-input"
              placeholder="粘贴自由文本大纲。"
            />
          </label>
          <button
            type="submit"
            class="primary project-create-button"
            data-testid="project-create-submit"
            :disabled="!dashboard.canCreate || dashboard.actionId === 'create-project'"
          >
            <Plus :size="16" />
            <span>创建项目</span>
          </button>
        </form>
      </aside>

      <main class="project-main">
        <section class="project-control-section project-overview" data-testid="project-overview">
          <div class="project-title-row">
            <div>
              <span class="eyebrow">Control</span>
              <h2>{{ project?.title || "项目总控" }}</h2>
              <p class="muted">{{ project?.genre || "自由大纲" }} · {{ statusLabel(project?.status) }}</p>
            </div>
            <div class="project-primary-actions">
              <button
                type="button"
                class="ghost"
                :disabled="!project || actionDisabled('generate-outline-plan')"
                data-testid="project-generate-plan"
                @click="generatePlan"
              >
                <WandSparkles :size="16" />
                <span>生成结构</span>
              </button>
              <button
                type="button"
                class="primary"
                :disabled="!latestPlan || latestPlan.status === 'approved' || actionDisabled('approve-outline-plan')"
                data-testid="project-approve-plan"
                @click="approvePlan"
              >
                <Check :size="16" />
                <span>确认结构</span>
              </button>
            </div>
          </div>

          <div class="project-stage-strip" data-testid="project-stage-strip">
            <div v-for="card in stageCards" :key="card.key" class="project-stage" :class="card.status">
              <span>{{ card.label }}</span>
              <strong>{{ card.status === "done" ? "完成" : card.status === "active" ? "当前" : "等待" }}</strong>
            </div>
          </div>
        </section>

        <section v-if="isSnowflakeProject" class="project-control-section snowflake-panel" data-testid="project-snowflake-panel">
          <div class="project-section-head">
            <div>
              <span class="eyebrow">Snowflake</span>
              <h2>雪花规划</h2>
            </div>
            <span class="badge">{{ snowflake?.ready_to_materialize ? "可物化" : currentSnowflakeStep?.label || "读取中" }}</span>
          </div>

          <div class="snowflake-layout">
            <div class="snowflake-step-list" data-testid="snowflake-step-list">
              <article
                v-for="step in snowflakeSteps"
                :key="step.step_key"
                class="snowflake-step-row"
                :class="snowflakeStepStatus(step)"
              >
                <span>{{ step.label }}</span>
                <strong>{{ snowflakeStatusLabel(step.artifact?.status) }}</strong>
              </article>
              <p v-if="!snowflakeSteps.length" class="muted">创建雪花项目后会显示十步规划。</p>
            </div>

            <div class="snowflake-workbench">
              <div v-if="currentSnowflakeStep" class="snowflake-current">
                <span class="eyebrow">当前步骤</span>
                <h3>{{ currentSnowflakeStep.label }}</h3>
                <p class="muted">{{ currentSnowflakeStep.description }}</p>
                <p v-if="currentSnowflakeArtifact?.status === 'stale'" class="snowflake-stale stale">
                  上游雪花已修改，本步需要重新生成或重新确认。
                </p>
              </div>
              <div v-else class="snowflake-current">
                <span class="eyebrow">当前步骤</span>
                <h3>雪花规划已完成</h3>
                <p class="muted">可以把已确认的场景列表和场景规划整理为结构计划。</p>
              </div>

              <textarea
                v-model="dashboard.snowflakeEditDraft"
                class="control-input snowflake-artifact-editor"
                data-testid="snowflake-artifact-editor"
                spellcheck="false"
                placeholder="生成候选后，可在这里微调 JSON，再确认本步。"
              />

              <div class="snowflake-actions">
                <button
                  type="button"
                  class="ghost"
                  :disabled="!currentSnowflakeStep || actionDisabled(`snowflake-generate:${currentSnowflakeStep.step_key}`)"
                  data-testid="snowflake-generate-step"
                  @click="generateSnowflake"
                >
                  <WandSparkles :size="16" />
                  <span>生成候选</span>
                </button>
                <button
                  type="button"
                  class="ghost"
                  :disabled="!currentSnowflakeArtifact || actionDisabled(`snowflake-save:${currentSnowflakeArtifact.artifact_id}`)"
                  data-testid="snowflake-save-artifact"
                  @click="saveSnowflakeArtifact"
                >
                  <FileText :size="16" />
                  <span>保存编辑</span>
                </button>
                <button
                  type="button"
                  class="primary"
                  :disabled="!currentSnowflakeArtifact || currentSnowflakeArtifact.status !== 'pending_review' || actionDisabled(`snowflake-approve:${currentSnowflakeArtifact.artifact_id}`)"
                  data-testid="snowflake-approve-artifact"
                  @click="approveSnowflake"
                >
                  <Check :size="16" />
                  <span>确认本步</span>
                </button>
                <button
                  type="button"
                  class="ghost"
                  :disabled="!dashboard.readyToMaterializeSnowflake || actionDisabled('snowflake-materialize')"
                  data-testid="snowflake-materialize-plan"
                  @click="materializeSnowflake"
                >
                  <BookOpenCheck :size="16" />
                  <span>整理成章节结构</span>
                </button>
              </div>
            </div>
          </div>
        </section>

        <section class="project-control-section project-plan" data-testid="project-plan-review">
          <div class="project-section-head">
            <div>
              <span class="eyebrow">Outline Plan</span>
              <h2>结构计划</h2>
            </div>
            <span class="badge">{{ statusLabel(latestPlan?.status) }}</span>
          </div>

          <div v-if="chapters.length" class="chapter-plan-list">
            <article v-for="chapter in chapters" :key="chapter.chapter_id" class="chapter-plan-row">
              <div class="chapter-plan-head">
                <div>
                  <strong>{{ chapter.title || chapter.chapter_id }}</strong>
                  <p>{{ chapter.chapter_goal }}</p>
                </div>
                <span class="badge">{{ chapter.scenes?.length || 0 }} 场</span>
              </div>
              <div class="scene-pill-list">
                <button
                  v-for="scene in chapter.scenes || []"
                  :key="scene.scene_id"
                  type="button"
                  class="scene-pill"
                  @click="openSmallRevision('scene', scene.scene_id)"
                >
                  {{ scene.scene_goal }}
                </button>
              </div>
            </article>
          </div>
          <p v-else class="muted">结构计划生成后会停在这里等待确认。</p>
        </section>

        <section class="project-control-section project-run-panel" data-testid="project-current-chapter">
          <div class="project-section-head">
            <div>
              <span class="eyebrow">Chapter Flow</span>
              <h2>当前章节</h2>
            </div>
            <span class="badge">{{ currentChapterId || "未开始" }}</span>
          </div>
          <div class="current-chapter-body">
            <div>
              <h3>{{ currentChapter?.chapter_goal || "确认结构后开始逐章推进" }}</h3>
              <p class="muted">{{ currentChapter?.main_plot_push || "每次只跑当前章节，完成后停在终稿确认。" }}</p>
            </div>
            <div class="chapter-run-actions">
              <button
                type="button"
                class="primary"
                :disabled="!currentChapterId || actionDisabled(`run:${currentChapterId}`)"
                data-testid="project-run-current-chapter"
                @click="runChapter"
              >
                <Play :size="16" />
                <span>运行本章</span>
              </button>
              <button type="button" class="ghost" :disabled="!currentChapterId" @click="openSmallRevision('chapter', currentChapterId)">
                <PenLine :size="16" />
                <span>小修写作</span>
              </button>
              <button
                type="button"
                class="ghost"
                :disabled="!firstSceneId(currentChapter)"
                @click="openSmallRevision('scene', firstSceneId(currentChapter))"
              >
                <FileText :size="16" />
                <span>场景小修</span>
              </button>
            </div>
          </div>
        </section>

        <section class="project-control-section project-backtrack-panel" data-testid="project-backtrack-panel">
          <div class="project-section-head">
            <div>
              <span class="eyebrow">Backtrack</span>
              <h2>返工项</h2>
            </div>
            <span class="badge">{{ backtrackItems.length ? `${backtrackItems.length} 项待处理` : "无阻塞" }}</span>
          </div>

          <div v-if="backtrackItems.length" class="backtrack-list">
            <article v-for="item in backtrackItems" :key="item.item_id" class="backtrack-row">
              <div class="chapter-plan-head">
                <div>
                  <strong>{{ item.scope }}</strong>
                  <p>{{ item.problem_summary }}</p>
                </div>
                <span class="badge">{{ item.status }}</span>
              </div>
              <p class="muted">{{ item.recommended_fix }}</p>
              <p v-if="item.reason_codes?.length" class="muted">原因：{{ item.reason_codes.join(" / ") }}</p>
              <div class="profile-bind-row">
                <input
                  v-model="backtrackNotes[item.item_id]"
                  class="control-input"
                  :data-testid="`project-backtrack-note-${item.item_id}`"
                  placeholder="关闭说明"
                />
                <button
                  type="button"
                  class="ghost"
                  :disabled="!item.scene_id && !item.chapter_id"
                  :data-testid="`project-backtrack-open-${item.item_id}`"
                  @click="openBacktrackTarget(item)"
                >
                  <PenLine :size="16" />
                  <span>打开对象</span>
                </button>
                <button
                  type="button"
                  class="primary"
                  :disabled="actionDisabled(`resolve-backtrack:${item.item_id}`)"
                  :data-testid="`project-backtrack-resolve-${item.item_id}`"
                  @click="resolveBacktrack(item)"
                >
                  <Check :size="16" />
                  <span>{{ dashboard.actionId === `resolve-backtrack:${item.item_id}` ? "处理中..." : "关闭返工项" }}</span>
                </button>
              </div>
            </article>
          </div>
          <p v-else class="muted">当前没有待处理返工项，章节推进不会被返工门禁阻塞。</p>
        </section>

        <section class="project-control-section project-final-review" data-testid="project-final-review">
          <div class="project-section-head">
            <div>
              <span class="eyebrow">Final Review</span>
              <h2>章节终稿审核包</h2>
            </div>
            <span class="badge">{{ reviewPacket ? "待确认" : "未到达" }}</span>
          </div>

          <div v-if="reviewPacket" class="review-packet">
            <div>
              <strong>{{ reviewPacket.chapter_id }}</strong>
              <p class="muted">{{ reviewPacket.chapter_goal || "本章终稿已生成。" }}</p>
            </div>
            <div class="review-safety">
              <span v-for="rule in reviewPacket.reference_safety || []" :key="rule">{{ rule }}</span>
            </div>
            <div v-if="reviewPacket.issues_summary?.length" class="review-issues">
              <p v-for="issue in reviewPacket.issues_summary" :key="issue.code || issue.message">
                {{ issue.message || issue.code }}
              </p>
            </div>
            <div class="chapter-run-actions">
              <button
                type="button"
                class="primary"
                :disabled="actionDisabled(`approve-final:${reviewPacket.chapter_id}`)"
                data-testid="project-approve-final"
                @click="approveFinal"
              >
                <BookOpenCheck :size="16" />
                <span>批准本章</span>
              </button>
              <button type="button" class="ghost" @click="openSmallRevision('chapter', reviewPacket.chapter_id)">
                <PenLine :size="16" />
                <span>小范围修改</span>
              </button>
            </div>
          </div>
          <p v-else class="muted">当前章节运行完成后，终稿确认会出现在这里。</p>
        </section>
      </main>

      <aside class="project-sidecar" aria-label="参考书画像">
        <section class="project-control-section project-reference-panel" data-testid="project-reference-panel">
          <div class="project-section-head">
            <div>
              <span class="eyebrow">Reference</span>
              <h2>参考书学习</h2>
            </div>
            <button type="button" class="icon-btn" title="打开参考书学习" @click="navigate('reference')">
              <BookOpenCheck :size="16" />
            </button>
          </div>

          <div class="profile-bind-row">
            <input
              v-model="dashboard.profileBindDraft"
              class="control-input"
              data-testid="project-reference-profile-input"
              placeholder="ready 画像 ID"
            />
            <button
              type="button"
              class="ghost"
              :disabled="!dashboard.profileBindDraft || dashboard.actionId === 'bind-reference-profile'"
              data-testid="project-bind-reference-profile"
              @click="bindProfile"
            >
              <Link :size="16" />
              <span>绑定</span>
            </button>
          </div>

          <div class="profile-list">
            <article v-for="profile in referenceProfiles" :key="profile.profile_id" class="profile-row">
              <strong>{{ profile.title || profile.profile_id }}</strong>
              <span>{{ profile.status }}</span>
            </article>
            <p v-if="!referenceProfiles.length" class="muted">只绑定 ready 状态画像。</p>
          </div>
        </section>

        <section class="project-control-section project-message-panel" data-testid="project-action-message">
          <div class="project-section-head">
            <div>
              <span class="eyebrow">Status</span>
              <h2>推进状态</h2>
            </div>
          </div>
          <p>{{ dashboard.lastActionMessage || "等待项目动作。" }}</p>
          <p v-if="dashboard.error" class="project-error">{{ dashboard.error }}</p>
        </section>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.project-dashboard-view {
  display: grid;
  gap: 18px;
}

.project-dashboard-grid {
  display: grid;
  grid-template-columns: minmax(230px, 280px) minmax(0, 1fr) minmax(220px, 300px);
  gap: 16px;
  align-items: start;
}

.project-sidebar,
.project-main,
.project-sidecar {
  display: grid;
  gap: 14px;
}

.project-control-section,
.project-sidebar {
  border: 1px solid rgba(117, 130, 116, 0.2);
  background: rgba(255, 255, 255, 0.82);
  box-shadow: 0 12px 30px rgba(42, 50, 37, 0.08);
}

.project-control-section,
.project-sidebar {
  border-radius: 8px;
  padding: 16px;
}

.project-section-head,
.project-title-row,
.chapter-plan-head,
.current-chapter-body,
.chapter-run-actions,
.project-primary-actions,
.profile-bind-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.project-section-head,
.project-title-row,
.chapter-plan-head,
.current-chapter-body {
  justify-content: space-between;
}

.project-section-head h2,
.project-title-row h2,
.current-chapter-body h3 {
  margin: 3px 0 0;
  line-height: 1.2;
}

.eyebrow {
  color: #687565;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.icon-btn {
  display: inline-grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  border: 1px solid rgba(92, 113, 88, 0.28);
  background: #f6f8f2;
  color: #30412f;
  cursor: pointer;
}

.project-list,
.project-create-form,
.chapter-plan-list,
.backtrack-list,
.profile-list,
.review-packet {
  display: grid;
  gap: 10px;
}

.project-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  text-align: left;
}

.project-row.active {
  border-color: rgba(54, 114, 103, 0.35);
  background: #eef7f2;
}

.project-row strong,
.project-row small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-row small {
  color: #71806d;
}

.project-create-form label {
  display: grid;
  gap: 6px;
}

.project-create-form label span {
  font-size: 0.78rem;
  font-weight: 700;
  color: #576352;
}

.project-number-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.outline-editor {
  min-height: 150px;
  resize: vertical;
}

.project-create-button,
.project-primary-actions button,
.chapter-run-actions button,
.profile-bind-row button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
}

.project-stage-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.project-stage {
  min-height: 64px;
  padding: 10px;
  border-radius: 8px;
  border: 1px solid rgba(109, 124, 108, 0.22);
  background: #f7f7f0;
}

.project-stage span,
.project-stage strong {
  display: block;
}

.project-stage strong {
  margin-top: 8px;
  color: #52604e;
}

.project-stage.active {
  border-color: rgba(204, 128, 58, 0.42);
  background: #fff5e7;
}

.project-stage.done {
  border-color: rgba(42, 130, 106, 0.38);
  background: #eef8f4;
}

.chapter-plan-row,
.backtrack-row,
.profile-row {
  border: 1px solid rgba(117, 130, 116, 0.18);
  border-radius: 8px;
  padding: 12px;
  background: rgba(250, 251, 246, 0.9);
}

.chapter-plan-row p,
.current-chapter-body p,
.review-packet p,
.project-message-panel p {
  margin: 4px 0 0;
}

.scene-pill-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.scene-pill {
  max-width: 100%;
  border: 1px solid rgba(64, 103, 98, 0.22);
  border-radius: 999px;
  background: #f5fbf8;
  color: #314a44;
  padding: 7px 10px;
  overflow-wrap: anywhere;
}

.chapter-run-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.snowflake-layout {
  display: grid;
  grid-template-columns: minmax(180px, 250px) minmax(0, 1fr);
  gap: 14px;
  margin-top: 12px;
}

.snowflake-step-list,
.snowflake-workbench {
  display: grid;
  gap: 8px;
}

.snowflake-step-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  min-height: 44px;
  padding: 9px 10px;
  border: 1px solid rgba(117, 130, 116, 0.18);
  border-radius: 8px;
  background: #fafbf6;
}

.snowflake-step-row span,
.snowflake-step-row strong {
  overflow-wrap: anywhere;
}

.snowflake-step-row strong {
  color: #60705d;
  font-size: 0.78rem;
}

.snowflake-step-row.active {
  border-color: rgba(204, 128, 58, 0.42);
  background: #fff5e7;
}

.snowflake-step-row.done {
  border-color: rgba(42, 130, 106, 0.35);
  background: #eef8f4;
}

.snowflake-step-row.stale,
.snowflake-stale {
  border-color: rgba(171, 82, 65, 0.35);
  background: #fff1ee;
  color: #7b372f;
}

.snowflake-current h3,
.snowflake-current p {
  margin: 4px 0 0;
}

.snowflake-artifact-editor {
  min-height: 220px;
  resize: vertical;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 0.86rem;
  line-height: 1.45;
}

.snowflake-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.snowflake-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
}

.review-safety {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.review-safety span {
  border: 1px solid rgba(208, 143, 59, 0.28);
  border-radius: 8px;
  background: #fff7ea;
  color: #68471e;
  padding: 7px 9px;
}

.review-issues {
  border-left: 3px solid #bd6c45;
  padding-left: 10px;
  color: #7a3e2b;
}

.profile-bind-row .control-input {
  min-width: 0;
}

.profile-row {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.project-error {
  color: #9a3e35;
}

@media (max-width: 1180px) {
  .project-dashboard-grid {
    grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);
  }

  .project-sidecar {
    grid-column: 1 / -1;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 820px) {
  .project-dashboard-grid,
  .project-sidecar,
  .project-stage-strip,
  .snowflake-layout {
    grid-template-columns: 1fr;
  }

  .project-title-row,
  .current-chapter-body {
    align-items: stretch;
    flex-direction: column;
  }

  .project-primary-actions,
  .chapter-run-actions {
    justify-content: flex-start;
  }
}
</style>
