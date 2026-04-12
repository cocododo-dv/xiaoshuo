<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue";

import PanelShell from "../components/PanelShell.vue";
import { useShellRouter } from "../router";
import { useAuthorWorkspaceStore } from "../stores/authorWorkspace";

const emit = defineEmits(["notice"]);

const authorWorkspace = useAuthorWorkspaceStore();
const { openTarget } = useShellRouter();

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
const creatingChapter = ref(false);
const creatingScene = ref(false);

const chapters = computed(() => authorWorkspace.chapters || []);
const scenes = computed(() => authorWorkspace.scenes || []);
const selectedScene = computed(() => scenes.value.find((scene) => scene.scene_id === selectedSceneId.value) || null);

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
    Object.assign(sceneForm, createEmptySceneForm(authorWorkspace.selectedChapterId));
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

function startNewChapter() {
  creatingChapter.value = true;
  assignChapterForm(null);
  selectedSceneId.value = "";
  creatingScene.value = true;
  assignSceneForm(null);
}

function startNewScene() {
  creatingScene.value = true;
  selectedSceneId.value = "";
  assignSceneForm(null);
}

async function refreshAuthorWorkspace() {
  await authorWorkspace.initialize();
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
  try {
    const message = await authorWorkspace.saveChapter({
      ...chapterForm,
      planned_scene_count: Number(chapterForm.planned_scene_count || 0),
      mid_aggregate_enabled: Number(chapterForm.mid_aggregate_enabled || 0),
    });
    creatingChapter.value = false;
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function saveScene() {
  try {
    const message = await authorWorkspace.saveScene({
      ...sceneForm,
      chapter_id: authorWorkspace.selectedChapterId || chapterForm.chapter_id,
      onstage_chars_json: textToList(sceneForm.onstage_chars_json),
      beats_json: textToList(sceneForm.beats_json),
    });
    creatingScene.value = false;
    if (sceneForm.scene_id) {
      selectedSceneId.value = sceneForm.scene_id;
    }
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
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
  try {
    emit("notice", await authorWorkspace.reorderScenes(orderedSceneIds, lastSceneId));
  } catch (error) {
    emit("notice", error.message);
  }
}

async function markSceneAsLast(sceneId) {
  try {
    emit("notice", await authorWorkspace.reorderScenes(
      scenes.value.map((scene) => scene.scene_id),
      sceneId,
    ));
  } catch (error) {
    emit("notice", error.message);
  }
}

function openInWorkbench(sceneId) {
  openTarget({
    target_type: "scene_card",
    target_id: sceneId,
    target_ref: `scene_card:${sceneId}`,
  });
  emit("notice", `Opened scene_card:${sceneId}`);
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
      sceneForm.chapter_id = nextChapterId || "";
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
    if (!selectedSceneId.value && scenes.value.length && !creatingScene.value) {
      selectedSceneId.value = scenes.value[0].scene_id;
    }
    if (selectedSceneId.value && !scenes.value.some((scene) => scene.scene_id === selectedSceneId.value)) {
      selectedSceneId.value = scenes.value[0]?.scene_id || "";
    }
  },
  { immediate: true },
);

onMounted(() => {
  refreshAuthorWorkspace();
});
</script>

<template>
  <section class="panel-grid" data-testid="author-workspace-view">
    <PanelShell
      eyebrow="Author Workspace"
      title="Shape chapters and scenes before runtime"
      description="Edit the chapter and scene source-of-truth, then hand scenes off into the existing workbench."
    >
      <template #actions>
        <div class="field-inline">
          <button data-testid="author-refresh-button" @click="refreshAuthorWorkspace">Refresh</button>
          <button class="ghost" data-testid="author-new-chapter-button" @click="startNewChapter">New Chapter</button>
          <button class="ghost" data-testid="author-new-scene-button" :disabled="!authorWorkspace.selectedChapterId" @click="startNewScene">
            New Scene
          </button>
        </div>
      </template>

      <div v-if="authorWorkspace.loading" class="empty">Loading author workspace...</div>
      <div v-else-if="authorWorkspace.error" class="empty">{{ authorWorkspace.error }}</div>
      <div v-else class="author-layout">
        <article class="paper author-sidebar">
          <div class="receipt-head">
            <div>
              <h3>Chapters</h3>
              <p class="muted receipt-copy">Select a chapter or start a new one.</p>
            </div>
            <span class="badge">{{ chapters.length }} chapters</span>
          </div>

          <div v-if="!chapters.length" class="empty">No chapters yet. Create the first chapter to begin.</div>
          <div v-else class="author-list">
            <button
              v-for="chapter in chapters"
              :key="chapter.chapter_id"
              class="author-list-item"
              :class="{ active: authorWorkspace.selectedChapterId === chapter.chapter_id }"
              :data-testid="`author-chapter-select-${chapter.chapter_id}`"
              @click="selectChapter(chapter.chapter_id)"
            >
              <strong>{{ chapter.chapter_id }}</strong>
              <span>{{ chapter.chapter_goal }}</span>
              <span class="muted">{{ chapter.current_phase }} / passed {{ chapter.chapter_passed_scene_count }}</span>
            </button>
          </div>
        </article>

        <article class="paper author-editor-card">
          <div class="receipt-head">
            <div>
              <h3>Chapter Form</h3>
              <p class="muted receipt-copy">Create or update the chapter brief that feeds bundle building and runtime.</p>
            </div>
            <span class="badge">{{ creatingChapter ? "new" : "edit" }}</span>
          </div>

          <div class="author-form-grid">
            <label>
              <span>Chapter ID</span>
              <input v-model="chapterForm.chapter_id" class="control-input" data-testid="author-chapter-id" :disabled="!creatingChapter && Boolean(chapterForm.chapter_id)" />
            </label>
            <label>
              <span>Planned Scene Count</span>
              <input v-model.number="chapterForm.planned_scene_count" type="number" class="control-input" data-testid="author-chapter-scene-count" min="1" />
            </label>
            <label class="checkbox-inline">
              <input v-model.number="chapterForm.mid_aggregate_enabled" type="checkbox" true-value="1" false-value="0" />
              <span>Mid aggregate enabled</span>
            </label>
            <div class="author-runtime-summary" v-if="authorWorkspace.chapterState">
              <span class="badge">phase {{ authorWorkspace.chapterState.current_phase }}</span>
              <span class="badge">passed {{ authorWorkspace.chapterState.chapter_passed_scene_count }}</span>
              <span class="badge">backfill {{ authorWorkspace.chapterState.chapter_backfill_pending_count }}</span>
            </div>
            <label class="author-wide">
              <span>Chapter Goal</span>
              <textarea v-model="chapterForm.chapter_goal" class="control-input" data-testid="author-chapter-goal" />
            </label>
            <label>
              <span>Main Plot Push</span>
              <textarea v-model="chapterForm.main_plot_push" class="control-input" />
            </label>
            <label>
              <span>Emotional Target</span>
              <textarea v-model="chapterForm.emotional_target" class="control-input" />
            </label>
            <label>
              <span>Ending Effect</span>
              <textarea v-model="chapterForm.ending_effect" class="control-input" />
            </label>
            <label>
              <span>Must Not</span>
              <textarea v-model="chapterForm.must_not" class="control-input" />
            </label>
            <label class="author-wide">
              <span>Notes</span>
              <textarea v-model="chapterForm.notes" class="control-input" />
            </label>
          </div>

          <div class="card-actions">
            <button
              :disabled="authorWorkspace.actionId === 'save-chapter' || !chapterForm.chapter_id"
              data-testid="author-save-chapter-button"
              @click="saveChapter"
            >
              {{ authorWorkspace.actionId === "save-chapter" ? "Saving..." : "Save Chapter" }}
            </button>
          </div>
        </article>

        <article class="paper author-editor-card">
          <div class="receipt-head">
            <div>
              <h3>Scenes</h3>
              <p class="muted receipt-copy">Reorder scenes, mark the chapter ending, and edit the selected scene.</p>
            </div>
            <span class="badge">{{ scenes.length }} scenes</span>
          </div>

          <div v-if="!authorWorkspace.selectedChapterId" class="empty">Create or select a chapter to edit its scenes.</div>
          <template v-else>
            <div class="author-scene-list">
              <article
                v-for="(scene, index) in scenes"
                :key="scene.scene_id"
                class="author-scene-row"
                :class="{ active: selectedSceneId === scene.scene_id }"
                :data-testid="`author-scene-row-${scene.scene_id}`"
              >
                <div class="author-scene-meta" @click="selectScene(scene.scene_id)">
                  <strong>{{ scene.scene_seq }}. {{ scene.scene_id }}</strong>
                  <span>{{ scene.scene_goal }}</span>
                  <span class="muted">{{ scene.scene_status }} / {{ scene.location || "No location" }}</span>
                </div>
                <div class="author-scene-actions">
                  <button class="ghost" :disabled="index === 0 || authorWorkspace.actionId === 'reorder-scenes'" :data-testid="`author-scene-move-up-${scene.scene_id}`" @click="moveScene(scene.scene_id, -1)">
                    Up
                  </button>
                  <button class="ghost" :disabled="index === scenes.length - 1 || authorWorkspace.actionId === 'reorder-scenes'" :data-testid="`author-scene-move-down-${scene.scene_id}`" @click="moveScene(scene.scene_id, 1)">
                    Down
                  </button>
                  <button class="ghost" :disabled="scene.is_chapter_last === 1 || authorWorkspace.actionId === 'reorder-scenes'" :data-testid="`author-scene-mark-last-${scene.scene_id}`" @click="markSceneAsLast(scene.scene_id)">
                    Mark Last
                  </button>
                  <button class="ghost" :data-testid="`author-open-workbench-${scene.scene_id}`" @click="openInWorkbench(scene.scene_id)">
                    Open in Scene Workbench
                  </button>
                </div>
              </article>
            </div>

            <div class="author-form-grid author-scene-form">
              <label>
                <span>Scene ID</span>
                <input v-model="sceneForm.scene_id" class="control-input" data-testid="author-scene-id" :disabled="!creatingScene && Boolean(sceneForm.scene_id)" />
              </label>
              <label>
                <span>POV Character</span>
                <input v-model="sceneForm.pov_character_id" class="control-input" />
              </label>
              <label class="author-wide">
                <span>Scene Goal</span>
                <textarea v-model="sceneForm.scene_goal" class="control-input" data-testid="author-scene-goal" />
              </label>
              <label>
                <span>Onstage Characters</span>
                <input v-model="sceneForm.onstage_chars_json" class="control-input" placeholder="CHAR_A, CHAR_B" />
              </label>
              <label>
                <span>Location</span>
                <input v-model="sceneForm.location" class="control-input" />
              </label>
              <label class="author-wide">
                <span>Beats</span>
                <textarea v-model="sceneForm.beats_json" class="control-input" placeholder="beat 1, beat 2" />
              </label>
              <label>
                <span>Must Include</span>
                <textarea v-model="sceneForm.must_include_text" class="control-input" />
              </label>
              <label>
                <span>Forbidden</span>
                <textarea v-model="sceneForm.forbidden_text" class="control-input" />
              </label>
              <label>
                <span>Exit Change</span>
                <textarea v-model="sceneForm.exit_change" class="control-input" />
              </label>
              <label>
                <span>Hook</span>
                <textarea v-model="sceneForm.hook" class="control-input" />
              </label>
              <label>
                <span>Target Length</span>
                <input v-model="sceneForm.target_length_band" class="control-input" />
              </label>
              <label>
                <span>Scene Type</span>
                <input v-model="sceneForm.scene_type" class="control-input" />
              </label>
            </div>

            <div class="card-actions">
              <button
                :disabled="authorWorkspace.actionId.startsWith('save-scene') || !sceneForm.scene_id"
                data-testid="author-save-scene-button"
                @click="saveScene"
              >
                {{ authorWorkspace.actionId.startsWith("save-scene") ? "Saving..." : "Save Scene" }}
              </button>
            </div>
          </template>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
