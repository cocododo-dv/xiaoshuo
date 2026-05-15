<script setup>
import { computed, ref } from "vue";
import { Check, History, Plus, RotateCcw, Save, SkipForward, WandSparkles } from "lucide-vue-next";

import FlowActionReceipt from "./FlowActionReceipt.vue";
import SnowflakeSkipStepDialog from "./SnowflakeSkipStepDialog.vue";
import SnowflakeStepGuideCard from "./SnowflakeStepGuideCard.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { artifactStatusLabel, sceneFormLabel, sourceLabel } from "../lib/snowflakeDisplay";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice", "go-triage"]);

const store = useSnowflakeWorkbenchStore();
const SNOWFLAKE_STEP_SCOPE = "snowflake:step";
const skipDialogOpen = ref(false);
const skipButton = ref(null);
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const project = computed(() => store.project);
const steps = computed(() => store.steps);
const currentStep = computed(() => store.currentStep);
const currentStepUsesFallback = computed(() => String(currentStep.value?.last_generation_source || "").toLowerCase() === "fallback");
const currentStepIndex = computed(() =>
  steps.value.findIndex((s) => s.step_key === currentStep.value?.step_key),
);
const readyToMaterialize = computed(() => store.readyToMaterialize);
const currentStepDirty = computed(() => store.currentStepDirty);
const currentStepStale = computed(() => currentStep.value?.artifact?.status === "stale");
const currentStepStaleAccepted = computed(() => Boolean(currentStep.value?.stale_accepted_at || currentStep.value?.artifact?.stale_accepted_at));
const currentStepStaleDismissed = computed(() => currentStepStale.value && store.isStaleStepDismissed(currentStep.value));
const currentStepHistory = computed(() =>
  store.stepHistory?.step_key === currentStep.value?.step_key ? (store.stepHistory?.items || []) : [],
);
const discoveryExcerpt = computed(() => {
  const text = String(store.discoveryDraftContent || store.discoveryDraft?.content || "").replace(/\s+/g, " ").trim();
  return text.length > 420 ? `${text.slice(0, 420).trim()}...` : text;
});
const completedStepCount = computed(() => steps.value.filter((s) => s.gate_satisfied).length);
const totalStepCount = computed(() => steps.value.length || 0);
const progressPercent = computed(() => {
  if (!totalStepCount.value) return 0;
  return Math.round((completedStepCount.value / totalStepCount.value) * 100);
});

function restoreSkipFocus() {
  const restore = typeof requestAnimationFrame === "function" ? requestAnimationFrame : (callback) => setTimeout(callback, 0);
  restore(() => skipButton.value?.focus?.());
}

function splitLines(value) {
  return String(value || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}

function joinLines(value) {
  return Array.isArray(value) ? value.join("\n") : "";
}

function isLongTextField(key) {
  return [
    "summary", "target_reader", "story_kind", "delight_reason", "genre_promise",
    "expected_reader_emotion", "goal", "conflict", "setback", "reaction", "dilemma",
    "decision", "scene_crucible", "synopsis", "one_paragraph_summary", "moral_premise",
    "how_character_changes", "appearance", "family_background", "relationships",
    "deepest_fear", "greatest_hope", "philosophy", "self_image", "public_image", "character_arc",
  ].includes(key);
}

function collectionFieldKeys(field) {
  return Object.keys(field?.template || {});
}

function isNestedCollectionField(field, key) {
  const v = field?.template?.[key];
  return v && typeof v === "object" && !Array.isArray(v);
}

function nestedCollectionFieldKeys(field, key) {
  const v = field?.template?.[key];
  return v && typeof v === "object" && !Array.isArray(v) ? Object.keys(v) : [];
}

function sceneDetailsEditorField() {
  return (currentStep.value?.editor?.fields || []).find((f) => f.kind === "scene_details") || null;
}

function scenePrimaryForm(scene) {
  return String(scene?.primary_form || scene?.scene_type || "proactive").toLowerCase() === "reactive" ? "reactive" : "proactive";
}

function sceneDetailMode(sceneOrType) {
  if (typeof sceneOrType === "object") return scenePrimaryForm(sceneOrType);
  return String(sceneOrType || "proactive").toLowerCase() === "reactive" ? "reactive" : "proactive";
}

function sceneDetailFieldMeta(sceneType, key) {
  const field = sceneDetailsEditorField();
  const mode = (field?.scene_modes || []).find((m) => m.value === sceneDetailMode(sceneType));
  return (mode?.fields || []).find((f) => f.key === key) || {};
}

function sceneDetailFieldLabel(sceneType, key, fallback) {
  return sceneDetailFieldMeta(sceneType, key).label || fallback;
}
function sceneDetailFieldHint(sceneType, key) {
  return sceneDetailFieldMeta(sceneType, key).hint || "";
}
function sceneDetailFieldPlaceholder(sceneType, key) {
  return sceneDetailFieldMeta(sceneType, key).placeholder || "";
}
function sceneDetailFieldRows(sceneType, key) {
  return sceneDetailFieldMeta(sceneType, key).rows || 3;
}

async function generateCurrentStep() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "生成候选",
    runningMessage: "正在生成当前雪花候选...",
    successMessage: () => store.lastActionMessage || "候选已生成。",
    nextStep: () => "下一步：检查候选内容，必要时编辑，然后保存并确认。",
    action: () => store.generateCurrentStep(),
  });
}

