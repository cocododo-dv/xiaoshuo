<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref } from "vue";

import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import SnowflakeAssistantPanel from "../components/SnowflakeAssistantPanel.vue";
import SnowflakeMaterializationPanel from "../components/SnowflakeMaterializationPanel.vue";
import SnowflakePlanningStage from "../components/SnowflakePlanningStage.vue";
import SnowflakeProjectPanel from "../components/SnowflakeProjectPanel.vue";
import SnowflakeSceneBoard from "../components/SnowflakeSceneBoard.vue";
import SnowflakeTriagePanel from "../components/SnowflakeTriagePanel.vue";
import { useShellRouter } from "../router";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const store = useSnowflakeWorkbenchStore();
const router = useShellRouter();
const projectPanel = ref(null);

const workbenchMode = computed(() => store.workbenchMode);
const sceneBoard = computed(() => store.sceneBoard);
const completedStepCount = computed(() => store.steps.filter((s) => s.gate_satisfied).length);
const totalStepCount = computed(() => store.steps.length || 0);
const discoveryCandidateSteps = computed(() => {
  const brief = store.discoveryStructureCandidate?.candidate_brief || {};
  const steps = brief.snowflake_steps || store.discoveryStructureCandidate?.snowflake_steps || {};
  return Object.entries(steps || {}).filter(([, value]) => value && typeof value === "object");
});
const triageStats = computed(() => {
  const items = store.triageDrafts || [];
  const effectiveStatus = (item) => item.effective_status || item.status || "";
  return {
    blocking: items.filter((item) => item.blocking).length,
    maybe: items.filter((item) => effectiveStatus(item) === "maybe").length,
  };
});

function setWorkbenchMode(mode) {
  store.setWorkbenchMode(mode);
}

async function ensureDiscoveryDraft() {
  await store.ensureDiscoveryDraft();
  emit("notice", { type: "success", message: "自由草稿已准备好。" });
}

async function saveDiscoveryDraft() {
  await store.saveDiscoveryDraft();
  emit("notice", { type: "success", message: "自由草稿已保存。" });
}

async function extractDiscoveryStructure() {
  await store.extractDiscoveryStructure();
  emit("notice", { type: "success", message: "结构候选已生成，可先预览再写入雪花。" });
}

async function applyDiscoveryStructure() {
  await store.applyDiscoveryStructure();
  emit("notice", { type: "success", message: "候选已写入雪花待审步骤。" });
}

async function openDiscoveryChapterDraft() {
  const payload = await store.openDiscoveryChapterDraft();
  const chapterId = payload?.target?.chapter_id || payload?.target?.object_id || payload?.chapter?.chapter_id || "";
  if (chapterId) {
    router.navigate("writer-room", {
      target: {
        focus: "chapter_goal",
        target: chapterId,
      },
    });
  }
  emit("notice", { type: "success", message: "已转入章节草稿，可以继续写正文。" });
}

function handleBeforeUnload(event) {
  if (!store.hasUnsavedStepDrafts) {
    return;
  }
  event.preventDefault();
  event.returnValue = "";
}

onMounted(() => {
  projectPanel.value?.initialize(false);
  if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", handleBeforeUnload);
  }
});
onActivated(() => projectPanel.value?.initialize(false));
onBeforeUnmount(() => {
  if (typeof window !== "undefined") {
    window.removeEventListener("beforeunload", handleBeforeUnload);
  }
});
</script>

