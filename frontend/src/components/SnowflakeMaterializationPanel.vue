<script setup>
import { computed } from "vue";
import { Check, RefreshCw, WandSparkles } from "lucide-vue-next";

import BaseBadge from "./base/BaseBadge.vue";
import FlowActionReceipt from "./FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { snowflakeGateStatusLabel } from "../lib/labels";
import { useShellRouter } from "../router";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const store = useSnowflakeWorkbenchStore();
const router = useShellRouter();
const SNOWFLAKE_STRUCTURE_SCOPE = "snowflake:structure";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const readyToMaterialize = computed(() => store.readyToMaterialize);
const materializationGate = computed(() => store.materializationGate);
const latestPlan = computed(() => store.latestPlan);
const pendingResyncCount = computed(() => store.pendingResyncCount);
const pendingResyncScenes = computed(() => store.pendingResyncScenes);
const planChapters = computed(() => latestPlan.value?.plan_json?.chapters || []);
const structureSummary = computed(() => {
  const chapters = planChapters.value;
  if (!chapters.length) {
    return null;
  }
  const sceneTotal = chapters.reduce((sum, chapter) => sum + (chapter.scenes?.length || 0), 0);
  const approved = String(latestPlan.value?.status || "").toLowerCase() === "approved";
  return { chapterCount: chapters.length, sceneTotal, approved };
});
const chapterFlowReady = computed(() =>
  ["chapter_ready", "chapter_running", "chapter_blocked", "chapter_final_review", "completed"]
    .includes(String(store.project?.status || "").toLowerCase()),
);
const structureHandoff = computed(() => {
  const planStatus = String(latestPlan.value?.status || "").toLowerCase();
  if (planStatus === "approved" || chapterFlowReady.value) {
    return {
      title: "结构已确认，去写作总控继续",
      body: "在写作总控里启动或继续当前章节，查看进度并处理终稿审阅。",
      actionLabel: "进入写作总控",
      testId: "snowflake-handoff-writer-flow",
      disabled: false,
      run: openWriterFlow,
    };
  }
  if (planStatus === "pending_review") {
    return {
      title: "章节大纲待你确认",
      body: "先检查每章的目标和场景拆分，确认后就可以开始写了。",
      actionLabel: "确认，开始写",
      testId: "snowflake-handoff-approve-outline",
      disabled: store.actionId === "approve-outline",
      run: approveOutline,
    };
  }
  if (readyToMaterialize.value) {
    return {
      title: "构思已完成，可以生成章节大纲了",
      body: "把你确认的构思和场景规划生成章节大纲，再由你检查确认。",
      actionLabel: "从构思生成大纲",
      testId: "snowflake-handoff-materialize",
      disabled: materializationGate.value.status === "blocked" || store.actionId === "materialize-outline",
      run: materializeOutline,
    };
  }
  return null;
});
const gateItems = computed(() => {
  if (Array.isArray(materializationGate.value?.items) && materializationGate.value.items.length) {
    return materializationGate.value.items;
  }
  return [
    ...(materializationGate.value?.blockers || []).map((message, index) => ({
      id: `blocker-${index}`,
      severity: "blocker",
      message,
      primary_action: { type: "inspect", label: "查看构思进度" },
    })),
    ...(materializationGate.value?.warnings || []).map((message, index) => ({
      id: `warning-${index}`,
      severity: "warning",
      message,
      primary_action: { type: "inspect", label: "查看提醒" },
    })),
  ];
});

function gateStatusLabel(status) {
  return snowflakeGateStatusLabel(status);
}

function gateItemTargetsScene(item) {
  const action = item?.primary_action || {};
  const actionType = String(action.type || "").toLowerCase();
  const kind = String(item?.kind || "").toLowerCase();
  return Boolean(
    item?.scene_id
    || item?.scene_plan_id
    || action.scene_id
    || action.scene_plan_id
    || action.panel === "triage"
    || actionType.includes("triage")
    || kind.includes("scene")
    || kind.includes("triage")
  );
}

function gateItemTargetsStep(item) {
  const action = item?.primary_action || {};
  return Boolean(item?.step_key || action.step_key);
}

