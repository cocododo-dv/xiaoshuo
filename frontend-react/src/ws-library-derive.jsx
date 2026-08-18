import { LIB_CATS, LIB_ENTRIES } from "./ws-library-data.jsx";

/* global window, LIB_CATS, LIB_ENTRIES */
/* ==========================================================
   Library — 派生层 (selectors)
   单一数据源 + 纯函数。所有视图共享这里推导出的结构：
   · 双向关系（forward links ∪ backlinks）
   · 故事圣经健康度 / 待处理队列 / 最近更新 / 孤立条目
   · 排序比较器
   不持有状态，输入 entries 数组 → 输出派生结构。
   ========================================================== */

/* ---- state classification ---- */
/* 每个条目的 state.label 归入四类，决定它在队列/健康度里的位置 */
const LIB_STATE_BUCKET = {
  "已应用": "done", "已就绪": "done", "已发布": "done", "已批准": "done",
  "学习中": "active",
  "待审核": "pending", "审核中": "pending", "等待": "pending", "草稿": "pending",
};
function libBucket(e) {
  if (!e.state) return "none";
  return LIB_STATE_BUCKET[e.state.label] || "none";
}

/* 队列优先级：越小越靠前 */
const LIB_QUEUE_PRIORITY = { "待审核": 0, "审核中": 1, "学习中": 2, "等待": 3, "草稿": 4 };
/* 队列里给每条目的一句行动召唤 */
const LIB_QUEUE_CTA = {
  "待审核": "等你决定是否应用",
  "审核中": "等你通过审核",
  "学习中": "正在学习中",
  "等待": "排队等待学习",
  "草稿": "尚在撰写 / 未完成",
};

/* ---- recency ranking (updated 文案 → 序数，越小越新) ---- */
const LIB_RECENCY = {
  "现在": 0, "今天": 1, "今晨": 1, "昨天": 2,
  "本周": 3, "三天前": 3, "上周": 6,
  "进行中": 4, "排队中": 5,
};
function libRecency(e) {
  const r = LIB_RECENCY[e.updated];
  return r === undefined ? 8 : r;
}

/* ==========================================================
   关系类型 — 把自由文本的 rel 归入 6 个语义类别。
   每个 link 可显式声明 type（编辑时写入）；否则按关键词推断。
   6 类对齐全局 6 个强调色，图谱/详情/编辑共用同一套语言。
   ========================================================== */
const LIB_REL_TYPES = [
  { id: "kin",      label: "亲缘", icon: "Users",     accent: "rose",
    hint: "血亲 · 师承 · 情感羁绊",
    kw: ["父", "母", "女儿", "儿", "子", "师", "徒", "前任", "夫", "妻", "兄", "弟", "姐", "妹", "亲"] },
  { id: "conflict", label: "对立", icon: "Zap",       accent: "crimson",
    hint: "敌对 · 决裂 · 张力",
    kw: ["对立", "宿敌", "敌", "决裂", "触犯", "威胁", "张力", "推翻", "反目", "仇", "背叛"] },
  { id: "ally",     label: "同盟", icon: "Link",      accent: "sage",
    hint: "搭档 · 援手 · 协作",
    kw: ["搭档", "外援", "协助", "结盟", "同伴", "合作", "协作", "盟", "援"] },
  { id: "place",    label: "处所", icon: "MapPin",    accent: "gold",
    hint: "所在 · 发生地 · 比邻",
    kw: ["工作", "出入", "比邻", "事发", "发生", "行踪", "场景", "来自", "主事", "居", "所在", "地点", "罹难"] },
  { id: "belong",   label: "归属", icon: "Layers",    accent: "slate",
    hint: "执掌 · 卷入 · 隶属",
    kw: ["执掌", "主任", "主体", "经历", "受益", "卷入", "制定", "视角", "服务", "隶属", "成员", "牵连", "记录", "掌"] },
  { id: "source",   label: "源流", icon: "GitBranch", accent: "ink",
    hint: "来源 · 派生 · 佐证（默认）",
    kw: [] },  /* 默认兜底类别 */
];
const LIB_REL_TYPE_BY_ID = LIB_REL_TYPES.reduce((m, t) => { m[t.id] = t; return m; }, {});
const LIB_REL_DEFAULT = LIB_REL_TYPES[LIB_REL_TYPES.length - 1];

