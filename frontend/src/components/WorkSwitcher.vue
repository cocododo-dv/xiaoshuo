<script setup>
import { Check, ChevronDown, Plus } from "lucide-vue-next";
import { computed, ref } from "vue";

import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["navigate"]);

const snowflake = useSnowflakeWorkbenchStore();
const open = ref(false);

const ACCENTS = ["crimson", "gold", "sage", "slate"];

const works = computed(() =>
  (snowflake.projects || []).map((project, index) => ({
    id: project.project_id,
    title: project.title || project.project_id,
    sub: project.genre || project.status || "未设定题材",
    mark: Array.from(String(project.title || "书"))[0],
    accent: ACCENTS[index % ACCENTS.length],
    active: project.project_id === snowflake.selectedProjectId,
  })),
);

const activeWork = computed(
  () => works.value.find((work) => work.active) || works.value[0] || null,
);

async function toggle() {
  open.value = !open.value;
  if (open.value) {
    snowflake.initialize().catch(() => {});
  }
}

async function pickWork(workId) {
  open.value = false;
  if (workId && workId !== snowflake.selectedProjectId) {
    try {
      await snowflake.selectProject(workId);
    } catch {
      /* 加载失败时主页会显示空态,不阻断切换 */
    }
  }
  emit("navigate", "home");
}

function startNew() {
  open.value = false;
  emit("navigate", "snowflake-workbench", { target: { panel: "project" } });
}
</script>

<template>
  <div class="ws-work-switcher">
    <button
      type="button"
      class="ws-brand"
      :class="{ 'is-open': open }"
      :title="activeWork ? `当前作品:${activeWork.title},点击切换` : '切换 / 新建作品'"
      data-testid="work-switcher"
      aria-haspopup="true"
      :aria-expanded="open"
      @click.stop="toggle"
    >
      <span class="ws-brand-mark" :data-accent="activeWork?.accent || 'crimson'" aria-hidden="true">
        {{ activeWork?.mark || "雪" }}
      </span>
      <span class="ws-brand-text">
        <span class="ws-brand-title">{{ activeWork?.title || "创作工作台" }}</span>
        <span class="ws-brand-sub">{{ activeWork?.sub || "小说创作系统" }}</span>
      </span>
      <span class="ws-brand-caret" aria-hidden="true"><ChevronDown :size="15" /></span>
    </button>

    <Teleport to="body">
      <div v-if="open" class="ws-wsw-scrim" @click="open = false">
        <div class="ws-wsw" role="menu" data-testid="work-switcher-popover" @click.stop>
          <div class="ws-wsw-head">
            <span class="ws-wsw-head-lbl">作品</span>
            <span class="ws-wsw-head-n">{{ works.length }} 部</span>
          </div>
          <div class="ws-wsw-list">
            <p v-if="!works.length" class="ws-wsw-empty">还没有作品——新建一部,从一句话开始。</p>
            <button
              v-for="work in works"
              :key="work.id"
              type="button"
              class="ws-wsw-row"
              :class="{ 'is-active': work.active }"
              role="menuitemradio"
              :aria-checked="work.active"
              :data-testid="`work-pick-${work.id}`"
              @click="pickWork(work.id)"
            >
              <span class="ws-wsw-mark" :data-accent="work.accent" aria-hidden="true">{{ work.mark }}</span>
              <span class="ws-wsw-meta">
                <span class="ws-wsw-title">{{ work.title }}</span>
                <span class="ws-wsw-sub">{{ work.sub }}</span>
              </span>
              <span v-if="work.active" class="ws-wsw-check"><Check :size="15" /></span>
            </button>
          </div>
          <button type="button" class="ws-wsw-new" @click="startNew">
            <span class="ws-wsw-new-ic"><Plus :size="16" /></span> 新建作品
          </button>
        </div>
      </div>
    </Teleport>
  </div>
</template>