<template>
  <section class="snowflake-workbench-view" data-testid="snowflake-workbench-view">
    <WorkflowPageHeader view-id="snowflake-workbench" kicker="雪花" />

    <div class="snowflake-workbench-shell">
      <main class="snowflake-workbench-main">
        <SnowflakeProjectPanel ref="projectPanel" @notice="emit('notice', $event)" />

        <section
          v-if="store.project?.project_id"
          class="snowflake-discovery-draft"
          data-testid="snowflake-discovery-draft"
        >
          <div class="panel-head">
            <div>
              <span class="eyebrow">Discovery draft</span>
              <h2>自由草稿</h2>
              <p class="muted">先写正文、想法或散乱素材，再提取成可审阅的雪花步骤。</p>
            </div>
            <button
              type="button"
              class="mini-btn"
              :disabled="store.actionId === 'discovery-ensure'"
              @click="ensureDiscoveryDraft"
            >
              打开草稿
            </button>
          </div>

          <textarea
            class="control-input discovery-textarea"
            :value="store.discoveryDraftContent"
            placeholder="把你想先写的内容放在这里。可以是整章草稿、场景碎片、人物动机或世界观笔记。"
            @input="store.setDiscoveryDraftContent($event.target.value)"
          />

          <div class="action-row discovery-actions">
            <button
              type="button"
              class="mini-btn"
              :disabled="!store.discoveryDraft || store.actionId === 'discovery-save'"
              @click="saveDiscoveryDraft"
            >
              保存
            </button>
            <button
              type="button"
              class="mini-btn"
              :disabled="!store.discoveryDraft || store.actionId === 'discovery-extract'"
              @click="extractDiscoveryStructure"
            >
              提取结构
            </button>
            <button
              type="button"
              class="action-btn"
              data-testid="snowflake-discovery-open-chapter-draft"
              :disabled="!store.discoveryDraft || store.actionId === 'discovery-open-chapter'"
              @click="openDiscoveryChapterDraft"
            >
              继续写正文
            </button>
            <button
              type="button"
              class="action-btn primary"
              :disabled="!store.discoveryStructureCandidate || store.actionId === 'discovery-apply'"
              @click="applyDiscoveryStructure"
            >
              写入待审雪花步骤
            </button>
          </div>

          <div v-if="discoveryCandidateSteps.length" class="discovery-preview">
            <strong>将写入这些待审步骤</strong>
            <ul>
              <li v-for="[stepKey, stepDraft] in discoveryCandidateSteps" :key="stepKey">
                <span>{{ stepKey }}</span>
                <small>{{ Object.keys(stepDraft || {}).join(" / ") }}</small>
              </li>
            </ul>
          </div>
        </section>

        <p v-if="store.recoveredDraftNotice" class="snowflake-draft-recovery" data-testid="snowflake-draft-recovery">
          {{ store.recoveredDraftNotice }}
        </p>

        <div class="snowflake-mode-switch" data-testid="snowflake-mode-switch">
          <button
            type="button"
            class="mode-tab"
            :class="{ active: workbenchMode === 'planning' }"
            data-testid="snowflake-mode-planning"
            @click="setWorkbenchMode('planning')"
          >
            <span>规划</span>
            <small>{{ completedStepCount }}/{{ totalStepCount }} 步</small>
          </button>
          <button
            type="button"
            class="mode-tab"
            :class="{ active: workbenchMode === 'triage' }"
            data-testid="snowflake-mode-triage"
            @click="setWorkbenchMode('triage')"
          >
            <span>急救</span>
            <small>{{ triageStats.blocking }} 阻塞 · {{ triageStats.maybe }} 待修</small>
          </button>
        </div>

        <SnowflakePlanningStage
          v-if="workbenchMode === 'planning'"
          @notice="emit('notice', $event)"
          @go-triage="setWorkbenchMode('triage')"
        />

        <SnowflakeSceneBoard
          v-if="workbenchMode === 'planning' && sceneBoard.scenes?.length"
          @notice="emit('notice', $event)"
        />

        <SnowflakeTriagePanel
          v-if="workbenchMode === 'triage'"
          @notice="emit('notice', $event)"
        />

        <SnowflakeMaterializationPanel
          v-if="workbenchMode === 'planning'"
          @notice="emit('notice', $event)"
        />
      </main>

      <SnowflakeAssistantPanel @notice="emit('notice', $event)" />
    </div>
  </section>
</template>

<style>
.snowflake-workbench-view {
  --snowflake-paper: #f7f6ef;
  --snowflake-paper-strong: #fffef8;
  --snowflake-panel: #fffdf7;
  --snowflake-ink: #24352f;
  --snowflake-heading: #152620;
  --snowflake-muted: #60746a;
  --snowflake-faint: #87968d;
  --snowflake-line: rgba(47, 111, 98, 0.16);
  --snowflake-line-strong: rgba(47, 111, 98, 0.28);
  --snowflake-moss: #2f6f62;
  --snowflake-moss-deep: #24564d;
  --snowflake-moss-soft: #edf7f2;
  --snowflake-teal: #3f7d86;
  --snowflake-teal-soft: #edf6f7;
  --snowflake-warning: #8c672b;
  --snowflake-warning-soft: #fff6e5;
  --snowflake-danger: #9f3f32;
  --snowflake-danger-soft: #fff1ed;
  --snowflake-shadow: 0 16px 34px rgba(31, 55, 48, 0.1);

  display: grid;
  gap: 18px;
  color: var(--snowflake-ink);
  min-width: 0;
  overflow-wrap: anywhere;
}

