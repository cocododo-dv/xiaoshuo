<script setup>
import { computed } from "vue";
import { Save, WandSparkles } from "lucide-vue-next";

import FlowActionReceipt from "./FlowActionReceipt.vue";
import SnowflakeTriageSceneCard from "./SnowflakeTriageSceneCard.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const store = useSnowflakeWorkbenchStore();
const SNOWFLAKE_TRIAGE_SCOPE = "snowflake:triage";
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const triageDrafts = computed(() => store.triageDrafts);
const filteredTriageItems = computed(() => store.filteredTriageItems);
const selectedTriageItem = computed(() => store.selectedTriageItem);
const selectedTriageIndex = computed(() =>
  triageDrafts.value.findIndex((item) => item?.scene_id === selectedTriageItem.value?.scene_id),
);
const triageStats = computed(() => {
  const items = triageDrafts.value || [];
  const effectiveStatus = (item) => item.effective_status || item.status || "";
  return {
    total: items.length,
    pass: items.filter((item) => effectiveStatus(item) === "pass").length,
    rewrite: items.filter((item) => effectiveStatus(item) === "rewrite").length,
    maybe: items.filter((item) => effectiveStatus(item) === "maybe").length,
    blocking: items.filter((item) => item.blocking).length,
  };
});

function triageStatusOf(item) {
  return String(item?.effective_status || item?.status || item?.recommended_status || "").toLowerCase();
}

function triageStatusLabel(status) {
  if (status === "pass") return "合格";
  if (status === "maybe") return "需修改";
  if (status === "rewrite") return "废除重写";
  return "未诊断";
}

function triageStatusClass(item) {
  return triageStatusOf(item) || "empty";
}

function scoreLabel(item) {
  return typeof item?.score === "number" ? `${item.score}` : "--";
}

function splitLines(value) {
  return String(value || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}

function updateTriageItem(index, key, value) {
  if (index < 0) return;
  store.triageDrafts[index] = { ...(store.triageDrafts[index] || {}), [key]: value };
}

function updateTriageListField(index, key, value) {
  updateTriageItem(index, key, splitLines(value));
}

function updateSelectedTriageItem(key, value) {
  updateTriageItem(selectedTriageIndex.value, key, value);
}

function updateSelectedTriageListField(key, value) {
  updateTriageListField(selectedTriageIndex.value, key, value);
}

async function requestSceneTriageSuggestions() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_TRIAGE_SCOPE,
    actionLabel: "生成急救建议",
    runningMessage: "正在检查场景压力和缺口...",
    successMessage: () => store.lastActionMessage || "场景急救建议已生成。",
    nextStep: () => "下一步：逐场标记合格、需修改或废除重写。",
    action: () => store.requestSceneTriageSuggestions(),
  });
}

async function persistSceneTriage() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_TRIAGE_SCOPE,
    actionLabel: "保存急救结果",
    runningMessage: "正在保存场景急救判断...",
    successMessage: () => store.lastActionMessage || "场景急救结果已保存。",
    nextStep: () => "下一步：修复阻塞场景，再回到规划页整理章节结构。",
    action: () => store.saveSceneTriage(),
  });
}

async function applyTriageRepair(item) {
  if (!item?.triage_id) return;
  await runFlowAction({
    scopeKey: SNOWFLAKE_TRIAGE_SCOPE,
    actionLabel: "应用急救补丁",
    runningMessage: "正在把补丁写回场景规划...",
    successMessage: () => store.lastActionMessage || "急救补丁已应用。",
    nextStep: () => "下一步：复查这一场，然后保存急救结果。",
    action: () => store.applyTriageRepair(item.triage_id),
  });
}

async function requestSelectedSceneAssistant() {
  const scene = selectedTriageItem.value;
  const label = scene?.title || scene?.scene_id || "当前场景";
  emit("notice", `请求助手分析场景「${label}」...`);
  await store.requestAssistant(`请检查选中场景「${label}」的坩埚、结构节点、挫折/决定和下一场驱动力。`);
}
</script>

<template>
  <section class="snowflake-scene-triage" data-testid="snowflake-scene-triage">
    <div class="panel-head">
      <div>
        <span class="eyebrow">场景急救</span>
        <h2>场景急救室</h2>
        <p class="muted">
          共 {{ triageStats.total }} 场 · 合格 {{ triageStats.pass }} · 需修改 {{ triageStats.maybe }} · 废除重写
          {{ triageStats.rewrite }} · 阻塞 {{ triageStats.blocking }}
        </p>
      </div>
      <div class="action-row">
        <button
          type="button"
          class="ghost action-btn"
          :disabled="!store.project || store.actionId === 'scene-triage-suggest'"
          @click="requestSceneTriageSuggestions"
        >
          <WandSparkles :size="16" />
          <span>生成急救建议</span>
        </button>
        <button
          type="button"
          class="ghost action-btn"
          :disabled="!triageDrafts.length || store.actionId === 'scene-triage'"
          @click="persistSceneTriage"
        >
          <Save :size="16" />
          <span>保存急救结果</span>
        </button>
      </div>
    </div>
    <FlowActionReceipt :receipt="receipt(SNOWFLAKE_TRIAGE_SCOPE)" />

    <div class="triage-filter-row">
      <button type="button" class="mini-btn" :class="{ active: store.triageFilter === 'all' }" @click="store.setTriageFilter('all')">全部</button>
      <button type="button" class="mini-btn" :class="{ active: store.triageFilter === 'rewrite' }" @click="store.setTriageFilter('rewrite')">重写</button>
      <button type="button" class="mini-btn" :class="{ active: store.triageFilter === 'maybe' }" @click="store.setTriageFilter('maybe')">需改</button>
      <button type="button" class="mini-btn" :class="{ active: store.triageFilter === 'pass' }" @click="store.setTriageFilter('pass')">合格</button>
      <button type="button" class="mini-btn" :class="{ active: store.triageFilter === 'manual' }" @click="store.setTriageFilter('manual')">人工标记</button>
    </div>

    <div v-if="triageDrafts.length" class="triage-workbench-grid">
      <div class="triage-queue" data-testid="snowflake-triage-queue">
        <button
          v-for="item in filteredTriageItems"
          :key="item.scene_id"
          type="button"
          class="triage-queue-row"
          :class="[triageStatusClass(item), { active: item.scene_id === selectedTriageItem?.scene_id }]"
          @click="store.selectTriageScene(item.scene_id)"
        >
          <div>
            <strong>{{ item.title || item.scene_id }}</strong>
            <small>{{ item.scene_id }}</small>
          </div>
          <span class="triage-score">{{ scoreLabel(item) }}</span>
          <span class="triage-badge" :class="triageStatusClass(item)">
            {{ triageStatusLabel(triageStatusOf(item)) }}
          </span>
        </button>
        <p v-if="!filteredTriageItems.length" class="muted">当前筛选下没有场景。</p>
      </div>

      <SnowflakeTriageSceneCard
        v-if="selectedTriageItem"
        :item="selectedTriageItem"
        data-testid="snowflake-triage-detail"
        @update:item-field="updateSelectedTriageItem"
        @update:list-field="updateSelectedTriageListField"
        @apply-repair="applyTriageRepair(selectedTriageItem)"
        @ask-assistant="requestSelectedSceneAssistant"
      />
    </div>
    <p v-else class="muted">完成 `scene_details` 后，场景急救会在这里汇总。</p>
  </section>
</template>
