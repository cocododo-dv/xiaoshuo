/* global window */

/* ==========================================================
   章节编排 — 结构常量（状态标签 / 幕框架）。章节真相来自后端目录。
   ========================================================== */

const ARR_ACTS = [
  { id: "act1", n: "卷一", tone: "sage" },
  { id: "act2", n: "卷二", tone: "gold" },
  { id: "act3", n: "卷三", tone: "crimson" },
];


/* 章节状态 */
const ARR_CH_STATE = {
  approved: { tone: "sage",    label: "已批准" },
  review:   { tone: "gold",    label: "审阅中" },
  draft:    { tone: "slate",   label: "草稿"   },
  writing:  { tone: "crimson", label: "进行中" },
  planned:  { tone: "ink",     label: "规划中" },
};

/* 场景生产状态 */
const ARR_SCENE_STATE = {
  done:    { tone: "sage",    label: "已完", dot: "var(--sage)" },
  writing: { tone: "crimson", label: "写中", dot: "var(--crimson)" },
  todo:    { tone: "slate",   label: "待写", dot: "var(--line-3)" },
};

/* 线索角色 */
const ARR_THREAD_ROLE = {
  "承接": { tone: "slate"   },
  "新引": { tone: "crimson" },
  "延续": { tone: "gold"    },
  "收束": { tone: "sage"    },
};

/* 已回收（跨章的历史场景版本）：由后端/本地真实操作填充 */
const ARR_ARCHIVED = [];

Object.assign(window, {
  ARR_ACTS, ARR_CH_STATE, ARR_SCENE_STATE, ARR_THREAD_ROLE, ARR_ARCHIVED,
});

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { ARR_ACTS, ARR_CH_STATE, ARR_SCENE_STATE, ARR_THREAD_ROLE, ARR_ARCHIVED };
