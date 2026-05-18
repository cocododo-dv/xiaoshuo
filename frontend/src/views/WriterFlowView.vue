<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { CheckCircle2, FileText, PlayCircle, RefreshCw, ShieldAlert, WandSparkles } from "lucide-vue-next";

import BaseEmptyState from "../components/base/BaseEmptyState.vue";
import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import {
  backtrackScopeLabel,
  bodyEmptyReasonLabel,
  bodySourceLabel,
  chapterListLabel,
  completionStatusLabel,
  latestErrorLabel,
  missingSceneLabels as packetMissingSceneLabels,
  nextActionLabel,
  runStatusLabel,
  sceneDisplayLabel,
  targetWordCountLabel as formatTargetWordCount,
} from "../lib/writerFlowDisplay";
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
const pollingActive = ref(false);
const readDrawerOpen = ref(false);

let pollTimer = null;
let pollInFlight = false;
const pollIntervalMs = 7000;

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
const readinessSteps = computed(() => [
  {
    label: "选择 provider",
    done: Boolean(store.runtime?.provider_ready),
  },
  {
    label: "填写 key/地址",
    done: Boolean(store.runtime?.provider_ready),
  },
  {
    label: "测试并激活",
    done: Boolean(store.runtime?.llm_enabled && store.runtime?.provider_ready && !(store.runtime?.missing_routes || []).length),
  },
]);
const authorAction = computed(() => store.authorAction || runStatus.value?.latest_error?.author_action || null);
const authorActionEvidence = computed(() => authorAction.value?.evidence_summary || []);
const referenceRuleTags = computed(() => {
  const fromProfiles = (store.referenceProfiles || []).flatMap((profile) => profile?.safe_summary?.abstract_tags || []);
  const safety = (reviewPacket.value?.reference_safety || []).map((summary) => ({ label: "安全提示", summary }));
  return [...fromProfiles, ...safety].filter((item) => item?.summary).slice(0, 6);
});
const isPolling = computed(() => pollingActive.value);
const approvalNotesCount = computed(() => approvalNotes.value.length);
const approvalNotesTooLong = computed(() => approvalNotesCount.value > 2000);
const runStatusText = computed(() => runStatusLabel(runStatus.value?.status, nextAction.value));
const runSourceText = computed(() => bodySourceLabel(runStatus.value?.source || ""));
const reviewBodySourceText = computed(() => bodySourceLabel(reviewPacket.value?.body_source || ""));
const reviewBodyHash = computed(() => String(reviewPacket.value?.body_hash || ""));
const reviewReadConfirmed = computed(() =>
  Boolean(reviewBodyHash.value && reviewPacket.value?.read_confirmation?.body_hash === reviewBodyHash.value),
);
const reviewEmptyText = computed(() => bodyEmptyReasonLabel(reviewPacket.value?.body_empty_reason));
const completionStatusText = computed(() => completionStatusLabel(reviewPacket.value?.completion_status));
const currentSceneText = computed(() => sceneDisplayLabel(currentChapter.value, runStatus.value?.current_scene_id));
const sceneReviews = computed(() => reviewPacket.value?.scene_reviews || []);
const sceneCoverage = computed(() => reviewPacket.value?.scene_coverage || {
  completed_count: sceneReviews.value.filter((item) => Number(item?.char_count || 0) > 0).length,
  total_count: sceneReviews.value.length,
  percent: sceneReviews.value.length
    ? Math.round((sceneReviews.value.filter((item) => Number(item?.char_count || 0) > 0).length / sceneReviews.value.length) * 100)
    : 0,
});
const missingSceneLabels = computed(() => packetMissingSceneLabels(reviewPacket.value));
const targetWordCountLabel = computed(() => formatTargetWordCount(reviewPacket.value?.target_word_count_band));
const visibleBacktrackItems = computed(() => (store.backtrackItems || []).filter((item) => item?.status !== "resolved").slice(0, 3));
const shouldShowBacktrackBanner = computed(() =>
  ["resolve_blocker", "resolve_backtrack_items"].includes(nextAction.value) && visibleBacktrackItems.value.length > 0,
);