async function saveCurrentStep() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "保存步骤",
    runningMessage: "正在保存当前雪花步骤...",
    successMessage: () => store.lastActionMessage || "雪花步骤已保存。",
    nextStep: () => "下一步：确认步骤，或继续补齐缺失字段。",
    action: () => store.saveCurrentStep(),
  });
}

async function approveCurrentStep() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "确认步骤",
    runningMessage: currentStepDirty.value ? "正在先保存修改，再确认步骤..." : "正在确认当前雪花步骤...",
    successMessage: () => store.lastActionMessage || "雪花步骤已确认。",
    nextStep: () => "下一步：继续确认下一层雪花，或在场景规划后进入急救。",
    action: () => store.approveCurrentStep(),
  });
}

async function skipCurrentStep(reason) {
  skipDialogOpen.value = false;
  if (!String(reason || "").trim()) return;
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "跳过步骤",
    runningMessage: "正在记录跳过原因...",
    successMessage: () => store.lastActionMessage || "已跳过当前步骤。",
    nextStep: () => "下一步：继续确认下一层雪花；整理章节结构前会再次提示跳过风险。",
    action: () => store.skipCurrentStep(reason),
  });
  restoreSkipFocus();
}

function requestSkipCurrentStep() {
  if (!currentStep.value?.can_skip) return;
  skipDialogOpen.value = true;
}

function dismissCurrentStepStale() {
  store.dismissStaleStep(currentStep.value);
}

function restoreCurrentStepStale() {
  store.restoreStaleStep(currentStep.value);
}

async function acceptCurrentStepStale() {
  if (!currentStep.value?.step_key) return;
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "复核需复核步骤",
    runningMessage: "正在记录复核结果...",
    successMessage: () => store.lastActionMessage || "已复核，当前内容仍可继续使用。",
    nextStep: () => "下一步：继续确认后续步骤，或整理成章节结构。",
    action: () => store.acceptStaleStep(currentStep.value, { note: "reviewed in snowflake workbench" }),
  });
}

function closeSkipDialog() {
  skipDialogOpen.value = false;
  restoreSkipFocus();
}

async function askAssistantForSkippedDraft() {
  skipDialogOpen.value = false;
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "助手起草",
    runningMessage: "正在让助手补一版当前步骤草稿...",
    successMessage: () => store.lastActionMessage || "助手草稿已生成。",
    nextStep: () => "下一步：检查助手草稿，保存后再确认。",
    action: () => store.requestAssistant({
      message: "请帮我为当前雪花步骤补一版可编辑草稿，不要替我确认。",
    }),
  });
}

async function openCurrentStepHistory() {
  if (!currentStep.value) return;
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "查看历史",
    runningMessage: "正在读取这个雪花步骤的历史版本...",
    successMessage: () => "历史版本已更新。",
    nextStep: () => "可以预览摘要；恢复旧版会生成新的待审草稿，不会直接确认。",
    action: () => store.loadCurrentStepHistory(),
  });
}

