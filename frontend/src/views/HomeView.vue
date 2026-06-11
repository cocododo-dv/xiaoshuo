<script setup>
import {
  ArrowRight,
  CheckCircle,
  Compass,
  Inbox,
  PenLine,
  Quote,
  Snowflake,
} from "lucide-vue-next";
import { computed, onActivated, onMounted, ref } from "vue";

import { fetchReviewItems } from "../lib/api";
import { useShellRouter } from "../router";
import { useSnowflakeWorkbenchStore } from "../stores/snowflakeWorkbench";

const emit = defineEmits(["notice"]);

const router = useShellRouter();
const snowflake = useSnowflakeWorkbenchStore();

/* 待办速览直接走 API,本地持有——不预热 reviewInbox store,
   避免污染收件箱视图自己的加载/聚焦时序。 */
const pendingReviewItems = ref([]);

async function refreshHomeData() {
  snowflake.initialize().catch(() => {});
  try {
    const data = await fetchReviewItems({ status: "pending" });
    pendingReviewItems.value = data?.items || [];
  } catch {
    pendingReviewItems.value = [];
  }
}

onMounted(refreshHomeData);
onActivated(refreshHomeData);

const project = computed(() => snowflake.project);
const steps = computed(() => snowflake.steps || []);
const hasProject = computed(() => Boolean(project.value?.project_id));

/* —— 一句话简介:优先读雪花第 2 步草稿,退回项目大纲 —— */
const logline = computed(() => {
  const sentenceStep = steps.value.find((step) => step.step_key === "one_sentence_summary");
  return (
    sentenceStep?.draft?.summary
    || project.value?.outline_text
    || "还没有一句话简介——到构思里,把这部作品压成一行。"
  );
});

/* —— 雪花进度 —— */
const snowTicks = computed(() =>
  steps.value.map((step) => {
    const status = step?.artifact?.status || "";
    const isCurrent = step.step_key === snowflake.currentStep?.step_key;
    return {
      key: step.step_key,
      name: step.label,
      s: isCurrent ? "active" : step.gate_satisfied ? "done" : status === "pending_review" || status === "stale" ? "warn" : "todo",
    };
  }),
);
const snowDone = computed(() => steps.value.filter((step) => step.gate_satisfied).length);
const snowNow = computed(() => snowflake.currentStep?.label || "全部完成");
const structurePct = computed(() => (steps.value.length ? Math.round((snowDone.value / steps.value.length) * 100) : 0));

/* —— 章节 / 场景(物化前来自场景板规划) —— */
const boardChapters = computed(() => snowflake.sceneBoard?.chapters || []);
const boardScenes = computed(() => snowflake.sceneBoard?.scenes || []);

const HOME_CHAP_ST = { approved: "定稿", review: "送审", draft: "草稿", writing: "在写", planned: "规划" };

const recentChapters = computed(() => {
  const scenesByChapter = {};
  boardScenes.value.forEach((scene) => {
    const key = scene.chapter_id || "";
    scenesByChapter[key] = scenesByChapter[key] || [];
    scenesByChapter[key].push(scene);
  });
  return boardChapters.value.slice(-5).map((chapter, index) => {
    const chapterId = chapter.chapter_id || chapter.id || String(chapter);
    const scenes = scenesByChapter[chapterId] || [];
    const filled = scenes.filter((scene) => scene.goal || scene.reaction || scene.summary).length;
    return {
      id: chapterId,
      n: String(chapter.chapter_seq || index + 1).padStart(2, "0"),
      t: chapter.title || chapter.chapter_title || chapterId,
      s: "planned",
      pct: scenes.length ? Math.round((filled / scenes.length) * 100) : 0,
      active: index === boardChapters.value.length - 1,
    };
  });
});

/* —— 此刻该写哪一幕:取第一个 GMC 未填满的场景规划,全满则取第一场 —— */
const heroScene = computed(() => {
  const scenes = boardScenes.value;
  if (!scenes.length) {
    return null;
  }
  return scenes.find((scene) => !(scene.goal || scene.reaction)) || scenes[0];
});

