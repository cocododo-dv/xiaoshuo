<script setup>
import { computed, onActivated, onMounted, reactive, ref, watch } from "vue";

import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import PanelShell from "../components/PanelShell.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import WriterReviewCard from "../components/WriterReviewCard.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useShellRouter } from "../router";
import { useChapterManuscriptsStore } from "../stores/chapterManuscripts";

const emit = defineEmits(["notice"]);

const manuscripts = useChapterManuscriptsStore();
const { navigate, openTarget } = useShellRouter();
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});

const MANUSCRIPT_SCOPE = "manuscript:center";
const CHAPTER_SCOPE = "manuscript:chapter";
const SCENE_SCOPE = "manuscript:scene";
const EXPORT_SCOPE = "manuscript:export";
const TRASH_SCOPE = "manuscript:trash";

function emptyChapterForm() {
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

function emptySceneForm(chapterId = "") {
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
    is_chapter_last: 0,
  };
}

const chapterForm = reactive(emptyChapterForm());
const sceneForm = reactive(emptySceneForm());
const selectedSceneId = ref("");
const selectedChapterIds = ref([]);
const selectedSceneIds = ref([]);
const selectedTrashChapterIds = ref([]);
const selectedTrashSceneIds = ref([]);
const creatingChapter = ref(false);
const creatingScene = ref(false);
const readingSource = ref("both");

const items = computed(() => manuscripts.items || []);
const detail = computed(() => manuscripts.detail || null);
const scenes = computed(() => detail.value?.scenes || []);
const selectedScene = computed(() => scenes.value.find((scene) => scene.scene_id === selectedSceneId.value) || null);
const assembled = computed(() => detail.value?.assembled || null);
const aggregate = computed(() => detail.value?.aggregate || null);
const writerReviewSummary = computed(() => detail.value?.writer_review_summary || null);
const missingSceneIds = computed(() => assembled.value?.missing_scene_ids || []);
const canUseAggregate = computed(() => manuscripts.canUseAggregate);
const showAssembled = computed(() => readingSource.value === "both" || readingSource.value === "assembled");
const showAggregate = computed(() => readingSource.value === "both" || readingSource.value === "aggregate");
const sourceSafetyScan = computed(() => detail.value?.source_safety_scan || {
  safe: true,
  blocked_terms: [],
  source_profile_ids: [],
  checked_at: "",
});
const sourceSafetyBlockedTerms = computed(() => sourceSafetyScan.value.blocked_terms || []);
const sourceSafetyProfileIds = computed(() => sourceSafetyScan.value.source_profile_ids || []);
const sourceSafetyStatusLabel = computed(() =>
  sourceSafetyScan.value.safe
    ? "未命中保护标记"
    : `命中 ${sourceSafetyBlockedTerms.value.length} 个保护标记`,
);

