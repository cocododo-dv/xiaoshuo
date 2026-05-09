<script setup>
import { computed } from "vue";
import { Check, WandSparkles } from "lucide-vue-next";

import FlowActionReceipt from "./FlowActionReceipt.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const store = useSnowflakeWorkbenchStore();
const SNOWFLAKE_STRUCTURE_SCOPE = "snowflake:structure";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const readyToMaterialize = computed(() => store.readyToMaterialize);
const materializationGate = computed(() => store.materializationGate);
const latestPlan = computed(() => store.latestPlan);
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
  if (status === "blocked") {
    return "还差几处才能整理";
  }
  if (status === "warning") {
    return "可以整理，但有提醒";
  }
  return "可以整理成章节结构";
}

function goToGateItem(item) {
  const action = item?.primary_action || {};
  if (item?.step_key || action.step_key) {
    store.setWorkbenchMode("planning");
    store.selectStep(item.step_key || action.step_key);
    emit("notice", "已跳到对应雪花步骤。");
    return;
  }
  if (item?.scene_id || item?.scene_plan_id || action.scene_id || action.scene_plan_id) {
    store.setWorkbenchMode("triage");
    store.selectTriageScene(item.scene_id || action.scene_id || "");
    emit("notice", "已打开对应场景急救项。");
    return;
  }
  if (action.panel === "triage") {
    store.setWorkbenchMode("triage");
    emit("notice", "已打开场景急救。");
    return;
  }
  emit("notice", "请按提示补齐后再整理章节结构。");
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
    nextStep: () => "下一步：进入写作房间小修正文，或去待处理建议里处理风险。",
    action: () => store.approveOutline(),
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
    <FlowActionReceipt :receipt="receipt(SNOWFLAKE_STRUCTURE_SCOPE)" />

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
