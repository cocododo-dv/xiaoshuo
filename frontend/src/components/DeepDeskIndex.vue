<script setup>
import { computed } from "vue";

import BaseEmptyState from "./base/BaseEmptyState.vue";
import CompactEntitySelect from "./CompactEntitySelect.vue";
import { compactEntityOptions, formatChapterChoice, formatSceneChoice } from "../lib/readableRefs";
import { useWriterDeepDeskStore } from "../stores/writerDeepDesk";

const emit = defineEmits(["notice"]);

const desk = useWriterDeepDeskStore();

const chapters = computed(() => desk.chapters || []);
const scenes = computed(() => desk.availableScenes || []);
const chapterChoiceState = computed(() =>
  compactEntityOptions(chapters.value, {
    idKey: "chapter_id",
    titleKeys: ["chapter_title", "chapter_goal"],
    selectedId: desk.selectedChapterId,
    formatter: formatChapterChoice,
  }),
);
const sceneChoiceState = computed(() =>
  compactEntityOptions(scenes.value, {
    idKey: "scene_id",
    titleKeys: ["scene_title", "scene_goal"],
    selectedId: desk.selectedSceneId,
    formatter: formatSceneChoice,
  }),
);
const visibleChapters = computed(() => chapterChoiceState.value.options.map((o) => o.item).filter(Boolean));
const sceneOptions = computed(() => sceneChoiceState.value.options);

function statusLabel(value) {
  return { not_run: "未运行", reviewed: "已诊断", candidate: "候选", accepted: "已采纳", rejected: "已拒绝", pending: "待决定", draft: "草稿", approved: "已审核", current: "当前", superseded: "已替换" }[value] || value || "-";
}

async function selectChapter(chapterId) {
  try {
    await desk.selectChapter(chapterId);
  } catch (error) {
    emit("notice", error.message);
  }
}

async function selectScene(value) {
  try {
    await desk.selectSceneDraft(typeof value === "string" ? value : value?.target?.value);
  } catch (error) {
    emit("notice", error.message);
  }
}
</script>

<template>
  <aside class="paper deep-desk-index">
    <div class="receipt-head compact">
      <div>
        <h3>章节 / 场景</h3>
        <p class="muted receipt-copy">先定位章节，再切换章稿或场景稿。</p>
      </div>
      <span class="badge">{{ visibleChapters.length }} / {{ chapters.length }} 章</span>
    </div>
    <p v-if="chapterChoiceState.hiddenCount" class="muted receipt-copy">
      已折叠 {{ chapterChoiceState.hiddenCount }} 条同名历史 QA 章节。
    </p>
    <BaseEmptyState v-if="!visibleChapters.length" description="还没有可阅读章节。" />
    <div v-else class="readable-list deep-chapter-list">
      <button
        v-for="chapter in visibleChapters"
        :key="chapter.chapter_id"
        type="button"
        class="readable-selector-row deep-chapter-row readable-selector-row-single"
        :class="{ active: desk.selectedChapterId === chapter.chapter_id }"
        @click="selectChapter(chapter.chapter_id)"
      >
        <span class="readable-row-main">
          <strong class="readable-row-title">{{ formatChapterChoice(chapter).label }}</strong>
          <span class="readable-row-copy">{{ chapter.chapter_goal || "未填写章节目标" }}</span>
          <small class="readable-tech-ref" :title="chapter.chapter_id">{{ formatChapterChoice(chapter).technical }}</small>
          <small class="readable-row-meta">
            <span>{{ statusLabel(chapter.completion_status) }}</span>
            <span>{{ statusLabel(chapter.comparison_status) }}</span>
          </small>
        </span>
      </button>
    </div>

    <section class="scene-switcher">
      <div class="receipt-head compact">
        <div>
          <h4>场景稿</h4>
          <p class="muted receipt-copy">场景稿可从场景卡 / 章节目标生成空白骨架。</p>
        </div>
        <span class="badge">{{ scenes.length }} 场</span>
      </div>
      <CompactEntitySelect
        label="场景稿"
        :model-value="desk.selectedSceneId"
        :options="sceneOptions"
        :folded-count="sceneChoiceState.hiddenCount"
        :disabled="!scenes.length"
        placeholder="选择场景稿"
        test-id="deep-desk-scene-select"
        @change="selectScene"
      />
    </section>
  </aside>
</template>

<style scoped>
.deep-desk-index {
  display: grid;
  gap: 1rem;
}

.deep-chapter-list,
.scene-switcher {
  display: grid;
  gap: 0.6rem;
  min-width: 0;
}

.deep-chapter-list {
  max-height: 32rem;
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 0.2rem;
}

.deep-chapter-row {
  display: grid;
  gap: 0.35rem;
  width: 100%;
  min-width: 0;
  text-align: left;
  background: rgba(255, 255, 255, 0.54);
  color: var(--ink);
  border: 1px solid var(--line);
  box-shadow: none;
}

.deep-chapter-row.active {
  border-color: rgba(132, 45, 29, 0.35);
  background: rgba(163, 63, 47, 0.1);
}

.deep-chapter-row:hover {
  transform: none;
}

.deep-chapter-row span,
.deep-chapter-row small {
  overflow-wrap: anywhere;
}
</style>