function statusLabel(value) {
  return {
    empty: "尚未生成",
    partial: "部分生成",
    complete: "完整",
    aggregate_missing: "未聚合",
    aggregate_matches_current: "聚合已同步",
    aggregate_differs_current: "聚合不同步",
  }[value] || value || "-";
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

function assignChapterForm(nextChapter) {
  Object.assign(chapterForm, emptyChapterForm(), nextChapter || {});
  if (!nextChapter) {
    chapterForm.chapter_id = "";
  }
}

function assignSceneForm(nextScene) {
  if (!nextScene) {
    Object.assign(sceneForm, emptySceneForm(manuscripts.selectedChapterId || chapterForm.chapter_id));
    return;
  }
  Object.assign(sceneForm, emptySceneForm(nextScene.chapter_id), {
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
    is_chapter_last: nextScene.is_chapter_last || 0,
  });
}

function confirmAction(message) {
  if (typeof window === "undefined" || typeof window.confirm !== "function") {
    return true;
  }
  return window.confirm(message);
}

async function refreshManuscripts() {
  await runFlowAction({
    scopeKey: MANUSCRIPT_SCOPE,
    actionLabel: "刷新章节成稿中心",
    runningMessage: "正在刷新章节成稿状态...",
    successMessage: () => "章节成稿中心已刷新。",
    nextStep: () => "下一步：选择章节查看实时正文与最终聚合版本。",
    action: () => manuscripts.ensureLoaded({ force: true }),
  });
}

async function ensureLoaded() {
  await manuscripts.ensureLoaded();
  if (manuscripts.error) {
    emit("notice", manuscripts.error);
  }
}

async function selectChapter(chapterId) {
  creatingChapter.value = false;
  creatingScene.value = false;
  try {
    await manuscripts.selectChapter(chapterId);
  } catch (error) {
    emit("notice", error.message);
  }
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

function chooseScene(sceneId) {
  creatingScene.value = false;
  selectedSceneId.value = sceneId;
}

async function saveChapter() {
  const result = await runFlowAction({
    scopeKey: CHAPTER_SCOPE,
    actionLabel: "保存章节",
    runningMessage: "正在保存章节信息...",
    successMessage: (message) => message || "章节已保存。",
    nextStep: () => "下一步：继续维护场景，或运行整章生成。",
    action: () =>
      manuscripts.saveChapter({
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
    scopeKey: SCENE_SCOPE,
    actionLabel: "保存场景",
    runningMessage: "正在保存场景信息...",
    successMessage: (message) => message || "场景已保存。",
    nextStep: () => "下一步：运行整章生成，或打开场景工作台查看证据。",
    action: () =>
      manuscripts.saveScene({
        ...sceneForm,
        chapter_id: manuscripts.selectedChapterId || chapterForm.chapter_id,
        onstage_chars_json: textToList(sceneForm.onstage_chars_json),
        beats_json: textToList(sceneForm.beats_json),
      }),
  });
  if (result) {
    creatingScene.value = false;
    selectedSceneId.value = sceneForm.scene_id;
  }
}

async function runSelectedChapter() {
  await runFlowAction({
    scopeKey: CHAPTER_SCOPE,
    actionLabel: "运行整章生成",
    runningMessage: "正在运行整章生成...",
    successMessage: (message) => message || "整章生成已推进。",
    nextStep: () => "下一步：检查缺失场景，必要时运行最终聚合。",
    action: () => manuscripts.runSelectedChapter(),
  });
}

async function runFinalAggregate() {
  await runFlowAction({
    scopeKey: CHAPTER_SCOPE,
    actionLabel: "运行最终聚合",
    runningMessage: "正在生成最终聚合版本...",
    successMessage: (message) => message || "最终聚合已更新。",
    nextStep: () => "下一步：确认右侧聚合版本是否与实时正文同步。",
    action: () => manuscripts.runFinalAggregate(),
  });
}

async function reorderScenes(sceneId, offset = 0) {
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
    scopeKey: SCENE_SCOPE,
    actionLabel: "调整场景顺序",
    runningMessage: "正在保存场景顺序...",
    successMessage: (message) => message || "场景顺序已更新。",
    nextStep: () => "下一步：确认实时拼接正文的阅读顺序。",
    action: () => manuscripts.reorderScenes(orderedSceneIds, lastSceneId),
  });
}

async function markSceneAsLast(sceneId) {
  await runFlowAction({
    scopeKey: SCENE_SCOPE,
    actionLabel: "标记末场",
    runningMessage: "正在标记章节末场...",
    successMessage: (message) => message || "章节末场已更新。",
    nextStep: () => "下一步：运行整章生成或最终聚合。",
    action: () =>
      manuscripts.reorderScenes(
        scenes.value.map((scene) => scene.scene_id),
        sceneId,
      ),
  });
}

async function trashScenes() {
  const sceneIds = [...selectedSceneIds.value];
  if (!sceneIds.length || !confirmAction(`确认将 ${sceneIds.length} 个场景移入回收站吗？`)) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: TRASH_SCOPE,
    actionLabel: "回收场景",
    runningMessage: "正在回收场景...",
    successMessage: (message) => message || "场景已移入回收站。",
    nextStep: () => "下一步：可在本页回收站区域恢复或清除。",
    action: () => manuscripts.trashScenes(sceneIds),
  });
  if (result) {
    selectedSceneIds.value = [];
  }
}

