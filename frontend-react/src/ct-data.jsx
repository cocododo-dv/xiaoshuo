import React from "react";

/* global React */
/* ==========================================================
   构思控制塔 — 数据模型 (single source of truth for the demo)

   把雪花十步当成一个「可编排的工程系统」：
   · 每一层是一个节点，带状态 / 健康度 / 上下游依赖
   · 03「一段话」里的三灾难 + 道德前提 = 故事脊柱，向下游强绑定
   · 连续性引擎跨层校验数字 / 年龄 / ID / 时间线
   · 统一质量标尺：10 步同一套 5 维评分，可横向比较
   ========================================================== */

/* ---- 五维质量标尺（全系统统一）---- */
const CT_RUBRIC_DIMS = [
  { key: "fractal",   short: "分形一致", q: "展开后回头压缩——上一层的概括是否仍然成立？" },
  { key: "causal",    short: "因果锁链", q: "每个事件是否锁死下一个走向——更难、更贵、更不可逆？" },
  { key: "character", short: "角色驱动", q: "是角色的选择在推动情节，还是你在替角色做决定？" },
  { key: "scenable",  short: "可落场景", q: "拆到最小单元时，每一场都有人想要什么、有什么挡着？" },
  { key: "promise",   short: "读者契约", q: "你承诺给读者的那种快感，这一层是否还在兑现？" },
];

const CT_TRACK = {
  orient:    { label: "定位", color: "var(--slate)",   wash: "var(--slate-wash)" },
  plot:      { label: "情节", color: "var(--crimson)", wash: "var(--crimson-wash)" },
  character: { label: "角色", color: "var(--gold)",    wash: "var(--gold-wash)" },
};

const CT_STATE = {
  approved: { label: "已确认", tone: "sage",   dot: "var(--sage)" },
  stale:    { label: "需复核", tone: "gold",   dot: "var(--gold)" },
  draft:    { label: "待补全", tone: "slate",  dot: "var(--slate)" },
  active:   { label: "进行中", tone: "crimson",dot: "var(--crimson)" },
  empty:    { label: "未开始", tone: "",       dot: "var(--line-3)" },
};

/* ---- 十层节点 ----
   deps  = 直接上游（数据派生自）
   feeds = 直接下游（影响谁）
   bindSpine = 该层是否强绑定故事脊柱（必须复用三灾难）
   gate = 整理成章节结构前的硬性门槛
*/
const CT_LAYERS = [
  { key: "audience",  num: "01", name: "读者定位",   track: "orient",    state: "approved", gate: true,
    deps: [], feeds: ["logline"], bindSpine: false, grow: "锚定目标读者",
    artifact: "25–35 岁文学向悬疑女性读者；要的是「谎言被最亲近的人拆穿」那下胸口发紧。",
    health: { score: 88, dims: { fractal: 90, causal: 78, character: 82, scenable: 70, promise: 96 } } },

  { key: "logline",   num: "02", name: "一句话概括", track: "plot",      state: "approved", gate: true,
    deps: ["audience"], feeds: ["paragraph"], bindSpine: false, grow: "1 句 · ≤40 字",
    artifact: "档案修复师林岑修复旧档时，发现整座城市的灾难记录正被人系统性重写。",
    health: { score: 84, dims: { fractal: 88, causal: 86, character: 80, scenable: 72, promise: 90 } } },

  { key: "paragraph", num: "03", name: "一段话 · 脊柱", track: "plot",   state: "approved", gate: true, isSpine: true,
    deps: ["logline"], feeds: ["characters", "synopsis", "outline", "scenes"], bindSpine: false, grow: "1 句 → 5 句",
    artifact: "五句三幕骨架：三灾难逐级抬高，灾难二把道德前提从「记录即正义」翻成「记录也能是凶器」。",
    health: { score: 91, dims: { fractal: 94, causal: 92, character: 84, scenable: 86, promise: 92 } } },

  { key: "characters",num: "04", name: "角色摘要表", track: "character", state: "approved", gate: false,
    deps: ["paragraph"], feeds: ["synopsis", "backstory", "profile"], bindSpine: true, grow: "每人 1 张表",
    artifact: "林岑（白纸黑字）× 周岚（为活人改写）价值观正面相撞——全书火种。",
    health: { score: 86, dims: { fractal: 88, causal: 80, character: 94, scenable: 78, promise: 84 } } },

  { key: "synopsis",  num: "05", name: "一页梗概",   track: "plot",      state: "approved", gate: false,
    deps: ["paragraph", "characters"], feeds: ["outline"], bindSpine: true, grow: "5 句 → 1 页",
    artifact: "五句各扩一段；T-0317 登记簿墨迹年份异常 → 认出周岚笔迹 → 父亲的名字。",
    health: { score: 82, dims: { fractal: 86, causal: 84, character: 80, scenable: 82, promise: 78 } } },

  { key: "backstory", num: "06", name: "角色背景",   track: "character", state: "stale",   gate: false,
    deps: ["characters"], feeds: ["profile"], bindSpine: false, grow: "每人半页",
    staleReason: "04 角色摘要上周更新了周岚的「价值观」，本层来路需同步复核。",
    artifact: "周岚那年冬天：三十一人遇难，她独自整理档案一周，把「对不起」留在纸上等人认领。",
    health: { score: 71, dims: { fractal: 64, causal: 72, character: 86, scenable: 66, promise: 70 } } },

  { key: "outline",   num: "07", name: "长篇大纲",   track: "plot",      state: "approved", gate: false,
    deps: ["synopsis"], feeds: ["scenes"], bindSpine: true, grow: "1 页 → 4 页",
    artifact: "第一幕 6 章已细化；第二、三幕仍是占位骨架（因果压力评分偏低）。",
    health: { score: 68, dims: { fractal: 72, causal: 54, character: 66, scenable: 70, promise: 74 } } },

  { key: "profile",   num: "08", name: "角色全档案", track: "character", state: "draft",    gate: false,
    deps: ["characters", "backstory"], feeds: ["scenes"], bindSpine: false, grow: "每人完整档案",
    artifact: "周岚四维档案草稿；童年、与岑父关系、第一次改档场景仍空缺。",
    health: { score: 58, dims: { fractal: 60, causal: 56, character: 70, scenable: 50, promise: 54 } } },

  { key: "scenes",    num: "09", name: "场景列表",   track: "plot",      state: "approved", gate: true,
    deps: ["outline", "profile"], feeds: ["planning"], bindSpine: true, grow: "全书拆成场",
    artifact: "S01–S05 已列；S05「找到父亲的名字」= 灾难一，须与脊柱一致。",
    health: { score: 80, dims: { fractal: 82, causal: 84, character: 76, scenable: 90, promise: 72 } } },

  { key: "planning",  num: "10", name: "场景规划",   track: "plot",      state: "approved", gate: true,
    deps: ["scenes"], feeds: ["materialize"], bindSpine: false, grow: "每场 GCS / RDD",
    artifact: "每场画 GCS / RDD 草图；出口「撞见阿恪」喂给下一场，主动→反应顺接。",
    health: { score: 83, dims: { fractal: 80, causal: 86, character: 78, scenable: 92, promise: 74 } } },
];