function goToGateItem(item) {
  const action = item?.primary_action || {};
  if (gateItemTargetsScene(item)) {
    store.setWorkbenchMode("triage");
    store.selectTriageScene(item.scene_id || action.scene_id || "");
    emit("notice", "已打开对应场景。");
    return;
  }
  if (gateItemTargetsStep(item)) {
    store.setWorkbenchMode("planning");
    store.selectStep(item.step_key || action.step_key);
    emit("notice", "已跳到对应雪花步骤。");
    return;
  }
  emit("notice", "请按提示补齐后再整理章节结构。");
}

async function previewResync() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "预览差异",
    runningMessage: "正在对比构思和已有章节...",
    successMessage: () => store.lastActionMessage || "差异已预览。",
    nextStep: () => "下一步：确认后更新章节描述，正文不会被改动。",
    action: () => store.previewResync(),
  });
}

async function resyncScenes() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "更新章节描述",
    runningMessage: "正在用最新构思更新章节描述...",
    successMessage: () => store.lastActionMessage || "章节描述已更新。",
    nextStep: () => "你写的正文、终稿和审核记录不会被改动。",
    action: () => store.resyncScenes(),
  });
}

async function acceptGateStaleScene(item) {
  const scenePlanId = item?.scene_plan_id || item?.primary_action?.scene_plan_id || "";
  if (!scenePlanId) return;
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "确认场景仍有效",
    runningMessage: "正在记录确认结果...",
    successMessage: () => store.lastActionMessage || "已确认，当前版本仍有效。",
    nextStep: () => "下一步：继续生成章节大纲。",
    action: () => store.acceptStaleScenes([scenePlanId], { note: "reviewed in materialization gate" }),
  });
}

async function materializeOutline() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "生成章节大纲",
    runningMessage: "正在从你的构思生成章节大纲...",
    successMessage: () => store.lastActionMessage || "章节大纲已生成。",
    nextStep: () => "下一步：检查每章的目标，然后确认开始写。",
    action: () => store.materializeOutline(),
  });
}

async function approveOutline() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "确认大纲",
    runningMessage: "正在确认章节大纲...",
    successMessage: () => store.lastActionMessage || "大纲已确认，可以开始写了。",
    nextStep: () => "下一步：开始写第一章。",
    target: (result) => ({
      view: "writer-flow",
      label: "进入写作总控",
      focus: "story_project",
      target: result?.project?.project_id || store.selectedProjectId || store.project?.project_id || "",
    }),
    action: () => store.approveOutline(),
  });
}

function openWriterFlow() {
  router.navigate("writer-flow", {
    target: {
      focus: "story_project",
      target: store.selectedProjectId || store.project?.project_id || "",
    },
  });
}

function handleReceiptNavigate(target) {
  if (!target?.view) {
    return;
  }
  router.navigate(target.view, {
    target: {
      focus: target.focus || "",
      target: target.target || "",
    },
  });
}
</script>