async function trashSelectedChapters() {
  const chapterIds = [...selectedChapterIds.value];
  if (!chapterIds.length || !confirmAction(`确认将 ${chapterIds.length} 个章节移入回收站吗？`)) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: TRASH_SCOPE,
    actionLabel: "回收章节",
    runningMessage: "正在回收章节...",
    successMessage: (message) => message || "章节已移入回收站。",
    nextStep: () => "下一步：可在本页回收站区域恢复或清除。",
    action: () => manuscripts.trashChapters(chapterIds),
  });
  if (result) {
    selectedChapterIds.value = [];
  }
}

async function loadTrash() {
  await runFlowAction({
    scopeKey: TRASH_SCOPE,
    actionLabel: "加载回收站",
    runningMessage: "正在加载回收站...",
    successMessage: () => "回收站已加载。",
    nextStep: () => "下一步：选择要恢复或彻底清理的章节/场景。",
    action: () => manuscripts.loadTrash(),
  });
}

async function restoreSelectedTrash() {
  const chapterIds = [...selectedTrashChapterIds.value];
  const sceneIds = [...selectedTrashSceneIds.value];
  if (!chapterIds.length && !sceneIds.length) {
    return;
  }
  await runFlowAction({
    scopeKey: TRASH_SCOPE,
    actionLabel: "恢复回收站项目",
    runningMessage: "正在恢复回收站项目...",
    successMessage: () => "已恢复选中的回收站项目。",
    nextStep: () => "下一步：回到章节列表继续管理成稿。",
    action: async () => {
      if (chapterIds.length) {
        await manuscripts.restoreChapters(chapterIds);
      }
      if (sceneIds.length) {
        await manuscripts.restoreScenes(sceneIds);
      }
      selectedTrashChapterIds.value = [];
      selectedTrashSceneIds.value = [];
    },
  });
}

async function purgeSelectedTrash() {
  const chapterIds = [...selectedTrashChapterIds.value];
  const sceneIds = [...selectedTrashSceneIds.value];
  if ((!chapterIds.length && !sceneIds.length) || !confirmAction("确认彻底清理选中的回收站项目吗？此操作不可撤销。")) {
    return;
  }
  await runFlowAction({
    scopeKey: TRASH_SCOPE,
    actionLabel: "彻底清理回收站项目",
    runningMessage: "正在彻底清理回收站项目...",
    successMessage: () => "已彻底清理选中的回收站项目。",
    nextStep: () => "下一步：继续检查章节成稿状态。",
    action: async () => {
      if (chapterIds.length) {
        await manuscripts.purgeChapters(chapterIds);
      }
      if (sceneIds.length) {
        await manuscripts.purgeScenes(sceneIds);
      }
      selectedTrashChapterIds.value = [];
      selectedTrashSceneIds.value = [];
    },
  });
}

function openSceneWorkbench(sceneId) {
  openTarget({
    target_type: "scene_card",
    target_id: sceneId,
    target_ref: `scene_card:${sceneId}`,
  });
}

function openTrashView() {
  navigate("trash");
}

async function runWriterReview() {
  await runFlowAction({
    scopeKey: MANUSCRIPT_SCOPE,
    actionLabel: "运行章节作家诊断",
    runningMessage: "正在诊断章节阅读效果...",
    successMessage: (message) => message || "章节作家诊断已完成。",
    nextStep: () => "下一步：查看节奏断点、场景缺口和候选修订。",
    action: () => manuscripts.runWriterReview(manuscripts.selectedChapterId),
  });
}

async function acceptWriterRevision(revisionId) {
  await runFlowAction({
    scopeKey: MANUSCRIPT_SCOPE,
    actionLabel: "采纳章节修订候选",
    runningMessage: "正在记录作者采纳...",
    successMessage: (message) => message || "修订候选已采纳；章节正文未被覆盖。",
    nextStep: () => "下一步：人工合并候选，或继续调整章节结构。",
    action: () => manuscripts.acceptRevision(revisionId, manuscripts.selectedChapterId),
  });
}