/* ---- 故事脊柱（单一真相源）----
   三灾难 + 道德前提是全书结构中心。下游 plot 层必须引用它；
   bindings 记录每个灾难「落」在下游哪一层的哪个位置，断了就告警。 */
const CT_SPINE = {
  premiseF: "把真相记下来，就对得起死者",
  premiseT: "对得起死者的，是让活人不必活在谎里",
  flipAt: "灾难二 · 第二幕中点",
  disasters: [
    { id: "灾一", act: "第一幕末", tone: "crimson",
      title: "认出周岚的补写笔迹", effect: "逼林岑入局——无法再假装没看见",
      bindings: [
        { layer: "synopsis", at: "第 2 段", status: "ok" },
        { layer: "outline",  at: "第 6 章 · 高潮", status: "ok" },
        { layer: "scenes",   at: "S05", status: "ok" },
      ] },
    { id: "灾二", act: "第二幕中点", tone: "gold", flip: true,
      title: "父亲死于周岚当年的决定", effect: "道德前提翻转：记录即正义 → 记录也能是凶器",
      bindings: [
        { layer: "synopsis", at: "第 3 段", status: "ok" },
        { layer: "outline",  at: "第 10 章（占位）", status: "weak" },
        { layer: "scenes",   at: "未落场", status: "missing" },
      ] },
    { id: "灾三", act: "第二幕末", tone: "crimson",
      title: "周岚销毁母本、向她摊牌", effect: "逼向终局——公开，还是共谋",
      bindings: [
        { layer: "outline",  at: "第 14 章（占位）", status: "weak" },
        { layer: "scenes",   at: "未落场", status: "missing" },
      ] },
  ],
};

