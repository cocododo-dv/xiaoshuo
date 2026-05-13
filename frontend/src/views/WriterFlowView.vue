<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { CheckCircle2, FileText, PlayCircle, RefreshCw, ShieldAlert, WandSparkles } from "lucide-vue-next";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";
import { useWriterFlowStore } from "../stores/writerFlow";

const emit = defineEmits(["notice"]);

const router = useShellRouter();
const snowflake = useSnowflakeWorkbenchStore();
const store = useWriterFlowStore();
const WRITER_FLOW_SCOPE = "writer-flow:main";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});
const approvalNotes = ref("");

let pollTimer = null;

const contextProjectId = computed(() => {
  const target = router.routeContext.value?.target || "";
  if (target.startsWith("PRJ_")) {
    return target;
  }
  return store.selectedProjectId || snowflake.selectedProjectId || snowflake.project?.project_id || "";
});
const project = computed(() => store.project);
const currentChapter = computed(() => store.currentChapter);
const reviewPacket = computed(() => store.reviewPacket);
const runStatus = computed(() => store.runStatus);
const nextAction = computed(() => store.nextAction);
const mainAction = computed(() => actionFor(nextAction.value));
const progressWidth = computed(() => `${Math.min(100, Math.max(0, Number(runStatus.value?.progress_pct || 0)))}%`);
const offlineBanner = computed(() => store.runtime?.llm_enabled === false);

function actionFor(action) {
  if (action === "run_current_chapter") {
    return {
      label: "开始起草当前章",
      icon: PlayCircle,
      disabled: offlineBanner.value,
      run: startRunJob,
      hint: offlineBanner.value ? "当前是离线模式，启用模型后才能生成真实正文。" : "启动后台章节起草，并在这里查看进度。",
    };
  }
  if (action === "view_chapter_progress") {
    return { label: "刷新起草进度", icon: RefreshCw, disabled: false, run: refreshProgress, hint: "查看当前后台运行状态。" };
  }
  if (action === "approve_chapter_final") {
    return {
      label: "批准本章",
      icon: CheckCircle2,
      disabled: !reviewPacket.value?.body,
      run: approveFinal,
      hint: reviewPacket.value?.body ? "确认正文后推进到下一章。" : "终稿审阅没有正文，先回到运行状态排查。",
    };
  }
  if (action === "resolve_blocker" || action === "resolve_backtrack_items") {
    return { label: "处理阻塞项", icon: ShieldAlert, disabled: false, run: () => router.navigate("review"), hint: "先处理待作者决定的阻塞或返工项。" };
  }
  if (action === "completed") {
    return { label: "查看成稿", icon: FileText, disabled: false, run: () => router.navigate("manuscripts"), hint: "项目主线已完成。" };
  }
  return { label: "回到雪花工作台", icon: WandSparkles, disabled: false, run: () => router.navigate("snowflake-workbench"), hint: "先确认结构，再进入章节起草。" };
}

function handleReceiptNavigate(target) {
  if (target?.view) {
    router.navigate(target.view, { target });
  }
}

async function loadProject(projectId = contextProjectId.value) {
  if (!projectId) {
    return null;
  }
  return store.loadProject(projectId);
}

async function startRunJob() {
  await runFlowAction({
    scopeKey: WRITER_FLOW_SCOPE,
    actionLabel: "开始起草当前章",
    runningMessage: "正在启动后台章节起草...",
    successMessage: () => "章节起草已进入后台运行。",
    nextStep: () => "留在写作总控查看进度；完成后会进入终稿审阅。",
    action: () => store.startCurrentChapterJob(),
  });
  startPolling();
}

async function refreshProgress() {
  await runFlowAction({
    scopeKey: WRITER_FLOW_SCOPE,
    actionLabel: "刷新起草进度",
    runningMessage: "正在读取章节运行状态...",
    successMessage: () => store.runStatus?.status === "completed" ? "章节起草已完成。" : "章节进度已更新。",
    nextStep: () => store.nextAction === "approve_chapter_final" ? "下一步：审阅并批准本章。" : "",
    action: () => store.refreshRunStatus(),
  });
}

