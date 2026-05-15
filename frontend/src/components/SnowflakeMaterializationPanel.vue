<script setup>
import { computed } from "vue";
import { Check, WandSparkles } from "lucide-vue-next";

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
const chapterFlowReady = computed(() =>
  ["chapter_ready", "chapter_running", "chapter_blocked", "chapter_final_review", "completed"]
    .includes(String(store.project?.status || "").toLowerCase()),
);
const structureHandoff = computed(() => {
  const planStatus = String(latestPlan.value?.status || "").toLowerCase();
  if (planStatus === "approved" || chapterFlowReady.value) {
    return {
      title: "章节结构已确认",
      body: "下一步在写作总控里启动当前章、查看运行进度，或处理终稿审阅。",
      actionLabel: "进入写作总控",
      testId: "snowflake-handoff-writer-flow",
      disabled: false,
      run: openWriterFlow,
    };
  }
  if (planStatus === "pending_review") {
    return {
      title: "章节结构草案待确认",
      body: "先检查章节目标和场景拆分，确认后系统会进入章节写作主线。",
      actionLabel: "确认结构",
      testId: "snowflake-handoff-approve-outline",
      disabled: store.actionId === "approve-outline",
      run: approveOutline,
    };
  }
  if (readyToMaterialize.value) {
    return {
      title: "雪花结构可以整理",
      body: "把已确认的雪花步骤和场景规划整理成章节结构草案，再由作者确认。",
      actionLabel: "整理成章节结构",
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
    emit("notice", "已打开对应场景急救项。");
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

async function acceptGateStaleScene(item) {
  const scenePlanId = item?.scene_plan_id || item?.primary_action?.scene_plan_id || "";
  if (!scenePlanId) return;
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "复核场景规划",
    runningMessage: "正在记录场景复核结果...",
    successMessage: () => store.lastActionMessage || "场景规划已复核，当前版本仍有效。",
    nextStep: () => "下一步：继续整理成章节结构。",
    action: () => store.acceptStaleScenes([scenePlanId], { note: "reviewed in materialization gate" }),
  });
}

async function materializeOutline() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "整理章节结构",
    runningMessage: "正在把雪花和场景规划整理成章节结构草案...",
    successMessage: () => store.lastActionMessage || "章节结构草案已生成。",
    nextStep: () => "下一步：检查章节计划，然后确认结构。",
    action: () => store.materializeOutline(),
  });
}

async function approveOutline() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STRUCTURE_SCOPE,
    actionLabel: "确认结构",
    runningMessage: "正在确认章节结构...",
    successMessage: () => store.lastActionMessage || "结构已确认。",
    nextStep: () => "下一步：进入写作总控，开始当前章节起草或查看阻塞项。",
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
        <span class="eyebrow">准备度检查</span>
        <h2>整理章节结构</h2>
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
          <span>整理成章节结构</span>
        </button>
        <button
          type="button"
          class="primary action-btn"
          :disabled="!latestPlan || latestPlan.status === 'approved' || store.actionId === 'approve-outline'"
          @click="approveOutline"
        >
          <Check :size="16" />
          <span>确认结构</span>
        </button>
      </div>
    </div>
    <FlowActionReceipt :receipt="receipt(SNOWFLAKE_STRUCTURE_SCOPE)" :on-navigate="handleReceiptNavigate" />

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
        <span class="eyebrow">准备度检查</span>
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
      <p v-if="materializationGate.status === 'ready'" class="muted">雪花步骤和场景急救没有阻塞项。</p>
    </div>

    <div v-if="latestPlan?.plan_json?.chapters?.length" class="outline-grid">
      <article v-for="chapter in latestPlan.plan_json.chapters" :key="chapter.chapter_id" class="outline-card">
        <strong>{{ chapter.title || chapter.chapter_id }}</strong>
        <p>{{ chapter.chapter_goal }}</p>
        <small>{{ chapter.scenes?.length || 0 }} 场景</small>
      </article>
    </div>
    <p v-else class="muted">雪花十步确认后，可以把场景结构整理到章节计划里。</p>
  </section>
</template>