.snowflake-workbench-view .snowflake-workbench-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
  gap: 16px;
  align-items: start;
}

.snowflake-workbench-view .snowflake-workbench-main,
.snowflake-workbench-view .snowflake-assistant-panel {
  display: grid;
  gap: 16px;
  min-width: 0;
}

.snowflake-workbench-view .snowflake-project-launcher,
.snowflake-workbench-view .snowflake-discovery-draft,
.snowflake-workbench-view .snowflake-assistant-panel,
.snowflake-workbench-view .snowflake-workbench-stage,
.snowflake-workbench-view .snowflake-scene-board,
.snowflake-workbench-view .snowflake-scene-triage,
.snowflake-workbench-view .snowflake-outline-approve {
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-panel);
  box-shadow: var(--snowflake-shadow);
  padding: 16px;
}

.snowflake-workbench-view .panel-head,
.snowflake-workbench-view .action-row,
.snowflake-workbench-view .scene-card-head,
.snowflake-workbench-view .collection-head,
.snowflake-workbench-view .assistant-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.snowflake-workbench-view .panel-head,
.snowflake-workbench-view .scene-card-head,
.snowflake-workbench-view .collection-head,
.snowflake-workbench-view .assistant-card-head {
  justify-content: space-between;
}

.snowflake-workbench-view .panel-head h2,
.snowflake-workbench-view .snowflake-project-launcher h2,
.snowflake-workbench-view .current-step-copy h3 {
  margin: 3px 0 0;
  color: var(--snowflake-heading);
}

.snowflake-workbench-view .project-list,
.snowflake-workbench-view .project-form,
.snowflake-workbench-view .editor-fields,
.snowflake-workbench-view .assistant-thread,
.snowflake-workbench-view .outline-grid,
.snowflake-workbench-view .triage-grid,
.snowflake-workbench-view .collection-grid,
.snowflake-workbench-view .scene-card-grid,
.snowflake-workbench-view .scene-board-table {
  display: grid;
  gap: 12px;
}

.snowflake-workbench-view .scene-board-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 320px);
  gap: 12px;
  align-items: start;
}

.snowflake-workbench-view .snowflake-project-launcher {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.snowflake-workbench-view .snowflake-discovery-draft {
  display: grid;
  gap: 12px;
}

.snowflake-workbench-view .discovery-textarea {
  min-height: 180px;
}

.snowflake-workbench-view .discovery-actions {
  flex-wrap: wrap;
}

.snowflake-workbench-view .discovery-preview {
  display: grid;
  gap: 8px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
  padding: 12px;
}

.snowflake-workbench-view .discovery-preview ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.snowflake-workbench-view .discovery-preview li {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  border-top: 1px solid var(--snowflake-line);
  padding-top: 6px;
}

.snowflake-workbench-view .discovery-preview small {
  color: var(--snowflake-muted);
  text-align: right;
}

.snowflake-workbench-view .snowflake-project-launcher > div:first-child {
  min-width: 0;
}

.snowflake-workbench-view .snowflake-project-launcher h2 {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snowflake-workbench-view .project-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  justify-content: flex-end;
  background: rgba(21, 38, 32, 0.24);
  padding: 18px;
}

.snowflake-workbench-view .snowflake-project-drawer {
  display: grid;
  gap: 16px;
  width: min(420px, 100%);
  max-height: 100%;
  overflow: auto;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-panel);
  box-shadow: 0 24px 60px rgba(21, 38, 32, 0.22);
  padding: 16px;
}

.snowflake-workbench-view .project-row,
.snowflake-workbench-view .step-pill,
.snowflake-workbench-view .assistant-card,
.snowflake-workbench-view .outline-card,
.snowflake-workbench-view .triage-card,
.snowflake-workbench-view .collection-card,
.snowflake-workbench-view .scene-card {
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
  color: var(--snowflake-ink);
}

