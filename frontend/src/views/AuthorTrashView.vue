<script setup>
import { computed, onMounted, ref, watch } from "vue";

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
    return "Unknown time";
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
  await authorTrash.load();
  syncSelections();
  if (authorTrash.error) {
    emit("notice", authorTrash.error);
  }
}

async function restoreSelectedChapters() {
  const chapterIds = [...selectedRestorableChapterIds.value];
  if (!chapterIds.length || !confirmAction(`Restore ${chapterIds.length} selected chapter(s)?`)) {
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
  if (!chapterIds.length || !confirmAction(`Permanently purge ${chapterIds.length} selected chapter(s)?`)) {
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
  if (!sceneIds.length || !confirmAction(`Restore ${sceneIds.length} selected scene(s)?`)) {
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
  if (!sceneIds.length || !confirmAction(`Permanently purge ${sceneIds.length} selected scene(s)?`)) {
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

onMounted(() => {
  refreshTrash();
});
</script>

<template>
  <section class="panel-grid" data-testid="author-trash-view">
    <PanelShell
      eyebrow="Author Trash"
      title="Restore or permanently purge author records"
      description="Trashed chapters and scenes stay out of normal authoring and runtime flows until they are restored. Purge remains conservative and respects downstream runtime artifacts."
    >
      <template #actions>
        <div class="field-inline">
          <button @click="refreshTrash">Refresh Trash</button>
          <span class="badge">{{ chapters.length }} chapters</span>
          <span class="badge">{{ scenes.length }} scenes</span>
        </div>
      </template>

      <div v-if="authorTrash.loading" class="empty">Loading author trash...</div>
      <div v-else-if="authorTrash.error" class="empty">{{ authorTrash.error }}</div>
      <div v-else-if="!hasTrash" class="empty" data-testid="author-trash-empty">Author trash is empty.</div>
      <div v-else class="trash-layout">
        <article class="paper trash-section">
          <div class="receipt-head">
            <div>
              <h3>Trashed Chapters</h3>
              <p class="muted receipt-copy">Restore a whole chapter cascade, or purge only when every child scene is runtime-clean.</p>
            </div>
            <span class="badge">{{ chapters.length }}</span>
          </div>

          <div class="trash-toolbar">
            <button
              data-testid="author-trash-restore-chapters-button"
              :disabled="!selectedRestorableChapterIds.length || authorTrash.actionId === 'restore-chapters'"
              @click="restoreSelectedChapters"
            >
              Restore Selected Chapters
            </button>
            <button
              class="danger-button"
              data-testid="author-trash-purge-chapters-button"
              :disabled="!selectedPurgeableChapterIds.length || authorTrash.actionId === 'purge-chapters'"
              @click="purgeSelectedChapters"
            >
              Purge Selected Chapters
            </button>
          </div>

          <div v-if="!chapters.length" class="empty">No trashed chapters.</div>
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
                    <p class="trash-copy">{{ chapter.chapter_goal || "No chapter goal saved." }}</p>
                  </div>
                  <div class="trash-meta">
                    <span class="badge">{{ chapter.scene_count }} scenes</span>
                    <span class="badge">trashed {{ formatTimestamp(chapter.trashed_at) }}</span>
                  </div>
                </div>
                <p class="muted">by {{ chapter.trashed_by || "unknown operator" }}</p>
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
              <h3>Trashed Scenes</h3>
              <p class="muted receipt-copy">Scenes trashed with their parent chapter stay managed from the chapter row until the chapter is restored.</p>
            </div>
            <span class="badge">{{ scenes.length }}</span>
          </div>

          <div class="trash-toolbar">
            <button
              data-testid="author-trash-restore-scenes-button"
              :disabled="!selectedRestorableSceneIds.length || authorTrash.actionId === 'restore-scenes'"
              @click="restoreSelectedScenes"
            >
              Restore Selected Scenes
            </button>
            <button
              class="danger-button"
              data-testid="author-trash-purge-scenes-button"
              :disabled="!selectedPurgeableSceneIds.length || authorTrash.actionId === 'purge-scenes'"
              @click="purgeSelectedScenes"
            >
              Purge Selected Scenes
            </button>
          </div>

          <div v-if="!scenes.length" class="empty">No trashed scenes.</div>
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
                    <p class="trash-copy">{{ scene.scene_goal || "No scene goal saved." }}</p>
                  </div>
                  <div class="trash-meta">
                    <span class="badge">chapter {{ scene.chapter_id }}</span>
                    <span class="badge">seq {{ scene.scene_seq }}</span>
                    <span v-if="scene.chapter_trashed" class="badge">chapter trashed</span>
                  </div>
                </div>
                <p class="muted">trashed {{ formatTimestamp(scene.trashed_at) }} by {{ scene.trashed_by || "unknown operator" }}</p>
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
