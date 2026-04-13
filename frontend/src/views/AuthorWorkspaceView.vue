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
const selectedChapterIdsForTrash = ref([]);
const selectedSceneIdsForTrash = ref([]);
const creatingChapter = ref(false);
const creatingScene = ref(false);

const chapters = computed(() => authorWorkspace.chapters || []);
const scenes = computed(() => authorWorkspace.scenes || []);
const selectedScene = computed(() => scenes.value.find((scene) => scene.scene_id === selectedSceneId.value) || null);
const selectedChapterTrashIds = computed(() =>
  selectedChapterIdsForTrash.value.filter((chapterId) =>
    chapters.value.some((chapter) => chapter.chapter_id === chapterId && Number(chapter.trash_allowed) === 1),
  ),
);
const selectedSceneTrashIds = computed(() =>
  selectedSceneIdsForTrash.value.filter((sceneId) => scenes.value.some((scene) => scene.scene_id === sceneId)),
);

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

function isChapterTrashAllowed(chapter) {
  return Number(chapter?.trash_allowed) === 1;
}

function syncChapterTrashSelection() {
  const selectableChapterIds = new Set(
    chapters.value.filter((chapter) => isChapterTrashAllowed(chapter)).map((chapter) => chapter.chapter_id),
  );
  selectedChapterIdsForTrash.value = selectedChapterIdsForTrash.value.filter((chapterId) =>
    selectableChapterIds.has(chapterId),
  );
}

function syncSceneTrashSelection() {
  const selectableSceneIds = new Set(scenes.value.map((scene) => scene.scene_id));
  selectedSceneIdsForTrash.value = selectedSceneIdsForTrash.value.filter((sceneId) => selectableSceneIds.has(sceneId));
}

async function refreshAuthorWorkspace() {
  await authorWorkspace.initialize();
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
    selectedSceneId.value = sceneForm.scene_id;
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
    emit(
      "notice",
      await authorWorkspace.reorderScenes(
        scenes.value.map((scene) => scene.scene_id),
        sceneId,
      ),
    );
  } catch (error) {
    emit("notice", error.message);
  }
}