/* ---- 连续性引擎：跨层事实校验 ---- */
const CT_CONTINUITY = [
  { id: "deaths", kind: "数字", icon: "Activity", severity: "high", status: "conflict",
    fact: "那场潮汐的遇难人数",
    values: [
      { layer: "backstory", label: "06 角色背景", val: "三十一人 (31)" },
      { layer: "outline",   label: "07 长篇大纲", val: "三十人 (30)" },
    ],
    note: "06 与 07 数字不一致；09 场景列表灾难规模引用此数，须先统一。" },

  { id: "zhou_age", kind: "年龄", icon: "Users", severity: "low", status: "ok",
    fact: "周岚年龄",
    values: [
      { layer: "characters", label: "04 角色摘要", val: "53" },
      { layer: "profile",    label: "08 角色全档案", val: "53" },
    ],
    note: "两处一致。" },

  { id: "doc_id", kind: "ID", icon: "Tag", severity: "low", status: "ok",
    fact: "潮汐登记簿编号",
    values: [
      { layer: "synopsis", label: "05 一页梗概", val: "T-0317" },
      { layer: "scenes",   label: "09 场景列表 · S01", val: "T-0317" },
    ],
    note: "ID 一致，已锁定。" },

  { id: "first_forge", kind: "时间线", icon: "Clock", severity: "med", status: "unverifiable",
    fact: "周岚第一次改档的年份",
    values: [
      { layer: "profile", label: "08 角色全档案", val: "缺失" },
    ],
    note: "08 仍为草稿，无法与「二十年前那场潮汐」对齐时间线——补全后自动复检。" },

  { id: "lin_age", kind: "年龄", icon: "Users", severity: "low", status: "ok",
    fact: "林岑年龄",
    values: [
      { layer: "characters", label: "04 角色摘要", val: "28" },
      { layer: "backstory",  label: "06 角色背景", val: "28（隐含）" },
    ],
    note: "一致。" },
];

/* ---- 下游：整理成章节结构（materialize）----
   09 场景列表 + 10 场景规划 → ChapterGoal + SceneCard，
   主动场写 Goal/Conflict/Setback，反应场写 Reaction/Dilemma/Decision。 */
const CT_MATERIALIZE = {
  gateLayers: ["audience", "logline", "paragraph", "scenes", "planning"],
  chapters: [
    { id: "CH01", title: "盐钟残片", scenes: [
      { id: "S01", pov: "林岑", form: "proactive", title: "地下修复室 · 收到 T-0317", brief: "目标 确认墨迹年份异常 / 冲突 规程要求上报 / 挫败 笔迹竟是周岚的" },
      { id: "S02", pov: "林岑", form: "proactive", title: "比对台 · 确认补写", brief: "目标 调出相邻年份副本 / 冲突 副本彼此矛盾 / 挫败 改写不止一页" },
    ] },
    { id: "CH02", title: "返回的潮声", scenes: [
      { id: "S03", pov: "林岑", form: "reactive",  title: "回忆 · 周岚教她修复的雨夜", brief: "反应 手抖、反复回想 / 两难 查下去 vs 装没看见 / 决定 先取证" },
      { id: "S04", pov: "林岑", form: "proactive", title: "主任办公室 · 试探周岚", brief: "目标 套出动机 / 冲突 周岚滴水不漏 / 挫败 反被警觉" },
    ] },
    { id: "CH03", title: "三号档案箱", scenes: [
      { id: "S05", pov: "林岑", form: "proactive", title: "深层书库 · 找到父亲的名字", brief: "目标 查清牵涉多深 / 冲突 久留即可疑 / 挫败 撞见阿恪 — 灾难一", spine: "灾一" },
    ] },
  ],
};

/* ---- 派生工具 ---- */
function ctLayer(key) { return CT_LAYERS.find(l => l.key === key); }
function ctLayerName(key) { const l = ctLayer(key); return l ? `${l.num} ${l.name}` : key; }

/* 计算某层被「模拟修改」后的下游影响半径（BFS over feeds） */
function ctBlastRadius(startKey) {
  const out = new Set();
  let frontier = [startKey];
  while (frontier.length) {
    const next = [];
    frontier.forEach(k => {
      const l = ctLayer(k);
      (l ? l.feeds : []).forEach(f => {
        if (f === "materialize") { out.add("materialize"); return; }
        if (!out.has(f)) { out.add(f); next.push(f); }
      });
    });
    frontier = next;
  }
  out.delete(startKey);
  return out;
}

function ctOverallHealth() {
  const s = CT_LAYERS.reduce((a, l) => a + l.health.score, 0);
  return Math.round(s / CT_LAYERS.length);
}
function ctApprovedCount() { return CT_LAYERS.filter(l => l.state === "approved").length; }
function ctContinuityAlerts() { return CT_CONTINUITY.filter(c => c.status === "conflict").length; }
function ctStaleCount() { return CT_LAYERS.filter(l => l.state === "stale").length; }

Object.assign(window, {
  CT_RUBRIC_DIMS, CT_TRACK, CT_STATE, CT_LAYERS, CT_SPINE, CT_CONTINUITY, CT_MATERIALIZE,
  ctLayer, ctLayerName, ctBlastRadius, ctOverallHealth, ctApprovedCount, ctContinuityAlerts, ctStaleCount,
});

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { CT_RUBRIC_DIMS, CT_TRACK, CT_STATE, CT_LAYERS, CT_SPINE, CT_CONTINUITY, CT_MATERIALIZE, ctLayer, ctLayerName, ctBlastRadius, ctOverallHealth, ctApprovedCount, ctContinuityAlerts, ctStaleCount };