<template>
  <section class="snowflake-outline-approve" data-testid="snowflake-outline-approve">
    <div class="panel-head">
      <div>
        <span class="eyebrow">进入写作前</span>
        <h2>生成章节大纲</h2>
      </div>
      <div class="action-row">
        <button
          type="button"
          class="ghost action-btn"
          :disabled="
            !readyToMaterialize ||
            materializationGate.status === 'blocked' ||
            store.actionId === 'materialize-outline'
          "
          @click="materializeOutline"
        >
          <WandSparkles :size="16" />
          <span>从构思生成大纲</span>
        </button>
        <button
          type="button"
          class="primary action-btn"
          :disabled="!latestPlan || latestPlan.status === 'approved' || store.actionId === 'approve-outline'"
          @click="approveOutline"
        >
          <Check :size="16" />
          <span>确认，开始写</span>
        </button>
      </div>
    </div>
    <FlowActionReceipt :receipt="receipt(SNOWFLAKE_STRUCTURE_SCOPE)" :on-navigate="handleReceiptNavigate" />

    <div v-if="pendingResyncCount" class="snowflake-resync-panel" data-testid="snowflake-resync-panel">
      <div>
        <span class="eyebrow">规划有更新</span>
        <strong>{{ pendingResyncCount }} 个章节的描述可以跟着更新</strong>
        <p class="muted">只更新章节描述和场景目标，你写的正文不会被改动。</p>
      </div>
      <div class="action-row">
        <button type="button" class="ghost action-btn" :disabled="store.actionId === 'preview-resync'" @click="previewResync">
          <RefreshCw :size="16" />
          <span>预览差异</span>
        </button>
        <button type="button" class="primary action-btn" :disabled="store.actionId === 'resync-scenes'" @click="resyncScenes">
          <Check :size="16" />
          <span>同步选中</span>
        </button>
      </div>
      <ul>
        <li v-for="scene in pendingResyncScenes.slice(0, 3)" :key="scene.scene_plan_id">{{ scene.title || scene.scene_id }}</li>
      </ul>
    </div>

    <div v-if="structureHandoff" class="snowflake-structure-handoff" data-testid="snowflake-structure-handoff">
      <div>
        <span class="eyebrow">下一步</span>
        <strong>{{ structureHandoff.title }}</strong>
        <p class="muted">{{ structureHandoff.body }}</p>
      </div>
      <button
        type="button"
        class="primary action-btn"
        :data-testid="structureHandoff.testId"
        :disabled="structureHandoff.disabled"
        @click="structureHandoff.run"
      >
        <Check :size="16" />
        <span>{{ structureHandoff.actionLabel }}</span>
      </button>
    </div>

    <div class="materialization-gate" :class="materializationGate.status">
      <div>
        <span class="eyebrow">进入写作前</span>
        <strong>{{ gateStatusLabel(materializationGate.status) }}</strong>
      </div>
      <div v-if="gateItems.length" class="gate-action-list" data-testid="materialization-gate-items">
        <article
          v-for="item in gateItems"
          :key="item.id || item.message"
          class="gate-action-item"
          :class="item.severity"
        >
          <p>{{ item.message }}</p>
          <button type="button" class="ghost mini-btn" @click="goToGateItem(item)">
            {{ item.primary_action?.label || "去处理" }}
          </button>
          <button
            v-if="item.kind === 'stale_scene_plan'"
            type="button"
            class="ghost mini-btn"
            data-testid="snowflake-scene-stale-accept"
            :disabled="store.actionId === 'accept-stale-scenes'"
            @click="acceptGateStaleScene(item)"
          >
            复核后仍有效
          </button>
        </article>
      </div>
      <p v-if="materializationGate.status === 'ready'" class="muted">一切就绪。</p>
    </div>

    <div v-if="structureSummary" class="outline-result">
      <div class="outline-summary" data-testid="snowflake-structure-summary">
        <div>
          <span class="eyebrow">{{ structureSummary.approved ? "已确认的章节结构" : "结构草案预览" }}</span>
          <strong>共 {{ structureSummary.chapterCount }} 章 · {{ structureSummary.sceneTotal }} 个场景</strong>
          <p class="muted">
            {{ structureSummary.approved
              ? "结构已确认，可在写作总控里逐章起草。"
              : "这是整理出的草案，逐章检查目标和场景拆分，确认后才会进入章节写作主线。" }}
          </p>
        </div>
        <BaseBadge :tone="structureSummary.approved ? 'success' : 'info'">
          {{ structureSummary.approved ? "已确认" : "待你确认" }}
        </BaseBadge>
      </div>
      <div class="outline-grid">
        <article v-for="chapter in planChapters" :key="chapter.chapter_id" class="outline-card">
          <strong>{{ chapter.title || chapter.chapter_id }}</strong>
          <p>{{ chapter.chapter_goal }}</p>
          <BaseBadge tone="neutral">{{ chapter.scenes?.length || 0 }} 场景</BaseBadge>
        </article>
      </div>
    </div>
    <p v-else-if="readyToMaterialize" class="muted" data-testid="snowflake-materialize-expectation">
      点「从构思生成大纲」后，系统会把你确认的构思生成章节大纲。生成后会列出每一章，你可以逐章检查，再点「确认，开始写」才会真正进入写作。
    </p>
    <p v-else class="muted">完成十步构思后，就可以生成章节大纲了。</p>
  </section>
</template>