.snowflake-workbench-view .project-row,
.snowflake-workbench-view .step-pill {
  display: grid;
  gap: 4px;
  width: 100%;
  padding: 12px;
  border-left-width: 4px;
  box-shadow: none;
  color: var(--snowflake-ink);
  text-align: left;
}

.snowflake-workbench-view .project-row strong,
.snowflake-workbench-view .step-pill strong {
  color: var(--snowflake-heading);
}

.snowflake-workbench-view .project-row span,
.snowflake-workbench-view .step-pill span {
  color: var(--snowflake-muted);
}

.snowflake-workbench-view .project-row small,
.snowflake-workbench-view .step-pill small {
  color: var(--snowflake-faint);
}

.snowflake-workbench-view .project-row:hover:not(:disabled),
.snowflake-workbench-view .step-pill:hover:not(:disabled) {
  transform: none;
  border-color: var(--snowflake-line-strong);
  background: var(--snowflake-paper);
  color: var(--snowflake-ink);
}

.snowflake-workbench-view .project-row.active,
.snowflake-workbench-view .step-pill.active {
  border-color: rgba(47, 111, 98, 0.42);
  background: var(--snowflake-moss-soft);
  color: var(--snowflake-ink);
  box-shadow: inset 4px 0 0 var(--snowflake-moss);
}

.snowflake-workbench-view .step-pill.done:not(.active) {
  border-color: rgba(47, 111, 98, 0.32);
  background: #f2faf5;
}

.snowflake-workbench-view .step-pill.stale:not(.active) {
  border-color: rgba(159, 63, 50, 0.28);
  background: var(--snowflake-danger-soft);
}

.snowflake-workbench-view .step-pill.dirty:not(.active) {
  border-color: rgba(63, 125, 134, 0.32);
  background: var(--snowflake-teal-soft);
}

.snowflake-workbench-view .snowflake-progress-panel,
.snowflake-workbench-view .snowflake-step-state-strip,
.snowflake-workbench-view .snowflake-guidance-card,
.snowflake-workbench-view .snowflake-discovery-context,
.snowflake-workbench-view .snowflake-step-history,
.snowflake-workbench-view .snowflake-structure-handoff,
.snowflake-workbench-view .materialization-gate {
  display: grid;
  gap: 10px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
  padding: 12px;
}

.snowflake-workbench-view .snowflake-step-state-strip {
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 11rem), 1fr));
}

.snowflake-workbench-view .snowflake-progress-panel {
  grid-template-columns: minmax(150px, auto) minmax(120px, 1fr) auto;
  align-items: center;
}

.snowflake-workbench-view .snowflake-structure-handoff {
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  border-color: rgba(47, 111, 98, 0.24);
  background: var(--snowflake-moss-soft);
}

.snowflake-workbench-view .snowflake-structure-handoff p {
  margin: 4px 0 0;
}

.snowflake-workbench-view .snowflake-draft-recovery {
  margin: 0;
  border: 1px solid rgba(63, 125, 134, 0.24);
  border-radius: 8px;
  background: var(--snowflake-teal-soft);
  color: var(--snowflake-moss-deep);
  padding: 10px 12px;
  overflow-wrap: anywhere;
}

.snowflake-workbench-view .snowflake-offline-demo-note {
  margin: 8px 0 0;
  border: 1px solid rgba(140, 103, 43, 0.24);
  border-radius: 8px;
  background: var(--snowflake-warning-soft);
  color: var(--snowflake-warning);
  padding: 10px 12px;
}

.snowflake-workbench-view .snowflake-discovery-context {
  margin-top: 10px;
  background: var(--snowflake-moss-soft);
}

.snowflake-workbench-view .snowflake-discovery-context summary {
  cursor: pointer;
  color: var(--snowflake-heading);
  font-weight: 800;
}

.snowflake-workbench-view .snowflake-discovery-context p,
.snowflake-workbench-view .history-version-row p {
  margin: 0;
}

.snowflake-workbench-view .triage-bulk-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.snowflake-workbench-view .triage-origin-badge {
  border: 1px solid var(--snowflake-line);
  border-radius: 999px;
  background: var(--snowflake-paper);
  color: var(--snowflake-muted);
  padding: 3px 7px;
  font-size: 0.74rem;
  font-weight: 700;
}