function actionFor(action) {
  if (action === "run_current_chapter") {
    return {
      label: "开始起草当前章",
      icon: PlayCircle,
      disabled: offlineBanner.value,
      run: startRunJob,
      hint: offlineBanner.value ? "当前是离线演示内容，只做流程演示，不会生成真实正文；启用模型后再起草。" : "启动后台章节起草，并在这里查看进度。",
    };
  }
  if (action === "view_chapter_progress") {
    return { label: "刷新起草进度", icon: RefreshCw, disabled: false, run: refreshProgress, hint: "查看当前后台运行状态。" };
  }
  if (action === "approve_chapter_final") {
    return {
      label: "批准本章",
      icon: CheckCircle2,
      disabled: !reviewPacket.value?.body || !reviewReadConfirmed.value || approvalNotesTooLong.value,
      run: approveFinal,
      hint: approvalNotesTooLong.value
        ? "批准备注需控制在 2000 字以内。"
        : !reviewPacket.value?.body ? "终稿审阅没有正文，先回到运行状态排查。"
          : reviewReadConfirmed.value ? "确认正文后推进到下一章。" : "批准前先通读全文并确认当前正文。",
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
  const note = approvalNotes.value.trim();
  await runFlowAction({
    scopeKey: WRITER_FLOW_SCOPE,
    actionLabel: "批准本章",
    runningMessage: "正在批准本章并推进项目...",
    successMessage: () => {
      const savedNote = store.lastApprovalNote?.revision_notes || note;
      const noteText = savedNote ? ` 备注已记录：${savedNote.slice(0, 80)}` : "";
      return `${store.lastActionMessage || "本章已批准。"}${noteText}`;
    },
    nextStep: () => store.nextAction === "completed" ? "项目主线已完成。" : "下一章已经准备好，可以继续起草。",
    target: () => ({ view: "writer-flow", label: "回到写作总控", target: store.project?.project_id || "" }),
    action: () => store.approveCurrentChapterFinal({ revision_notes: note }),
  });
  approvalNotes.value = "";
  stopPolling();
}

async function confirmFullRead() {
  await runFlowAction({
    scopeKey: WRITER_FLOW_SCOPE,
    actionLabel: "确认通读全文",
    runningMessage: "正在记录阅读确认...",
    successMessage: () => store.lastActionMessage || "已确认通读当前正文。",
    nextStep: () => "下一步：可以批准本章，或回到小修入口处理局部问题。",
    action: () => store.confirmCurrentChapterRead({ note: "confirmed from writer flow full reader" }),
  });
  readDrawerOpen.value = false;
}

function openSystemConfig() {
  router.navigate('config', { target: { panel: "llm" } });
}

function openAuthorAction(action = authorAction.value) {
  if (!action?.target_view) {
    return;
  }
  if (action.target_view === "config") {
    router.navigate("config", { target: { panel: "llm", target: action.target_ref || "" } });
    return;
  }
  if (action.target_view === "workbench") {
    router.navigate("workbench", { target: { target: action.target_ref || "", project_id: project.value?.project_id || "" } });
    return;
  }
  if (action.target_view === "snowflake-workbench") {
    router.navigate("snowflake-workbench", { target: { target: action.target_ref || "", project_id: project.value?.project_id || "" } });
    return;
  }
  if (action.target_view === "review") {
    router.navigate("review", { target: { target_ref: action.target_ref || "", project_id: project.value?.project_id || "" } });
    return;
  }
  router.navigate(action.target_view, { target: { target: action.target_ref || "", project_id: project.value?.project_id || "" } });
}

function openWriterRoomForChapter() {
  router.navigate("writer-room", {
    target: {
      focus: "chapter",
      target: currentChapter.value?.chapter_id || "",
      returnTo: 'writer-flow',
      returnTarget: project.value?.project_id || "",
      returnLabel: '返回批准',
    },
  });
}

function openWriterRoomForScene(sceneReview) {
  router.navigate("writer-room", {
    target: {
      focus: "scene",
      target: sceneReview?.scene_id || "",
      chapter_id: currentChapter.value?.chapter_id || "",
      returnTo: 'writer-flow',
      returnTarget: project.value?.project_id || "",
      returnLabel: '返回批准',
    },
  });
}

function openBacktrackItem(item) {
  router.navigate("review", {
    target: {
      project_id: project.value?.project_id || "",
      backtrack_id: item?.item_id || item?.backtrack_id || "",
      target_ref: item?.target_ref || "",
      chapter_id: item?.chapter_id || "",
      scene_id: item?.scene_id || "",
    },
  });
}

function chapterGoalSummary(chapter) {
  return chapter?.chapter_goal || chapter?.title || "这一章还没有目标摘要";
}

function startPolling() {
  stopPolling();
  if (!store.project?.current_chapter_id) {
    return;
  }
  pollingActive.value = true;
  pollTimer = window.setInterval(async () => {
    if (!store.project?.current_chapter_id) {
      stopPolling();
      return;
    }
    if (pollInFlight) {
      return;
    }
    pollInFlight = true;
    try {
      await store.refreshRunStatus();
      if (!store.isRunning) {
        stopPolling();
      }
    } catch (error) {
      emit("notice", error.message);
      stopPolling();
    } finally {
      pollInFlight = false;
    }
  }, pollIntervalMs);
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
  pollingActive.value = false;
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

    <BaseEmptyState
      v-if="!project"
      title="选择一个雪花项目继续"
      description="确认章节结构后，这里会接住当前章的起草、审阅和批准。"
    >
      <template #action>
        <button type="button" @click="router.navigate('snowflake-workbench')">回到雪花工作台</button>
      </template>
    </BaseEmptyState>

    <template v-else>
      <aside v-if="offlineBanner" class="writer-flow-banner" data-testid="writer-flow-offline-banner">
        <span>当前是离线演示内容模式，不会生成真实正文或真实 AI 修改；启用模型后再开始章节起草。</span>
        <button type="button" class="ghost" data-testid="writer-flow-config-action" @click="openSystemConfig">
          打开系统配置
        </button>
      </aside>

      <section class="writer-flow-readiness-card" data-testid="writer-flow-readiness-card">
        <div>
          <span class="eyebrow">模型准备度</span>
          <h3>{{ store.runtime?.llm_enabled ? "真实模型已启用" : "启用真实模型后再起草" }}</h3>
          <p class="muted">
            {{ store.runtime?.llm_enabled ? "章节正文会走真实模型路由。" : "主按钮会保持禁用，离线演示只作为高级测试逃生口。" }}
          </p>
        </div>
        <ol>
          <li v-for="step in readinessSteps" :key="step.label" :class="{ done: step.done }">{{ step.label }}</li>
        </ol>
        <button type="button" class="ghost" @click="openSystemConfig">去系统配置</button>
      </section>

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

      <section v-if="authorAction" class="writer-flow-author-action" data-testid="writer-flow-author-action">
        <div>
          <span class="eyebrow">下一步行动</span>
          <h3>{{ authorAction.title || "先处理阻塞项" }}</h3>
          <p>{{ authorAction.message || latestErrorLabel(runStatus?.latest_error) }}</p>
          <ul v-if="authorActionEvidence.length">
            <li v-for="item in authorActionEvidence" :key="item">{{ item }}</li>
          </ul>
        </div>
        <div class="writer-flow-author-actions">
          <button type="button" class="primary" @click="openAuthorAction(authorAction)">
            {{ authorAction.primary_button_label || "去处理" }}
          </button>
          <button type="button" class="ghost" @click="openSystemConfig">去系统配置</button>
          <button type="button" class="ghost" @click="router.navigate('workbench')">去场景工作台</button>
        </div>
      </section>

      <section v-if="referenceRuleTags.length" class="writer-flow-reference-rules" data-testid="writer-flow-reference-rules">
        <span class="eyebrow">本次写作使用的画像 / 规则 / 安全提示</span>
        <div>
          <span v-for="item in referenceRuleTags" :key="`${item.label}:${item.summary}`">
            <strong>{{ item.label }}：</strong>{{ item.summary }}
          </span>
        </div>
      </section>

      <section v-if="shouldShowBacktrackBanner" class="writer-flow-backtrack-banner" data-testid="writer-flow-backtrack-banner">
        <div class="panel-head">
          <div>
            <span class="eyebrow">{{ nextActionLabel(nextAction) }}</span>
            <h3>先处理这些影响，再继续写</h3>
          </div>
          <button type="button" class="ghost" @click="router.navigate('review', { target: { project_id: project?.project_id || '' } })">
            打开审阅中心
          </button>
        </div>
        <ul>
          <li v-for="item in visibleBacktrackItems" :key="item.item_id || item.target_ref">
            <div>
              <strong>{{ item.problem_summary || "有一处内容需要复核" }}</strong>
              <p>{{ item.recommended_fix || "先确认影响范围，再决定是否重跑或小修。" }}</p>
              <small>{{ backtrackScopeLabel(item) }}</small>
            </div>
            <button type="button" class="ghost mini" @click="openBacktrackItem(item)">去处理</button>
          </li>
        </ul>
      </section>

      <section class="writer-flow-grid">
        <article class="writer-flow-panel" data-testid="writer-flow-progress-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">运行进度</span>
              <h3>{{ runStatusText }}</h3>
            </div>
            <button type="button" class="ghost" @click="loadProject()">刷新</button>
          </div>
          <div class="progress-track"><span :style="{ width: progressWidth }"></span></div>
          <p v-if="isPolling" class="writer-flow-polling" data-testid="writer-flow-polling-status">
            正在跟进后台起草进度...
          </p>
          <dl>
            <div><dt>场景</dt><dd>{{ runStatus?.completed_count || 0 }}/{{ runStatus?.scene_count || currentChapter?.scenes?.length || 0 }}</dd></div>
            <div><dt>当前</dt><dd>{{ currentSceneText }}</dd></div>
            <div v-if="runSourceText"><dt>来源</dt><dd>{{ runSourceText }}</dd></div>
          </dl>
          <p v-if="runStatus?.latest_error" class="writer-flow-error">{{ latestErrorLabel(runStatus.latest_error) }}</p>
        </article>

        <article class="writer-flow-panel" data-testid="writer-flow-review-panel">
          <div class="panel-head">
            <div>
              <span class="eyebrow">终稿审阅</span>
              <h3>{{ reviewBodySourceText || "等待正文" }}</h3>
            </div>
            <button type="button" class="ghost" @click="openWriterRoomForChapter">
              需要小修
            </button>
          </div>
          <p v-if="reviewPacket?.body" class="writer-flow-body-preview">{{ reviewPacket.body }}</p>
          <p v-else class="muted">{{ reviewEmptyText }}</p>
          <div v-if="reviewPacket?.body" class="writer-flow-read-actions" data-testid="writer-flow-read-actions">
            <button type="button" class="ghost" data-testid="writer-flow-read-full" @click="readDrawerOpen = true">
              通读全文
            </button>
            <span :class="{ confirmed: reviewReadConfirmed }" data-testid="writer-flow-read-confirmation">
              {{ reviewReadConfirmed ? "已确认通读当前正文" : "批准前需通读确认" }}
            </span>
          </div>
          <div class="badge-row">
            <span>{{ reviewPacket?.char_count || 0 }} 字符</span>
            <span>{{ completionStatusText }}</span>
            <span v-if="sceneCoverage.total_count">已完成 {{ sceneCoverage.completed_count }}/{{ sceneCoverage.total_count }} 场</span>
            <span v-if="targetWordCountLabel">预计 {{ targetWordCountLabel }}</span>
          </div>
          <div v-if="missingSceneLabels.length" class="writer-flow-missing-scenes" data-testid="writer-flow-missing-scenes">
            <strong>缺失场景</strong>
            <ul>
              <li v-for="label in missingSceneLabels" :key="label">{{ label }}</li>
            </ul>
          </div>
          <div v-if="sceneReviews.length" class="writer-flow-scene-reviews" data-testid="writer-flow-scene-reviews">
            <article v-for="scene in sceneReviews" :key="scene.scene_id" :class="{ missing: scene.missing }">
              <div>
                <span>第 {{ scene.scene_seq || "-" }} 场</span>
                <strong>{{ scene.title || scene.scene_id }}</strong>
                <small>{{ scene.char_count || 0 }} 字符</small>
              </div>
              <p>{{ scene.body_excerpt || "这一场还没有可审阅正文。" }}</p>
              <div v-if="scene.issues_summary?.length" class="writer-flow-qc-evidence" data-testid="writer-flow-qc-evidence">
                <strong>{{ scene.issues_summary[0].issue }}</strong>
                <small v-if="scene.issues_summary[0].evidence">证据：{{ scene.issues_summary[0].evidence }}</small>
                <small v-if="scene.issues_summary[0].suggested_action">建议：{{ scene.issues_summary[0].suggested_action }}</small>
              </div>
              <button type="button" class="ghost mini" @click="openWriterRoomForScene(scene)">小修</button>
            </article>
          </div>
          <label class="writer-flow-approval-notes" data-testid="writer-flow-approval-notes">
            <span :class="{ over: approvalNotesTooLong }">批准备注 / 后续小修提醒 {{ approvalNotesCount }}/2000</span>
            <textarea
              v-model="approvalNotes"
              class="control-input"
              :disabled="nextAction !== 'approve_chapter_final'"
              placeholder="可选：这一章节奏是否顺、有没有缺失场景、下一章要延续什么张力、后续小修要记住什么。"
            />
          </label>
        </article>
      </section>

      <section class="writer-flow-chapters" data-testid="writer-flow-chapter-list">
        <article v-for="(chapter, index) in store.chapters" :key="chapter.chapter_id" :class="{ active: chapter.chapter_id === project.current_chapter_id }">
          <strong>{{ chapterListLabel(chapter, index) }}</strong>
          <p>{{ chapterGoalSummary(chapter) }}</p>
          <small>{{ chapter.scenes?.length || 0 }} 场景</small>
        </article>
      </section>

      <div v-if="readDrawerOpen" class="writer-flow-reader-backdrop" data-testid="writer-flow-read-drawer">
        <article class="writer-flow-reader">
          <div class="panel-head">
            <div>
              <span class="eyebrow">全文审阅</span>
              <h3>{{ currentChapter?.chapter_goal || "当前章节" }}</h3>
            </div>
            <button type="button" class="ghost" @click="readDrawerOpen = false">关闭</button>
          </div>
          <pre>{{ reviewPacket?.body || "" }}</pre>
          <div class="writer-flow-reader-actions">
            <span>{{ reviewPacket?.char_count || 0 }} 字符</span>
            <button
              type="button"
              class="primary"
              data-testid="writer-flow-read-confirm"
              :disabled="!reviewPacket?.body || store.actionId?.startsWith('read-confirm:')"
              @click="confirmFullRead"
            >
              我已通读，确认可批准
            </button>
          </div>
        </article>
      </div>
    </template>
  </section>
</template>

<style>
.writer-flow-view {
  display: grid;
  gap: 16px;
  color: #22332f;
}

.writer-flow-hero,
.writer-flow-panel,
.writer-flow-chapters article,
.writer-flow-backtrack-banner,
.writer-flow-readiness-card,
.writer-flow-author-action,
.writer-flow-reference-rules,
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

.writer-flow-readiness-card,
.writer-flow-author-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.writer-flow-readiness-card ol,
.writer-flow-author-action ul {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.writer-flow-readiness-card li,
.writer-flow-author-action li {
  border: 1px solid rgba(40, 124, 114, 0.18);
  border-radius: 999px;
  padding: 4px 8px;
  background: #eef7f3;
  color: #33544c;
  font-size: 12px;
}

.writer-flow-readiness-card li.done {
  background: #e6f7eb;
  color: #246551;
}

.writer-flow-author-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.writer-flow-reference-rules {
  display: grid;
  gap: 10px;
}

.writer-flow-reference-rules div {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.writer-flow-reference-rules span,
.writer-flow-qc-evidence {
  border: 1px solid rgba(40, 124, 114, 0.16);
  border-radius: 8px;
  background: #f5fbf7;
  padding: 7px 9px;
  color: #34544c;
}

.writer-flow-qc-evidence {
  display: grid;
  gap: 4px;
  margin-top: 8px;
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

.writer-flow-read-actions,
.writer-flow-reader-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
}

.writer-flow-read-actions span {
  color: #8c672b;
  font-size: 0.9rem;
  font-weight: 700;
}

.writer-flow-read-actions span.confirmed {
  color: #2f6f62;
}

.writer-flow-reader-backdrop {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  background: rgba(19, 31, 28, 0.34);
  padding: 18px;
}

.writer-flow-reader {
  display: grid;
  gap: 14px;
  width: min(920px, 100%);
  max-height: min(86vh, 900px);
  overflow: auto;
  border: 1px solid rgba(43, 95, 88, 0.18);
  border-radius: 8px;
  background: #fffefa;
  box-shadow: 0 28px 70px rgba(20, 35, 31, 0.28);
  padding: 18px;
}

.writer-flow-reader pre {
  margin: 0;
  white-space: pre-wrap;
  color: #1f2f2b;
  font: inherit;
  line-height: 1.8;
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

.writer-flow-approval-notes span.over {
  color: #9a3d31;
}

.writer-flow-approval-notes textarea {
  min-height: 86px;
  resize: vertical;
}

.writer-flow-error {
  color: #9a3d31;
}

.writer-flow-backtrack-banner {
  border-color: rgba(154, 61, 49, 0.24);
  background: #fff9f5;
}

.writer-flow-backtrack-banner ul,
.writer-flow-missing-scenes ul {
  list-style: none;
  padding: 0;
  margin: 12px 0 0;
}

.writer-flow-backtrack-banner li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid rgba(154, 61, 49, 0.12);
  padding: 10px 0 0;
}

.writer-flow-backtrack-banner p,
.writer-flow-scene-reviews p {
  margin: 4px 0;
}

.writer-flow-polling {
  margin: -4px 0 12px;
  color: #287c72;
  font-weight: 700;
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

.writer-flow-missing-scenes {
  margin-top: 12px;
  border-left: 3px solid #b35c38;
  padding-left: 10px;
  color: #6c3828;
}

.writer-flow-scene-reviews {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.writer-flow-scene-reviews article {
  border: 1px solid rgba(40, 124, 114, 0.16);
  border-radius: 8px;
  padding: 10px;
  background: #fbfefb;
}

.writer-flow-scene-reviews article.missing {
  border-color: rgba(179, 92, 56, 0.3);
  background: #fff9f5;
}

.writer-flow-scene-reviews article > div {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 8px;
}

.writer-flow-view button.mini {
  min-height: 30px;
  padding: 3px 8px;
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
  .writer-flow-readiness-card,
  .writer-flow-author-action,
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