const heroSlug = computed(() => {
  const scene = heroScene.value;
  if (!scene) {
    return "";
  }
  const form = String(scene.primary_form || scene.scene_type || "proactive").toLowerCase() === "reactive" ? "反应" : "主动";
  return `${scene.chapter_id || "未编章"} · #${scene.scene_seq || 1} · ${form}场景`;
});

const heroTitle = computed(() => heroScene.value?.title || heroScene.value?.summary || heroScene.value?.scene_id || "—");

const heroGos = computed(() => {
  const scene = heroScene.value;
  if (!scene) {
    return [];
  }
  const reactive = String(scene.primary_form || scene.scene_type || "proactive").toLowerCase() === "reactive";
  if (reactive) {
    return [
      { k: "反应", tone: "sage", v: scene.reaction || "(反应待规划)" },
      { k: "困境", tone: "gold", v: scene.dilemma || "(困境待规划)" },
      { k: "决定", tone: "crimson", v: scene.decision || "(决定待规划)" },
    ];
  }
  return [
    { k: "目标", tone: "sage", v: scene.goal || "(本场目标待规划)" },
    { k: "冲突", tone: "gold", v: scene.conflict || "(冲突待规划)" },
    { k: "挫折", tone: "crimson", v: scene.setback || "(挫折待规划)" },
  ];
});

/* —— 待办速览(与待办收件箱同一后端数据) —— */
const todos = computed(() =>
  pendingReviewItems.value
    .map((item) => ({
      id: item.review_id,
      tone: "gold",
      label: "待审",
      title: item.candidate_text || item.review_id,
    }))
    .slice(0, 3),
);

function go(viewId, options) {
  router.navigate(viewId, options);
}

/* —— 进度环 —— */
const RING_SIZE = 66;
const ringStroke = Math.max(6, Math.round(RING_SIZE * 0.105));
const ringRadius = (RING_SIZE - ringStroke) / 2 - 1;
const ringCircumference = 2 * Math.PI * ringRadius;
const ringDash = computed(() => (structurePct.value / 100) * ringCircumference);
</script>

