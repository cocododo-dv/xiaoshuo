<script setup>
import { computed, onActivated, ref, watch } from "vue";

import BaseEmptyState from "../components/base/BaseEmptyState.vue";
import DangerConfirm from "../components/DangerConfirm.vue";
import FlowActionReceipt from "../components/FlowActionReceipt.vue";
import PanelShell from "../components/PanelShell.vue";
import VirtualList from "../components/VirtualList.vue";
import WorkflowPageHeader from "../components/WorkflowPageHeader.vue";
import { useFlowActionFeedback } from "../composables/useFlowActionFeedback";
import { useAuthorTrashStore } from "../stores/authorTrash";

const emit = defineEmits(["notice"]);

const authorTrash = useAuthorTrashStore();
const selectedChapterIds = ref([]);
const selectedSceneIds = ref([]);
const { receipt, runFlowAction } = useFlowActionFeedback({
  emitNotice: (message) => emit("notice", message),
});
const TRASH_CHAPTER_SCOPE = "author-trash:chapters";
const TRASH_SCENE_SCOPE = "author-trash:scenes";
const TRASH_REFRESH_SCOPE = "author-trash:refresh";

const chapters = computed(() => authorTrash.chapters || []);
const scenes = computed(() => authorTrash.scenes || []);
const hasTrash = computed(() => chapters.value.length > 0 || scenes.value.length > 0);
const pinnedChapterKeys = computed(() => [...selectedChapterIds.value]);
const pinnedSceneKeys = computed(() => [...selectedSceneIds.value]);
const selectedRestorableChapterIds = computed(() =>
  selectedChapterIds.value.filter((chapterId) =>
    chapters.value.some((chapter) => chapter.chapter_id === chapterId && Number(chapter.restore_allowed) === 1),
  ),
);
const selectedPurgeableChapterIds = computed(() =>
  selectedChapterIds.value.filter((chapterId) =>
    chapters.value.some((chapter) => chapter.chapter_id === chapterId && Number(chapter.purge_allowed) === 1),
  ),
);
const selectedRestorableSceneIds = computed(() =>
  selectedSceneIds.value.filter((sceneId) =>
    scenes.value.some((scene) => scene.scene_id === sceneId && Number(scene.restore_allowed) === 1),
  ),
);
const selectedPurgeableSceneIds = computed(() =>
  selectedSceneIds.value.filter((sceneId) =>
    scenes.value.some((scene) => scene.scene_id === sceneId && Number(scene.purge_allowed) === 1),
  ),
);

function confirmAction(message) {
  if (typeof window === "undefined" || typeof window.confirm !== "function") {
    return true;
  }
  return window.confirm(message);
}

function formatTimestamp(value) {
  if (!value) {
    return "未知时间";
  }
  return String(value).replace("T", " ").replace("Z", "");
}

function chapterSelectable(chapter) {
  return Number(chapter.restore_allowed) === 1 || Number(chapter.purge_allowed) === 1;
}

function sceneSelectable(scene) {
  return Number(scene.restore_allowed) === 1 || Number(scene.purge_allowed) === 1;
}

function authorTrashChapterRow(item) {
  return {
    item,
    chapterId: item?.chapter_id || "",
    goal: item?.chapter_goal || "尚未保存章节目标。",
    sceneCount: item?.scene_count ?? 0,
    selectable: chapterSelectable(item),
    trashedAtLabel: formatTimestamp(item?.trashed_at),
    trashedByLabel: item?.trashed_by || "未知操作员",
    restoreBlockReason: item?.restore_block_reason || "",
    purgeBlockReason: item?.purge_block_reason || "",
  };
}

