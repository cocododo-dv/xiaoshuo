<script setup>
import { computed, onActivated, ref, watch } from "vue";

import PanelShell from "../components/PanelShell.vue";
import { useAuthorTrashStore } from "../stores/authorTrash";

const emit = defineEmits(["notice"]);

const authorTrash = useAuthorTrashStore();
const selectedChapterIds = ref([]);
const selectedSceneIds = ref([]);

const chapters = computed(() => authorTrash.chapters || []);
const scenes = computed(() => authorTrash.scenes || []);
const hasTrash = computed(() => chapters.value.length > 0 || scenes.value.length > 0);
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

function syncSelections() {
  const chapterIds = new Set(chapters.value.filter((chapter) => chapterSelectable(chapter)).map((chapter) => chapter.chapter_id));
  const sceneIds = new Set(scenes.value.filter((scene) => sceneSelectable(scene)).map((scene) => scene.scene_id));
  selectedChapterIds.value = selectedChapterIds.value.filter((chapterId) => chapterIds.has(chapterId));
  selectedSceneIds.value = selectedSceneIds.value.filter((sceneId) => sceneIds.has(sceneId));
}

async function refreshTrash() {
  await authorTrash.ensureLoaded({ force: true });
  syncSelections();
  if (authorTrash.error) {
    emit("notice", authorTrash.error);
  }
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
  try {
    const message = await authorTrash.restoreChapters(chapterIds);
    selectedChapterIds.value = [];
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function purgeSelectedChapters() {
  const chapterIds = [...selectedPurgeableChapterIds.value];
  if (!chapterIds.length || !confirmAction(`确认永久清除选中的 ${chapterIds.length} 个章节吗？此操作不可撤销。`)) {
    return;
  }
  try {
    const message = await authorTrash.purgeChapters(chapterIds);
    selectedChapterIds.value = [];
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function restoreSelectedScenes() {
  const sceneIds = [...selectedRestorableSceneIds.value];
  if (!sceneIds.length || !confirmAction(`确认恢复选中的 ${sceneIds.length} 个场景吗？`)) {
    return;
  }
  try {
    const message = await authorTrash.restoreScenes(sceneIds);
    selectedSceneIds.value = [];
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function purgeSelectedScenes() {
  const sceneIds = [...selectedPurgeableSceneIds.value];
  if (!sceneIds.length || !confirmAction(`确认永久清除选中的 ${sceneIds.length} 个场景吗？此操作不可撤销。`)) {
    return;
  }
  try {
    const message = await authorTrash.purgeScenes(sceneIds);
    selectedSceneIds.value = [];
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

watch(
  () => [
    chapters.value.map((chapter) => `${chapter.chapter_id}:${chapter.restore_allowed}:${chapter.purge_allowed}`).join("|"),
    scenes.value.map((scene) => `${scene.scene_id}:${scene.restore_allowed}:${scene.purge_allowed}`).join("|"),
  ],
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

      <div v-if="authorTrash.loading" class="empty">正在加载作者回收站...</div>
      <div v-else-if="authorTrash.error" class="empty">{{ authorTrash.error }}</div>
      <div v-else-if="!hasTrash" class="empty" data-testid="author-trash-empty">作者回收站为空。</div>
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
            <button
              class="danger-button"
              data-testid="author-trash-purge-chapters-button"
              :disabled="!selectedPurgeableChapterIds.length || authorTrash.actionId === 'purge-chapters'"
              @click="purgeSelectedChapters"
            >
              永久清除所选章节
            </button>
          </div>

          <div v-if="!chapters.length" class="empty">当前没有已回收章节。</div>
          <div v-else class="trash-list">
            <article
              v-for="chapter in chapters"
              :key="chapter.chapter_id"
              class="trash-row"
              :class="{ disabled: !chapterSelectable(chapter) }"
              :data-testid="`author-trash-chapter-row-${chapter.chapter_id}`"
            >
              <label class="author-select-cell" :for="`trash-chapter-${chapter.chapter_id}`">
                <input
                  :id="`trash-chapter-${chapter.chapter_id}`"
                  v-model="selectedChapterIds"
                  type="checkbox"
                  :value="chapter.chapter_id"
                  :data-testid="`author-trash-chapter-select-${chapter.chapter_id}`"
                  :disabled="!chapterSelectable(chapter)"
                />
              </label>

              <div class="trash-row-copy">
                <div class="trash-row-head">
                  <div>
                    <strong>{{ chapter.chapter_id }}</strong>
                    <p class="trash-copy">{{ chapter.chapter_goal || "尚未保存章节目标。" }}</p>
                  </div>
                  <div class="trash-meta">
                    <span class="badge">{{ chapter.scene_count }} 个场景</span>
                    <span class="badge">回收于 {{ formatTimestamp(chapter.trashed_at) }}</span>
                  </div>
                </div>
                <p class="muted">操作员：{{ chapter.trashed_by || "未知操作员" }}</p>
                <div class="trash-reason-list">
                  <p v-if="chapter.restore_block_reason" class="trash-reason">{{ chapter.restore_block_reason }}</p>
                  <p v-if="chapter.purge_block_reason" class="trash-reason">{{ chapter.purge_block_reason }}</p>
                </div>
              </div>
            </article>
          </div>
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
            <button
              class="danger-button"
              data-testid="author-trash-purge-scenes-button"
              :disabled="!selectedPurgeableSceneIds.length || authorTrash.actionId === 'purge-scenes'"
              @click="purgeSelectedScenes"
            >
              永久清除所选场景
            </button>
          </div>

          <div v-if="!scenes.length" class="empty">当前没有已回收场景。</div>
          <div v-else class="trash-list">
            <article
              v-for="scene in scenes"
              :key="scene.scene_id"
              class="trash-row"
              :class="{ disabled: !sceneSelectable(scene) }"
              :data-testid="`author-trash-scene-row-${scene.scene_id}`"
            >
              <label class="author-select-cell" :for="`trash-scene-${scene.scene_id}`">
                <input
                  :id="`trash-scene-${scene.scene_id}`"
                  v-model="selectedSceneIds"
                  type="checkbox"
                  :value="scene.scene_id"
                  :data-testid="`author-trash-scene-select-${scene.scene_id}`"
                  :disabled="!sceneSelectable(scene)"
                />
              </label>

              <div class="trash-row-copy">
                <div class="trash-row-head">
                  <div>
                    <strong>{{ scene.scene_id }}</strong>
                    <p class="trash-copy">{{ scene.scene_goal || "尚未保存场景目标。" }}</p>
                  </div>
                  <div class="trash-meta">
                    <span class="badge">章节 {{ scene.chapter_id }}</span>
                    <span class="badge">顺序 {{ scene.scene_seq }}</span>
                    <span v-if="scene.chapter_trashed" class="badge">所属章节已回收</span>
                  </div>
                </div>
                <p class="muted">回收于 {{ formatTimestamp(scene.trashed_at) }}，操作员：{{ scene.trashed_by || "未知操作员" }}</p>
                <div class="trash-reason-list">
                  <p v-if="scene.restore_block_reason" class="trash-reason">{{ scene.restore_block_reason }}</p>
                  <p v-if="scene.purge_block_reason" class="trash-reason">{{ scene.purge_block_reason }}</p>
                </div>
              </div>
            </article>
          </div>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