.snowflake-workbench-view .triage-origin-badge.manual {
  border-color: rgba(47, 111, 98, 0.28);
  color: var(--snowflake-moss-deep);
}

.snowflake-workbench-view .triage-origin-badge.override {
  border-color: rgba(140, 103, 43, 0.32);
  background: var(--snowflake-warning-soft);
  color: var(--snowflake-warning);
}

.snowflake-workbench-view .snowflake-step-history {
  background: var(--snowflake-paper);
}

.snowflake-workbench-view .history-version-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  border-top: 1px solid var(--snowflake-line);
  padding-top: 10px;
}

.snowflake-workbench-view .snowflake-stale-note {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid rgba(159, 63, 50, 0.22);
  border-radius: 8px;
  background: var(--snowflake-danger-soft);
  color: var(--snowflake-danger);
  padding: 12px;
}

.snowflake-workbench-view .snowflake-stale-note.collapsed {
  border-color: rgba(140, 103, 43, 0.18);
  background: var(--snowflake-warning-soft);
  color: var(--snowflake-warning);
}

.snowflake-workbench-view .snowflake-stale-note p {
  margin: 4px 0 0;
}

.snowflake-workbench-view .snowflake-progress-track {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(47, 111, 98, 0.12);
}

.snowflake-workbench-view .snowflake-progress-track span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--snowflake-moss), var(--snowflake-teal));
}

.snowflake-workbench-view .snowflake-guidance-card ul,
.snowflake-workbench-view .gate-blockers,
.snowflake-workbench-view .gate-warnings {
  margin: 0;
  padding-left: 18px;
  color: var(--snowflake-ink);
}

.snowflake-workbench-view .snowflake-scene-dynamics-card {
  display: grid;
  gap: 12px;
  border: 1px solid rgba(63, 125, 134, 0.28);
  border-radius: 8px;
  background: linear-gradient(135deg, #f3f8f2, #eef7f6);
  color: var(--snowflake-ink);
  padding: 14px 16px;
}

.snowflake-workbench-view .snowflake-scene-dynamics-card h4 {
  margin: 0;
  color: var(--snowflake-moss-deep);
  font-size: 0.86rem;
  font-weight: 800;
  letter-spacing: 0.02em;
}

.snowflake-workbench-view .scene-dynamics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.snowflake-workbench-view .scene-dynamics-grid article {
  display: grid;
  gap: 6px;
  border: 1px solid rgba(47, 111, 98, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.54);
  padding: 12px 14px;
}

.snowflake-workbench-view .scene-dynamics-grid strong {
  color: var(--snowflake-teal);
  font-size: 0.86rem;
}

.snowflake-workbench-view .scene-dynamics-grid p {
  margin: 0;
  color: var(--snowflake-muted);
  font-size: 0.82rem;
  line-height: 1.8;
}

.snowflake-workbench-view .snowflake-triage-handoff {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border: 1px dashed var(--snowflake-line-strong);
  border-radius: 8px;
  background: var(--snowflake-moss-soft);
  padding: 12px 14px;
}

.snowflake-workbench-view .snowflake-triage-handoff strong {
  display: block;
  color: var(--snowflake-heading);
  margin: 2px 0 4px;
}

.snowflake-workbench-view .completion-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  border-top: 1px solid var(--snowflake-line);
  padding-top: 10px;
  color: var(--snowflake-muted);
}

.snowflake-workbench-view .materialization-gate.blocked {
  border-color: rgba(159, 63, 50, 0.32);
  background: var(--snowflake-danger-soft);
}

.snowflake-workbench-view .materialization-gate.warning {
  border-color: rgba(140, 103, 43, 0.34);
  background: var(--snowflake-warning-soft);
}

.snowflake-workbench-view .materialization-gate.ready {
  border-color: rgba(47, 111, 98, 0.32);
  background: var(--snowflake-moss-soft);
}

.snowflake-workbench-view .gate-blockers {
  color: var(--snowflake-danger);
}

.snowflake-workbench-view .gate-warnings {
  color: var(--snowflake-warning);
}

.snowflake-workbench-view .gate-action-list {
  display: grid;
  gap: 8px;
}

.snowflake-workbench-view .gate-action-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
  padding: 10px;
}

.snowflake-workbench-view .gate-action-item p {
  margin: 0;
  color: var(--snowflake-ink);
  overflow-wrap: anywhere;
}