/* 解析关系类型：传入 link 对象（优先用显式 type）或裸 rel 字符串 */
function LIB_relType(x) {
  if (x && typeof x === "object") {
    if (x.type && LIB_REL_TYPE_BY_ID[x.type]) return LIB_REL_TYPE_BY_ID[x.type];
    x = x.rel;
  }
  const s = String(x || "");
  for (const t of LIB_REL_TYPES) {
    if (t.kw.some(k => s.includes(k))) return t;
  }
  return LIB_REL_DEFAULT;
}

/* ---- backlinks：谁引用了我 ---- */
/* → { [id]: [{ id, rel, type }] }  (reverse edges, 不含自身已声明的 forward) */
function LIB_buildBacklinks(entries) {
  const back = {};
  entries.forEach(e => {
    (e.links || []).forEach(l => {
      (back[l.id] = back[l.id] || []).push({ id: e.id, rel: l.rel, type: l.type });
    });
  });
  return back;
}

/* 统一关系视图：forward 优先，补上未被镜像的 backlinks。
   返回 [{ id, rel, type, typeId, dir: 'out' | 'in' }]，按目标去重。 */
function LIB_connections(entry, byId, backlinks) {
  if (!entry) return [];
  const seen = new Set();
  const out = [];
  const push = (id, rel, type, dir) => {
    if (!byId[id] || seen.has(id)) return;
    seen.add(id);
    out.push({ id, rel, type, typeId: LIB_relType({ rel, type }).id, dir });
  };
  (entry.links || []).forEach(l => push(l.id, l.rel, l.type, "out"));
  (backlinks[entry.id] || []).forEach(b => push(b.id, b.rel, b.type, "in"));
  return out;
}

/* 把一组 connections 按关系类型分组，保持 LIB_REL_TYPES 的顺序 */
function LIB_groupConnections(conns) {
  const buckets = {};
  (conns || []).forEach(c => { (buckets[c.typeId] = buckets[c.typeId] || []).push(c); });
  return LIB_REL_TYPES
    .map(t => ({ type: t, items: buckets[t.id] || [] }))
    .filter(g => g.items.length);
}

/* 关联总数（含反向，去重） */
function LIB_degree(entry, byId, backlinks) {
  return LIB_connections(entry, byId, backlinks).length;
}

/* ---- chapter helpers ---- */
function LIB_chapOf(s) {
  const m = /CH\s*0*(\d+)/i.exec(s || "");
  return m ? "CH" + String(m[1]).padStart(2, "0") : null;
}
function LIB_isCited(e) {
  return (e.appears || []).some(a => /CH\s*\d/i.test(a));
}

/* ---- 健康度 / 落地页数据 ---- */
function LIB_health(entries) {
  const byId = entries.reduce((m, e) => { m[e.id] = e; return m; }, {});
  const backlinks = LIB_buildBacklinks(entries);

  const total = entries.length;
  const linksN = entries.reduce((n, e) => n + (e.links ? e.links.length : 0), 0);
  const cited = entries.filter(LIB_isCited).length;

  /* 状态桶 */
  const buckets = { done: 0, active: 0, pending: 0, none: 0 };
  entries.forEach(e => { buckets[libBucket(e)]++; });

  /* 待处理队列：pending + active，按优先级 */
  const queue = entries
    .filter(e => { const b = libBucket(e); return b === "pending" || b === "active"; })
    .map(e => ({
      e,
      pr: LIB_QUEUE_PRIORITY[e.state.label] ?? 9,
      cta: LIB_QUEUE_CTA[e.state.label] || "待处理",
    }))
    .sort((a, b) => a.pr - b.pr || libRecency(a.e) - libRecency(b.e));

  /* 最近更新 */
  const recent = entries
    .map(e => ({ e, r: libRecency(e) }))
    .sort((a, b) => a.r - b.r)
    .slice(0, 6)
    .map(x => x.e);

  /* 置顶 */
  const pinned = entries.filter(e => e.pinned);

  /* 孤立条目：零关联（含反向） */
  const isolated = entries.filter(e => LIB_degree(e, byId, backlinks) === 0);

  /* 关系最密集 */
  const mostLinked = entries
    .map(e => ({ e, d: LIB_degree(e, byId, backlinks) }))
    .sort((a, b) => b.d - a.d)
    .slice(0, 5);

  /* 类别分布 */
  const byCat = LIB_CATS.map(c => ({
    cat: c,
    n: entries.filter(e => e.cat === c.id).length,
  }));

  /* 完成度：done / 有状态的条目 */
  const stated = total - buckets.none;
  const readiness = stated ? Math.round((buckets.done / stated) * 100) : 100;

  return {
    total, linksN, cited, buckets, queue, recent, pinned,
    isolated, mostLinked, byCat, readiness, stated,
  };
}