async function trashSelectedScenes() {
  const sceneIds = [...selectedSceneTrashIds.value];
  if (!sceneIds.length || !confirmAction(`确认将选中的 ${sceneIds.length} 个场景移入作者回收站吗？`)) {
    return;
  }
  try {
    const message = await authorWorkspace.trashScenes(sceneIds);
    selectedSceneIdsForTrash.value = [];
    emit("notice", message);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function trashSelectedChapters() {
  const chapterIds = [...selectedChapterTrashIds.value];
  if (!chapterIds.length || !confirmAction(`确认将选中的 ${chapterIds.length} 个章节移入作者回收站吗？`)) {
    return;
  }
  try {
    const message = await authorWorkspace.trashChapters(chapterIds);
    creatingChapter.value = false;
    creatingScene.value = false;
    selectedChapterIdsForTrash.value = [];
    selectedSceneId.value = "";
    emit("notice", message);
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
  () => chapters.value.map((chapter) => `${chapter.chapter_id}:${chapter.trash_allowed}`).join("|"),
  () => {
    syncChapterTrashSelection();
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
            data-testid="author-new-scene-button"
            :disabled="!authorWorkspace.selectedChapterId"
            @click="startNewScene"
          >
            新建场景
          </button>
        </div>
      </template>

      <div v-if="authorWorkspace.loading" class="empty">正在加载作者工作台...</div>
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

          <div v-if="!chapters.length" class="empty">当前还没有活跃章节。</div>
          <div v-else class="author-list">
            <article
              v-for="chapter in chapters"
              :key="chapter.chapter_id"
              class="author-list-row"
              :class="{ disabled: !isChapterTrashAllowed(chapter) }"
            >
              <label class="author-select-cell" :for="`chapter-trash-${chapter.chapter_id}`">
                <input
                  :id="`chapter-trash-${chapter.chapter_id}`"
                  v-model="selectedChapterIdsForTrash"
                  type="checkbox"
                  :value="chapter.chapter_id"
                  :data-testid="`author-chapter-select-for-trash-${chapter.chapter_id}`"
                  :disabled="!isChapterTrashAllowed(chapter) || authorWorkspace.actionId === 'trash-chapters'"
                  @click.stop
                />
              </label>

              <div class="author-list-content">
                <button
                  class="author-list-item"
                  :class="{ active: authorWorkspace.selectedChapterId === chapter.chapter_id }"
                  :data-testid="`author-chapter-select-${chapter.chapter_id}`"
                  @click="selectChapter(chapter.chapter_id)"
                >
                  <strong>{{ chapter.chapter_id }}</strong>
                  <span>{{ chapter.chapter_goal }}</span>
                  <span class="muted">{{ chapter.current_phase }} · {{ chapter.active_scene_count }} 个活跃场景</span>
                </button>

                <div class="author-list-meta">
                  <span class="badge">{{ chapter.active_scene_count }} 个活跃场景</span>
                  <span class="badge">{{ chapter.trashed_scene_count }} 个已回收场景</span>
                  <p
                    v-if="chapter.trash_block_reason"
                    class="author-block-reason"
                    :data-testid="`author-chapter-trash-block-${chapter.chapter_id}`"
                  >
                    {{ chapter.trash_block_reason }}
                  </p>
                </div>
              </div>
            </article>
          </div>
        </article>

        <article class="paper author-editor-card">
          <div class="receipt-head">
            <div>
              <h3>章节表单</h3>
              <p class="muted receipt-copy">维护面向作者的章节简报，供后续运行时流程直接消费。</p>
            </div>
            <span class="badge">{{ creatingChapter ? "新建中" : "编辑中" }}</span>
          </div>

          <div class="author-form-grid">
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
          </div>
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

          <div v-if="!authorWorkspace.selectedChapterId" class="empty">请先选择或新建章节，再编辑场景。</div>
          <template v-else>
            <div class="author-scene-list">
              <article
                v-for="(scene, index) in scenes"
                :key="scene.scene_id"
                class="author-scene-row"
                :class="{ active: selectedSceneId === scene.scene_id }"
                :data-testid="`author-scene-row-${scene.scene_id}`"
              >
                <label class="author-select-cell" :for="`scene-trash-${scene.scene_id}`">
                  <input
                    :id="`scene-trash-${scene.scene_id}`"
                    v-model="selectedSceneIdsForTrash"
                    type="checkbox"
                    :value="scene.scene_id"
                    :data-testid="`author-scene-select-${scene.scene_id}`"
                    :disabled="authorWorkspace.actionId === 'trash-scenes'"
                    @click.stop
                  />
                </label>

                <div class="author-scene-body">
                  <div class="author-scene-meta" @click="selectScene(scene.scene_id)">
                    <strong>{{ scene.scene_seq }}. {{ scene.scene_id }}</strong>
                    <span>{{ scene.scene_goal }}</span>
                    <span class="muted">{{ scene.scene_status }} · {{ scene.location || "未设置地点" }}</span>
                  </div>

                  <div class="author-scene-actions">
                    <button
                      class="ghost"
                      :disabled="index === 0 || authorWorkspace.actionId === 'reorder-scenes'"
                      :data-testid="`author-scene-move-up-${scene.scene_id}`"
                      @click="moveScene(scene.scene_id, -1)"
                    >
                      上移
                    </button>
                    <button
                      class="ghost"
                      :disabled="index === scenes.length - 1 || authorWorkspace.actionId === 'reorder-scenes'"
                      :data-testid="`author-scene-move-down-${scene.scene_id}`"
                      @click="moveScene(scene.scene_id, 1)"
                    >
                      下移
                    </button>
                    <button
                      class="ghost"
                      :disabled="scene.is_chapter_last === 1 || authorWorkspace.actionId === 'reorder-scenes'"
                      :data-testid="`author-scene-mark-last-${scene.scene_id}`"
                      @click="markSceneAsLast(scene.scene_id)"
                    >
                      标记为章节结尾
                    </button>
                    <button
                      class="ghost"
                      :data-testid="`author-open-workbench-${scene.scene_id}`"
                      @click="openInWorkbench(scene.scene_id)"
                    >
                      在场景工作台打开
                    </button>
                  </div>
                </div>
              </article>
            </div>

            <div class="author-form-grid author-scene-form">
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
                :disabled="authorWorkspace.actionId.startsWith('save-scene') || !sceneForm.scene_id"
                data-testid="author-save-scene-button"
                @click="saveScene"
              >
                {{ authorWorkspace.actionId.startsWith("save-scene") ? "保存中..." : "保存场景" }}
              </button>
            </div>
          </template>
        </article>
      </div>
    </PanelShell>
  </section>
</template>