.snowflake-workbench-view .gate-action-item.blocker {
  border-color: rgba(159, 63, 50, 0.28);
}

.snowflake-workbench-view .gate-action-item.warning {
  border-color: rgba(140, 103, 43, 0.28);
}

.snowflake-workbench-view .project-form label,
.snowflake-workbench-view .field-block,
.snowflake-workbench-view .triage-repair-field,
.snowflake-workbench-view .collection-card label,
.snowflake-workbench-view .scene-card label {
  display: grid;
  gap: 6px;
}

.snowflake-workbench-view .project-form-grid,
.snowflake-workbench-view .object-grid,
.snowflake-workbench-view .sentence-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.snowflake-workbench-view .sentence-grid {
  grid-template-columns: 1fr;
}

.snowflake-workbench-view .snowflake-workbench-stage-grid {
  display: grid;
  grid-template-columns: minmax(210px, 260px) minmax(0, 1fr);
  gap: 16px;
}

.snowflake-workbench-view .control-input {
  width: 100%;
  min-height: 42px;
  padding: 10px 12px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: #fff;
  color: var(--snowflake-ink);
}

.snowflake-workbench-view .control-input::placeholder {
  color: rgba(96, 116, 106, 0.55);
}

.snowflake-workbench-view textarea.control-input {
  min-height: 110px;
  resize: vertical;
}

.snowflake-workbench-view .compact-textarea {
  min-height: 72px;
}

.snowflake-workbench-view .compact {
  min-height: 36px;
}

.snowflake-workbench-view .scene-board-row {
  display: grid;
  grid-template-columns: minmax(160px, 1.1fr) repeat(5, minmax(120px, 1fr));
  gap: 10px;
  align-items: start;
  padding: 12px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
}

.snowflake-workbench-view .scene-board-row.active {
  border-color: var(--snowflake-line-strong);
  box-shadow: inset 4px 0 0 var(--snowflake-moss);
}

.snowflake-workbench-view .scene-board-drawer {
  position: sticky;
  top: 12px;
  display: grid;
  gap: 10px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
  padding: 12px;
}

.snowflake-workbench-view .scene-board-drawer h3 {
  margin: 3px 0;
  color: var(--snowflake-heading);
}

.snowflake-workbench-view .scene-board-row label,
.snowflake-workbench-view .scene-board-main {
  min-width: 0;
}

.snowflake-workbench-view .scene-board-main strong,
.snowflake-workbench-view .scene-board-main small {
  display: block;
}

.snowflake-workbench-view .scene-board-main small {
  margin-top: 6px;
  color: var(--snowflake-muted);
}

.snowflake-workbench-view .outline-input {
  min-height: 160px;
}

.snowflake-workbench-view .action-btn,
.snowflake-workbench-view .mini-btn,
.snowflake-workbench-view .icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border-radius: 999px;
  border: 1px solid var(--snowflake-line);
  padding: 10px 14px;
  background: var(--snowflake-paper-strong);
  color: var(--snowflake-moss-deep);
}

.snowflake-workbench-view .action-btn:hover:not(:disabled),
.snowflake-workbench-view .mini-btn:hover:not(:disabled),
.snowflake-workbench-view .icon-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: var(--snowflake-line-strong);
  background: var(--snowflake-moss-soft);
  color: var(--snowflake-moss-deep);
}

.snowflake-workbench-view .primary {
  background: var(--snowflake-moss);
  border-color: var(--snowflake-moss);
  color: #fff;
}

.snowflake-workbench-view .primary:hover:not(:disabled) {
  background: var(--snowflake-moss-deep);
  border-color: var(--snowflake-moss-deep);
  color: #fff;
}

.snowflake-workbench-view .ghost {
  background: var(--snowflake-paper-strong);
  color: var(--snowflake-moss-deep);
}

.snowflake-workbench-view .icon-btn {
  width: 38px;
  height: 38px;
  padding: 0;
}

.snowflake-workbench-view .assistant-card,
.snowflake-workbench-view .outline-card,
.snowflake-workbench-view .triage-card,
.snowflake-workbench-view .collection-card,
.snowflake-workbench-view .scene-card {
  display: grid;
  gap: 10px;
  padding: 12px;
}

