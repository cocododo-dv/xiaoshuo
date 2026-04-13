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
  emit("notice", `已打开 scene_card:${sceneId}`);
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
      eyebrow="作者工作台"
      title="在运行前整理章节与场景"
      description="编辑章节和场景的源数据，再把场景交给现有工作台继续处理。"
    >
      <template #actions>
        <div class="field-inline">
          <button data-testid="author-refresh-button" @click="refreshAuthorWorkspace">刷新</button>
          <button class="ghost" data-testid="author-new-chapter-button" @click="startNewChapter">新建章节</button>
          <button class="ghost" data-testid="author-new-scene-button" :disabled="!authorWorkspace.selectedChapterId" @click="startNewScene">
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
              <h3>章节</h3>
              <p class="muted receipt-copy">选择一个章节，或从零开始新建。</p>
            </div>
            <span class="badge">{{ chapters.length }} 个章节</span>
          </div>

          <div v-if="!chapters.length" class="empty">还没有章节，先创建第一章再开始。</div>
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
              <h3>章节表单</h3>
              <p class="muted receipt-copy">创建或更新用于构包与运行时的章节概要。</p>
            </div>
            <span class="badge">{{ creatingChapter ? "新建" : "编辑" }}</span>
          </div>

          <div class="author-form-grid">
            <label>
              <span>章节 ID</span>
              <input v-model="chapterForm.chapter_id" class="control-input" data-testid="author-chapter-id" :disabled="!creatingChapter && Boolean(chapterForm.chapter_id)" />
            </label>
            <label>
              <span>计划场景数</span>
              <input v-model.number="chapterForm.planned_scene_count" type="number" class="control-input" data-testid="author-chapter-scene-count" min="1" />
            </label>
            <label class="checkbox-inline">
              <input v-model.number="chapterForm.mid_aggregate_enabled" type="checkbox" true-value="1" false-value="0" />
              <span>启用中途聚合</span>
            </label>
            <div class="author-runtime-summary" v-if="authorWorkspace.chapterState">
              <span class="badge">阶段 {{ authorWorkspace.chapterState.current_phase }}</span>
              <span class="badge">已通过 {{ authorWorkspace.chapterState.chapter_passed_scene_count }}</span>
              <span class="badge">待补写 {{ authorWorkspace.chapterState.chapter_backfill_pending_count }}</span>
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
              <span>禁止项</span>
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
              <h3>场景</h3>
              <p class="muted receipt-copy">调整场景顺序、标记章末场景，并编辑当前选中场景。</p>
            </div>
            <span class="badge">{{ scenes.length }} 个场景</span>
          </div>

          <div v-if="!authorWorkspace.selectedChapterId" class="empty">先创建或选择章节，再编辑它的场景。</div>
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
                  <span class="muted">{{ scene.scene_status }} / {{ scene.location || "未填写地点" }}</span>
                </div>
                <div class="author-scene-actions">
                  <button class="ghost" :disabled="index === 0 || authorWorkspace.actionId === 'reorder-scenes'" :data-testid="`author-scene-move-up-${scene.scene_id}`" @click="moveScene(scene.scene_id, -1)">
                    上移
                  </button>
                  <button class="ghost" :disabled="index === scenes.length - 1 || authorWorkspace.actionId === 'reorder-scenes'" :data-testid="`author-scene-move-down-${scene.scene_id}`" @click="moveScene(scene.scene_id, 1)">
                    下移
                  </button>
                  <button class="ghost" :disabled="scene.is_chapter_last === 1 || authorWorkspace.actionId === 'reorder-scenes'" :data-testid="`author-scene-mark-last-${scene.scene_id}`" @click="markSceneAsLast(scene.scene_id)">
                    设为章末
                  </button>
                  <button class="ghost" :data-testid="`author-open-workbench-${scene.scene_id}`" @click="openInWorkbench(scene.scene_id)">
                    在场景工作台打开
                  </button>
                </div>
              </article>
            </div>

            <div class="author-form-grid author-scene-form">
              <label>
                <span>场景 ID</span>
                <input v-model="sceneForm.scene_id" class="control-input" data-testid="author-scene-id" :disabled="!creatingScene && Boolean(sceneForm.scene_id)" />
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
                <input v-model="sceneForm.onstage_chars_json" class="control-input" placeholder="CHAR_A, CHAR_B" />
              </label>
              <label>
                <span>地点</span>
                <input v-model="sceneForm.location" class="control-input" />
              </label>
              <label class="author-wide">
                <span>情节点</span>
                <textarea v-model="sceneForm.beats_json" class="control-input" placeholder="beat 1, beat 2" />
              </label>
              <label>
                <span>必须包含</span>
                <textarea v-model="sceneForm.must_include_text" class="control-input" />
              </label>
              <label>
                <span>禁止出现</span>
                <textarea v-model="sceneForm.forbidden_text" class="control-input" />
              </label>
              <label>
                <span>收尾变化</span>
                <textarea v-model="sceneForm.exit_change" class="control-input" />
              </label>
              <label>
                <span>钩子</span>
                <textarea v-model="sceneForm.hook" class="control-input" />
              </label>
              <label>
                <span>目标长度</span>
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
