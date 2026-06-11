import React from "react";

/* global React, window */
/* ==========================================================
   WsWorks — 作品（书）数据层 + 切换 store
   --------------------------------------------------------
   过去整套工作台是写死在单一作品「潮汐档案」上的：侧栏品牌、
   首页 masthead、页面标题、各模块标题都直接绑了书名，所以无法
   切换 / 新建作品。这一层引入一个轻量的「作品」概念：
     · 一份作品列表，任意时刻有一部「当前作品」
     · 当前作品 + 用户新建的作品持久化到 localStorage
     · 一个 subscribe / notify store，让品牌区、首页、页面标题、
       模块标题都跟随当前作品变化
     · 新建作品 = 一部空白书，进入后首页是引导性空状态
   种子作品（tide / salt）始终来自代码，用户新建的作品另存，
   这样既能持久保留新作品，又能在更新种子时立即生效。
   ========================================================== */

const WS_WORKS_LS = "ws_works_created_v1";
const WS_ACTIVE_LS = "ws_active_work_v1";
const WS_PATCH_LS = "ws_works_seed_patch_v1"; // 种子作品的运行时覆写（进度/字数等），持久化

/* ---- 种子作品 ①：潮汐档案（原系统的全部首页数据搬到这里）---- */
const WORK_TIDE = {
  id: "tide",
  title: "潮汐档案",
  genre: "悬疑 · 长篇",
  mark: "汐",
  accent: "crimson",
  sub: "近未来沿海城市的档案修复师林岑，发现旧潮汐记录正被某种规律重写——一部关于记忆与权力的悬疑长篇。",
  greet: "晚上好 · 今晚馆里很安静",
  wordsTotal: 38420, wordsTarget: 120000, chaptersWritten: 7, chaptersTotal: 24,
  wordsToday: 850, wordsTargetDay: 1500, streak: 6,
  home: {
    slug: "CH 08 · SC 03 · 主动场景",
    scene: "夜班修复台 · 二次发现",
    snowNow: "角色背景 · 周岚",
    gos: [
      { k: "目标", tone: "sage", v: "在馆长发现前，独自核对 No.31 的真伪" },
      { k: "阻碍", tone: "gold", v: "馆长晚归，仍在馆中走动" },
      { k: "挫折", tone: "crimson", v: "系统提示「读取异常」，记录开始自我改写" },
    ],
    resume: {
      ch: "08",
      lines: [
        "潮汐表第三页的墨迹还没干透，林岑却已经认出，那不是她昨夜留下的笔迹。",
        "走廊尽头只剩一盏灯。No.31 的编号在屏幕上轻轻跳了一下，像是有人也在另一端，读着同一行字。",
      ],
      sceneWords: 1240, pausedAgo: "3 天前",
    },
    snow: [
      { name: "读者定位", s: "done" }, { name: "一句话", s: "done" }, { name: "一段话", s: "done" },
      { name: "角色摘要", s: "done" }, { name: "一页梗概", s: "done" }, { name: "角色背景", s: "active" },
      { name: "长篇大纲", s: "done" }, { name: "角色全档案", s: "warn" }, { name: "场景列表", s: "done" }, { name: "场景规划", s: "done" },
    ],
    chaps: [
      { n: "04", t: "回声讲堂", s: "approved", pct: 100 },
      { n: "05", t: "夜班指南", s: "review", pct: 80 },
      { n: "06", t: "周岚的钥匙", s: "draft", pct: 88 },
      { n: "07", t: "三号档案箱", s: "draft", pct: 70 },
      { n: "08", t: "返回的潮声", s: "writing", pct: 12, active: true },
    ],
  },
};

