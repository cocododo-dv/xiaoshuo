import React from "react";
import { WsCatalog } from "./ws-catalog.jsx";
import { WsWorks } from "./ws-works.jsx";

/* global React */
/* ==========================================================
   长篇控制塔 v2 — 单一数据源（全书模型 + AI 工作记忆）
   控制塔替 AI 记住整本书，并把"该守住的"装进它写下一章的记忆。
   命名前缀 LF2_ / lf2，避免与旧模块全局冲突。
   ========================================================== */

let LF2_BOOK = {
  title: "潮汐档案",
  genre: "悬疑 · 长篇",
  total: 24,     // 计划章数
  written: 8,    // 已落稿（含正在写的第 8 章）
  now: 8,        // AI 当前所在章
  windowK: 5,    // AI 可靠记得最近 K 章（其余正在淡出上下文）
};
let LF2_NEXT = LF2_BOOK.now + 1;

/* 章节：已写章带真实字数 / 实际张力；计划章只有目标张力。beat = 结构节拍锚点。
   运行时会被 lf2SyncFromCatalog() 用 WsCatalog 的真相覆写（仅潮汐档案）。 */
let LF2_CHAPTERS = [
  { n: 1,  title: "盐钟残片",   words: 5840, pace: 0.30, beat: "开端" },
  { n: 2,  title: "潮汐记录室", words: 6210, pace: 0.42, beat: "触发" },
  { n: 3,  title: "被改写的人", words: 5970, pace: 0.48 },
  { n: 4,  title: "回声讲堂",   words: 5500, pace: 0.44 },
  { n: 5,  title: "夜班指南",   words: 4820, pace: 0.66, beat: "中点" },
  { n: 6,  title: "周岚的钥匙", words: 5180, pace: 0.55 },
  { n: 7,  title: "三号档案箱", words: 4900, pace: 0.72, beat: "情节点一" },
  { n: 8,  title: "返回的潮声", words: 1800, pace: 0.60, current: true },
  { n: 9,  title: "（待写）",   planned: true },
  { n: 10, title: "（待写）",   planned: true },
  { n: 11, title: "（待写）",   planned: true },
  { n: 12, title: "（待写）",   planned: true, beat: "情节点二" },
  { n: 13, title: "（待写）",   planned: true },
  { n: 14, title: "（待写）",   planned: true },
  { n: 15, title: "（待写）",   planned: true },
  { n: 16, title: "（待写）",   planned: true },
  { n: 17, title: "（待写）",   planned: true },
  { n: 18, title: "（待写）",   planned: true, beat: "危机" },
  { n: 19, title: "（待写）",   planned: true },
  { n: 20, title: "（待写）",   planned: true },
  { n: 21, title: "（待写）",   planned: true },
  { n: 22, title: "（待写）",   planned: true, beat: "高潮" },
  { n: 23, title: "（待写）",   planned: true },
  { n: 24, title: "（待写）",   planned: true, beat: "结局" },
];

/* 理想张力曲线（全书 24 章"应当"走势）— 与实际对比即见泄气点 */
const LF2_TARGET = [
  0.28, 0.40, 0.46, 0.52, 0.60, 0.58, 0.70, 0.66,
  0.64, 0.70, 0.69, 0.76, 0.73, 0.78, 0.80, 0.82,
  0.81, 0.90, 0.86, 0.91, 0.93, 0.99, 0.84, 0.62,
];

/* 故事线：在场区段 = [from,to]。最后活跃章远落后于 now 即"停滞"。 */
let LF2_THREADS = [
  { id: "main", name: "主线 · 父亲的真相",   short: "主线",   color: "crimson", segs: [[1, 8]] },
  { id: "sub",  name: "副线 · 档案学院改组", short: "副线",   color: "slate",   segs: [[2, 2], [4, 4]] },
  { id: "anti", name: "对抗线 · 周岚",       short: "对抗线", color: "ink",     segs: [[5, 8]] },
  { id: "love", name: "感情线 · 林岑×阿恪",  short: "感情线", color: "gold",    segs: [[1, 1], [4, 4], [6, 6], [8, 8]] },
];