function authorTrashSceneRow(item) {
  return {
    item,
    sceneId: item?.scene_id || "",
    goal: item?.scene_goal || "尚未保存场景目标。",
    chapterId: item?.chapter_id || "-",
    sceneSeq: item?.scene_seq ?? "-",
    selectable: sceneSelectable(item),
    chapterTrashed: Boolean(item?.chapter_trashed),
    trashedAtLabel: formatTimestamp(item?.trashed_at),
    trashedByLabel: item?.trashed_by || "未知操作员",
    restoreBlockReason: item?.restore_block_reason || "",
    purgeBlockReason: item?.purge_block_reason || "",
  };
}

function syncSelections() {
  const chapterIds = new Set(chapters.value.filter((chapter) => chapterSelectable(chapter)).map((chapter) => chapter.chapter_id));
  const sceneIds = new Set(scenes.value.filter((scene) => sceneSelectable(scene)).map((scene) => scene.scene_id));
  selectedChapterIds.value = selectedChapterIds.value.filter((chapterId) => chapterIds.has(chapterId));
  selectedSceneIds.value = selectedSceneIds.value.filter((sceneId) => sceneIds.has(sceneId));
}

async function refreshTrash() {
  const result = await runFlowAction({
    scopeKey: TRASH_REFRESH_SCOPE,
    actionLabel: "刷新回收站",
    runningMessage: "正在刷新作者回收站...",
    successMessage: () => "作者回收站已刷新。",
    nextStep: () => "下一步：选择可恢复或可清除的记录。",
    action: () => authorTrash.ensureLoaded({ force: true }),
  });
  if (result !== null) syncSelections();
}

async function ensureTrashLoaded() {
  await authorTrash.ensureLoaded({ force: true });
  syncSelections();
  if (authorTrash.error) {
    emit("notice", authorTrash.error);
  }
}

async function restoreSelectedChapters() {
  const chapterIds = [...selectedRestorableChapterIds.value];
  if (!chapterIds.length || !confirmAction(`确认恢复选中的 ${chapterIds.length} 个章节吗？`)) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: TRASH_CHAPTER_SCOPE,
    actionLabel: "恢复章节",
    runningMessage: `正在恢复 ${chapterIds.length} 个章节...`,
    successMessage: (message) => message || "章节已恢复。",
    nextStep: () => "下一步：回到作者工作台继续编辑或运行章节。",
    action: () => authorTrash.restoreChapters(chapterIds),
  });
  if (result) {
    selectedChapterIds.value = [];
  }
}

async function purgeSelectedChapters() {
  const chapterIds = [...selectedPurgeableChapterIds.value];
  if (!chapterIds.length) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: TRASH_CHAPTER_SCOPE,
    actionLabel: "永久清除章节",
    runningMessage: `正在永久清除 ${chapterIds.length} 个章节...`,
    successMessage: (message) => message || "章节已永久清除。",
    nextStep: () => "下一步：继续检查回收站是否还有待处理记录。",
    action: () => authorTrash.purgeChapters(chapterIds),
  });
  if (result) {
    selectedChapterIds.value = [];
  }
}

async function restoreSelectedScenes() {
  const sceneIds = [...selectedRestorableSceneIds.value];
  if (!sceneIds.length || !confirmAction(`确认恢复选中的 ${sceneIds.length} 个场景吗？`)) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: TRASH_SCENE_SCOPE,
    actionLabel: "恢复场景",
    runningMessage: `正在恢复 ${sceneIds.length} 个场景...`,
    successMessage: (message) => message || "场景已恢复。",
    nextStep: () => "下一步：回到作者工作台继续编辑或运行场景。",
    action: () => authorTrash.restoreScenes(sceneIds),
  });
  if (result) {
    selectedSceneIds.value = [];
  }
}

async function purgeSelectedScenes() {
  const sceneIds = [...selectedPurgeableSceneIds.value];
  if (!sceneIds.length) {
    return;
  }
  const result = await runFlowAction({
    scopeKey: TRASH_SCENE_SCOPE,
    actionLabel: "永久清除场景",
    runningMessage: `正在永久清除 ${sceneIds.length} 个场景...`,
    successMessage: (message) => message || "场景已永久清除。",
    nextStep: () => "下一步：继续检查回收站是否还有待处理记录。",
    action: () => authorTrash.purgeScenes(sceneIds),
  });
  if (result) {
    selectedSceneIds.value = [];
  }
}