async function approveFinal() {
  await runFlowAction({
    scopeKey: WRITER_FLOW_SCOPE,
    actionLabel: "批准本章",
    runningMessage: "正在批准本章并推进项目...",
    successMessage: () => store.lastActionMessage || "本章已批准。",
    nextStep: () => store.nextAction === "completed" ? "项目主线已完成。" : "下一章已经准备好，可以继续起草。",
    target: () => ({ view: "writer-flow", label: "回到写作总控", target: store.project?.project_id || "" }),
    action: () => store.approveCurrentChapterFinal({ revision_notes: approvalNotes.value.trim() }),
  });
  approvalNotes.value = "";
  stopPolling();
}

function openSystemConfig() {
  router.navigate('config', { target: { panel: "llm" } });
}

function startPolling() {
  stopPolling();
  if (!store.project?.current_chapter_id) {
    return;
  }
  pollTimer = window.setInterval(() => {
    if (!store.project?.current_chapter_id) {
      stopPolling();
      return;
    }
    store.refreshRunStatus().catch((error) => {
      emit("notice", error.message);
      stopPolling();
    });
    if (!store.isRunning) {
      stopPolling();
    }
  }, 1600);
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

onMounted(async () => {
  await loadProject();
  if (store.nextAction === "view_chapter_progress") {
    startPolling();
  }
});
onBeforeUnmount(stopPolling);
watch(() => router.routeContext.value?.target, (target) => {
  if (target && target !== store.selectedProjectId) {
    loadProject(target);
  }
});
</script>

<template>
  <section class="writer-flow-view" data-testid="writer-flow-view">
    <WorkflowPageHeader view-id="writer-flow" kicker="Flow" />

    <div v-if="!project" class="writer-flow-empty">
      <h2>选择一个雪花项目继续</h2>
      <p>确认章节结构后，这里会接住当前章的起草、审阅和批准。</p>
      <button type="button" @click="router.navigate('snowflake-workbench')">回到雪花工作台</button>
    </div>

    <template v-else>
      <aside v-if="offlineBanner" class="writer-flow-banner" data-testid="writer-flow-offline-banner">
        <span>当前是离线演示模式，不会生成真实正文。启用模型后再开始章节起草。</span>
        <button type="button" class="ghost" data-testid="writer-flow-config-action" @click="openSystemConfig">
          打开系统配置
        </button>
      </aside>

      <section class="writer-flow-hero">
        <div>
          <span class="eyebrow">当前项目</span>
          <h2>{{ project.title || project.project_id }}</h2>
          <p>{{ currentChapter?.chapter_goal || "当前没有待起草章节。" }}</p>
        </div>
        <div class="writer-flow-action">
          <button
            type="button"
            class="primary"
            data-testid="writer-flow-main-action"
            :disabled="mainAction.disabled || Boolean(store.actionId)"
            @click="mainAction.run"
          >
            <component :is="mainAction.icon" :size="17" />
            <span>{{ mainAction.label }}</span>
          </button>
          <small>{{ mainAction.hint }}</small>
        </div>
      </section>

      <FlowActionReceipt :receipt="receipt(WRITER_FLOW_SCOPE)" :on-navigate="handleReceiptNavigate" />

      <section class="writer-flow-grid">
        <article class="writer-flow-panel" data-testid="writer-flow-progress-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">运行进度</span>
              <h3>{{ runStatus?.status || nextAction }}</h3>
            </div>
            <button type="button" class="ghost" @click="loadProject()">刷新</button>
          </div>
          <div class="progress-track"><span :style="{ width: progressWidth }"></span></div>
          <dl>
            <div><dt>场景</dt><dd>{{ runStatus?.completed_count || 0 }}/{{ runStatus?.scene_count || currentChapter?.scenes?.length || 0 }}</dd></div>
            <div><dt>当前</dt><dd>{{ runStatus?.current_scene_id || currentChapter?.chapter_id || "-" }}</dd></div>
            <div><dt>来源</dt><dd>{{ runStatus?.source || reviewPacket?.body_source || "llm" }}</dd></div>
          </dl>
          <p v-if="runStatus?.latest_error" class="writer-flow-error">{{ runStatus.latest_error.message }}</p>
        </article>

        <article class="writer-flow-panel" data-testid="writer-flow-review-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">终稿审阅</span>
              <h3>{{ reviewPacket?.body_source || "等待正文" }}</h3>
            </div>
            <button type="button" class="ghost" @click="router.navigate('writer-room', { target: { focus: 'chapter', target: currentChapter?.chapter_id || '' } })">需要小修</button>
          </div>
          <p v-if="reviewPacket?.body" class="writer-flow-body-preview">{{ reviewPacket.body }}</p>
          <p v-else class="muted">{{ reviewPacket?.body_empty_reason || "章节起草完成后会在这里显示正文。" }}</p>
          <div class="badge-row">
            <span>{{ reviewPacket?.char_count || 0 }} 字符</span>
            <span>{{ reviewPacket?.completion_status || "pending" }}</span>
            <span v-if="reviewPacket?.missing_scene_ids?.length">{{ reviewPacket.missing_scene_ids.length }} 场缺失</span>
          </div>
          <label class="writer-flow-approval-notes" data-testid="writer-flow-approval-notes">
            <span>批准备注 / 后续小修提醒</span>
            <textarea
              v-model="approvalNotes"
              class="control-input"
              :disabled="nextAction !== 'approve_chapter_final'"
              placeholder="可选：记录批准时的保留意见、下一章需要延续的张力，或稍后小修提醒。"
            />
          </label>
        </article>
      </section>

      <section class="writer-flow-chapters" data-testid="writer-flow-chapter-list">
        <article v-for="chapter in store.chapters" :key="chapter.chapter_id" :class="{ active: chapter.chapter_id === project.current_chapter_id }">
          <strong>{{ chapter.chapter_id }}</strong>
          <p>{{ chapter.chapter_goal }}</p>
          <small>{{ chapter.scenes?.length || 0 }} 场景</small>
        </article>
      </section>
    </template>
  </section>
</template>

<style>
.writer-flow-view {
  display: grid;
  gap: 16px;
  color: #22332f;
}

.writer-flow-empty,
.writer-flow-hero,
.writer-flow-panel,
.writer-flow-chapters article,
.writer-flow-banner {
  border: 1px solid rgba(43, 95, 88, 0.16);
  border-radius: 8px;
  background: #fffdf8;
  padding: 16px;
  box-shadow: 0 16px 30px rgba(30, 52, 48, 0.08);
}

.writer-flow-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-color: rgba(154, 91, 31, 0.28);
  background: #fff7e8;
  color: #76511d;
}