/* 悬念债 = 对读者的承诺。setup 起飞，payoff 落地；payoff < now 仍 open = 逾期。 */
let LF2_LOOPS = [
  { id: "l1", title: "「No.31」编号到底指什么", setup: 1, payoff: 12, state: "open", pri: "high", pinned: true,
    note: "父亲遗物盐钟上刻的编号，全书核心谜面。" },
  { id: "l2", title: "父亲最后一次值班的录像", setup: 3, payoff: 10, state: "open", pri: "high", pinned: true,
    note: "证明改写发生的关键物证，读者已被明确许诺会看到。" },
  { id: "l6", title: "楼梯间的第二组脚印", setup: 2, payoff: 6, state: "open", pri: "high", pinned: false,
    note: "第 2 章埋下、原计划第 6 章揭晓——已越过当前章仍未回收。" },
  { id: "l3", title: "周岚母亲的来信", setup: 4, payoff: 20, state: "open", pri: "medium", pinned: false,
    note: "可推到结尾区段，作为周岚转向的情感支点。" },
  { id: "l4", title: "档案学院 2011 改组真相", setup: 4, payoff: null, state: "open", pri: "medium", pinned: false,
    note: "尚未排定回收章——副线停滞的根因。" },
  { id: "l5", title: "盐钟铭牌背面的备份单", setup: 1, payoff: 8, state: "closing", pri: "low", pinned: false,
    note: "本章（第 8 章）正在回收。" },
];

/* 连续性风险：drift = 由最近一次 AI 生成引入的矛盾（控制塔重点抓的） */
let LF2_RISKS = [
  { id: "r1", type: "设定", text: "林岑年龄出现两个版本：第 1 章「28 岁」与第 5 章「还在念中学」", ch: 5, sev: "high",   drift: true,
    fix: "林岑年龄统一为 28 岁（以第 1 章为准）", canon: "c1" },
  { id: "r2", type: "设定", text: "盐钟材质前后不一：第 1 章写「铜」，第 7 章写「生铁」", ch: 7, sev: "medium", drift: true,
    fix: "盐钟材质统一为「铜」（以第 1 章为准）", canon: "c2" },
  { id: "r3", type: "时序", text: "第 3 章「三天后」与第 5 章「同一周内」时间线冲突", ch: 5, sev: "medium", drift: false,
    fix: "统一为「案发后第三天」（以第 3 章为准）", canon: "c3" },
  { id: "r4", type: "结构", text: "周岚于第 6 章才正式登场，前五章读者难以建立对手形象", ch: 6, sev: "low", drift: false },
];

/* 设定锚点 — AI 不许自相矛盾的"既定事实"。conflict = 当前有漂移待统一。 */
let LF2_CANON = [
  { id: "c1", subject: "林岑 · 年龄",     value: "28 岁",            source: 1, status: "conflict", drift: true,  conflictCh: 5, conflictText: "第 5 章「还在念中学」与第 1 章「28 岁」冲突", critical: true,  pinned: true },
  { id: "c2", subject: "盐钟 · 材质",     value: "铜",               source: 1, status: "conflict", drift: true,  conflictCh: 7, conflictText: "第 7 章写「生铁」，与第 1 章「铜」冲突", critical: false, pinned: false },
  { id: "c3", subject: "时间线 · 父亲失踪", value: "案发后第三天",     source: 3, status: "conflict", drift: false, conflictCh: 5, conflictText: "第 5 章「同一周内」与第 3 章「三天后」冲突", critical: false, pinned: false },
  { id: "c4", subject: "周岚 · 身份",     value: "档案学院督察",     source: 6, status: "locked",   critical: true,  pinned: true },
  { id: "c5", subject: "No.31 · 含义",    value: "父亲盐钟编号·核心谜面", source: 1, status: "locked", critical: true,  pinned: true },
  { id: "c6", subject: "叙事 · 人称",     value: "第三人称限知（林岑视角）", source: 1, status: "locked", critical: false, pinned: false },
];

/* 人物弧线：沿章节推进的内部状态值（0..1） */
let LF2_ARCS = [
  { name: "林岑", role: "主角", color: "crimson", state: "二次发现 · 0.75 ↑", points: [
    { ch: 1, v: 0.30, label: "守护父亲" }, { ch: 2, v: 0.35 }, { ch: 3, v: 0.40, label: "怀疑出现" },
    { ch: 4, v: 0.45 }, { ch: 5, v: 0.55 }, { ch: 6, v: 0.62 }, { ch: 7, v: 0.70, label: "证据 No.1" },
    { ch: 8, v: 0.75, label: "二次发现", current: true } ] },
  { name: "周岚", role: "对立", color: "slate", state: "被迫接触 · 0.48 ↓", points: [
    { ch: 1, v: 0.80, label: "无瑕" }, { ch: 2, v: 0.78 }, { ch: 3, v: 0.74 }, { ch: 4, v: 0.70 },
    { ch: 5, v: 0.65, label: "微小裂缝" }, { ch: 6, v: 0.58 }, { ch: 7, v: 0.55 },
    { ch: 8, v: 0.48, label: "被迫接触", current: true } ] },
  { name: "阿恪", role: "次要", color: "gold", state: "自第 6 章无成长点", stalledFrom: 6, points: [
    { ch: 1, v: 0.50, label: "搭档" }, { ch: 4, v: 0.55, label: "提示" }, { ch: 6, v: 0.62 },
    { ch: 8, v: 0.62, label: "电话出场", current: true } ] },
];

