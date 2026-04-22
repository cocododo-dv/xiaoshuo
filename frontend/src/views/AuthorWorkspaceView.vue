<script setup>
import { computed, onActivated, reactive, ref, watch } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import PanelShell from "../components/PanelShell.vue";
import VirtualList from "../components/VirtualList.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useAuthorWorkspaceStore } from "../stores/authorWorkspace";

const emit = defineEmits(["notice"]);

const authorWorkspace = useAuthorWorkspaceStore();
const { openTarget } = useShellRouter();
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});
const AUTHOR_WORKSPACE_SCOPE = "author:workspace";
const AUTHOR_CHAPTER_SCOPE = "author:chapter";
const AUTHOR_SCENE_SCOPE = "author:scene";
const AUTHOR_ORDER_SCOPE = "author:order";

function createEmptyChapterForm() {
  return {
    chapter_id: "",
    planned_scene_count: 1,
    mid_aggregate_enabled: 0,
    chapter_goal: "",
    main_plot_push: "",
    emotional_target: "",
    ending_effect: "",
    must_not: "",
    notes: "",
  };
}

function createEmptySceneForm(chapterId = "") {
  return {
    scene_id: "",
    chapter_id: chapterId,
    pov_character_id: "",
    onstage_chars_json: "",
    location: "",
    scene_goal: "",
    beats_json: "",
    must_include_text: "",
    forbidden_text: "",
    exit_change: "",
    hook: "",
    target_length_band: "medium",
    scene_type: "reunion",
  };
}

const chapterForm = reactive(createEmptyChapterForm());
const sceneForm = reactive(createEmptySceneForm());
const selectedSceneId = ref("");
const selectedChapterIdsForTrash = ref([]);
const selectedSceneIdsForTrash = ref([]);
const creatingChapter = ref(false);
const creatingScene = ref(false);

const chapters = computed(() => authorWorkspace.chapters || []);
const scenes = computed(() => authorWorkspace.scenes || []);
const pinnedChapterKeys = computed(() => (authorWorkspace.selectedChapterId ? [authorWorkspace.selectedChapterId] : []));
const pinnedSceneKeys = computed(() => (selectedSceneId.value ? [selectedSceneId.value] : []));
const chapterRunStatus = computed(() => authorWorkspace.chapterRunStatus || null);
const selectedScene = computed(() => scenes.value.find((scene) => scene.scene_id === selectedSceneId.value) || null);
const trashableChapterIds = computed(() => {
  const ids = new Set();
  chapters.value.forEach((item) => {
    if (isChapterTrashAllowed(item)) {
      ids.add(item.chapter_id);
    }
  });
  return ids;
});
const selectableSceneIds = computed(() => {
  const ids = new Set();
  scenes.value.forEach((scene) => {
    ids.add(scene.scene_id);
  });
  return ids;
});
const selectedChapterTrashIds = computed(() =>
  selectedChapterIdsForTrash.value.filter((chapterId) => trashableChapterIds.value.has(chapterId)),
);
const selectedSceneTrashIds = computed(() =>
  selectedSceneIdsForTrash.value.filter((sceneId) => selectableSceneIds.value.has(sceneId)),
);
const chapterRunCompletedCount = computed(() => chapterRunStatus.value?.completed_scene_ids?.length || 0);
const chapterRunActionLabel = computed(() =>
  chapterRunStatus.value?.status === "blocked" ? "Resume chapter run" : "Run chapter",
);
const completedSceneIdSet = computed(() => new Set(chapterRunStatus.value?.completed_scene_ids || []));
const sceneRowMapVersion = computed(() => [
  chapterRunStatus.value?.status || "",
  chapterRunStatus.value?.current_scene_id || "",
  chapterRunStatus.value?.blocked_scene_id || "",
  scenes.value.length,
  chapterRunStatus.value?.completed_scene_ids?.join("|") || "",
].join("::"));
const sceneActionDisabled = computed(() =>
  authorWorkspace.loading || !authorWorkspace.selectedChapterId || authorWorkspace.actionId === "load-scene-draft",
);