.snowflake-workbench-view .collection-field-group {
  display: grid;
  gap: 8px;
}

.snowflake-workbench-view .nested-group-title {
  color: var(--snowflake-heading);
  font-size: 0.82rem;
  font-weight: 700;
}

.snowflake-workbench-view .assistant-list {
  margin: 0;
  padding-left: 18px;
  color: var(--snowflake-ink);
}

.snowflake-workbench-view .assistant-quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.snowflake-workbench-view .snowflake-mode-switch {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-panel);
  box-shadow: var(--snowflake-shadow);
  padding: 8px;
}

.snowflake-workbench-view .mode-tab {
  display: grid;
  gap: 2px;
  min-height: 58px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--snowflake-muted);
}

.snowflake-workbench-view .mode-tab span {
  color: inherit;
  font-weight: 700;
}

.snowflake-workbench-view .mode-tab small {
  color: var(--snowflake-faint);
}

.snowflake-workbench-view .mode-tab.active {
  border-color: rgba(47, 111, 98, 0.28);
  background: var(--snowflake-moss-soft);
  color: var(--snowflake-moss-deep);
}

.snowflake-workbench-view .triage-filter-row,
.snowflake-workbench-view .triage-tag-row,
.snowflake-workbench-view .triage-diagnosis-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.snowflake-workbench-view .triage-filter-row .mini-btn.active {
  background: var(--snowflake-moss);
  border-color: var(--snowflake-moss);
  color: #fff;
}

.snowflake-workbench-view .triage-workbench-grid {
  display: grid;
  grid-template-columns: minmax(250px, 34%) minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}

.snowflake-workbench-view .triage-queue {
  display: grid;
  gap: 8px;
}

.snowflake-workbench-view .triage-queue-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: 1px solid var(--snowflake-line);
  border-left-width: 5px;
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
  color: var(--snowflake-ink);
  padding: 10px;
  text-align: left;
}

.snowflake-workbench-view .triage-queue-row:hover:not(:disabled),
.snowflake-workbench-view .triage-queue-row.active {
  transform: none;
  background: var(--snowflake-paper);
  border-color: var(--snowflake-line-strong);
}

.snowflake-workbench-view .triage-queue-row.pass {
  border-left-color: var(--snowflake-moss);
}

.snowflake-workbench-view .triage-queue-row.maybe {
  border-left-color: var(--snowflake-warning);
}

.snowflake-workbench-view .triage-queue-row.rewrite {
  border-left-color: var(--snowflake-danger);
}

.snowflake-workbench-view .triage-queue-row small {
  display: block;
  color: var(--snowflake-faint);
  margin-top: 2px;
}

.snowflake-workbench-view .triage-score {
  min-width: 34px;
  border-radius: 999px;
  background: rgba(47, 111, 98, 0.1);
  color: var(--snowflake-moss-deep);
  font-weight: 700;
  padding: 5px 8px;
  text-align: center;
}

.snowflake-workbench-view .triage-badge,
.snowflake-workbench-view .triage-tag-row span,
.snowflake-workbench-view .triage-diagnosis-strip span {
  border-radius: 999px;
  background: var(--snowflake-paper);
  color: var(--snowflake-muted);
  font-size: 0.78rem;
  padding: 5px 8px;
}

.snowflake-workbench-view .triage-badge.pass,
.snowflake-workbench-view .triage-score-ring.pass {
  background: var(--snowflake-moss-soft);
  color: var(--snowflake-moss-deep);
}

.snowflake-workbench-view .triage-badge.maybe,
.snowflake-workbench-view .triage-score-ring.maybe {
  background: var(--snowflake-warning-soft);
  color: var(--snowflake-warning);
}

.snowflake-workbench-view .triage-badge.rewrite,
.snowflake-workbench-view .triage-score-ring.rewrite {
  background: var(--snowflake-danger-soft);
  color: var(--snowflake-danger);
}

.snowflake-workbench-view .triage-detail-card {
  display: grid;
  gap: 12px;
  border: 1px solid var(--snowflake-line);
  border-radius: 8px;
  background: var(--snowflake-paper-strong);
  padding: 14px;
}

.snowflake-workbench-view .triage-detail-card h3 {
  margin: 3px 0;
  color: var(--snowflake-heading);
}