/* 结构幕：起承转合，每幕 6 章 */
const LF2_ACTS = [
  { id: "qi",    name: "起", sub: "建置", from: 1,  to: 6  },
  { id: "cheng", name: "承", sub: "纠葛", from: 7,  to: 12 },
  { id: "zhuan", name: "转", sub: "升级", from: 13, to: 18 },
  { id: "he",    name: "合", sub: "决战", from: 19, to: 24 },
];

/* ---------- 派生 ---------- */
const lf2Tone = (v) => (v >= 0.72 ? "sage" : v >= 0.55 ? "gold" : "rose");
const lf2ThreadLast = (t) => t.segs.reduce((m, s) => Math.max(m, s[1]), 0);
const lf2ThreadStalled = (t, now) => now - lf2ThreadLast(t) >= 3 && t.id !== "main";

function lf2Derive(loops, canon) {
  const now = LF2_BOOK.now;
  const win = LF2_BOOK.windowK;
  const horizon = now - win + 1; // 早于此章的内容正在淡出 AI 上下文
  const open = loops.filter(l => l.state !== "closed");
  const overdue = open.filter(l => l.payoff != null && l.payoff < now && l.state === "open");
  const unscheduled = open.filter(l => l.payoff == null);
  const stalledThreads = LF2_THREADS.filter(t => lf2ThreadStalled(t, now));
  const driftRisks = LF2_RISKS.filter(r => r.drift);
  const conflicts = canon.filter(c => c.status === "conflict");
  const driftConflicts = conflicts.filter(c => c.drift);
  const pinned = loops.filter(l => l.pinned && l.state !== "closed");

  // AI 记忆：早于视野且未钉入的关键内容 = 可能已被遗忘
  const fading = [];
  open.forEach(l => { if (l.setup < horizon && !l.pinned) fading.push({ kind: "loop", id: l.id, ch: l.setup, text: l.title }); });
  canon.forEach(c => { if (c.source < horizon && !c.pinned && c.critical) fading.push({ kind: "canon", id: c.id, ch: c.source, text: c.subject }); });

  const wordsWritten = LF2_CHAPTERS.filter(c => !c.planned).reduce((a, c) => a + (c.words || 0), 0);
  const writtenPaces = LF2_CHAPTERS.filter(c => !c.planned).map(c => c.pace);
  const tensionHealth = Math.round(
    100 - LF2_CHAPTERS.filter(c => !c.planned).reduce((a, c) => a + Math.max(0, LF2_TARGET[c.n - 1] - c.pace) * 120, 0) / writtenPaces.length
  );
  const arcStalled = LF2_ARCS.filter(a => a.stalledFrom);
  return {
    now, win, horizon,
    progress: { written: LF2_BOOK.written, total: LF2_BOOK.total, words: wordsWritten },
    tensionHealth, open, overdue, unscheduled, stalledThreads, driftRisks, conflicts, driftConflicts, pinned, fading, arcStalled,
  };
}

/* 战情板：六类失控统一排序（漂移/逾期 优先，其后停滞/泄气/弧线）。
   每条都能一键钉入下一章交接。 */