async function restoreHistoryItem(item) {
  if (!item?.step_run_id) return;
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "恢复历史草稿",
    runningMessage: "正在把历史版本恢复为新的待审草稿...",
    successMessage: () => store.lastActionMessage || "历史草稿已恢复为待审版本。",
    nextStep: () => "下一步：检查恢复出的草稿，必要时编辑，然后再确认。",
    action: () => store.restoreStepFromHistory(item.step_run_id),
  });
}

async function askAssistantWithDiscoveryDraft() {
  await runFlowAction({
    scopeKey: SNOWFLAKE_STEP_SCOPE,
    actionLabel: "参考自由草稿补稿",
    runningMessage: "正在把自由草稿作为上下文交给助手...",
    successMessage: () => store.lastActionMessage || "助手已根据自由草稿给出补稿建议。",
    nextStep: () => "下一步：检查助手候选，满意后手动保存并确认。",
    action: () => store.requestAssistantFromDiscoveryDraft(),
  });
}

function selectStep(stepKey) { store.selectStep(stepKey); }
function updateSimpleField(key, value) { store.updateDraftField(key, value); }
function updateSentence(key, index, value) { store.updateDraftArrayItem(key, index, value); }
function updateListField(key, value) { store.replaceDraftListField(key, splitLines(value)); }
function updateNestedField(parentKey, key, value) { store.updateNestedDraftField(parentKey, key, value); }
function addCollectionItem(field) { store.addDraftCollectionItem(field.key, field.template || {}); }
function updateCollectionField(fieldKey, index, key, value) { store.updateDraftCollectionItem(fieldKey, index, key, value); }

function updateNestedCollectionField(fieldKey, index, key, nestedKey, value) {
  const currentItems = Array.isArray(currentStep.value?.draft?.[fieldKey]) ? currentStep.value.draft[fieldKey] : [];
  const currentItem = currentItems[index] || {};
  store.updateDraftCollectionItem(fieldKey, index, key, {
    ...(currentItem[key] && typeof currentItem[key] === "object" ? currentItem[key] : {}),
    [nestedKey]: value,
  });
}

function updateScenePrimaryForm(fieldKey, index, value) {
  const form = value === "reactive" ? "reactive" : "proactive";
  store.updateDraftCollectionItem(fieldKey, index, "primary_form", form);
  store.updateDraftCollectionItem(fieldKey, index, "scene_type", form);
}

function updateCollectionListField(fieldKey, index, key, value) {
  store.replaceDraftCollectionListField(fieldKey, index, key, splitLines(value));
}

function updateSceneCrucible(fieldKey, index, value) {
  store.updateDraftCollectionItem(fieldKey, index, "crucible", value);
  store.updateDraftCollectionItem(fieldKey, index, "scene_crucible", value);
}
</script>

