<script setup>
import {
  ArrowRight,
  BookOpenText,
  ClipboardCheck,
  Layout,
  PenLine,
  Snowflake,
} from "lucide-vue-next";
import { computed, onActivated, onMounted, ref } from "vue";

import { fetchChapterManuscripts, fetchReviewItems } from "../lib/api";
import { useShellRouter } from "../router";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

defineEmits(["notice"]);

const router = useShellRouter();
const snowflake = useSnowflakeWorkbenchStore();

const manuscriptItems = ref([]);
const pendingReviewCount = ref(0);

async function refresh() {
  snowflake.initialize().catch(() => {});
  try {
    const payload = await fetchChapterManuscripts();
    manuscriptItems.value = payload?.items || [];
  } catch {
    manuscriptItems.value = [];
  }
  try {
    const payload = await fetchReviewItems({ status: "pending" });
    pendingReviewCount.value = (payload?.items || []).length;
  } catch {
    pendingReviewCount.value = 0;
  }
}

onMounted(refresh);
onActivated(refresh);

const steps = computed(() => snowflake.steps || []);
const snowDone = computed(() => steps.value.filter((step) => step.gate_satisfied).length);
const snowStale = computed(() => steps.value.filter((step) => step?.artifact?.status === "stale").length);
const boardChapters = computed(() => snowflake.sceneBoard?.chapters || []);
const boardScenes = computed(() => snowflake.sceneBoard?.scenes || []);
const blockingTriage = computed(() => (snowflake.triageDrafts || []).filter((item) => item.blocking).length);
const completeChapters = computed(() => manuscriptItems.value.filter((item) => item.completion_status === "complete").length);
const partialChapters = computed(() => manuscriptItems.value.filter((item) => item.completion_status === "partial").length);

/* 旅程五站:构思 → 结构 → 起草与写作 → 成稿 → 待你拍板。
   每站的口径都来自真实数据;tone:ok=苔绿 / busy=暮金 / attention=绯红 / idle=灰 */
const stations = computed(() => [
  {
    id: "snowflake",
    icon: Snowflake,
    title: "构思",
    stat: steps.value.length ? `${snowDone.value}/${steps.value.length} 步已确认` : "还没开始",
    detail: snowStale.value ? `${snowStale.value} 步需复核` : "雪花十步",
    tone: snowStale.value ? "attention" : snowDone.value >= steps.value.length && steps.value.length ? "ok" : "busy",
    view: "snowflake-workbench",
    cta: "去构思",
  },
  {
    id: "structure",
    icon: Layout,
    title: "结构",
    stat: boardChapters.value.length ? `${boardChapters.value.length} 章 · ${boardScenes.value.length} 场` : "待规划",
    detail: blockingTriage.value ? `${blockingTriage.value} 场必须修` : "章节编排与场景体检",
    tone: blockingTriage.value ? "attention" : boardChapters.value.length ? "ok" : "idle",
    view: "author",
    cta: "去编排",
  },
  {
    id: "draft",
    icon: PenLine,
    title: "起草与写作",
    stat: partialChapters.value ? `${partialChapters.value} 章在写` : "暂无在写章节",
    detail: "AI 起草台与写作房间殊途同归",
    tone: partialChapters.value ? "busy" : "idle",
    view: "writer-room",
    cta: "进写作房间",
  },
  {
    id: "manuscripts",
    icon: BookOpenText,
    title: "成稿",
    stat: manuscriptItems.value.length ? `${completeChapters.value}/${manuscriptItems.value.length} 章完整` : "还没有成稿",
    detail: "书脊与章级闸门",
    tone: completeChapters.value ? "ok" : "idle",
    view: "manuscripts",
    cta: "看成稿",
  },
  {
    id: "review",
    icon: ClipboardCheck,
    title: "待你拍板",
    stat: pendingReviewCount.value ? `${pendingReviewCount.value} 项待审` : "没有积压",
    detail: "审核、退回与恢复事件",
    tone: pendingReviewCount.value ? "attention" : "ok",
    view: "review",
    cta: "去收件箱",
  },
]);