function lf2Issues(d, loops, canon) {
  const out = [];
  canon.filter(c => c.status === "conflict").forEach(c => out.push({
    id: "conf-" + c.id, kind: "conflict",
    tone: c.drift ? "rose" : "gold", icon: c.drift ? "Cpu" : "AlertTriangle",
    label: c.drift ? "AI 漂移" : "连续性冲突",
    title: c.conflictText || `${c.subject} 前后不一`,
    meta: `第 ${c.conflictCh} 章引入${c.fresh ? " · 本轮新发现" : " · 待统一锁定"}`,
    sev: c.drift ? "high" : "medium", fresh: c.fresh,
    action: "统一并锁定", ref: { type: "canon", id: c.id } }));
  LF2_RISKS.filter(r => !r.canon && !r.drift).forEach(r => out.push({
    id: "cont-" + r.id, kind: "continuity", tone: "slate", icon: "ShieldCheck", label: "连续性提示",
    title: r.text, meta: `第 ${r.ch} 章 · 结构 / 时序`, sev: r.sev,
    action: "前往", ref: { type: "risk", id: r.id } }));
  d.overdue.forEach(l => out.push({
    id: "od-" + l.id, kind: "overdue", tone: "rose", icon: "Clock", label: "悬念逾期",
    title: l.title, meta: `第 ${l.setup} 章埋设 · 计划第 ${l.payoff} 章回收 · 已越过现在`, sev: "high",
    action: "钉入交接", ref: { type: "loop", id: l.id } }));
  d.stalledThreads.forEach(t => out.push({
    id: "stall-" + t.id, kind: "stall", tone: "gold", icon: "GitBranch", label: "线索停滞",
    title: t.name, meta: `已 ${d.now - lf2ThreadLast(t)} 章未推进`, sev: "medium",
    action: "钉入交接", ref: { type: "thread", id: t.id } }));
  // 泄气：已写章里实际张力显著低于目标
  LF2_CHAPTERS.filter(c => !c.planned && c.pace < LF2_TARGET[c.n - 1] - 0.05).forEach(c => out.push({
    id: "dip-" + c.n, kind: "dip", tone: "slate", icon: "Activity", label: "张力泄气",
    title: `第 ${c.n} 章实际张力 ${c.pace.toFixed(2)}，低于目标 ${LF2_TARGET[c.n - 1].toFixed(2)}`,
    meta: "中段最易泄气 · 影响下一章基准", sev: "low",
    action: "设为目标", ref: { type: "chapter", id: c.n } }));
  d.arcStalled.forEach(a => out.push({
    id: "arc-" + a.name, kind: "arc", tone: "slate", icon: "Users", label: "人物弧停滞",
    title: `${a.name} ${a.state}`, meta: "角色停止成长，读者会失去投入", sev: "low",
    action: "查看", ref: { type: "arc", id: a.name } }));
  const rank = { high: 0, medium: 1, low: 2 };
  return out.sort((a, b) => rank[a.sev] - rank[b.sev]);
}

/* 下一章交接简报 = AI 写第 N+1 章要装进记忆的长程约束，分"记忆层" */
function lf2Handoff(loops, canon, dropped) {
  const now = LF2_BOOK.now, next = LF2_NEXT;
  const d = lf2Derive(loops, canon);
  const off = dropped || new Set();
  const strata = [];
  const push = (key, title, icon, items) => { if (items.length) strata.push({ key, title, icon, items }); };

  // 1) 设定锚点（不可变 / 待统一）
  push("canon", "设定锚点 · 不可矛盾", "Lock",
    canon.filter(c => c.pinned || c.status === "conflict").map(c => ({
      id: "ho-" + c.id, tone: c.status === "conflict" ? "rose" : "crimson",
      label: c.status === "conflict" ? "统一设定" : "锁定设定",
      text: `${c.subject} = ${c.value}` + (c.status === "conflict" ? `（修正第 ${c.conflictCh} 章漂移）` : ""),
      source: `第 ${c.source} 章确立`, adopted: !off.has("ho-" + c.id) })));

  // 2) 到期 / 临近承诺
  const promises = [...d.overdue, ...d.pinned.filter(l => l.payoff != null && l.payoff >= now && l.payoff - now <= 4 && !d.overdue.includes(l))];
  push("promise", "到期承诺 · 必须回收", "Clock",
    promises.map(l => ({
      id: "ho-" + l.id, tone: l.payoff < now ? "rose" : "gold",
      label: l.payoff < now ? "逾期回收" : "守住承诺",
      text: l.title, source: l.payoff < now ? `第 ${l.setup} 章埋设 · 已逾期` : `计划第 ${l.payoff} 章前回收`,
      adopted: !off.has("ho-" + l.id) })));

  // 3) 推进停滞线索
  push("thread", "待推进 · 别让线索断更", "GitBranch",
    d.stalledThreads.map(t => ({
      id: "ho-" + t.id, tone: "gold", label: "推进线索",
      text: t.name, source: `已 ${now - lf2ThreadLast(t)} 章未触及`, adopted: !off.has("ho-" + t.id) })));

  // 4) 张力目标
  strata.push({ key: "tension", title: "张力目标 · 别泄气", icon: "Activity", items: [{
    id: "ho-tension", tone: "slate", label: "本章张力",
    text: `第 ${next} 章目标张力 ${LF2_TARGET[next - 1].toFixed(2)}`, source: "承上启下 · 维持悬置",
    adopted: !off.has("ho-tension") }] });

  // 5) 人物状态（进入本章时）
  push("arc", "人物状态 · 进入本章", "Users",
    LF2_ARCS.map(a => ({
      id: "ho-arc-" + a.name, tone: a.stalledFrom ? "rose" : "slate",
      label: a.stalledFrom ? "需给成长点" : "保持弧线",
      text: `${a.name} · ${a.state}`, source: a.role, adopted: !off.has("ho-arc-" + a.name) })));

  const all = strata.flatMap(s => s.items);
  const adopted = all.filter(i => i.adopted).length;
  return { next, strata, total: all.length, adopted };
}