function sceneBatchState(sceneId) {
  if (chapterRunStatus.value?.blocked_scene_id === sceneId) {
    return "blocked";
  }
  if (completedSceneIdSet.value.has(sceneId)) {
    return "completed";
  }
  if (chapterRunStatus.value?.current_scene_id === sceneId && chapterRunStatus.value?.status === "running") {
    return "running";
  }
  return "pending";
}

function sceneBatchLabel(sceneId) {
  return `Batch ${sceneBatchState(sceneId)}`;
}

function assignChapterForm(nextChapter) {
  Object.assign(chapterForm, createEmptyChapterForm(), nextChapter || {});
  if (!nextChapter) {
    chapterForm.chapter_id = "";
  }
}

function listToText(value) {
  return Array.isArray(value) ? value.join(", ") : "";
}

function textToList(value) {
  return (value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function assignSceneForm(nextScene) {
  if (!nextScene) {
    Object.assign(sceneForm, createEmptySceneForm(authorWorkspace.selectedChapterId || chapterForm.chapter_id));
    return;
  }
  Object.assign(sceneForm, createEmptySceneForm(nextScene.chapter_id), {
    scene_id: nextScene.scene_id,
    chapter_id: nextScene.chapter_id,
    pov_character_id: nextScene.pov_character_id || "",
    onstage_chars_json: listToText(nextScene.onstage_chars_json),
    location: nextScene.location || "",
    scene_goal: nextScene.scene_goal || "",
    beats_json: listToText(nextScene.beats_json),
    must_include_text: nextScene.must_include_text || "",
    forbidden_text: nextScene.forbidden_text || "",
    exit_change: nextScene.exit_change || "",
    hook: nextScene.hook || "",
    target_length_band: nextScene.target_length_band || "medium",
    scene_type: nextScene.scene_type || "reunion",
  });
}

function confirmAction(message) {
  if (typeof window === "undefined" || typeof window.confirm !== "function") {
    return true;
  }
  return window.confirm(message);
}

function startNewChapter() {
  creatingChapter.value = true;
  creatingScene.value = true;
  selectedSceneId.value = "";
  assignChapterForm(null);
  assignSceneForm(null);
}

function startNewScene() {
  creatingScene.value = true;
  selectedSceneId.value = "";
  assignSceneForm(null);
}

function loadSceneDraft() {
  return authorWorkspace.loadSceneDraft();
}

async function startQuickScene() {
  creatingScene.value = true;
  selectedSceneId.value = "";
  const draft = await runFlowAction({
    scopeKey: AUTHOR_SCENE_SCOPE,
    actionLabel: "生成智能草稿",
    runningMessage: "正在生成场景智能草稿...",
    successMessage: (result) => `已生成智能草稿 ${result?.scene_id || ""}`.trim(),
    nextStep: () => "下一步：检查草稿内容并保存场景。",
    action: () => {
      return loadSceneDraft();
    },
  });
  if (draft) {
    assignSceneForm(draft);
  } else {
    creatingScene.value = false;
  }
}

function isChapterTrashAllowed(item) {
  return Number(item?.trash_allowed) === 1;
}

function authorChapterRow(item) {
  return {
    item,
    chapterId: item?.chapter_id || "",
    chapterGoal: item?.chapter_goal || "",
    currentPhase: item?.current_phase || "-",
    activeSceneCount: item?.active_scene_count ?? 0,
    trashedSceneCount: item?.trashed_scene_count ?? 0,
    trashAllowed: isChapterTrashAllowed(item),
    trashBlockReason: item?.trash_block_reason || "",
  };
}

function authorSceneRow(item) {
  const sceneId = item?.scene_id || "";

  return {
    item,
    sceneId,
    sceneSeq: item?.scene_seq ?? 0,
    sceneGoal: item?.scene_goal || "",
    sceneStatus: item?.scene_status || "-",
    locationLabel: item?.location || "未设置地点",
    batchLabel: sceneBatchLabel(sceneId),
    moveUpDisabled: item?.scene_seq === 1,
    moveDownDisabled: item?.scene_seq === scenes.value.length,
    markLastDisabled: item?.is_chapter_last === 1,
  };
}

function syncChapterTrashSelection() {
  selectedChapterIdsForTrash.value = selectedChapterIdsForTrash.value.filter((chapterId) =>
    trashableChapterIds.value.has(chapterId),
  );
}

function syncSceneTrashSelection() {
  selectedSceneIdsForTrash.value = selectedSceneIdsForTrash.value.filter((sceneId) => selectableSceneIds.value.has(sceneId));
}

async function refreshAuthorWorkspace() {
  const result = await runFlowAction({
    scopeKey: AUTHOR_WORKSPACE_SCOPE,
    actionLabel: "刷新作者工作台",
    runningMessage: "正在刷新作者工作台...",
    successMessage: () => "作者工作台已刷新。",
    nextStep: () => "下一步：选择章节或继续编辑当前草稿。",
    action: () => authorWorkspace.ensureLoaded({ force: true }),
  });
  if (result !== null) {
    syncChapterTrashSelection();
    syncSceneTrashSelection();
  }
}

async function ensureAuthorWorkspaceLoaded() {
  await authorWorkspace.ensureLoaded();
  syncChapterTrashSelection();
  syncSceneTrashSelection();
  if (authorWorkspace.error) {
    emit("notice", authorWorkspace.error);
  }
}

async function selectChapter(chapterId) {
  creatingChapter.value = false;
  creatingScene.value = false;
  try {
    await authorWorkspace.selectChapter(chapterId);
  } catch (error) {
    emit("notice", error.message);
  }
}

function selectScene(sceneId) {
  creatingScene.value = false;
  selectedSceneId.value = sceneId;
}

async function saveChapter() {
  const result = await runFlowAction({
    scopeKey: AUTHOR_CHAPTER_SCOPE,
    actionLabel: "保存章节",
    runningMessage: "正在保存章节简报...",
    successMessage: (message) => message || "章节已保存。",
    nextStep: () => "下一步：保存场景，或运行章节批处理。",
    action: () => authorWorkspace.saveChapter({
      ...chapterForm,
      planned_scene_count: Number(chapterForm.planned_scene_count || 0),
      mid_aggregate_enabled: Number(chapterForm.mid_aggregate_enabled || 0),
    }),
  });
  if (result) {
    creatingChapter.value = false;
  }
}

async function saveScene() {
  const result = await runFlowAction({
    scopeKey: AUTHOR_SCENE_SCOPE,
    actionLabel: "保存场景",
    runningMessage: "正在保存场景目标...",
    successMessage: (message) => message || "场景已保存。",
    nextStep: () => "下一步：打开场景工作台运行，或继续调整场景顺序。",
    action: () => authorWorkspace.saveScene({
      ...sceneForm,
      chapter_id: authorWorkspace.selectedChapterId || chapterForm.chapter_id,
      onstage_chars_json: textToList(sceneForm.onstage_chars_json),
      beats_json: textToList(sceneForm.beats_json),
    }),
  });
  if (result) {
    creatingScene.value = false;
    selectedSceneId.value = sceneForm.scene_id;
  }
}

async function runChapter() {
  await runFlowAction({
    scopeKey: AUTHOR_CHAPTER_SCOPE,
    actionLabel: "运行章节",
    runningMessage: "正在运行章节批处理...",
    successMessage: (message) => message || "章节运行已推进。",
    nextStep: () => "下一步：查看章节运行状态，处理阻塞场景或继续运行。",
    action: () => authorWorkspace.runChapter(),
  });
}

async function moveScene(sceneId, offset) {
  const currentIndex = scenes.value.findIndex((scene) => scene.scene_id === sceneId);
  const nextIndex = currentIndex + offset;
  if (currentIndex < 0 || nextIndex < 0 || nextIndex >= scenes.value.length) {
    return;
  }
  const orderedSceneIds = scenes.value.map((scene) => scene.scene_id);
  const [movedSceneId] = orderedSceneIds.splice(currentIndex, 1);
  orderedSceneIds.splice(nextIndex, 0, movedSceneId);
  const lastSceneId = scenes.value.find((scene) => scene.is_chapter_last === 1)?.scene_id || orderedSceneIds.at(-1);
  await runFlowAction({
    scopeKey: AUTHOR_ORDER_SCOPE,
    actionLabel: "调整场景顺序",
    runningMessage: "正在保存场景顺序...",
    successMessage: (message) => message || "场景顺序已更新。",
    nextStep: () => "下一步：确认章节尾场景，或运行章节。",
    action: () => authorWorkspace.reorderScenes(orderedSceneIds, lastSceneId),
  });
}

async function markSceneAsLast(sceneId) {
  await runFlowAction({
    scopeKey: AUTHOR_ORDER_SCOPE,
    actionLabel: "标记章节结尾",
    runningMessage: "正在标记章节结尾场景...",
    successMessage: (message) => message || "章节结尾场景已更新。",
    nextStep: () => "下一步：运行章节或继续编辑场景。",
    action: () =>
      authorWorkspace.reorderScenes(
        scenes.value.map((scene) => scene.scene_id),
        sceneId,
      ),
  });
}

async function trashSelectedScenes() {
  const sceneIds = [...selectedSceneTrashIds.value];
  if (!sceneIds.length || !confirmAction(`确认将选中的 ${sceneIds.length} 个场景移入作者回收站吗？`)) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: AUTHOR_SCENE_SCOPE,
    actionLabel: "回收场景",
    runningMessage: `正在回收 ${sceneIds.length} 个场景...`,
    successMessage: (message) => message || "场景已移入回收站。",
    nextStep: () => "下一步：如需恢复，可到作者回收站处理。",
    action: () => authorWorkspace.trashScenes(sceneIds),
  });
  if (result) {
    selectedSceneIdsForTrash.value = [];
  }
}