.snowflake-workbench-view .triage-score-ring {
  display: grid;
  justify-items: center;
  min-width: 70px;
  border-radius: 8px;
  padding: 10px;
}

.snowflake-workbench-view .triage-score-ring strong {
  font-size: 1.4rem;
  line-height: 1;
}

.snowflake-workbench-view .triage-detail-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.snowflake-workbench-view .triage-repair-apply {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--snowflake-line);
}

.snowflake-workbench-view .field-hint {
  color: var(--snowflake-faint);
  line-height: 1.35;
}

.snowflake-workbench-view .step-meta,
.snowflake-workbench-view .assistant-candidate-label {
  margin: 0;
  color: var(--snowflake-muted);
}

.snowflake-workbench-view .muted {
  margin: 0;
  color: var(--snowflake-muted);
}

.snowflake-workbench-view .error-box {
  border-radius: 8px;
  background: var(--snowflake-danger-soft);
  color: var(--snowflake-danger);
  padding: 12px;
}

.snowflake-workbench-view .eyebrow {
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--snowflake-muted);
}

@media (max-width: 1180px) {
  .snowflake-workbench-view .snowflake-workbench-shell {
    grid-template-columns: 1fr;
  }

  .snowflake-workbench-view .snowflake-project-launcher {
    align-items: stretch;
    flex-direction: column;
  }

  .snowflake-workbench-view .project-drawer-backdrop {
    padding: 10px;
  }

  .snowflake-workbench-view .snowflake-workbench-stage-grid {
    grid-template-columns: 1fr;
  }

  .snowflake-workbench-view .scene-board-layout,
  .snowflake-workbench-view .scene-board-row {
    grid-template-columns: 1fr;
  }

  .snowflake-workbench-view .scene-board-drawer {
    position: static;
  }

  .snowflake-workbench-view .snowflake-triage-handoff {
    align-items: stretch;
    flex-direction: column;
  }

  .snowflake-workbench-view .triage-workbench-grid,
  .snowflake-workbench-view .triage-detail-columns,
  .snowflake-workbench-view .scene-dynamics-grid {
    grid-template-columns: 1fr;
  }

  .snowflake-workbench-view .triage-repair-apply {
    align-items: stretch;
    flex-direction: column;
  }
}

@media (max-width: 640px) {
  .snowflake-workbench-view,
  .snowflake-workbench-view .snowflake-workbench-shell,
  .snowflake-workbench-view .snowflake-workbench-stage,
  .snowflake-workbench-view .snowflake-workbench-side {
    min-width: 0;
  }

  .snowflake-workbench-view {
    gap: 10px;
  }

  .snowflake-workbench-view .snowflake-project-drawer {
    width: min(100%, 24rem);
  }

  .snowflake-workbench-view .snowflake-project-drawer,
  .snowflake-workbench-view .snowflake-workbench-stage-card,
  .snowflake-workbench-view .snowflake-side-panel,
  .snowflake-workbench-view .triage-detail-card,
  .snowflake-workbench-view .scene-dynamics-grid article {
    padding: 12px;
  }

  .snowflake-workbench-view .snowflake-stage-head,
  .snowflake-workbench-view .snowflake-stage-actions,
  .snowflake-workbench-view .snowflake-mode-switch,
  .snowflake-workbench-view .snowflake-triage-handoff,
  .snowflake-workbench-view .triage-filter-row,
  .snowflake-workbench-view .triage-tag-row,
  .snowflake-workbench-view .triage-diagnosis-strip,
  .snowflake-workbench-view .assistant-quick-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .snowflake-workbench-view .snowflake-stage-actions button,
  .snowflake-workbench-view .snowflake-mode-switch button,
  .snowflake-workbench-view .triage-filter-row button,
  .snowflake-workbench-view .assistant-quick-actions button {
    width: 100%;
    min-height: 44px;
  }

  .snowflake-workbench-view .snowflake-progress-panel,
  .snowflake-workbench-view .snowflake-step-state-strip,
  .snowflake-workbench-view .triage-queue-row {
    grid-template-columns: 1fr;
  }

  .snowflake-workbench-view .triage-repair-apply button,
  .snowflake-workbench-view .materialization-gate button {
    width: 100%;
    min-height: 44px;
  }

  .snowflake-workbench-view .gate-action-item {
    grid-template-columns: 1fr;
  }
}
</style>