/* ---- 种子作品 ②：盐镇来信（用于演示切换 — 另一题材、较早进度）---- */
const WORK_SALT = {
  id: "salt",
  title: "盐镇来信",
  genre: "年代 · 家族",
  mark: "盐",
  accent: "gold",
  sub: "八十年代末，盐场子弟苏怀梅离乡前写下最后一封没寄出的信，牵出三代人围绕一片废弃盐田的隐忍与亏欠——一部缓慢生长的家族长篇。",
  greet: "下午好 · 海风停了，盐场很静",
  wordsTotal: 12600, wordsTarget: 100000, chaptersWritten: 3, chaptersTotal: 20,
  wordsToday: 0, wordsTargetDay: 1200, streak: 0,
  home: {
    slug: "CH 03 · SC 01 · 主动场景",
    scene: "盐田尽头 · 没寄出的信",
    snowNow: "一页梗概 · 三代人的盐",
    gos: [
      { k: "目标", tone: "sage", v: "把信塞进祖父的旧木匣，赶在天亮前离开盐镇" },
      { k: "阻碍", tone: "gold", v: "祖父半夜起身，坐在堂屋没有开灯" },
      { k: "挫折", tone: "crimson", v: "木匣里早已躺着另一封字迹相同的信" },
    ],
    resume: {
      ch: "03",
      lines: [
        "怀梅把信纸对折了三次，折痕压得很重，像是要把那些没说出口的话一并压进去。",
        "堂屋的方向没有声音，可她知道，祖父就坐在那张吱呀作响的藤椅上，等着她走，又怕她真走。",
      ],
      sceneWords: 760, pausedAgo: "昨天",
    },
    snow: [
      { name: "读者定位", s: "done" }, { name: "一句话", s: "done" }, { name: "一段话", s: "active" },
      { name: "角色摘要", s: "done" }, { name: "一页梗概", s: "warn" }, { name: "角色背景", s: "todo" },
      { name: "长篇大纲", s: "todo" }, { name: "角色全档案", s: "todo" }, { name: "场景列表", s: "todo" }, { name: "场景规划", s: "todo" },
    ],
    chaps: [
      { n: "01", t: "盐场的早班", s: "approved", pct: 100 },
      { n: "02", t: "藤椅与旧匣", s: "review", pct: 76 },
      { n: "03", t: "没寄出的信", s: "writing", pct: 34, active: true },
    ],
  },
};

const WS_WORKS_SEED = [WORK_TIDE, WORK_SALT];
const WS_SEED_IDS = new Set(WS_WORKS_SEED.map(w => w.id));

/* 一部空白新作品的模板 */
function wsBlankWork(data) {
  const title = (data.title || "").trim() || "未命名作品";
  return {
    id: "w" + Date.now().toString(36) + Math.floor(Math.random() * 1e3).toString(36),
    title,
    genre: (data.genre || "").trim() || "未定题材",
    mark: data.mark || Array.from(title)[0] || "新",
    accent: data.accent || "slate",
    sub: (data.sub || "").trim(),
    greet: "新的开始 · 从一个念头起步",
    wordsTotal: 0, wordsTarget: Number(data.wordsTarget) || 100000,
    chaptersWritten: 0, chaptersTotal: 0,
    wordsToday: 0, wordsTargetDay: 1000, streak: 0,
    home: { blank: true },
  };
}

/* ---- store ---- */
function wsLoadSeedPatches() {
  try { return JSON.parse(localStorage.getItem(WS_PATCH_LS)) || {}; } catch (e) { return {}; }
}
function wsLoadWorks() {
  const patches = wsLoadSeedPatches();
  const seeds = WS_WORKS_SEED.map(w => (patches[w.id] ? { ...w, ...patches[w.id] } : w));
  try {
    const created = JSON.parse(localStorage.getItem(WS_WORKS_LS));
    if (Array.isArray(created)) {
      const extra = created.filter(w => w && w.id && !WS_SEED_IDS.has(w.id));
      return [...seeds, ...extra];
    }
  } catch (e) {}
  return seeds;
}

let WS_WORKS = wsLoadWorks();
let WS_ACTIVE_ID = (() => {
  try { const id = localStorage.getItem(WS_ACTIVE_LS); if (id && WS_WORKS.some(w => w.id === id)) return id; } catch (e) {}
  return WS_WORKS[0].id;
})();

const wsSubs = new Set();
function wsSave() {
  try {
    const created = WS_WORKS.filter(w => !WS_SEED_IDS.has(w.id));
    localStorage.setItem(WS_WORKS_LS, JSON.stringify(created));
    localStorage.setItem(WS_ACTIVE_LS, WS_ACTIVE_ID);
  } catch (e) {}
}
/* 种子作品的字段覆写需要单独落盘（种子本体始终来自代码）*/
const WS_PATCHABLE = ["wordsTotal", "wordsToday", "wordsTarget", "wordsTargetDay", "chaptersWritten", "chaptersTotal", "streak", "title", "genre", "sub"];
function wsSaveSeedPatch(id, patch) {
  try {
    const all = wsLoadSeedPatches();
    const cur = all[id] || {};
    WS_PATCHABLE.forEach(k => { if (k in patch) cur[k] = patch[k]; });
    all[id] = cur;
    localStorage.setItem(WS_PATCH_LS, JSON.stringify(all));
  } catch (e) {}
}
function wsNotify() {
  wsSubs.forEach(fn => { try { fn(); } catch (e) {} });
  try { window.dispatchEvent(new CustomEvent("ws:work-changed", { detail: WS_ACTIVE_ID })); } catch (e) {}
}