async function trashSelectedChapters() {
  const chapterIds = [...selectedChapterTrashIds.value];
  if (!chapterIds.length || !confirmAction(`确认将选中的 ${chapterIds.length} 个章节移入作者回收站吗？`)) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: AUTHOR_CHAPTER_SCOPE,
    actionLabel: "回收章节",
    runningMessage: `正在回收 ${chapterIds.length} 个章节...`,
    successMessage: (message) => message || "章节已移入回收站。",
    nextStep: () => "下一步：如需恢复，可到作者回收站处理。",
    action: () => authorWorkspace.trashChapters(chapterIds),
  });
  if (result) {
    creatingChapter.value = false;
    creatingScene.value = false;
    selectedChapterIdsForTrash.value = [];
    selectedSceneId.value = "";
  }
}

function openInWorkbench(sceneId) {
  openTarget({
    target_type: "scene_card",
    target_id: sceneId,
    target_ref: `scene_card:${sceneId}`,
  });
  emit("notice", `已在场景工作台打开 scene_card:${sceneId}`);
}

watch(
  () => authorWorkspace.chapter,
  (nextChapter) => {
    if (!creatingChapter.value) {
      assignChapterForm(nextChapter);
    }
  },
  { immediate: true },
);

watch(
  () => authorWorkspace.selectedChapterId,
  (nextChapterId) => {
    if (!creatingScene.value) {
      assignSceneForm(selectedScene.value);
    } else {
      assignSceneForm(null);
      sceneForm.chapter_id = nextChapterId || chapterForm.chapter_id || "";
    }
  },
  { immediate: true },
);