<template>
  <div class="ws-page ws-view hm" data-testid="home-view">
    <!-- ===== 全新/空白状态 ===== -->
    <template v-if="!hasProject || !steps.length">
      <header class="hm-top">
        <div class="hm-id">
          <div class="hm-greet"><span class="hm-greet-dot" /> 新的开始</div>
          <h1 class="hm-title">{{ project?.title || "开一部新书" }}</h1>
          <p class="hm-logline">还没有简介——可以先用一句话,说清这部作品是关于什么的。</p>
        </div>
      </header>

      <section class="hm-empty">
        <div class="hm-empty-mark">{{ (project?.title || "新")[0] }}</div>
        <h2 class="hm-empty-title">这部作品还是一张白纸</h2>
        <p class="hm-empty-sub">先把念头落成结构,再开始写。<br />不知道从哪起步的话,雪花十步会一步步带着你走。</p>
        <div class="hm-empty-actions">
          <button type="button" class="btn btn-accent btn-lg" @click="go('snowflake-workbench')">
            <Snowflake :size="16" /> 开始雪花构思
          </button>
          <button type="button" class="btn btn-ghost btn-lg" @click="go('writer-room')">
            <PenLine :size="16" /> 直接进入写作
          </button>
        </div>
      </section>

      <section class="hm-start">
        <div class="hm-chaps-head"><div class="hm-chaps-title">起步清单</div></div>
        <div class="hm-start-grid">
          <button type="button" class="hm-start-card" @click="go('snowflake-workbench')">
            <span class="hm-start-ic"><Snowflake :size="20" /></span>
            <div class="hm-start-title">雪花构思</div>
            <div class="hm-start-desc">从一句话故事开始,逐步长出人物与大纲。</div>
            <span class="hm-start-cta">开始十步 <ArrowRight :size="13" /></span>
          </button>
          <button type="button" class="hm-start-card" @click="go('reference')">
            <span class="hm-start-ic"><Quote :size="20" /></span>
            <div class="hm-start-title">设定风格基调</div>
            <div class="hm-start-desc">给这部作品定一个叙述声音与语感。</div>
            <span class="hm-start-cta">去设定 <ArrowRight :size="13" /></span>
          </button>
          <button type="button" class="hm-start-card" @click="go('writer-room')">
            <span class="hm-start-ic"><PenLine :size="20" /></span>
            <div class="hm-start-title">直接开写</div>
            <div class="hm-start-desc">想到哪写到哪,结构可以之后再补。</div>
            <span class="hm-start-cta">进写作房间 <ArrowRight :size="13" /></span>
          </button>
        </div>
      </section>
    </template>

    <!-- ===== 有进展的作品 ===== -->
    <template v-else>
      <header class="hm-top">
        <div class="hm-id">
          <div class="hm-greet"><span class="hm-greet-dot" /> 继续写作</div>
          <h1 class="hm-title">{{ project.title }}</h1>
          <p class="hm-logline">{{ logline }}</p>
        </div>
        <div class="hm-book" role="group" aria-label="结构进度">
          <svg class="home-ring hm-ring" :width="RING_SIZE" :height="RING_SIZE" :viewBox="`0 0 ${RING_SIZE} ${RING_SIZE}`" aria-hidden="true">
            <defs>
              <linearGradient id="wsRing" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0%" stop-color="var(--crimson)" />
                <stop offset="100%" stop-color="var(--gold)" />
              </linearGradient>
            </defs>
            <circle :cx="RING_SIZE / 2" :cy="RING_SIZE / 2" :r="ringRadius" fill="none" stroke="var(--line-1)" :stroke-width="ringStroke" />
            <circle
              :cx="RING_SIZE / 2"
              :cy="RING_SIZE / 2"
              :r="ringRadius"
              fill="none"
              stroke="url(#wsRing)"
              :stroke-width="ringStroke"
              stroke-linecap="round"
              :stroke-dasharray="ringCircumference"
              :stroke-dashoffset="ringCircumference - ringDash"
              :transform="`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`"
            />
            <text :x="RING_SIZE / 2" :y="RING_SIZE / 2 + RING_SIZE * 0.055" text-anchor="middle" :style="{ fontSize: `${RING_SIZE * 0.3}px`, fontWeight: 600, fill: 'var(--ink-1)' }">
              {{ structurePct }}<tspan :font-size="RING_SIZE * 0.155" :dy="-RING_SIZE * 0.04">%</tspan>
            </text>
          </svg>
          <div class="hm-book-meta">
            <div class="hm-book-lbl">结构进度</div>
            <div class="hm-book-val"><b>{{ boardChapters.length }}</b> 章规划</div>
            <div class="hm-book-sub">{{ boardScenes.length }} 场 · 雪花 {{ snowDone }}/{{ steps.length }}</div>
          </div>
        </div>
      </header>

      <section class="hm-hero">
        <div class="hm-hero-main">
          <div class="hm-hero-bar">
            <span class="hm-eyebrow"><Compass :size="13" /> 此刻 · 继续写作</span>
          </div>
          <template v-if="heroScene">
            <div class="hm-slug">{{ heroSlug }}</div>
            <h2 class="hm-scene">{{ heroTitle }}</h2>
            <div class="hm-gos">
              <div v-for="g in heroGos" :key="g.k" class="hm-gos-row">
                <span class="hm-gos-k" :class="`t-${g.tone}`">{{ g.k }}</span>
                <span class="hm-gos-v">{{ g.v }}</span>
              </div>
            </div>
          </template>
          <template v-else>
            <h2 class="hm-scene">还没规划到具体场景</h2>
            <div class="hm-gos">
              <div class="hm-gos-row">
                <span class="hm-gos-k t-sage">下一步</span>
                <span class="hm-gos-v">把雪花推进到场景列表与场景规划,这里就会出现「此刻该写哪一幕」。</span>
              </div>
            </div>
          </template>
          <div class="hm-hero-actions">
            <button type="button" class="btn btn-accent btn-lg" @click="go('writer-room')">
              <PenLine :size="16" /> 进入写作房间
            </button>
            <button type="button" class="btn btn-ghost btn-lg" @click="go('snowflake-workbench')">
              <Snowflake :size="16" /> 回到构思
            </button>
          </div>
        </div>

        <button type="button" class="hm-resume" title="回到上次中断处" @click="go('writer-room')">
          <span class="hm-resume-tab">{{ heroScene?.chapter_id || "CH —" }}</span>
          <div class="hm-resume-head"><Quote :size="12" /> 上次写到这里</div>
          <div class="hm-resume-body">
            <p>这一场还没有正文——进去写下第一段,它会出现在这里。<span class="hm-caret" /></p>
          </div>
          <div class="hm-resume-foot">
            <span class="hm-resume-words">{{ heroScene?.target_length_band || "篇幅待定" }}</span>
          </div>
        </button>
      </section>

      <section class="home-row">
        <button type="button" class="home-card" @click="go('snowflake-workbench')">
          <div class="home-card-head">
            <div class="home-card-title"><span class="ic"><Snowflake :size="17" /></span> 构思 · 雪花十步</div>
            <span class="home-card-go">打开 <ArrowRight :size="13" /></span>
          </div>
          <div class="home-snow-track">
            <span v-for="tick in snowTicks" :key="tick.key" class="home-snow-tick" :class="`s-${tick.s}`" :title="tick.name" />
          </div>
          <div class="home-snow-now">
            <div>
              <div class="home-snow-now-label">当前焦点</div>
              <div class="home-snow-now-name">{{ snowNow }}</div>
            </div>
            <div class="home-snow-count"><b>{{ snowDone }}</b> <span class="text-muted text-sm">/ {{ steps.length }} 已确认</span></div>
          </div>
        </button>

        <div class="home-card is-static">
          <div class="home-card-head">
            <div class="home-card-title"><span class="ic"><Inbox :size="17" /></span> 待办收件箱</div>
            <button type="button" class="home-card-go home-card-go-btn" @click="go('review')">全部 <ArrowRight :size="13" /></button>
          </div>
          <div class="home-todo-list">
            <div v-if="!todos.length" class="home-todo-empty">
              <CheckCircle :size="18" /> 待办都处理完了,回去继续写吧。
            </div>
            <button
              v-for="todo in todos"
              :key="todo.id"
              type="button"
              class="home-todo"
              title="去待办收件箱处理"
              @click="go('review')"
            >
              <span class="pill text-xs" :class="`pill-${todo.tone}`"><span class="pill-dot" />{{ todo.label }}</span>
              <span class="home-todo-text">{{ todo.title }}</span>
              <span class="home-todo-go"><ArrowRight :size="14" /></span>
            </button>
            <div v-if="todos.length" class="home-todo-foot">
              共 <b>{{ todos.length }}</b> 条速览,到收件箱看全部。
            </div>
          </div>
        </div>
      </section>

      <section v-if="recentChapters.length" class="hm-chaps">
        <div class="hm-chaps-head">
          <div class="hm-chaps-title">最近章节</div>
          <button type="button" class="btn btn-quiet btn-sm" @click="go('manuscripts')">全部章节 <ArrowRight :size="13" /></button>
        </div>
        <div class="hm-chap-track">
          <button
            v-for="chapter in recentChapters"
            :key="chapter.id"
            type="button"
            class="hm-chap"
            :class="[`s-${chapter.s}`, { 'is-active': chapter.active }]"
            @click="go('snowflake-workbench')"
          >
            <div class="hm-chap-top">
              <span class="hm-chap-n">CH {{ chapter.n }}</span>
              <span class="hm-chap-st" :class="`st-${chapter.s}`">{{ HOME_CHAP_ST[chapter.s] || "规划" }}</span>
            </div>
            <div class="hm-chap-t">{{ chapter.t }}</div>
            <div class="hm-chap-bar"><i :style="{ width: chapter.pct + '%' }" /></div>
          </button>
        </div>
      </section>
    </template>
  </div>
</template>