const LF2_CLR = {
  crimson: { c: "var(--crimson)", w: "var(--crimson-wash)" },
  slate:   { c: "var(--slate)",   w: "var(--slate-wash)" },
  gold:    { c: "var(--gold)",    w: "var(--gold-wash)" },
  ink:     { c: "var(--ink-2)",   w: "var(--paper-3)" },
  rose:    { c: "var(--rose)",    w: "var(--rose-wash)" },
  sage:    { c: "var(--sage)",    w: "var(--sage-wash)" },
};

Object.assign(window, {
  LF2_BOOK, LF2_NEXT, LF2_CHAPTERS, LF2_TARGET, LF2_THREADS, LF2_LOOPS, LF2_RISKS,
  LF2_CANON, LF2_ARCS, LF2_ACTS, LF2_CLR,
  lf2Tone, lf2ThreadLast, lf2ThreadStalled, lf2Derive, lf2Issues, lf2Handoff,
});

/* ==========================================================
   与 WsCatalog 同步（仅潮汐档案 — 其它作品由 lf6 引导态接管）。
   章节标题 / 字数 / 张力 / 在写状态来自目录单一真相源；
   beat 锚点与理想张力曲线（LF2_TARGET）沿用本文件的结构设定。
   悬念债 / 设定锚点 / 故事线等仍是 tide 的演示数据层。
   ========================================================== */
const LF2_BEATS = { 1: "开端", 2: "触发", 5: "中点", 7: "情节点一", 12: "情节点二", 18: "危机", 22: "高潮", 24: "结局" };
function lf2SyncFromCatalog() {
  try {
    if (!WsCatalog || !WsWorks || WsWorks.activeId() !== "tide") return;
    const cat = WsCatalog.get();
    if (!cat.length) return;
    const total = Math.max(24, cat.length);
    const rows = cat.map((c, i) => {
      const n = i + 1;
      if (c.state === "planned") return { n, title: c.title, planned: true, beat: LF2_BEATS[n] };
      const row = { n, title: c.title, words: (c.words && c.words.cur) || 0, pace: typeof c.tension === "number" ? c.tension : 0.5, beat: LF2_BEATS[n] };
      if (c.current || c.state === "writing") row.current = true;
      return row;
    });
    for (let n = cat.length + 1; n <= total; n++) rows.push({ n, title: "（待写）", planned: true, beat: LF2_BEATS[n] });
    LF2_CHAPTERS = rows;
    const written = rows.filter(r => !r.planned).length;
    const curRow = rows.find(r => r.current);
    LF2_BOOK = { ...LF2_BOOK, total, written, now: curRow ? curRow.n : Math.max(1, written) };
    LF2_NEXT = LF2_BOOK.now + 1;
    Object.assign(window, { LF2_BOOK, LF2_NEXT, LF2_CHAPTERS });
  } catch (e) {}
}
lf2SyncFromCatalog();
window.lf2SyncFromCatalog = lf2SyncFromCatalog;

/* ==========================================================
   FE-ALIGN F4：可视化数据层接后端锚点库（longform/anchors）。
   悬念债(promise) / 设定锚点(fact|trait|setting|timeline) /
   故事线(thread) / 人物弧线(arc) —— FE 形状以 JSON 存 note.fe；
   有锚点的作品以后端为准（tide 由 seed 维护，等于原演示数据），
   无锚点的非 tide 作品清空演示层（lf6 引导态接管）。
   塔内的钉入/排期/回收/锁定经 lf2LoopOp/lf2CanonOp 写回 PATCH。
   ========================================================== */
let LF2_ANCHOR_IDS = {};   // fe id -> anchor_id（写回路由）
let LF2_TOWER_WORK = null; // 已水合且有锚点数据的作品