const WsWorks = {
  list: () => WS_WORKS,
  active: () => WS_WORKS.find(w => w.id === WS_ACTIVE_ID) || WS_WORKS[0],
  activeId: () => WS_ACTIVE_ID,
  setActive(id) {
    if (id !== WS_ACTIVE_ID && WS_WORKS.some(w => w.id === id)) { WS_ACTIVE_ID = id; wsSave(); wsNotify(); }
  },
  create(data) {
    const w = wsBlankWork(data || {});
    WS_WORKS = [...WS_WORKS, w];
    WS_ACTIVE_ID = w.id;
    wsSave(); wsNotify();
    return w;
  },
  remove(id) {
    if (WS_WORKS.length <= 1) return;
    if (WS_SEED_IDS.has(id)) return; // 种子作品不可删除（演示基底）
    const victim = WS_WORKS.find(w => w.id === id);
    WS_WORKS = WS_WORKS.filter(w => w.id !== id);
    if (WS_ACTIVE_ID === id) WS_ACTIVE_ID = WS_WORKS[0].id;
    /* 该作品的全部命名空间存储（::id 后缀）连同作品本体进回收站，
       可整体恢复；彻底删除由回收站 purge 完成 */
    try {
      const suffix = "::" + id;
      const doomed = [];
      const keep = {};
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.slice(-suffix.length) === suffix) doomed.push(k);
      }
      doomed.forEach(k => { keep[k.slice(0, -suffix.length)] = localStorage.getItem(k); localStorage.removeItem(k); });
      if (victim && window.WsTrashStore) {
        window.WsTrashStore.push({ kind: "作品", title: `《${victim.title}》· 整部`, payload: { type: "work", work: victim, keys: keep } });
      }
    } catch (e) {}
    wsSave(); wsNotify();
  },
  update(id, patch) {
    WS_WORKS = WS_WORKS.map(w => (w.id === id ? { ...w, ...patch } : w));
    if (WS_SEED_IDS.has(id)) wsSaveSeedPatch(id, patch);
    wsSave(); wsNotify();
  },
  isSeed: (id) => WS_SEED_IDS.has(id),
  /* 从回收站整体恢复一部作品（作品本体 + 全部命名空间键） */
  restoreWork(w, keys) {
    if (!w || !w.id) return false;
    let work = w;
    if (WS_WORKS.some(x => x.id === w.id) || WS_SEED_IDS.has(w.id)) {
      // id 冲突（理论上不会）：重新发号
      work = { ...w, id: "w" + Date.now().toString(36) + Math.floor(Math.random() * 1e3).toString(36) };
    }
    WS_WORKS = [...WS_WORKS, work];
    try { Object.keys(keys || {}).forEach(base => localStorage.setItem(base + "::" + work.id, keys[base])); } catch (e) {}
    wsSave(); wsNotify();
    return true;
  },
  subscribe(fn) { wsSubs.add(fn); return () => wsSubs.delete(fn); },
};

/* ---- per-work storage namespace ----
   Functional isolation: every module persists under a key suffixed with
   the active work id, so edits in one work never leak into another.
   Mock seed data is shared (a fresh work falls back to the same seeds),
   but each work owns its own saved state. 风格参考 stays global and does
   NOT call this — it is intentionally shared across works. */
function wsKey(base) { return base + "::" + WS_ACTIVE_ID; }

/* ---- React hooks ---- */
function useActiveWork() {
  const [, force] = React.useState(0);
  React.useEffect(() => WsWorks.subscribe(() => force(n => n + 1)), []);
  return WsWorks.active();
}
function useWorks() {
  const [, force] = React.useState(0);
  React.useEffect(() => WsWorks.subscribe(() => force(n => n + 1)), []);
  return WsWorks.list();
}

Object.assign(window, { WsWorks, useActiveWork, useWorks, wsKey });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { WsWorks, useActiveWork, useWorks, wsKey };