/* ---- 排序比较器 ---- */
const LIB_SORTS = {
  recent: { label: "最近更新", cmp: (a, b) => libRecency(a) - libRecency(b) },
  name:   { label: "名称",     cmp: (a, b) => (a.name || "").localeCompare(b.name || "", "zh") },
  code:   { label: "编号",     cmp: (a, b) => (a.code || "").localeCompare(b.code || "", "zh") },
};
/* 在比较器之上，置顶永远优先 */
function LIB_sortWithPin(items, sortKey) {
  const cmp = (LIB_SORTS[sortKey] || LIB_SORTS.recent).cmp;
  return [...items].sort((a, b) => {
    if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
    return cmp(a, b);
  });
}

/* ---- 状态流转：让待处理队列真正可推进 ----
   每个 (cat, 当前 state.label) → 下一步动作。点击后把 patch 合并进编辑覆盖层，
   条目状态随之改变，队列 / 就绪度 / 状态桶全部实时联动。 */
const LIB_TRANSITIONS = {
  profiles: {
    "待审核": { label: "应用到项目", icon: "Check",   kind: "accent",  patch: { state: { tone: "crimson", label: "已应用" } } },
    "已应用": { label: "取消应用",   icon: "Ban",     kind: "ghost",   patch: { state: { tone: "gold", label: "待审核" } } },
    "草稿":   { label: "学习未完成", icon: "Clock",   kind: "ghost",   disabled: true },
  },
  refs: {
    "等待":   { label: "开始学习",   icon: "Play",    kind: "accent",  patch: { state: { tone: "gold", label: "学习中" }, progress: 0.04 } },
    "学习中": { label: "标记学完",   icon: "Check",   kind: "accent",  patch: { state: { tone: "sage", label: "已就绪" }, progress: 1 } },
    "已就绪": { label: "复学",       icon: "Refresh", kind: "ghost",   patch: { state: { tone: "gold", label: "学习中" }, progress: 0.5 } },
  },
  knowledge: {
    "草稿":   { label: "提交审核",   icon: "UploadCloud", kind: "accent", patch: { state: { tone: "slate", label: "审核中" } } },
    "审核中": { label: "通过审核",   icon: "Check",   kind: "accent",  patch: { state: { tone: "gold", label: "已批准" } } },
    "已批准": { label: "发布",       icon: "UploadCloud", kind: "primary", patch: { state: { tone: "sage", label: "已发布" } } },
    "已发布": { label: "已发布",     icon: "CheckCircle", kind: "ghost", disabled: true },
  },
};
function LIB_nextAction(e) {
  if (!e || !e.state) return null;
  const t = LIB_TRANSITIONS[e.cat];
  return (t && t[e.state.label]) || null;
}

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { LIB_buildBacklinks, LIB_connections, LIB_degree, LIB_chapOf, LIB_isCited, LIB_health, libBucket, libRecency, LIB_SORTS, LIB_sortWithPin, LIB_QUEUE_CTA, LIB_TRANSITIONS, LIB_nextAction, LIB_REL_TYPES, LIB_REL_TYPE_BY_ID, LIB_relType, LIB_groupConnections };