const lf2ParseFe = (a) => { try { return (JSON.parse(a.note || "{}") || {}).fe || null; } catch (e) { return null; } };

async function lf2SyncFromTower() {
  let workId = null;
  try { workId = WsWorks && WsWorks.activeId(); } catch (e) {}
  if (!workId) return;
  let data = null;
  try {
    const { apiGet } = await import("./lib/client.js");
    data = await apiGet(`/api/v2/projects/${workId}/longform/anchors`);
  } catch (e) { return; }
  const anchors = (data && data.anchors) || [];
  if (!anchors.length) {
    if (workId !== "tide") {
      LF2_LOOPS = []; LF2_CANON = []; LF2_THREADS = []; LF2_ARCS = []; LF2_RISKS = [];
      LF2_TOWER_WORK = null; LF2_ANCHOR_IDS = {};
      lf2PushGlobals();
    }
    return;
  }
  const loops = [], canon = [], threads = [], arcs = [];
  const ids = {};
  anchors.forEach(a => {
    const fe = lf2ParseFe(a);
    if (!fe || !fe.id) return;
    ids[fe.id] = a.anchor_id;
    if (a.kind === "promise") loops.push({ ...fe });
    else if (a.kind === "thread") threads.push({ ...fe });
    else if (a.kind === "arc") arcs.push({ ...fe });
    else canon.push({ ...fe });
  });
  LF2_LOOPS = loops; LF2_CANON = canon; LF2_THREADS = threads; LF2_ARCS = arcs;
  if (workId !== "tide") LF2_RISKS = []; // 演示用结构提示仅属 tide
  LF2_ANCHOR_IDS = ids;
  LF2_TOWER_WORK = workId;
  lf2PushGlobals();
  try { window.dispatchEvent(new CustomEvent("lf2:tower-synced", { detail: workId })); } catch (e) {}
}

function lf2PushGlobals() {
  Object.assign(window, { LF2_LOOPS, LF2_CANON, LF2_THREADS, LF2_ARCS, LF2_RISKS });
}

async function lf2AnchorPatch(feId, fe) {
  const anchorId = LF2_ANCHOR_IDS[feId];
  if (!anchorId || !LF2_TOWER_WORK) return;
  try {
    const { apiPatch } = await import("./lib/client.js");
    await apiPatch(`/api/v2/projects/${LF2_TOWER_WORK}/longform/anchors/${anchorId}`, {
      note: JSON.stringify({ fe }),
    });
  } catch (e) { console.warn("[lf2] 锚点写回失败:", feId, e); }
}

/* 塔内操作写回（视图一行接缝调用；同时改本模块缓存让重挂载读到最新） */
function lf2LoopOp(op, id, arg) {
  const loop = LF2_LOOPS.find(l => l.id === id);
  if (!loop) return;
  if (op === "pin") loop.pinned = !loop.pinned;
  else if (op === "ensurePin") loop.pinned = true;
  else if (op === "schedule") loop.payoff = arg;
  else if (op === "resolve") { loop.state = "closed"; loop.pinned = false; }
  lf2AnchorPatch(id, { id, ...loop });
}
function lf2CanonOp(op, id) {
  const c = LF2_CANON.find(x => x.id === id);
  if (!c) return;
  if (op === "pin") c.pinned = !c.pinned;
  else if (op === "lock") { c.status = "locked"; c.pinned = true; }
  lf2AnchorPatch(id, { id, ...c });
}
const lf2HasTowerData = () => !!LF2_TOWER_WORK && (LF2_LOOPS.length + LF2_CANON.length + LF2_THREADS.length) > 0;

window.addEventListener("ws:work-changed", () => { lf2SyncFromTower(); });
window.addEventListener("hashchange", () => {
  if ((location.hash || "").indexOf("longform") >= 0) lf2SyncFromTower();
});
setTimeout(() => lf2SyncFromTower(), 700); // 启动水合（等 WsWorks 就绪）

Object.assign(window, { lf2SyncFromTower, lf2LoopOp, lf2CanonOp, lf2HasTowerData });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { LF2_BOOK, LF2_NEXT, LF2_CHAPTERS, LF2_TARGET, LF2_THREADS, LF2_LOOPS, LF2_RISKS, LF2_CANON, LF2_ARCS, LF2_ACTS, LF2_CLR, lf2Tone, lf2ThreadLast, lf2ThreadStalled, lf2Derive, lf2Issues, lf2Handoff, lf2SyncFromCatalog };