async function rejectWriterRevision(revisionId) {
  await runFlowAction({
    scopeKey: MANUSCRIPT_SCOPE,
    actionLabel: "拒绝章节修订候选",
    runningMessage: "正在记录作者拒绝...",
    successMessage: (message) => message || "修订候选已拒绝。",
    nextStep: () => "下一步：可修改戏剧卡后重新诊断。",
    action: () => manuscripts.rejectRevision(revisionId, manuscripts.selectedChapterId),
  });
}

async function copyManuscript(source) {
  const text = manuscripts.exportText(source);
  await runFlowAction({
    scopeKey: EXPORT_SCOPE,
    actionLabel: "复制成稿",
    runningMessage: "正在复制成稿...",
    successMessage: () => "成稿已复制到剪贴板。",
    nextStep: () => "下一步：粘贴到你的写作工具或继续对照聚合版本。",
    action: async () => {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      }
      return text;
    },
  });
}

function downloadManuscript(source, format = "md") {
  const chapterId = detail.value?.chapter?.chapter_id || "chapter";
  const text = format === "md" ? manuscripts.exportMarkdown(source) : manuscripts.exportText(source);
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${chapterId}-${source}.${format}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

watch(
  () => detail.value?.chapter,
  (nextChapter) => {
    if (!creatingChapter.value) {
      assignChapterForm(nextChapter);
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
  () => scenes.value.map((scene) => scene.scene_id).join("|"),
  () => {
    selectedSceneIds.value = selectedSceneIds.value.filter((sceneId) => scenes.value.some((scene) => scene.scene_id === sceneId));
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
  () => manuscripts.selectedChapterId,
  (chapterId) => {
    if (creatingScene.value) {
      assignSceneForm(null);
      sceneForm.chapter_id = chapterId || chapterForm.chapter_id || "";
    }
  },
);

onMounted(() => {
  ensureLoaded();
});

onActivated(() => {
  ensureLoaded();
});
</script>

<template>
  <section class="panel-grid chapter-manuscript-view" data-testid="chapter-manuscript-view">
    <WorkflowPageHeader view-id="manuscripts" />
    <PanelShell
      eyebrow="章节成稿中心"
      title="查看完整章节，管理生成后的正文"
      description="在同一处查看实时拼接正文与最终聚合版本，处理缺失场景、过期聚合和章节场景管理。"
    >
      <template #actions>
        <div class="field-inline manuscript-actions">
          <button data-testid="manuscript-refresh-button" @click="refreshManuscripts">刷新</button>
          <button class="ghost" data-testid="manuscript-new-chapter-button" @click="startNewChapter">新建章节</button>
          <button class="ghost" data-testid="manuscript-new-scene-button" :disabled="!manuscripts.selectedChapterId" @click="startNewScene">
            新建场景
          </button>
          <button class="ghost" data-testid="manuscript-load-trash-button" @click="loadTrash">回收站</button>
        </div>
      </template>

      <FlowActionReceipt :receipt="receipt(MANUSCRIPT_SCOPE)" />
      <div v-if="manuscripts.loading" class="empty">正在加载章节成稿...</div>
      <div v-else-if="manuscripts.error" class="empty">{{ manuscripts.error }}</div>

      <div v-else class="manuscript-layout">
        <aside class="paper manuscript-list-panel">
          <div class="receipt-head">
            <div>
              <h3>章节</h3>
              <p class="muted receipt-copy">选择章节查看成稿、运行状态和聚合对照。</p>
            </div>
            <span class="badge">{{ items.length }} 章</span>
          </div>
          <div class="author-list-toolbar">
            <button
              class="danger-button"
              data-testid="manuscript-trash-chapters-button"
              :disabled="!selectedChapterIds.length || manuscripts.actionId === 'trash-chapters'"
              @click="trashSelectedChapters"
            >
              回收所选章节
            </button>
          </div>
          <div v-if="!items.length" class="empty">还没有活跃章节。</div>
          <div v-else class="manuscript-chapter-list" data-testid="manuscript-chapter-list">
            <article
              v-for="item in items"
              :key="item.chapter_id"
              class="manuscript-list-row"
              :class="{ active: manuscripts.selectedChapterId === item.chapter_id }"
            >
              <label class="author-select-cell" :for="`manuscript-chapter-${item.chapter_id}`">
                <input
                  :id="`manuscript-chapter-${item.chapter_id}`"
                  v-model="selectedChapterIds"
                  type="checkbox"
                  :value="item.chapter_id"
                  :disabled="Number(item.trash_allowed) !== 1"
                />
              </label>
              <button class="manuscript-list-button" :data-testid="`manuscript-select-${item.chapter_id}`" @click="selectChapter(item.chapter_id)">
                <strong>{{ item.chapter_id }}</strong>
                <span>{{ item.chapter_goal || "未填写章节目标" }}</span>
                <span class="muted">
                  {{ item.generated_scene_count }}/{{ item.scene_count }} 场 · {{ statusLabel(item.completion_status) }} ·
                  {{ statusLabel(item.comparison_status) }}
                </span>
                <span v-if="item.chapter_backfill_pending_count" class="badge">待回填 {{ item.chapter_backfill_pending_count }}</span>
              </button>
            </article>
          </div>
        </aside>

        <section class="paper manuscript-management" data-testid="manuscript-management-panel">
          <div class="receipt-head">
            <div>
              <h3>章节与场景管理</h3>
              <p class="muted receipt-copy">维护作者输入，运行生成，处理当前章节的场景顺序。</p>
            </div>
            <span class="badge">{{ statusLabel(detail?.completion_status) }}</span>
          </div>

          <div class="manuscript-status-strip">
            <span class="badge">{{ statusLabel(detail?.comparison_status) }}</span>
            <span class="badge">实时 {{ assembled?.generated_scene_count || 0 }}/{{ assembled?.scene_count || 0 }} 场</span>
            <span class="badge">聚合 {{ aggregate?.row_id || "未生成" }}</span>
          </div>
          <article class="paper mini" data-testid="manuscript-source-safety-card">
            <h4>源书安全扫描</h4>
            <p><strong>{{ sourceSafetyStatusLabel }}</strong></p>
            <p class="muted">
              {{ sourceSafetyBlockedTerms.length ? sourceSafetyBlockedTerms.join("、") : "没有命中源书专名、设定或受保护桥段标记。" }}
            </p>
            <p class="muted">
              {{ sourceSafetyProfileIds.length ? sourceSafetyProfileIds.join(", ") : "暂无参考画像来源 ID" }}
            </p>
          </article>
          <p v-if="missingSceneIds.length" class="inline-warning">
            缺失终稿场景：{{ missingSceneIds.join(", ") }}
          </p>

          <div class="manuscript-form-grid">
            <label>
              <span>章节 ID</span>
              <input v-model="chapterForm.chapter_id" class="control-input" :disabled="!creatingChapter && Boolean(chapterForm.chapter_id)" />
            </label>
            <label>
              <span>计划场景数</span>
              <input v-model.number="chapterForm.planned_scene_count" type="number" min="1" class="control-input" />
            </label>
            <label class="checkbox-inline">
              <input v-model.number="chapterForm.mid_aggregate_enabled" type="checkbox" true-value="1" false-value="0" />
              <span>启用中段汇总</span>
            </label>
            <label class="manuscript-wide">
              <span>章节目标</span>
              <textarea v-model="chapterForm.chapter_goal" class="control-input" />
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
          </div>

          <div class="card-actions">
            <button data-testid="manuscript-save-chapter-button" :disabled="!chapterForm.chapter_id" @click="saveChapter">保存章节</button>
            <button class="ghost" data-testid="run-selected-chapter-button" :disabled="!manuscripts.selectedChapterId" @click="runSelectedChapter">
              运行整章生成
            </button>
            <button
              class="ghost"
              data-testid="run-final-aggregate-button"
              :disabled="!manuscripts.selectedChapterId"
              @click="runFinalAggregate"
            >
              运行最终聚合
            </button>
          </div>
          <FlowActionReceipt :receipt="receipt(CHAPTER_SCOPE)" />

          <div class="manuscript-scene-area">
            <div class="receipt-head">
              <div>
                <h4>场景</h4>
                <p class="muted receipt-copy">按顺序管理章节场景，并跳转查看生成证据。</p>
              </div>
              <button
                class="danger-button"
                data-testid="manuscript-trash-scenes-button"
                :disabled="!selectedSceneIds.length"
                @click="trashScenes"
              >
                回收所选场景
              </button>
            </div>

            <div class="manuscript-scene-list">
              <article
                v-for="(scene, index) in scenes"
                :key="scene.scene_id"
                class="manuscript-scene-row"
                :class="{ active: selectedSceneId === scene.scene_id }"
              >
                <label class="author-select-cell" :for="`manuscript-scene-${scene.scene_id}`">
                  <input :id="`manuscript-scene-${scene.scene_id}`" v-model="selectedSceneIds" type="checkbox" :value="scene.scene_id" />
                </label>
                <button class="manuscript-scene-main" @click="chooseScene(scene.scene_id)">
                  <strong>{{ scene.scene_seq }}. {{ scene.scene_id }}</strong>
                  <span>{{ scene.scene_goal }}</span>
                  <span class="muted">{{ scene.scene_status }} · {{ scene.final_scene ? "已有终稿" : "缺失终稿" }}</span>
                </button>
                <div class="manuscript-scene-actions">
                  <button class="ghost" :disabled="index === 0" @click="reorderScenes(scene.scene_id, -1)">↑</button>
                  <button class="ghost" :disabled="index === scenes.length - 1" @click="reorderScenes(scene.scene_id, 1)">↓</button>
                  <button class="ghost" :disabled="scene.is_chapter_last === 1" @click="markSceneAsLast(scene.scene_id)">末场</button>
                  <button class="ghost" @click="openSceneWorkbench(scene.scene_id)">证据</button>
                </div>
              </article>
            </div>

            <div class="manuscript-form-grid scene-form">
              <label>
                <span>场景 ID</span>
                <input v-model="sceneForm.scene_id" class="control-input" :disabled="!creatingScene && Boolean(sceneForm.scene_id)" />
              </label>
              <label>
                <span>章节 ID</span>
                <input v-model="sceneForm.chapter_id" class="control-input" />
              </label>
              <label>
                <span>地点</span>
                <input v-model="sceneForm.location" class="control-input" />
              </label>
              <label>
                <span>场景类型</span>
                <input v-model="sceneForm.scene_type" class="control-input" />
              </label>
              <label class="manuscript-wide">
                <span>场景目标</span>
                <textarea v-model="sceneForm.scene_goal" class="control-input" />
              </label>
              <label>
                <span>角色</span>
                <input v-model="sceneForm.onstage_chars_json" class="control-input" />
              </label>
              <label>
                <span>节拍</span>
                <input v-model="sceneForm.beats_json" class="control-input" />
              </label>
              <label>
                <span>必须包含</span>
                <textarea v-model="sceneForm.must_include_text" class="control-input" />
              </label>
              <label>
                <span>禁止包含</span>
                <textarea v-model="sceneForm.forbidden_text" class="control-input" />
              </label>
            </div>
            <div class="card-actions">
              <button data-testid="manuscript-save-scene-button" :disabled="!sceneForm.scene_id || !sceneForm.chapter_id" @click="saveScene">
                保存场景
              </button>
            </div>
            <FlowActionReceipt :receipt="receipt(SCENE_SCOPE)" />
          </div>

          <div class="manuscript-trash-panel">
            <div class="receipt-head">
              <div>
                <h4>回收站管理</h4>
                <p class="muted receipt-copy">恢复或彻底清理已回收章节和场景。</p>
              </div>
              <button class="ghost" @click="openTrashView">打开回收站页</button>
            </div>
            <div class="manuscript-trash-grid">
              <label v-for="chapter in manuscripts.trash.chapters" :key="chapter.chapter_id" class="trash-choice">
                <input v-model="selectedTrashChapterIds" type="checkbox" :value="chapter.chapter_id" />
                <span>{{ chapter.chapter_id }} · {{ chapter.chapter_goal }}</span>
              </label>
              <label v-for="scene in manuscripts.trash.scenes" :key="scene.scene_id" class="trash-choice">
                <input v-model="selectedTrashSceneIds" type="checkbox" :value="scene.scene_id" />
                <span>{{ scene.scene_id }} · {{ scene.scene_goal }}</span>
              </label>
            </div>
            <div class="card-actions">
              <button class="ghost" :disabled="!selectedTrashChapterIds.length && !selectedTrashSceneIds.length" @click="restoreSelectedTrash">
                恢复所选
              </button>
              <button class="danger-button" :disabled="!selectedTrashChapterIds.length && !selectedTrashSceneIds.length" @click="purgeSelectedTrash">
                彻底清理所选
              </button>
            </div>
            <FlowActionReceipt :receipt="receipt(TRASH_SCOPE)" />
          </div>
        </section>

        <WriterReviewCard
          :summary="writerReviewSummary"
          :busy="manuscripts.actionId === 'writer-review' || manuscripts.actionId.startsWith('revision-')"
          title="这一章读起来是否成立"
          run-label="运行章节诊断"
          @run="runWriterReview"
          @accept="acceptWriterRevision"
          @reject="rejectWriterRevision"
        />

        <section class="paper manuscript-reader">
          <div class="receipt-head">
            <div>
              <h3>成稿对照</h3>
              <p class="muted receipt-copy">实时拼接来自当前场景终稿；最终聚合来自章节记忆。</p>
            </div>
            <select v-model="readingSource" class="control-input manuscript-view-mode" aria-label="阅读视图">
              <option value="both">双栏对照</option>
              <option value="assembled">实时拼接</option>
              <option value="aggregate">最终聚合</option>
            </select>
          </div>

          <div class="manuscript-reader-grid" :class="{ single: readingSource !== 'both' }">
            <article v-if="showAssembled" class="manuscript-pane" data-testid="assembled-manuscript-pane">
              <div class="manuscript-pane-head">
                <div>
                  <h4>实时拼接正文</h4>
                  <p class="muted">{{ assembled?.char_count || 0 }} 字 · {{ statusLabel(detail?.completion_status) }}</p>
                </div>
                <div class="field-inline">
                  <button class="ghost" data-testid="copy-assembled-button" @click="copyManuscript('assembled')">复制</button>
                  <button class="ghost" data-testid="download-assembled-button" @click="downloadManuscript('assembled', 'md')">下载</button>
                </div>
              </div>
              <pre class="manuscript-text">{{ assembled?.content || "还没有可阅读的实时正文。" }}</pre>
            </article>

            <article v-if="showAggregate" class="manuscript-pane" data-testid="aggregate-manuscript-pane">
              <div class="manuscript-pane-head">
                <div>
                  <h4>最终聚合正文</h4>
                  <p class="muted">{{ aggregate?.char_count || 0 }} 字 · {{ statusLabel(detail?.comparison_status) }}</p>
                </div>
                <div class="field-inline">
                  <button class="ghost" data-testid="copy-aggregate-button" :disabled="!canUseAggregate" @click="copyManuscript('aggregate')">
                    复制
                  </button>
                  <button
                    class="ghost"
                    data-testid="download-aggregate-button"
                    :disabled="!canUseAggregate"
                    @click="downloadManuscript('aggregate', 'md')"
                  >
                    下载
                  </button>
                </div>
              </div>
              <pre class="manuscript-text">{{ aggregate?.content || "尚未生成最终聚合。" }}</pre>
            </article>
          </div>
          <FlowActionReceipt :receipt="receipt(EXPORT_SCOPE)" />
        </section>
      </div>
    </PanelShell>
  </section>
</template>