watch(
  () => selectedScene.value,
  (nextScene) => {
    if (!creatingScene.value) {
      assignSceneForm(nextScene);
    }
  },
  { immediate: true },
);

watch(
  () => authorWorkspace.sceneListVersion,
  () => {
    syncSceneTrashSelection();
    if (!selectedSceneId.value && scenes.value.length && !creatingScene.value) {
      selectedSceneId.value = scenes.value[0].scene_id;
    }
    if (selectedSceneId.value && !scenes.value.some((scene) => scene.scene_id === selectedSceneId.value)) {
      selectedSceneId.value = scenes.value[0]?.scene_id || "";
    }
  },
  { immediate: true },
);

watch(
  () => authorWorkspace.chapterListVersion,
  () => {
    syncChapterTrashSelection();
  },
  { immediate: true },
);

onActivated(() => {
  ensureAuthorWorkspaceLoaded();
});
</script>

<template>
  <section class="panel-grid" data-testid="author-workspace-view">
    <PanelShell
      eyebrow="作者工作台"
      title="在进入运行时之前编排活跃章节"
      description="在这里起草章节与场景，把不再参与当前创作流的记录批量移入回收站，并在准备就绪时把场景交给场景工作台继续处理。"
    >
      <template #actions>
        <div class="field-inline">
          <button data-testid="author-refresh-button" @click="refreshAuthorWorkspace">刷新工作台</button>
          <button class="ghost" data-testid="author-new-chapter-button" @click="startNewChapter">新建章节</button>
          <button
            class="ghost"
            data-testid="author-quick-scene-button"
            :disabled="sceneActionDisabled"
            @click="startQuickScene"
          >
            快速新建场景
          </button>
          <button
            class="ghost"
            data-testid="author-new-scene-button"
            :disabled="sceneActionDisabled"
            @click="startNewScene"
          >
            新建场景
          </button>
        </div>
      </template>
      <FlowActionReceipt :receipt="receipt(AUTHOR_WORKSPACE_SCOPE)" />

      <div v-if="authorWorkspace.loading" class="empty loading-pulse">正在加载作者工作台...</div>
      <div v-else-if="authorWorkspace.error" class="empty">{{ authorWorkspace.error }}</div>
      <div v-else class="author-layout">
        <article class="paper author-sidebar">
          <div class="receipt-head">
            <div>
              <h3>章节列表</h3>
              <p class="muted receipt-copy">选择一个活跃章节继续编辑，或从这里新建章节。</p>
            </div>
            <span class="badge">{{ chapters.length }} 个活跃章节</span>
          </div>

          <div class="author-list-toolbar">
            <button
              class="danger-button"
              data-testid="author-trash-selected-chapters-button"
              :disabled="!selectedChapterTrashIds.length || authorWorkspace.actionId === 'trash-chapters'"
              @click="trashSelectedChapters"
            >
              移入所选章节
            </button>
          </div>
          <FlowActionReceipt compact :receipt="receipt(AUTHOR_CHAPTER_SCOPE)" />

          <div v-if="!chapters.length" class="empty">当前还没有活跃章节。</div>
          <VirtualList
            v-else
            class="author-list"
            :items="chapters"
            item-key="chapter_id"
            :estimated-item-height="128"
            :threshold="8"
            :viewport-height="520"
            :pinned-keys="pinnedChapterKeys"
            :map-item="authorChapterRow"
            test-id="author-chapter-virtual-list"
          >
            <template #default="{ row }">
              <article
                class="author-list-row"
                :class="{ disabled: !row.trashAllowed }"
              >
              <label class="author-select-cell" :for="`chapter-trash-${row.chapterId}`">
                <input
                  :id="`chapter-trash-${row.chapterId}`"
                  v-model="selectedChapterIdsForTrash"
                  type="checkbox"
                  :value="row.chapterId"
                  :data-testid="`author-chapter-select-for-trash-${row.chapterId}`"
                  :disabled="!row.trashAllowed || authorWorkspace.actionId === 'trash-chapters'"
                  @click.stop
                />
              </label>

              <div class="author-list-content">
                <button
                  class="author-list-item"
                  :class="{ active: authorWorkspace.selectedChapterId === row.chapterId }"
                  :data-testid="`author-chapter-select-${row.chapterId}`"
                  @click="selectChapter(row.chapterId)"
                >
                  <strong>{{ row.chapterId }}</strong>
                  <span>{{ row.chapterGoal }}</span>
                  <span class="muted">{{ row.currentPhase }} · {{ row.activeSceneCount }} 个活跃场景</span>
                </button>

                <div class="author-list-meta">
                  <span class="badge">{{ row.activeSceneCount }} 个活跃场景</span>
                  <span class="badge">{{ row.trashedSceneCount }} 个已回收场景</span>
                  <p
                    v-if="row.trashBlockReason"
                    class="author-block-reason"
                    :data-testid="`author-chapter-trash-block-${row.chapterId}`"
                  >
                    {{ row.trashBlockReason }}
                  </p>
                </div>
              </div>
              </article>
            </template>
          </VirtualList>
        </article>

        <article class="paper author-editor-card">
          <div class="receipt-head">
            <div>
              <h3>章节表单</h3>
              <p class="muted receipt-copy">维护面向作者的章节简报，供后续运行时流程直接消费。</p>
            </div>
            <span class="badge">{{ creatingChapter ? "新建中" : "编辑中" }}</span>
          </div>

          <div class="author-form-grid" data-testid="author-chapter-form">
            <label>
              <span>章节 ID</span>
              <input
                v-model="chapterForm.chapter_id"
                class="control-input"
                data-testid="author-chapter-id"
                :disabled="!creatingChapter && Boolean(chapterForm.chapter_id)"
              />
            </label>
            <label>
              <span>计划场景数</span>
              <input
                v-model.number="chapterForm.planned_scene_count"
                type="number"
                class="control-input"
                data-testid="author-chapter-scene-count"
                min="1"
              />
            </label>
            <label class="checkbox-inline">
              <input v-model.number="chapterForm.mid_aggregate_enabled" type="checkbox" true-value="1" false-value="0" />
              <span>启用章节中段汇总</span>
            </label>
            <div class="author-runtime-summary" v-if="authorWorkspace.chapterState">
              <span class="badge">阶段 {{ authorWorkspace.chapterState.current_phase }}</span>
              <span class="badge">已通过 {{ authorWorkspace.chapterState.chapter_passed_scene_count }}</span>
              <span class="badge">待回填 {{ authorWorkspace.chapterState.chapter_backfill_pending_count }}</span>
            </div>
            <div
              v-if="authorWorkspace.selectedChapterId"
              class="author-runtime-summary"
              data-testid="chapter-run-status-panel"
            >
              <span class="badge">Batch {{ chapterRunStatus?.status || "idle" }}</span>
              <span class="badge">Current {{ chapterRunStatus?.current_scene_id || "none" }}</span>
              <span class="badge">Done {{ chapterRunCompletedCount }}/{{ scenes.length }}</span>
              <span v-if="chapterRunStatus?.blocked_scene_id" class="badge">
                Blocked {{ chapterRunStatus.blocked_scene_id }}
              </span>
              <p v-if="chapterRunStatus?.latest_error" class="author-block-reason">
                {{ chapterRunStatus.latest_error.code }}: {{ chapterRunStatus.latest_error.message }}
              </p>
            </div>
            <label class="author-wide">
              <span>章节目标</span>
              <textarea v-model="chapterForm.chapter_goal" class="control-input" data-testid="author-chapter-goal" />
            </label>
            <label>
              <span>主线推进</span>
              <textarea v-model="chapterForm.main_plot_push" class="control-input" />
            </label>
            <label>
              <span>情绪目标</span>
              <textarea v-model="chapterForm.emotional_target" class="control-input" />
            </label>
            <label>
              <span>结尾效果</span>
              <textarea v-model="chapterForm.ending_effect" class="control-input" />
            </label>
            <label>
              <span>禁止包含</span>
              <textarea v-model="chapterForm.must_not" class="control-input" />
            </label>
            <label class="author-wide">
              <span>备注</span>
              <textarea v-model="chapterForm.notes" class="control-input" />
            </label>
          </div>

          <div class="card-actions">
            <button
              :disabled="authorWorkspace.actionId === 'save-chapter' || !chapterForm.chapter_id"
              data-testid="author-save-chapter-button"
              @click="saveChapter"
            >
              {{ authorWorkspace.actionId === "save-chapter" ? "保存中..." : "保存章节" }}
            </button>
            <button
              class="ghost"
              :disabled="!authorWorkspace.selectedChapterId || authorWorkspace.actionId === 'run-chapter'"
              data-testid="author-run-chapter-button"
              @click="runChapter"
            >
              {{ authorWorkspace.actionId === "run-chapter" ? "Running..." : chapterRunActionLabel }}
            </button>
          </div>
          <FlowActionReceipt :receipt="receipt(AUTHOR_CHAPTER_SCOPE)" />
        </article>

        <article class="paper author-editor-card">
          <div class="receipt-head">
            <div>
              <h3>场景列表</h3>
              <p class="muted receipt-copy">调整场景顺序、标记章节结尾场景，并把选中的场景批量移入回收站。</p>
            </div>
            <span class="badge">{{ scenes.length }} 个活跃场景</span>
          </div>

          <div class="author-list-toolbar" v-if="authorWorkspace.selectedChapterId">
            <button
              class="danger-button"
              data-testid="author-trash-selected-scenes-button"
              :disabled="!selectedSceneTrashIds.length || authorWorkspace.actionId === 'trash-scenes'"
              @click="trashSelectedScenes"
            >
              移入所选场景
            </button>
          </div>
          <FlowActionReceipt compact :receipt="receipt(AUTHOR_ORDER_SCOPE)" />
          <FlowActionReceipt compact :receipt="receipt(AUTHOR_SCENE_SCOPE)" />

          <div v-if="!authorWorkspace.selectedChapterId" class="empty">请先选择或新建章节，再编辑场景。</div>
          <template v-else>
            <VirtualList
              class="author-scene-list"
              :items="scenes"
              item-key="scene_id"
              :estimated-item-height="188"
              :threshold="10"
              :viewport-height="560"
              :pinned-keys="pinnedSceneKeys"
              :map-item="authorSceneRow"
              :map-version="sceneRowMapVersion"
              test-id="author-scene-virtual-list"
            >
              <template #default="{ row }">
                <article
                  class="author-scene-row"
                  :class="{ active: selectedSceneId === row.sceneId }"
                  :data-testid="`author-scene-row-${row.sceneId}`"
                >
                <label class="author-select-cell" :for="`scene-trash-${row.sceneId}`">
                  <input
                    :id="`scene-trash-${row.sceneId}`"
                    v-model="selectedSceneIdsForTrash"
                    type="checkbox"
                    :value="row.sceneId"
                    :data-testid="`author-scene-select-${row.sceneId}`"
                    :disabled="authorWorkspace.actionId === 'trash-scenes'"
                    @click.stop
                  />
                </label>

                <div class="author-scene-body">
                  <div class="author-scene-meta" @click="selectScene(row.sceneId)">
                    <strong>{{ row.sceneSeq }}. {{ row.sceneId }}</strong>
                    <span>{{ row.sceneGoal }}</span>
                    <span class="muted">{{ row.sceneStatus }} · {{ row.locationLabel }}</span>
                    <span class="badge" :data-testid="`author-scene-batch-state-${row.sceneId}`">
                      {{ row.batchLabel }}
                    </span>
                  </div>

                  <div class="author-scene-actions">
                    <button
                      class="ghost"
                      :disabled="row.moveUpDisabled || authorWorkspace.actionId === 'reorder-scenes'"
                      :data-testid="`author-scene-move-up-${row.sceneId}`"
                      @click="moveScene(row.sceneId, -1)"
                    >
                      上移
                    </button>
                    <button
                      class="ghost"
                      :disabled="row.moveDownDisabled || authorWorkspace.actionId === 'reorder-scenes'"
                      :data-testid="`author-scene-move-down-${row.sceneId}`"
                      @click="moveScene(row.sceneId, 1)"
                    >
                      下移
                    </button>
                    <button
                      class="ghost"
                      :disabled="row.markLastDisabled || authorWorkspace.actionId === 'reorder-scenes'"
                      :data-testid="`author-scene-mark-last-${row.sceneId}`"
                      @click="markSceneAsLast(row.sceneId)"
                    >
                      标记为章节结尾
                    </button>
                    <button
                      class="ghost"
                      :data-testid="`author-open-workbench-${row.sceneId}`"
                      @click="openInWorkbench(row.sceneId)"
                    >
                      在场景工作台打开
                    </button>
                  </div>
                </div>
                </article>
              </template>
            </VirtualList>

            <div class="author-form-grid author-scene-form" data-testid="author-scene-form">
              <label>
                <span>场景 ID</span>
                <input
                  v-model="sceneForm.scene_id"
                  class="control-input"
                  data-testid="author-scene-id"
                  :disabled="!creatingScene && Boolean(sceneForm.scene_id)"
                />
              </label>
              <label>
                <span>视角角色</span>
                <input v-model="sceneForm.pov_character_id" class="control-input" />
              </label>
              <label class="author-wide">
                <span>场景目标</span>
                <textarea v-model="sceneForm.scene_goal" class="control-input" data-testid="author-scene-goal" />
              </label>
              <label>
                <span>出场角色</span>
                <input v-model="sceneForm.onstage_chars_json" class="control-input" placeholder="角色 A，角色 B" />
              </label>
              <label>
                <span>地点</span>
                <input v-model="sceneForm.location" class="control-input" />
              </label>
              <label class="author-wide">
                <span>节拍</span>
                <textarea v-model="sceneForm.beats_json" class="control-input" placeholder="节拍 1，节拍 2" />
              </label>
              <label>
                <span>必须包含</span>
                <textarea v-model="sceneForm.must_include_text" class="control-input" />
              </label>
              <label>
                <span>禁用文本</span>
                <textarea v-model="sceneForm.forbidden_text" class="control-input" />
              </label>
              <label>
                <span>离场变化</span>
                <textarea v-model="sceneForm.exit_change" class="control-input" />
              </label>
              <label>
                <span>钩子</span>
                <textarea v-model="sceneForm.hook" class="control-input" />
              </label>
              <label>
                <span>目标篇幅档位</span>
                <input v-model="sceneForm.target_length_band" class="control-input" />
              </label>
              <label>
                <span>场景类型</span>
                <input v-model="sceneForm.scene_type" class="control-input" />
              </label>
            </div>

            <div class="card-actions">
              <button
                :disabled="sceneActionDisabled || authorWorkspace.actionId.startsWith('save-scene') || !sceneForm.scene_id"
                data-testid="author-save-scene-button"
                @click="saveScene"
              >
                {{ authorWorkspace.actionId.startsWith("save-scene") ? "保存中..." : "保存场景" }}
              </button>
            </div>
            <FlowActionReceipt :receipt="receipt(AUTHOR_SCENE_SCOPE)" />
          </template>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