watch(
  () => [authorTrash.chapterListVersion, authorTrash.sceneListVersion],
  () => {
    syncSelections();
  },
  { immediate: true },
);

onActivated(() => {
  ensureTrashLoaded();
});
</script>

<template>
  <section class="panel-grid" data-testid="author-trash-view">
    <WorkflowPageHeader view-id="trash" />
    <PanelShell
      eyebrow="作者回收站"
      title="恢复或永久清除作者记录"
      description="移入回收站的章节与场景会暂时退出常规创作与运行时流程，只有恢复后才会重新参与。永久清除仍会谨慎校验下游运行时产物。"
    >
      <template #actions>
        <div class="field-inline">
          <button @click="refreshTrash">刷新回收站</button>
          <span class="badge">{{ chapters.length }} 个章节</span>
          <span class="badge">{{ scenes.length }} 个场景</span>
        </div>
      </template>
      <FlowActionReceipt :receipt="receipt(TRASH_REFRESH_SCOPE)" />

      <div v-if="authorTrash.loading" class="empty">正在加载作者回收站...</div>
      <div v-else-if="authorTrash.error" class="empty">{{ authorTrash.error }}</div>
      <BaseEmptyState v-else-if="!hasTrash" data-testid="author-trash-empty" description="作者回收站为空。" />
      <div v-else class="trash-layout">
        <article class="paper trash-section">
          <div class="receipt-head">
            <div>
              <h3>已回收章节</h3>
              <p class="muted receipt-copy">可以整章恢复，也可以在所有子场景都没有运行时残留时再执行永久清除。</p>
            </div>
            <span class="badge">{{ chapters.length }}</span>
          </div>

          <div class="trash-toolbar">
            <button
              data-testid="author-trash-restore-chapters-button"
              :disabled="!selectedRestorableChapterIds.length || authorTrash.actionId === 'restore-chapters'"
              @click="restoreSelectedChapters"
            >
              恢复所选章节
            </button>
            <DangerConfirm
              label="永久清除所选章节"
              confirm-label="确认永久清除"
              :message="`将永久清除 ${selectedPurgeableChapterIds.length} 个章节。此操作不可撤销。`"
              test-id="author-trash-purge-chapters-button"
              :disabled="!selectedPurgeableChapterIds.length || authorTrash.actionId === 'purge-chapters'"
              @confirm="purgeSelectedChapters"
            />
          </div>
          <FlowActionReceipt compact :receipt="receipt(TRASH_CHAPTER_SCOPE)" />

          <BaseEmptyState v-if="!chapters.length" description="当前没有已回收章节。" />
          <VirtualList
            v-else
            class="trash-list"
            :items="chapters"
            item-key="chapter_id"
            :estimated-item-height="180"
            :threshold="8"
            :viewport-height="560"
            :pinned-keys="pinnedChapterKeys"
            :map-item="authorTrashChapterRow"
            test-id="author-trash-chapter-virtual-list"
          >
            <template #default="{ row }">
              <article
                class="trash-row"
                :class="{ disabled: !row.selectable }"
                :data-testid="`author-trash-chapter-row-${row.chapterId}`"
              >
              <label class="author-select-cell" :for="`trash-chapter-${row.chapterId}`">
                <input
                  :id="`trash-chapter-${row.chapterId}`"
                  v-model="selectedChapterIds"
                  type="checkbox"
                  :value="row.chapterId"
                  :data-testid="`author-trash-chapter-select-${row.chapterId}`"
                  :disabled="!row.selectable"
                />
              </label>

              <div class="trash-row-copy">
                <div class="trash-row-head">
                  <div>
                    <strong>{{ row.chapterId }}</strong>
                    <p class="trash-copy">{{ row.goal }}</p>
                  </div>
                  <div class="trash-meta">
                    <span class="badge">{{ row.sceneCount }} 个场景</span>
                    <span class="badge">回收于 {{ row.trashedAtLabel }}</span>
                  </div>
                </div>
                <p class="muted">操作员：{{ row.trashedByLabel }}</p>
                <div class="trash-reason-list">
                  <p v-if="row.restoreBlockReason" class="trash-reason">{{ row.restoreBlockReason }}</p>
                  <p v-if="row.purgeBlockReason" class="trash-reason">{{ row.purgeBlockReason }}</p>
                </div>
              </div>
              </article>
            </template>
          </VirtualList>
        </article>

        <article class="paper trash-section">
          <div class="receipt-head">
            <div>
              <h3>已回收场景</h3>
              <p class="muted receipt-copy">如果场景是随所属章节一起回收的，需要先恢复章节，再从章节行统一管理。</p>
            </div>
            <span class="badge">{{ scenes.length }}</span>
          </div>

          <div class="trash-toolbar">
            <button
              data-testid="author-trash-restore-scenes-button"
              :disabled="!selectedRestorableSceneIds.length || authorTrash.actionId === 'restore-scenes'"
              @click="restoreSelectedScenes"
            >
              恢复所选场景
            </button>
            <DangerConfirm
              label="永久清除所选场景"
              confirm-label="确认永久清除"
              :message="`将永久清除 ${selectedPurgeableSceneIds.length} 个场景。此操作不可撤销。`"
              test-id="author-trash-purge-scenes-button"
              :disabled="!selectedPurgeableSceneIds.length || authorTrash.actionId === 'purge-scenes'"
              @confirm="purgeSelectedScenes"
            />
          </div>
          <FlowActionReceipt compact :receipt="receipt(TRASH_SCENE_SCOPE)" />

          <BaseEmptyState v-if="!scenes.length" description="当前没有已回收场景。" />
          <VirtualList
            v-else
            class="trash-list"
            :items="scenes"
            item-key="scene_id"
            :estimated-item-height="180"
            :threshold="8"
            :viewport-height="560"
            :pinned-keys="pinnedSceneKeys"
            :map-item="authorTrashSceneRow"
            test-id="author-trash-scene-virtual-list"
          >
            <template #default="{ row }">
              <article
                class="trash-row"
                :class="{ disabled: !row.selectable }"
                :data-testid="`author-trash-scene-row-${row.sceneId}`"
              >
              <label class="author-select-cell" :for="`trash-scene-${row.sceneId}`">
                <input
                  :id="`trash-scene-${row.sceneId}`"
                  v-model="selectedSceneIds"
                  type="checkbox"
                  :value="row.sceneId"
                  :data-testid="`author-trash-scene-select-${row.sceneId}`"
                  :disabled="!row.selectable"
                />
              </label>

              <div class="trash-row-copy">
                <div class="trash-row-head">
                  <div>
                    <strong>{{ row.sceneId }}</strong>
                    <p class="trash-copy">{{ row.goal }}</p>
                  </div>
                  <div class="trash-meta">
                    <span class="badge">章节 {{ row.chapterId }}</span>
                    <span class="badge">顺序 {{ row.sceneSeq }}</span>
                    <span v-if="row.chapterTrashed" class="badge">所属章节已回收</span>
                  </div>
                </div>
                <p class="muted">回收于 {{ row.trashedAtLabel }}，操作员：{{ row.trashedByLabel }}</p>
                <div class="trash-reason-list">
                  <p v-if="row.restoreBlockReason" class="trash-reason">{{ row.restoreBlockReason }}</p>
                  <p v-if="row.purgeBlockReason" class="trash-reason">{{ row.purgeBlockReason }}</p>
                </div>
              </div>
              </article>
            </template>
          </VirtualList>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