.writer-flow-hero,
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.writer-flow-hero h2,
.writer-flow-panel h3 {
  margin: 4px 0;
  color: #152620;
}

.writer-flow-action {
  display: grid;
  gap: 8px;
  justify-items: end;
  max-width: 320px;
}

.writer-flow-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: 16px;
}

.writer-flow-panel {
  min-width: 0;
}

.progress-track {
  height: 9px;
  border-radius: 999px;
  overflow: hidden;
  background: #e8efe9;
  margin: 14px 0;
}

.progress-track span {
  display: block;
  height: 100%;
  background: #287c72;
  transition: width 180ms ease;
}

.writer-flow-panel dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 0;
}

.writer-flow-panel dt,
.eyebrow,
.muted {
  color: #66776f;
}

.writer-flow-panel dd {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
}

.writer-flow-body-preview {
  max-height: 260px;
  overflow: auto;
  white-space: pre-wrap;
  line-height: 1.7;
}

.writer-flow-approval-notes {
  display: grid;
  gap: 6px;
  margin-top: 12px;
}

.writer-flow-approval-notes span {
  color: #445b52;
  font-weight: 700;
}

.writer-flow-approval-notes textarea {
  min-height: 86px;
  resize: vertical;
}

.writer-flow-error {
  color: #9a3d31;
}

.badge-row,
.writer-flow-chapters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.badge-row span {
  border: 1px solid rgba(40, 124, 114, 0.18);
  border-radius: 999px;
  padding: 4px 8px;
  background: #eef7f3;
  font-size: 12px;
}

.writer-flow-chapters {
  align-items: stretch;
}

.writer-flow-chapters article {
  flex: 1 1 220px;
}

.writer-flow-chapters article.active {
  border-color: rgba(40, 124, 114, 0.42);
  background: #f3fbf6;
}

.writer-flow-view button {
  min-height: 38px;
  border: 1px solid rgba(40, 124, 114, 0.22);
  border-radius: 8px;
  background: #f7fbf8;
  color: #1d4f48;
  font-weight: 700;
  cursor: pointer;
}

.writer-flow-view button.primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: #287c72;
  color: white;
}

.writer-flow-view button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

@media (max-width: 820px) {
  .writer-flow-hero,
  .panel-head {
    align-items: stretch;
    flex-direction: column;
  }

  .writer-flow-action {
    justify-items: stretch;
    max-width: none;
  }

  .writer-flow-grid,
  .writer-flow-panel dl {
    grid-template-columns: 1fr;
  }
}
</style>