function go(viewId) {
  router.navigate(viewId);
}
</script>

<template>
  <div class="ws-page ws-view flow" data-testid="flowmap-view">
    <header class="page-header">
      <div>
        <div class="page-eyebrow">流程</div>
        <h1 class="page-title">这部作品此刻在全流程的哪儿</h1>
        <p class="page-subtitle">构思 → 结构 → 起草与写作 → 成稿 → 拍板。每一站都是真实状态,红点就是下一步。</p>
      </div>
    </header>

    <div class="flow-track" data-testid="flowmap-track">
      <template v-for="(station, index) in stations" :key="station.id">
        <article class="flow-station card" :class="`t-${station.tone}`" :data-testid="`flow-station-${station.id}`">
          <div class="flow-station-head">
            <span class="flow-station-ic"><component :is="station.icon" :size="18" /></span>
            <h2 class="flow-station-title">{{ station.title }}</h2>
            <span class="flow-station-dot" aria-hidden="true" />
          </div>
          <div class="flow-station-stat">{{ station.stat }}</div>
          <div class="flow-station-detail">{{ station.detail }}</div>
          <button type="button" class="btn btn-quiet btn-sm flow-station-cta" @click="go(station.view)">
            {{ station.cta }} <ArrowRight :size="13" />
          </button>
        </article>
        <span v-if="index < stations.length - 1" class="flow-link" aria-hidden="true"><ArrowRight :size="15" /></span>
      </template>
    </div>

    <p class="flow-note text-muted">
      这张地图只读不拦路:状态来自构思工作台、场景体检、成稿中心与审核收件箱的同一份数据。
    </p>
  </div>
</template>

<style scoped>
.flow-track {
  display: flex;
  align-items: stretch;
  gap: 8px;
  flex-wrap: wrap;
}

.flow-station {
  flex: 1 1 170px;
  min-width: 170px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 3px solid var(--line-2);
}

.flow-station.t-ok { border-top-color: var(--sage); }
.flow-station.t-busy { border-top-color: var(--gold); }
.flow-station.t-attention { border-top-color: var(--crimson); }

.flow-station-head {
  display: flex;
  align-items: center;
  gap: 9px;
}

.flow-station-ic {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  background: var(--paper-2);
  color: var(--ink-2);
}

.flow-station.t-attention .flow-station-ic {
  background: var(--crimson-wash);
  color: var(--crimson);
}

.flow-station.t-ok .flow-station-ic {
  background: var(--sage-wash);
  color: var(--sage);
}

.flow-station.t-busy .flow-station-ic {
  background: var(--gold-wash);
  color: var(--gold);
}

.flow-station-title {
  font-family: var(--font-serif);
  font-size: 16px;
  font-weight: 600;
  margin: 0;
}

.flow-station-dot {
  margin-left: auto;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--line-3);
}

.flow-station.t-ok .flow-station-dot { background: var(--sage); }
.flow-station.t-busy .flow-station-dot { background: var(--gold); }
.flow-station.t-attention .flow-station-dot { background: var(--crimson); box-shadow: 0 0 0 3px var(--crimson-wash); }

.flow-station-stat {
  font-family: var(--font-serif);
  font-size: 17px;
  font-weight: 600;
  color: var(--ink-1);
  font-variant-numeric: tabular-nums;
}

.flow-station-detail {
  font-size: 12px;
  color: var(--ink-3);
  flex: 1;
}

.flow-station-cta {
  align-self: flex-start;
}

.flow-link {
  align-self: center;
  color: var(--ink-4);
  flex: 0 0 auto;
}

.flow-note {
  margin-top: 18px;
  font-size: 12.5px;
}

@media (max-width: 980px) {
  .flow-track {
    flex-direction: column;
  }

  .flow-link {
    transform: rotate(90deg);
    align-self: flex-start;
    margin-left: 24px;
  }
}
</style>