<template>
  <section class="snowflake-workbench-stage">
    <div class="panel-head">
      <div>
        <span class="eyebrow">Workspace</span>
        <h2>{{ project?.title || "雪花工作台" }}</h2>
        <p class="muted">
          {{ project?.genre || "等待项目" }}
          <span v-if="currentStep"> / 当前：{{ currentStep.label }}</span>
          <span v-else-if="readyToMaterialize"> / 雪花已完成，等待整理成章节结构</span>
          <span v-if="currentStepDirty"> / 未保存</span>
        </p>
      </div>
      <div class="action-row">
        <button type="button" class="ghost action-btn" :disabled="!currentStep || store.actionId === `generate:${currentStep?.step_key}`" @click="generateCurrentStep">
          <WandSparkles :size="16" /><span>生成候选</span>
        </button>
        <button ref="skipButton" type="button" class="ghost action-btn" :disabled="!currentStep?.can_skip || store.actionId === `generate:${currentStep?.step_key}`" @click="requestSkipCurrentStep">
          <SkipForward :size="16" /><span>跳过</span>
        </button>
        <button type="button" class="ghost action-btn" data-testid="snowflake-step-history-trigger" :disabled="!currentStep || store.actionId === `history:${currentStep?.step_key}`" @click="openCurrentStepHistory">
          <History :size="16" /><span>历史</span>
        </button>
        <button type="button" class="ghost action-btn" :disabled="!currentStep || store.actionId === `save:${currentStep?.step_key}`" @click="saveCurrentStep">
          <Save :size="16" /><span>{{ currentStepDirty ? "保存修改" : "保存步骤" }}</span>
        </button>
        <button type="button" class="primary action-btn" :disabled="!currentStep || store.actionId === `approve:${currentStep?.step_key}`" @click="approveCurrentStep">
          <Check :size="16" /><span>{{ currentStepDirty ? "保存并确认" : "确认步骤" }}</span>
        </button>
      </div>
    </div>
    <FlowActionReceipt :receipt="receipt(SNOWFLAKE_STEP_SCOPE)" />
    <SnowflakeSkipStepDialog
      :open="skipDialogOpen"
      :step="currentStep"
      @close="closeSkipDialog"
      @confirm="skipCurrentStep"
      @draft-assistant="askAssistantForSkippedDraft"
    />

    <div v-if="currentStep || readyToMaterialize" class="snowflake-step-state-strip" data-testid="snowflake-step-state-strip" aria-live="polite">
      <span class="badge">{{ currentStep ? `当前：${currentStep.label}` : "雪花步骤已完成" }}</span>
      <span class="badge" :class="{ active: currentStepDirty }">{{ currentStepDirty ? "未保存" : "已保存" }}</span>
      <span class="badge">{{ readyToMaterialize ? "可做准备度检查" : "继续补齐并确认" }}</span>
    </div>

    <div v-if="currentStepStale" class="snowflake-stale-note" :class="{ collapsed: currentStepStaleDismissed }">
      <template v-if="!currentStepStaleDismissed">
        <div>
          <span class="eyebrow">上游影响</span>
          <strong>这个步骤受前面已修改内容影响，建议复核。</strong>
          <p class="muted">{{ currentStep.artifact?.stale_reason || "上游内容已更新，这里的判断或文本可能需要同步调整。" }}</p>
        </div>
        <button
          v-if="!currentStepStaleAccepted"
          type="button"
          class="ghost mini-btn"
          data-testid="snowflake-stale-accept"
          :disabled="store.actionId === `accept-stale:${currentStep?.step_key}`"
          @click="acceptCurrentStepStale"
        >
          复核后仍有效
        </button>
        <button type="button" class="ghost mini-btn" data-testid="snowflake-stale-dismiss" @click="dismissCurrentStepStale">
          我知道，暂时收起
        </button>
      </template>
      <template v-else>
        <span data-testid="snowflake-stale-collapsed">已收起上游影响提醒，风险标记仍保留。</span>
        <button type="button" class="ghost mini-btn" @click="restoreCurrentStepStale">重新展开提醒</button>
      </template>
    </div>

    <div class="snowflake-progress-panel" data-testid="snowflake-progress-panel">
      <div>
        <span class="eyebrow">Progress</span>
        <strong>{{ completedStepCount }} / {{ totalStepCount }} 步已确认</strong>
      </div>
      <div class="snowflake-progress-track" aria-hidden="true">
        <span :style="{ width: `${progressPercent}%` }" />
      </div>
      <small>{{ progressPercent }}%</small>
    </div>

    <div class="snowflake-workbench-stage-grid">
      <div class="snowflake-workbench-step-list" data-testid="snowflake-workbench-step-list">
        <button
          v-for="step in steps"
          :key="step.step_key"
          type="button"
          class="step-pill"
          :class="{ active: step.step_key === currentStep?.step_key, done: step.gate_satisfied, stale: step.artifact?.status === 'stale', dirty: store.dirtyStepKeys?.[step.step_key] }"
          @click="selectStep(step.step_key)"
        >
          <span>{{ step.phase }}</span>
          <strong>{{ step.label }}</strong>
          <small>
            {{ artifactStatusLabel(step.artifact?.status || "draft") }}
            <template v-if="step.completeness"> · {{ step.completeness.filled_count }}/{{ step.completeness.total_count }}</template>
            <template v-if="store.dirtyStepKeys?.[step.step_key]"> · 未保存</template>
          </small>
        </button>
      </div>

      <div class="snowflake-editor-card">
        <template v-if="currentStep">
          <div class="current-step-copy">
            <span class="eyebrow">当前步骤</span>
            <h3>{{ currentStep.label }}</h3>
            <p class="muted">{{ currentStep.description }}</p>
            <p v-if="currentStep.last_generation_source || currentStep.last_llm_call_id" class="step-meta">
              <span v-if="currentStep.last_generation_source">生成来源：{{ sourceLabel(currentStep.last_generation_source) }}</span>
              <span v-if="currentStep.last_llm_call_id"> / 已记录模型调用</span>
            </p>
            <p v-if="currentStepUsesFallback" class="snowflake-offline-demo-note" data-testid="snowflake-offline-demo-note">
              当前内容来自离线演示，不代表真实模型生成；启用模型后再用于正文生产。
            </p>
            <details v-if="discoveryExcerpt" class="snowflake-discovery-context" data-testid="snowflake-discovery-context">
              <summary>自由草稿摘录</summary>
              <p>{{ discoveryExcerpt }}</p>
              <button type="button" class="ghost action-btn" data-testid="snowflake-discovery-assistant" @click="askAssistantWithDiscoveryDraft">
                <WandSparkles :size="16" /><span>参考自由草稿补本步草稿</span>
              </button>
            </details>
          </div>

          <section v-if="currentStepHistory.length" class="snowflake-step-history" data-testid="snowflake-step-history">
            <div class="collection-head">
              <div>
                <span class="eyebrow">历史版本</span>
                <strong>{{ currentStep.label }}</strong>
              </div>
              <button type="button" class="ghost mini-btn" @click="openCurrentStepHistory">刷新</button>
            </div>
            <article v-for="item in currentStepHistory" :key="item.step_run_id" class="history-version-row">
              <div>
                <strong>v{{ item.version }} · {{ artifactStatusLabel(item.status) }}</strong>
                <p class="muted">{{ item.draft_summary || "这一版没有可读摘要。" }}</p>
                <small>{{ item.generation_source || "author" }} · {{ item.updated_at || item.created_at }}</small>
              </div>
              <button type="button" class="ghost mini-btn" @click="restoreHistoryItem(item)">
                <RotateCcw :size="14" /><span>恢复</span>
              </button>
            </article>
          </section>

          <SnowflakeStepGuideCard
            class="snowflake-guidance-card"
            :step="currentStep"
            :steps="steps"
            :current-step-index="Math.max(currentStepIndex, 0)"
            :completed-step-count="completedStepCount"
            :total-step-count="totalStepCount"
            :current-step-dirty="currentStepDirty"
            @select-step="selectStep"
            @go-triage="$emit('go-triage')"
          />

          <section v-if="currentStep.step_key === 'scene_details'" class="snowflake-scene-dynamics-card" data-testid="snowflake-scene-dynamics-card">
            <h4>💡 场景动力学 — 蔡格尼克开放循环原理</h4>
            <div class="scene-dynamics-grid">
              <article>
                <strong>主动场景 — 紧张引擎</strong>
                <p>• 目标：「可拍摄」——能用摄影机呈现</p>
                <p>• 冲突：反复的尝试→受阻循环</p>
                <p>• 挫折：主角比开场时更糟</p>
                <p>• 胜利：也要混入代价（否则读者放书）</p>
              </article>
              <article>
                <strong>被动场景 — 呼吸与选择</strong>
                <p>• 反应：先身体/情感，后理性</p>
                <p>• 困境：每个选项都有真实代价</p>
                <p>• 决定：必须决断，不能回避</p>
                <p>• 决定直接引发下一个目标</p>
              </article>
            </div>
          </section>

          <div class="editor-fields">
            <template v-for="field in currentStep.editor?.fields || []" :key="field.key">
              <label v-if="field.kind === 'text'" class="field-block">
                <span>{{ field.label }}</span>
                <small v-if="field.hint" class="field-hint">{{ field.hint }}</small>
                <input class="control-input" :value="currentStep.draft?.[field.key] || ''" :placeholder="field.placeholder || ''" @input="updateSimpleField(field.key, $event.target.value)" />
              </label>

              <label v-else-if="field.kind === 'textarea'" class="field-block">
                <span>{{ field.label }}</span>
                <small v-if="field.hint" class="field-hint">{{ field.hint }}</small>
                <textarea class="control-input" :value="currentStep.draft?.[field.key] || ''" :placeholder="field.placeholder || ''" @input="updateSimpleField(field.key, $event.target.value)" />
              </label>

              <label v-else-if="field.kind === 'list' || field.kind === 'paragraphs'" class="field-block">
                <span>{{ field.label }}</span>
                <small v-if="field.hint" class="field-hint">{{ field.hint }}</small>
                <textarea class="control-input" :value="joinLines(currentStep.draft?.[field.key])" :placeholder="field.placeholder || ''" @input="updateListField(field.key, $event.target.value)" />
              </label>

              <div v-else-if="field.kind === 'sentences'" class="field-block">
                <span>{{ field.label }}</span>
                <small v-if="field.hint" class="field-hint">{{ field.hint }}</small>
                <div class="sentence-grid">
                  <textarea v-for="(sentence, index) in currentStep.draft?.[field.key] || []" :key="`${field.key}-${index}`" class="control-input" :value="sentence" :placeholder="field.placeholder || ''" @input="updateSentence(field.key, index, $event.target.value)" />
                </div>
              </div>

              <div v-else-if="field.kind === 'object'" class="field-block">
                <span>{{ field.label }}</span>
                <div class="object-grid">
                  <label v-for="nestedField in field.fields || []" :key="nestedField.key">
                    <span>{{ nestedField.label }}</span>
                    <small v-if="nestedField.hint" class="field-hint">{{ nestedField.hint }}</small>
                    <input class="control-input" :value="currentStep.draft?.[field.key]?.[nestedField.key] || ''" :placeholder="nestedField.placeholder || ''" @input="updateNestedField(field.key, nestedField.key, $event.target.value)" />
                  </label>
                </div>
              </div>

              <div v-else-if="['characters', 'character_synopses', 'character_bibles'].includes(field.kind)" class="field-block">
                <div class="collection-head">
                  <span>{{ field.label }}</span>
                  <button type="button" class="ghost mini-btn" @click="addCollectionItem(field)"><Plus :size="14" /><span>新增</span></button>
                </div>
                <div class="collection-grid">
                  <article v-for="(item, index) in currentStep.draft?.[field.key] || []" :key="item.character_id || `${field.key}-${index}`" class="collection-card">
                    <div v-for="subKey in collectionFieldKeys(field)" :key="subKey" class="collection-field-group">
                      <template v-if="isNestedCollectionField(field, subKey)">
                        <span class="nested-group-title">{{ subKey }}</span>
                        <label v-for="nestedKey in nestedCollectionFieldKeys(field, subKey)" :key="nestedKey">
                          <span>{{ nestedKey }}</span>
                          <textarea v-if="isLongTextField(nestedKey)" class="control-input" :value="item?.[subKey]?.[nestedKey] || ''" @input="updateNestedCollectionField(field.key, index, subKey, nestedKey, $event.target.value)" />
                          <input v-else class="control-input" :value="item?.[subKey]?.[nestedKey] || ''" @input="updateNestedCollectionField(field.key, index, subKey, nestedKey, $event.target.value)" />
                        </label>
                      </template>
                      <label v-else>
                        <span>{{ subKey }}</span>
                        <textarea v-if="Array.isArray(field.template?.[subKey]) || isLongTextField(subKey)" class="control-input" :value="Array.isArray(item?.[subKey]) ? joinLines(item?.[subKey]) : item?.[subKey] || ''" @input="Array.isArray(field.template?.[subKey]) ? updateCollectionListField(field.key, index, subKey, $event.target.value) : updateCollectionField(field.key, index, subKey, $event.target.value)" />
                        <input v-else class="control-input" :value="item?.[subKey] || ''" @input="updateCollectionField(field.key, index, subKey, $event.target.value)" />
                      </label>
                    </div>
                  </article>
                </div>
              </div>

              <div v-else-if="field.kind === 'scene_list'" class="field-block">
                <span>{{ field.label }}</span>
                <div class="scene-card-grid">
                  <article v-for="(scene, index) in currentStep.draft?.scenes || []" :key="scene.scene_id || `${field.key}-${index}`" class="scene-card">
                    <div class="scene-card-head">
                      <strong>{{ scene.scene_id || `SCENE ${index + 1}` }}</strong>
                      <select class="control-input compact" :value="scenePrimaryForm(scene)" @change="updateScenePrimaryForm(field.key, index, $event.target.value)">
                        <option value="proactive">主动场景</option>
                        <option value="reactive">反应场景</option>
                      </select>
                    </div>
                    <label><span>章节标题</span><input class="control-input" :value="scene.chapter_title || ''" @input="updateCollectionField(field.key, index, 'chapter_title', $event.target.value)" /></label>
                    <label><span>场景摘要</span><textarea class="control-input" :value="scene.summary || ''" @input="updateCollectionField(field.key, index, 'summary', $event.target.value)" /></label>
                    <label><span>章节职责</span><input class="control-input" :value="scene.chapter_role || ''" @input="updateCollectionField(field.key, index, 'chapter_role', $event.target.value)" /></label>
                  </article>
                </div>
              </div>

              <div v-else-if="field.kind === 'scene_details'" class="field-block">
                <span>{{ field.label }}</span>
                <div class="scene-card-grid">
                  <article v-for="(scene, index) in currentStep.draft?.scenes || []" :key="scene.scene_id || `${field.key}-${index}`" class="scene-card">
                    <div class="scene-card-head">
                      <div><strong>{{ scene.title || scene.scene_id || `场景 ${index + 1}` }}</strong><small>{{ scene.scene_id }}</small></div>
                      <select class="control-input compact" :value="scenePrimaryForm(scene)" @change="updateScenePrimaryForm(field.key, index, $event.target.value)">
                        <option value="proactive">主动场景</option>
                        <option value="reactive">反应场景</option>
                      </select>
                    </div>
                    <label>
                      <span>{{ sceneDetailFieldLabel(scenePrimaryForm(scene), "crucible", "坩埚") }}</span>
                      <small v-if="sceneDetailFieldHint(scenePrimaryForm(scene), 'crucible')" class="field-hint">{{ sceneDetailFieldHint(scenePrimaryForm(scene), "crucible") }}</small>
                      <textarea class="control-input" :value="scene.crucible || scene.scene_crucible || ''" :placeholder="sceneDetailFieldPlaceholder(scenePrimaryForm(scene), 'crucible')" :rows="sceneDetailFieldRows(scenePrimaryForm(scene), 'crucible')" @input="updateSceneCrucible(field.key, index, $event.target.value)" />
                    </label>
                    <template v-if="scenePrimaryForm(scene) === 'proactive'">
                      <label>
                        <span>{{ sceneDetailFieldLabel(scenePrimaryForm(scene), "goal", "目标") }}</span>
                        <small v-if="sceneDetailFieldHint(scenePrimaryForm(scene), 'goal')" class="field-hint">{{ sceneDetailFieldHint(scenePrimaryForm(scene), "goal") }}</small>
                        <textarea class="control-input" :value="scene.goal || ''" :placeholder="sceneDetailFieldPlaceholder(scenePrimaryForm(scene), 'goal')" :rows="sceneDetailFieldRows(scenePrimaryForm(scene), 'goal')" @input="updateCollectionField(field.key, index, 'goal', $event.target.value)" />
                      </label>
                      <label>
                        <span>{{ sceneDetailFieldLabel(scenePrimaryForm(scene), "conflict", "冲突") }}</span>
                        <small v-if="sceneDetailFieldHint(scenePrimaryForm(scene), 'conflict')" class="field-hint">{{ sceneDetailFieldHint(scenePrimaryForm(scene), "conflict") }}</small>
                        <textarea class="control-input" :value="scene.conflict || ''" :placeholder="sceneDetailFieldPlaceholder(scenePrimaryForm(scene), 'conflict')" :rows="sceneDetailFieldRows(scenePrimaryForm(scene), 'conflict')" @input="updateCollectionField(field.key, index, 'conflict', $event.target.value)" />
                      </label>
                      <label>
                        <span>{{ sceneDetailFieldLabel(scenePrimaryForm(scene), "setback", "挫折") }}</span>
                        <small v-if="sceneDetailFieldHint(scenePrimaryForm(scene), 'setback')" class="field-hint">{{ sceneDetailFieldHint(scenePrimaryForm(scene), "setback") }}</small>
                        <textarea class="control-input" :value="scene.setback || ''" :placeholder="sceneDetailFieldPlaceholder(scenePrimaryForm(scene), 'setback')" :rows="sceneDetailFieldRows(scenePrimaryForm(scene), 'setback')" @input="updateCollectionField(field.key, index, 'setback', $event.target.value)" />
                      </label>
                    </template>
                    <template v-else>
                      <label>
                        <span>{{ sceneDetailFieldLabel(scenePrimaryForm(scene), "reaction", "反应") }}</span>
                        <small v-if="sceneDetailFieldHint(scenePrimaryForm(scene), 'reaction')" class="field-hint">{{ sceneDetailFieldHint(scenePrimaryForm(scene), "reaction") }}</small>
                        <textarea class="control-input" :value="scene.reaction || ''" :placeholder="sceneDetailFieldPlaceholder(scenePrimaryForm(scene), 'reaction')" :rows="sceneDetailFieldRows(scenePrimaryForm(scene), 'reaction')" @input="updateCollectionField(field.key, index, 'reaction', $event.target.value)" />
                      </label>
                      <label>
                        <span>{{ sceneDetailFieldLabel(scenePrimaryForm(scene), "dilemma", "困境") }}</span>
                        <small v-if="sceneDetailFieldHint(scenePrimaryForm(scene), 'dilemma')" class="field-hint">{{ sceneDetailFieldHint(scenePrimaryForm(scene), "dilemma") }}</small>
                        <textarea class="control-input" :value="scene.dilemma || ''" :placeholder="sceneDetailFieldPlaceholder(scenePrimaryForm(scene), 'dilemma')" :rows="sceneDetailFieldRows(scenePrimaryForm(scene), 'dilemma')" @input="updateCollectionField(field.key, index, 'dilemma', $event.target.value)" />
                      </label>
                      <label>
                        <span>{{ sceneDetailFieldLabel(scenePrimaryForm(scene), "decision", "决定") }}</span>
                        <small v-if="sceneDetailFieldHint(scenePrimaryForm(scene), 'decision')" class="field-hint">{{ sceneDetailFieldHint(scenePrimaryForm(scene), "decision") }}</small>
                        <textarea class="control-input" :value="scene.decision || ''" :placeholder="sceneDetailFieldPlaceholder(scenePrimaryForm(scene), 'decision')" :rows="sceneDetailFieldRows(scenePrimaryForm(scene), 'decision')" @input="updateCollectionField(field.key, index, 'decision', $event.target.value)" />
                      </label>
                    </template>
                    <label><span>离场变化</span><textarea class="control-input" :value="scene.exit_change || ''" placeholder="这一场结束后，人物处境、信息或关系发生了什么不可逆变化。" @input="updateCollectionField(field.key, index, 'exit_change', $event.target.value)" /></label>
                    <label><span>钩子</span><textarea class="control-input" :value="scene.hook || ''" placeholder="留给下一场或下一章的悬念、承诺或刺点。" @input="updateCollectionField(field.key, index, 'hook', $event.target.value)" /></label>
                    <label><span>目标篇幅</span><input class="control-input" :value="scene.target_length_band || ''" placeholder="短 / 中 / 长，或 1200-1800 字" @input="updateCollectionField(field.key, index, 'target_length_band', $event.target.value)" /></label>
                  </article>
                </div>
              </div>
            </template>
          </div>

          <div v-if="store.error" class="error-box">{{ store.error }}</div>

          <div v-if="['scene_list', 'scene_details'].includes(currentStep.step_key)" class="snowflake-triage-handoff" data-testid="snowflake-triage-handoff">
            <div>
              <span class="eyebrow">下一步</span>
              <strong>完成场景列表和场景规划后，进入场景急救。</strong>
              <p class="muted">用合格、需修改、废除重写三类先筛薄弱场景，再决定是否整理成章节结构。</p>
            </div>
            <button type="button" class="primary action-btn" @click="$emit('go-triage')">
              <WandSparkles :size="16" /><span>进入场景急救</span>
            </button>
          </div>
        </template>
        <p v-else class="muted">创建项目后，这里会展示十步雪花的结构化编辑区。</p>
      </div>
    </div>
  </section>
</template>
