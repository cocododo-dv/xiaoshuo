import React from "react";
import { WsWorks, wsKey } from "./ws-works.jsx";
import { ARR_CHAPTERS } from "./ws-author-data.jsx";
import { apiDelete, apiGet, apiPatch, apiPost } from "./lib/client.js";

/* global window, React, ARR_CHAPTERS */
/* ==========================================================
   WsCatalog — 章节 / 场景单一真相源（per-work）
   ----------------------------------------------------------
   过去章节表在 home / writer / author / manuscripts / palette
   各存一份且互相矛盾。这一层把「全书结构」收敛成一个 store：
     · 数据形状沿用 ws-author-data 的 ARR_CHAPTERS（最完整：
       GMC 场景、戏剧卡、字数预算、张力值）
     · 持久化键沿用作者台已有的 wsKey("arr.chapters")，
       老用户在编排台做过的编辑直接成为全局真相
     · 种子：tide → ARR_CHAPTERS；salt → 内置小种子；
       新建作品 → 空（由写作器引导建第一章）
     · 字数回写：写作器保存正文时按增量更新 场景字数 →
       章节字数 → 作品总字数 / 今日字数（WsWorks）
   场景 id（sid）在首次载入时按 chId + "s" + 序号 确定性补齐，
   与写作器历史上使用的 ch08s3 等 id 兼容。
   ========================================================== */

const CAT_LS = "arr.chapters.v2";            // v2：目录收敛后的新键；旧键由旧版编排台自动写入的陈旧种子，不再读取
const CAT_DAY_LS = "ws_words_today_v1";     // 每日写作字数 { d, n }
const CAT_STREAK_LS = "ws_streak_v1";       // 连续写作天数 { last, streak }，按作品

const catKey = (base) => (wsKey ? wsKey(base) : base);
const catActiveId = () => { try { return WsWorks ? WsWorks.activeId() : "tide"; } catch (e) { return "tide"; } };

/* ---- 种子作品 ②「盐镇来信」的章节种子（ARR 形状的精简版）---- */
const CAT_SALT_CHAPTERS = [
  {
    id: "ch01", act: "act1", n: "01", title: "盐场的早班", state: "approved",
    tension: 0.3, pov: "苏怀梅", time: "D1 · 晨", place: "盐场",
    words: { cur: 5400, target: 5400 },
    entry: "霜降后的第一个早班，怀梅替父亲去盐场点名。",
    exit: "她在工牌箱底摸到一枚早已注销的旧工牌。",
    align: true,
    promise: "盐场的秩序下，藏着这个家从不提起的一段空白。",
    drama: {
      promise: "盐场的秩序下，藏着这个家从不提起的一段空白。",
      spine: "一次替班，让怀梅第一次碰到家史的边缘。",
      arc: "由「替父亲跑腿的女儿」转向「起了疑心的人」。",
      problem: "一枚注销的工牌，为什么还留在箱底？",
      aftertaste: "她把工牌放回去，又拿了出来。",
      ending: "早班结束，海风停了。",
      forbidden: "—", notes: "开篇章：立盐场与家庭秩序。",
    },
    threads: [{ name: "旧工牌", role: "新引" }],
    scenes: [
      { title: "交班 · 盐场点名", kind: "主动", state: "done", goal: "替父亲完成点名", obstacle: "老工人们对她欲言又止", turn: "有人喊错了她的姓" },
      { title: "工牌箱底", kind: "主动", state: "done", goal: "归还钥匙与名册", obstacle: "箱底卡着一枚旧工牌", turn: "工牌的名字被磨掉了" },
      { title: "回家的堤路", kind: "反应", state: "done", goal: "想清楚要不要问父亲", obstacle: "家里从不谈盐场旧事", turn: "她决定先不问" },
    ],
  },
  {
    id: "ch02", act: "act1", n: "02", title: "藤椅与旧匣", state: "review",
    tension: 0.46, pov: "苏怀梅", time: "D3 · 夜", place: "祖屋 · 堂屋",
    words: { cur: 5670, target: 7400 },
    entry: "祖父的藤椅整夜在堂屋里吱呀作响。",
    exit: "她看见祖父把一只旧木匣锁进了床底。",
    align: true,
    promise: "旧木匣是三代人之间没人肯先开口的那句话。",
    drama: {
      promise: "旧木匣是三代人之间没人肯先开口的那句话。",
      spine: "一夜失眠，怀梅看见了这个家藏东西的方式。",
      arc: "由「起疑」转向「确定家里有事瞒她」。",
      problem: "木匣里装的是谁的东西？",
      aftertaste: "藤椅停了，堂屋静得反常。",
      ending: "天亮前她躺回床上，装作什么都没看见。",
      forbidden: "—", notes: "审阅中：注意藤椅声的节奏复现。",
    },
    threads: [{ name: "旧木匣", role: "新引" }, { name: "旧工牌", role: "延续" }],
    scenes: [
      { title: "吱呀声", kind: "反应", state: "done", goal: "弄清祖父为何整夜不睡", obstacle: "堂屋没有开灯", turn: "她听见锁扣的声音" },
      { title: "床底的木匣", kind: "主动", state: "done", goal: "看清祖父藏了什么", obstacle: "地板会响，离堂屋太近", turn: "看见木匣，没看清里面" },
      { title: "装睡", kind: "反应", state: "done", goal: "不让祖父察觉", obstacle: "心跳压不下去", turn: "决定找机会开匣" },
    ],
  },
  {
    id: "ch03", act: "act1", n: "03", title: "没寄出的信", state: "writing",
    tension: 0.62, pov: "苏怀梅", time: "D6 · 凌晨", place: "盐田尽头", current: true,
    words: { cur: 1530, target: 4500 },
    entry: "离乡前夜，怀梅写下那封不打算寄出的信。",
    exit: "（在写）",
    align: true,
    promise: "她以为是告别，其实是把自己写进了家史。",
    drama: {
      promise: "她以为是告别，其实是把自己写进了家史。",
      spine: "把信放进木匣的一夜，三代人的沉默第一次交锋。",
      arc: "由「准备离开的人」转向「被留下的事拽住的人」。",
      problem: "木匣里那封字迹相同的信，是谁写的？",
      aftertaste: "（待写）", ending: "（待写）",
      forbidden: "—", notes: "在写：结尾与第 4 章入口待定。",
    },
    threads: [{ name: "旧木匣", role: "延续" }, { name: "没寄出的信", role: "新引" }],
    scenes: [
      { title: "盐田尽头 · 没寄出的信", kind: "主动", state: "writing", words: 760, goal: "把信塞进祖父的旧木匣，赶在天亮前离开盐镇", obstacle: "祖父半夜起身，坐在堂屋没有开灯", turn: "木匣里早已躺着另一封字迹相同的信" },
      { title: "堂屋的灯", kind: "反应", state: "todo", goal: "面对没开灯的祖父", obstacle: "他先开了口", turn: "（待规划）" },
      { title: "天亮前", kind: "主动", state: "todo", goal: "决定走还是留", obstacle: "车票在口袋里", turn: "（待规划）" },
    ],
  },
];

/* ---- 确定性补齐场景 sid：chId + "s" + 序号（兼容写作器历史 id）---- */
function catStamp(list) {
  return (list || []).map((c) => {
    const used = new Set((c.scenes || []).map(s => s.sid).filter(Boolean));
    let i = 0;
    return {
      ...c,
      scenes: (c.scenes || []).map((s) => {
        if (s.sid) return s;
        i += 1; let sid = c.id + "s" + i;
        while (used.has(sid)) { i += 1; sid = c.id + "s" + i; }
        used.add(sid);
        return { ...s, sid };
      }),
    };
  });
}

function catSeedFor(workId) {
  if (workId === "tide") return (typeof ARR_CHAPTERS !== "undefined" ? ARR_CHAPTERS : ARR_CHAPTERS) || [];
  if (workId === "salt") return CAT_SALT_CHAPTERS;
  return []; // 新建作品：空白结构，由写作器 / 编排台引导建章
}

/* 汇总同步进 WsWorks（切换器 / 主页进度同源）。
   FE-ALIGN P2（D2）：字数/今日/streak 改读后端 writing-stats（只读派生，
   经 WsWorks.__applyDerived 注入，WsWorks.update 的回写路径已删除）；
   chaptersWritten 在目录统一（P3）前仍取本地目录 rollup。 */
function catPushTotals() {
  if (!WsWorks) return;
  const id = catActiveId();
  if (!id || id === "__loading__") return; // 启动占位作品（列表尚未从后端返回）
  const chs = catLoad(id);
  const written = chs.filter(c => ((c.words && c.words.cur) || 0) > 0).length;
  apiGet(`/api/v2/projects/${id}/writing-stats`).then((stats) => {
    if (!stats || !WsWorks.__applyDerived) return;
    const w = WsWorks.list().find(x => x.id === id);
    const next = {
      wordsTotal: stats.words_total || 0,
      wordsToday: stats.words_today || 0,
      streak: stats.streak_days || 0,
      chaptersWritten: written,
    };
    /* 仅在值变化时注入 —— __applyDerived 会广播 ws:work-changed，
       而本函数又监听该事件，无守卫会形成异步自激循环 */
    if (w && (w.wordsTotal !== next.wordsTotal || w.wordsToday !== next.wordsToday
      || w.streak !== next.streak || w.chaptersWritten !== next.chaptersWritten)) {
      WsWorks.__applyDerived(id, next);
    }
  }).catch(() => {
    /* 后端不可达：保持现值（缓存影子），不再做本地回写 */
  });
}

/* ---- store（FE-ALIGN Phase 3：目录真相源 = /api/v2/projects/{id}/catalog）----
   · get() 保持同步：每作品一份内存缓存，启动/切换作品时从 API 填充，
     写后乐观更新 + 端点调用，失败整体重拉（服务端为准）+ 提示。
   · 视图章节/场景形状与原型一致；C4 裁决：反应场景的 RDD 映射进
     goal/obstacle/turn 槽位，附 kindFields 标签元数据。
   · set() 写穿点改为 diff 拆解：字段变化→PATCH，新增→POST，删除→v1 trash，
     排序→v1 scene-order（复用既有逻辑，不另起排序端点）。
   · 一次性迁移：旧 localStorage 目录编辑（arr.chapters.v2::<id>）在后端目录
     为空时经 POST catalog/import 上行，打 ws_catalog_migrated_v1::<id> 标记。 */

const KIND_FIELDS_GCS = ["目标", "阻碍", "挫折"];
const KIND_FIELDS_RDD = ["反应", "两难", "决定"];
const CAT_MIGRATED_LS = "ws_catalog_migrated_v1";

function catFromApiScene(s) {
  const reactive = s.kind === "reactive";
  const b = s.brief || {};
  return {
    sid: s.slug,
    backendId: s.scene_id,
    title: s.title,
    kind: reactive ? "反应" : "主动",
    state: s.state,
    words: s.words || 0,
    goal: reactive ? (b.reaction || "") : (b.goal || ""),
    obstacle: reactive ? (b.dilemma || "") : (b.conflict || ""),
    turn: reactive ? (b.decision || "") : (b.setback || ""),
    kindFields: reactive ? KIND_FIELDS_RDD : KIND_FIELDS_GCS,
  };
}

function catFromApiChapter(c) {
  return {
    id: c.slug,
    backendId: c.chapter_id,
    act: c.act || "act1",
    n: c.no,
    title: c.title,
    state: c.state,
    tension: typeof c.tension === "number" ? c.tension : 0.3,
    pov: c.pov || "",
    time: c.time_label || "",
    place: c.place || "",
    current: !!c.current,
    words: { cur: (c.words && c.words.cur) || 0, target: (c.words && c.words.target) || 0 },
    entry: c.entry || "",
    exit: c.exit || "",
    align: c.align !== false,
    promise: c.promise || "",
    drama: { promise: "", spine: "", arc: "", problem: "", aftertaste: "", ending: "", forbidden: "", notes: "", ...(c.drama || {}) },
    threads: c.threads || [],
    scenes: (c.scenes || []).map(catFromApiScene),
  };
}

/* 章对象 diff → PATCH 载荷（只含变化字段） */
function catChapterPatch(prev, next) {
  const patch = {};
  if (next.title !== prev.title) patch.title = next.title;
  if (next.state !== prev.state) patch.state = next.state;
  const prevTarget = (prev.words && prev.words.target) || 0;
  const nextTarget = (next.words && next.words.target) || 0;
  if (nextTarget !== prevTarget) patch.words_target = nextTarget || null;
  if (next.act !== prev.act) patch.act = next.act;
  if (next.tension !== prev.tension) patch.tension = next.tension;
  if (next.pov !== prev.pov) patch.pov = next.pov;
  if (next.time !== prev.time) patch.time_label = next.time;
  if (next.place !== prev.place) patch.place = next.place;
  if (next.entry !== prev.entry) patch.entry = next.entry;
  if (next.exit !== prev.exit) patch.exit = next.exit;
  if (next.align !== prev.align) patch.align = next.align;
  if (next.promise !== prev.promise) patch.promise = next.promise;
  if (JSON.stringify(next.drama || {}) !== JSON.stringify(prev.drama || {})) patch.drama = next.drama || {};
  if (JSON.stringify(next.threads || []) !== JSON.stringify(prev.threads || [])) patch.threads = next.threads || [];
  if (next.current && !prev.current) patch.current = true;
  return patch;
}

function catScenePatch(prev, next) {
  const patch = {};
  if (next.title !== prev.title) patch.title = next.title;
  if (next.state !== prev.state) patch.state = next.state;
  const reactive = next.kind === "反应";
  if (next.kind !== prev.kind) {
    patch.kind = reactive ? "reactive" : "proactive";
    // 换型时把三个槽位整体写到新键
    patch.brief = reactive
      ? { reaction: next.goal || "", dilemma: next.obstacle || "", decision: next.turn || "" }
      : { goal: next.goal || "", conflict: next.obstacle || "", setback: next.turn || "" };
    return patch;
  }
  const brief = {};
  if (next.goal !== prev.goal) brief[reactive ? "reaction" : "goal"] = next.goal || "";
  if (next.obstacle !== prev.obstacle) brief[reactive ? "dilemma" : "conflict"] = next.obstacle || "";
  if (next.turn !== prev.turn) brief[reactive ? "decision" : "setback"] = next.turn || "";
  if (Object.keys(brief).length) patch.brief = brief;
  return patch;
}

function catSceneCreateBody(s, at) {
  const reactive = s.kind === "反应";
  return {
    title: s.title,
    kind: reactive ? "reactive" : "proactive",
    at,
    state: s.state === "active" ? "writing" : (s.state || "todo"),
    brief: reactive
      ? { reaction: s.goal || "", dilemma: s.obstacle || "", decision: s.turn || "" }
      : { goal: s.goal || "", conflict: s.obstacle || "", setback: s.turn || "" },
  };
}

/* ---- 缓存与装载 ---- */
const catCache = {};       // workId → view chapters
const catReadyMap = {};    // workId → API 已返回
const catSubs = new Set();
const catPendingCreates = {}; // slug/sid → 创建中的 Promise（后端 id 待回填）

function catNotify() { catSubs.forEach(fn => { try { fn(); } catch (e) {} }); }
const catApiBase = (id) => `/api/v2/projects/${id}/catalog`;

function catLoad(workId) { return catCache[workId] || []; }

const catFetching = {};
function catFetch(workId, options) {
  const migrate = !options || options.migrate !== false;
  if (!workId || workId === "__loading__") return Promise.resolve();
  if (catFetching[workId]) return catFetching[workId];
  catFetching[workId] = (async () => {
    try {
      let data = await apiGet(catApiBase(workId));
      let chapters = (data && data.chapters) || [];
      if (migrate && !chapters.length) {
        const imported = await catMigrateLegacy(workId);
        if (imported) {
          data = await apiGet(catApiBase(workId));
          chapters = (data && data.chapters) || [];
        }
      }
      catCache[workId] = chapters.map(catFromApiChapter);
      catReadyMap[workId] = true;
      catNotify();
      catPushTotals();
      try { window.WrDocs && window.WrDocs.hydrateActive && window.WrDocs.hydrateActive(); } catch (e) {}
    } catch (e) {
      console.warn("[WsCatalog] 拉取目录失败:", e);
    } finally {
      delete catFetching[workId];
    }
  })();
  return catFetching[workId];
}

/* 旧 localStorage 目录编辑 → 一次性上行（仅后端目录为空时；import 端点 loopback 免 token） */
async function catMigrateLegacy(workId) {
  try {
    if (localStorage.getItem(CAT_MIGRATED_LS + "::" + workId)) return false;
    const raw = localStorage.getItem(CAT_LS + "::" + workId);
    const parsed = raw ? JSON.parse(raw) : null;
    if (!Array.isArray(parsed) || !parsed.length) {
      localStorage.setItem(CAT_MIGRATED_LS + "::" + workId, new Date().toISOString());
      return false;
    }
    await apiPost(catApiBase(workId) + "/import", { chapters: parsed });
    localStorage.setItem(CAT_MIGRATED_LS + "::" + workId, new Date().toISOString());
    return true;
  } catch (e) {
    console.warn("[WsCatalog] 旧目录迁移失败（保留旧键，下次再试）:", e);
    return false;
  }
}

/* 写失败统一恢复：以服务端为准整体重拉 + 提示 */
function catRecover(error) {
  try { window.alert((error && error.message) || "目录保存失败，已恢复为服务端版本。"); } catch (e) {}
  catFetch(catActiveId(), { migrate: false });
}

/* 后端 id 解析（含等待乐观创建完成） */
async function catBackendChapterId(chId) {
  const find = () => { const c = catLoad(catActiveId()).find(x => x.id === chId); return c && c.backendId; };
  let id = find();
  if (!id && catPendingCreates[chId]) { await catPendingCreates[chId]; id = find(); }
  return id;
}
async function catBackendSceneId(sid) {
  const lookup = () => {
    for (const c of catLoad(catActiveId())) {
      const s = (c.scenes || []).find(x => x.sid === sid);
      if (s) return { scene: s, chapter: c };
    }
    return null;
  };
  let hit = lookup();
  if (hit && !hit.scene.backendId && catPendingCreates[hit.chapter.id]) {
    await catPendingCreates[hit.chapter.id];
    hit = lookup();
  }
  if (hit && !hit.scene.backendId && catPendingCreates[sid]) {
    await catPendingCreates[sid];
    hit = lookup();
  }
  return hit && hit.scene.backendId;
}

function catCreateChapterViaApi(workId, nc) {
  const p = (async () => {
    const result = await apiPost(`${catApiBase(workId)}/chapters`, {
      title: nc.title,
      state: nc.state === "active" ? "writing" : nc.state,
      current: !!nc.current,
      words_target: (nc.words && nc.words.target) || null,
      act: nc.act,
      tension: nc.tension,
      pov: nc.pov,
      time_label: nc.time,
      place: nc.place,
      entry: nc.entry,
      exit: nc.exit,
      align: nc.align,
      promise: nc.promise,
      drama: nc.drama || {},
      threads: nc.threads || [],
      with_scene: false,
    });
    const created = result && result.chapter;
    if (!created) return;
    const mine = catLoad(workId).find(c => c.id === nc.id);
    if (mine) mine.backendId = created.chapter_id;
    for (let i = 0; i < (nc.scenes || []).length; i++) {
      const s = nc.scenes[i];
      const sres = await apiPost(
        `${catApiBase(workId)}/chapters/${created.chapter_id}/scenes`,
        catSceneCreateBody(s, i)
      );
      const mineScene = mine && (mine.scenes || []).find(x => x.sid === s.sid);
      if (mineScene && sres && sres.scene) mineScene.backendId = sres.scene.scene_id;
    }
  })();
  catPendingCreates[nc.id] = p;
  p.finally(() => { delete catPendingCreates[nc.id]; });
  return p;
}

function catCreateSceneViaApi(workId, chId, s, at) {
  const p = (async () => {
    const chapterId = await catBackendChapterId(chId);
    if (!chapterId) return;
    const res = await apiPost(`${catApiBase(workId)}/chapters/${chapterId}/scenes`, catSceneCreateBody(s, at));
    const chapter = catLoad(workId).find(x => x.id === chId);
    const mine = chapter && (chapter.scenes || []).find(x => x.sid === s.sid);
    if (mine && res && res.scene) mine.backendId = res.scene.scene_id;
  })();
  catPendingCreates[s.sid] = p;
  p.finally(() => { delete catPendingCreates[s.sid]; });
  return p;
}

/* set() 写穿点的 diff 拆解（视图层零修改的关键）：乐观缓存已先行，
   这里按差异派发端点调用；任何一步失败 → 整体重拉恢复。 */
async function catDispatchDiff(workId, prev, next) {
  const ops = [];
  const prevById = Object.fromEntries(prev.map(c => [c.id, c]));
  const nextIds = new Set(next.map(c => c.id));
  for (const c of prev) {
    if (!nextIds.has(c.id) && c.backendId) {
      ops.push(() => apiPost("/api/v1/chapters/trash", { chapter_ids: [c.backendId] }));
    }
  }
  for (const nc of next) {
    const pc = prevById[nc.id];
    if (!pc) {
      ops.push(() => catCreateChapterViaApi(workId, nc));
      continue;
    }
    const patch = catChapterPatch(pc, nc);
    if (Object.keys(patch).length) {
      ops.push(async () => {
        const chapterId = await catBackendChapterId(nc.id);
        if (chapterId) await apiPatch(`${catApiBase(workId)}/chapters/${chapterId}`, patch);
      });
    }
    const prevScenes = pc.scenes || [];
    const nextScenes = nc.scenes || [];
    const prevBySid = Object.fromEntries(prevScenes.map(s => [s.sid, s]));
    const nextSids = new Set(nextScenes.map(s => s.sid));
    for (const s of prevScenes) {
      if (!nextSids.has(s.sid) && s.backendId) {
        ops.push(() => apiPost("/api/v1/scenes/trash", { scene_ids: [s.backendId] }));
      }
    }
    nextScenes.forEach((s, index) => {
      const ps = prevBySid[s.sid];
      if (!ps) {
        ops.push(() => catCreateSceneViaApi(workId, nc.id, s, index));
        return;
      }
      const scenePatch = catScenePatch(ps, s);
      if (Object.keys(scenePatch).length) {
        ops.push(async () => {
          const sceneId = await catBackendSceneId(s.sid);
          if (sceneId) await apiPatch(`${catApiBase(workId)}/scenes/${sceneId}`, scenePatch);
        });
      }
    });
    const prevOrder = prevScenes.map(s => s.sid).filter(sid => nextSids.has(sid));
    const nextOrder = nextScenes.map(s => s.sid).filter(sid => prevBySid[sid]);
    if (prevOrder.join("|") !== nextOrder.join("|")) {
      ops.push(async () => {
        const chapterId = await catBackendChapterId(nc.id);
        if (!chapterId) return;
        const sceneIds = [];
        for (const s of nextScenes) {
          const sceneId = await catBackendSceneId(s.sid);
          if (sceneId) sceneIds.push(sceneId);
        }
        if (sceneIds.length) {
          await apiPost(`/api/v1/chapters/${chapterId}/scene-order`, {
            scene_ids: sceneIds,
            last_scene_id: sceneIds[sceneIds.length - 1],
          });
        }
      });
    }
  }
  if (!ops.length) return;
  try {
    for (const op of ops) await op();
    catFetch(workId, { migrate: false }); // 以服务端编号/rollup 收敛
    try { window.dispatchEvent(new CustomEvent("ws:trash-changed")); } catch (e) {}
  } catch (e) {
    catRecover(e);
  }
}

const WsCatalog = {
  get() { return catLoad(catActiveId()); },
  isEmpty() { return this.get().length === 0; },
  /* 目录是否已从后端装载（短暂为空数组时视图可区分 loading / 真空目录） */
  ready() { return !!catReadyMap[catActiveId()]; },
  set(next) {
    const id = catActiveId();
    const prev = catLoad(id);
    catCache[id] = catStamp(Array.isArray(next) ? next : []);
    catNotify();
    catDispatchDiff(id, prev, catCache[id]);
  },
  /* 重置 = 丢弃本地缓存、以服务端为准重拉（demo 作品的种子由后端 seed 维护） */
  reset() {
    const id = catActiveId();
    delete catCache[id];
    catFetch(id, { migrate: false });
    catNotify();
    return this.get();
  },
  /* —— 查找 —— */
  sceneById(sid) {
    for (const c of this.get()) { const s = (c.scenes || []).find(x => x.sid === sid); if (s) return { chapter: c, scene: s, index: c.scenes.indexOf(s) }; }
    return null;
  },
  currentChapter() {
    const chs = this.get();
    return chs.find(c => c.current) || chs.find(c => c.state === "writing") || chs[chs.length - 1] || null;
  },
  writingScene() {
    const chs = this.get();
    const cur = this.currentChapter();
    if (cur) {
      const s = (cur.scenes || []).find(x => x.state === "writing");
      if (s) return { chapter: cur, scene: s, index: cur.scenes.indexOf(s) };
    }
    for (const c of chs) { const s = (c.scenes || []).find(x => x.state === "writing"); if (s) return { chapter: c, scene: s, index: c.scenes.indexOf(s) }; }
    if (cur && cur.scenes && cur.scenes.length) return { chapter: cur, scene: cur.scenes[0], index: 0 };
    return null;
  },
  /* —— 写作器结构操作（经 set() 的 diff 引擎落端点）—— */
  renameScene(chId, sid, title) {
    this.set(this.get().map(c => c.id !== chId ? c : { ...c, scenes: c.scenes.map(s => s.sid === sid ? { ...s, title } : s) }));
  },
  moveScene(chId, from, to) {
    this.set(this.get().map(c => {
      if (c.id !== chId) return c;
      const scenes = c.scenes.slice(); const [m] = scenes.splice(from, 1); scenes.splice(to, 0, m);
      return { ...c, scenes };
    }));
  },
  addScene(chId, title) {
    this.set(this.get().map(c => c.id !== chId ? c : {
      ...c, scenes: [...c.scenes, { title: title || "新场景", kind: "主动", state: "todo", goal: "（本场目标待规划）", obstacle: "", turn: "" }],
    }));
  },
  removeScene(chId, sid) {
    this.set(this.get().map(c => c.id !== chId ? c : { ...c, scenes: c.scenes.filter(s => s.sid !== sid) }));
  },
  /* 从回收站恢复场景；原章节已删时退而插入当前章（P4 切换为后端 restore 端点） */
  restoreScene(chId, scene, index) {
    const chs = this.get();
    let target = chs.find(c => c.id === chId);
    if (!target) { target = this.currentChapter(); if (!target) return false; }
    const at = Math.max(0, Math.min(typeof index === "number" ? index : target.scenes.length, target.scenes.length));
    const restored = { ...scene, backendId: undefined }; // 重新建行（旧行已 trash，P4 接 restore）
    this.set(chs.map(c => c.id !== target.id ? c : {
      ...c, scenes: [...c.scenes.slice(0, at), restored, ...c.scenes.slice(at)],
    }));
    return true;
  },
  addChapter(title) {
    const chs = this.get();
    const n = String(chs.length + 1).padStart(2, "0");
    const id = "ch" + n + (chs.some(c => c.id === "ch" + n) ? "-" + Date.now().toString(36) : "");
    const ch = {
      id, act: "act1", n, title: (title || "").trim() || `第 ${chs.length + 1} 章`, state: "writing",
      tension: 0.3, pov: "", time: "", place: "", current: true,
      words: { cur: 0, target: 4000 },
      entry: "", exit: "", align: true, promise: "",
      drama: { promise: "", spine: "", arc: "", problem: "", aftertaste: "", ending: "", forbidden: "", notes: "" },
      threads: [],
      scenes: [{ title: "开场", kind: "主动", state: "writing", goal: "（本场目标待规划）", obstacle: "", turn: "" }],
    };
    this.set([...chs.map(c => ({ ...c, current: false })), ch]);
    return this.get().find(c => c.id === id);
  },
  /* —— 雪花大纲 → 目录。FE-ALIGN F3：构思已接 v2 工作台——后端闸门全过
     （ready_to_materialize）时走 materialize 主路径（approved scene plans →
     ChapterGoal/SceneCard，成功后目录重拉）；闸门未满足则沿用目录批量建章兜底。 */
  adoptOutline(list) {
    try {
      if (window.SnowSync && window.SnowSync.readyToMaterialize()) {
        const n = (list || []).filter(c => (c.title || "").trim() && !c.title.includes("待补")).length;
        window.SnowSync.materialize().catch(() => {});
        return n; // 乐观计数：物化结果以重拉后的目录为准
      }
    } catch (e) {}
    return this.__adoptByDiff(list);
  },
  __adoptByDiff(list) {
    const cur = this.get();
    const existing = new Set(cur.map(c => (c.title || "").trim()));
    const fresh = (list || []).filter(c => {
      const t = (c.title || "").trim();
      return t && !t.includes("待补") && !existing.has(t);
    });
    if (!fresh.length) return 0;
    const wasEmpty = cur.length === 0;
    const next = cur.slice();
    fresh.forEach((c, i) => {
      const n = String(next.length + 1).padStart(2, "0");
      let id = "ch" + n;
      if (next.some(x => x.id === id)) id = id + "-" + Date.now().toString(36) + i;
      const first = wasEmpty && i === 0;
      const summary = (c.summary || "").trim();
      next.push({
        id, act: "act" + (c.act || 1), n, title: (c.title || "").trim(),
        state: first ? "writing" : "planned",
        tension: c.act === 3 ? 0.7 : c.act === 2 ? 0.5 : 0.3,
        pov: "", time: "", place: "", current: first,
        words: { cur: 0, target: 4000 },
        entry: "", exit: "", align: true,
        promise: summary,
        drama: { promise: summary, spine: c.spine ? `灾难落点 · ${c.spine}` : "", arc: "", problem: "", aftertaste: "", ending: "", forbidden: "", notes: "由雪花大纲采用" },
        threads: [],
        scenes: [{ title: "开场", kind: "主动", state: first ? "writing" : "todo", goal: summary || "（本场目标待规划）", obstacle: "", turn: "" }],
      });
    });
    this.set(next);
    return fresh.length;
  },
  /* —— 字数（写作器自动保存时调用）：本地即时更新；
     权威 rollup 由正文保存响应经 __applyWordsRollup 注入，统计走服务端 —— */
  recordSceneWords(sid, count) {
    const hit = this.sceneById(sid);
    if (!hit) return;
    const delta = count - (hit.scene.words || 0);
    if (!delta) return;
    const id = catActiveId();
    catCache[id] = this.get().map(c => c.id !== hit.chapter.id ? c : {
      ...c,
      words: { ...c.words, cur: Math.max(0, ((c.words && c.words.cur) || 0) + delta) },
      scenes: c.scenes.map(s => s.sid === sid ? { ...s, words: count } : s),
    });
    catNotify();
  },
  totals() {
    const chs = this.get();
    const words = chs.reduce((s, c) => s + ((c.words && c.words.cur) || 0), 0);
    const active = WsWorks ? WsWorks.active() : null;
    return {
      words,
      written: chs.filter(c => ((c.words && c.words.cur) || 0) > 0).length,
      planned: chs.length,
      approved: chs.filter(c => c.state === "approved").length,
      today: (active && active.wordsToday) || 0,
    };
  },
  subscribe(fn) { catSubs.add(fn); return () => catSubs.delete(fn); },
  /* —— FE-ALIGN 内部接缝（非契约面）—— */
  __backendSceneId: catBackendSceneId,
  __applyWordsRollup(sid, rollup) {
    if (!rollup) return;
    const hit = this.sceneById(sid);
    const id = catActiveId();
    if (hit) {
      catCache[id] = this.get().map(c => c.id !== hit.chapter.id ? c : {
        ...c,
        words: { ...c.words, cur: rollup.chapter_words },
        scenes: c.scenes.map(s => s.sid === sid ? { ...s, words: rollup.scene_words } : s),
      });
      catNotify();
    }
    catPushTotals();
  },
  __refresh(workId) { return catFetch(workId || catActiveId(), { migrate: false }); },
};

/* hook：订阅目录 + 作品切换 */
function useCatalogChapters() {
  const [, force] = React.useState(0);
  React.useEffect(() => {
    const bump = () => force(n => n + 1);
    const un = WsCatalog.subscribe(bump);
    window.addEventListener("ws:work-changed", bump);
    return () => { un(); window.removeEventListener("ws:work-changed", bump); };
  }, []);
  return WsCatalog.get();
}

/* 启动 & 切换作品：装载目录 + 同步统计（进度同源） */
try { catFetch(catActiveId()); } catch (e) {}
try { catPushTotals(); } catch (e) {}
window.addEventListener("ws:work-changed", () => {
  try { catFetch(catActiveId()); } catch (e) {}
  try { catPushTotals(); } catch (e) {}
});


/* ==========================================================
   WsTrashStore — 回收站（FE-ALIGN Phase 4：接真后端统一三级列表）
   GET /api/v2/trash?project_id=… = 全局作品桶 + 当前作品的章/场景桶；
   软删端点自动产生条目，push() 退化为「触发刷新」的兼容壳。
   restore/purge 走对应端点；失败由 store 自行提示并以服务端为准刷新。
   ========================================================== */
const trashSubs = new Set();
let trashCache = [];
let trashFetching = null;
const TRASH_KIND_LABEL = { work: "作品", chapter: "章节", scene: "场景" };

function trashNotify() { trashSubs.forEach(fn => { try { fn(); } catch (e) {} }); }

function trashAdapt(item) {
  return {
    id: item.id,
    kind: TRASH_KIND_LABEL[item.kind] || item.kind || "内容",
    title: item.kind === "work" ? `《${item.title}》· 整部` : item.title,
    removedAt: item.removed_at ? (Date.parse(item.removed_at) || Date.now()) : Date.now(),
    restorable: item.restorable !== false,
    payload: { type: item.kind },
  };
}

function trashFetch() {
  if (trashFetching) return trashFetching;
  const id = catActiveId();
  const qs = id && id !== "__loading__" ? `?project_id=${encodeURIComponent(id)}` : "";
  trashFetching = apiGet(`/api/v2/trash${qs}`).then((data) => {
    trashCache = ((data && data.items) || []).map(trashAdapt);
    trashNotify();
  }).catch((e) => {
    console.warn("[WsTrashStore] 拉取回收站失败:", e);
  }).finally(() => { trashFetching = null; });
  return trashFetching;
}

const WsTrashStore = {
  list() { return trashCache; },
  /* 兼容壳：各软删端点已自动产生后端条目，这里只触发刷新（旧调用点无害化） */
  push(item) {
    trashFetch();
    return { id: "pending", removedAt: Date.now(), ...(item || {}) };
  },
  restore(id) {
    apiPost(`/api/v2/trash/${encodeURIComponent(id)}/restore`, {}).then(() => {
      trashFetch();
      if (String(id).startsWith("work:")) {
        if (WsWorks && WsWorks.__refresh) WsWorks.__refresh();
      } else {
        catFetch(catActiveId(), { migrate: false });
      }
    }).catch((e) => {
      try { window.alert((e && e.message) || "恢复失败。"); } catch (e2) {}
      trashFetch();
    });
    return true; // 乐观返回；失败走上面的独立提示
  },
  purge(id) {
    apiDelete(`/api/v2/trash/${encodeURIComponent(id)}`).then(() => {
      trashFetch();
    }).catch((e) => {
      try { window.alert((e && e.message) || "永久删除失败。"); } catch (e2) {}
      trashFetch();
    });
  },
  clear() {
    (async () => {
      for (const it of trashCache.slice()) {
        try { await apiDelete(`/api/v2/trash/${encodeURIComponent(it.id)}`); } catch (e) {}
      }
      trashFetch();
    })();
  },
  subscribe(fn) { trashSubs.add(fn); return () => trashSubs.delete(fn); },
};

try { trashFetch(); } catch (e) {}
window.addEventListener("ws:work-changed", () => { try { trashFetch(); } catch (e) {} });
/* 软删端点完成后的精确刷新信号（WsWorks.remove / 目录删除成功时 dispatch） */
window.addEventListener("ws:trash-changed", () => { try { trashFetch(); } catch (e) {} });

/* ==========================================================
   WsDemoTag — 演示工作台的诚实标识
   场景工作台 / 深改台 / 控制塔目前只接入示例作品的模拟数据，
   头部统一挂这个小标签，避免用户误以为操作会写入自己的目录。
   ========================================================== */
function WsDemoTag({ note }) {
  return (
    <span className="pill pill-gold text-xs" style={{ cursor: "help", flexShrink: 0 }}
      title={note || "演示工作台：展示的是示例数据，这里的操作不会写入你的章节目录。"}>
      <span className="pill-dot" />演示数据
    </span>
  );
}

Object.assign(window, { WsCatalog, useCatalogChapters, WsTrashStore, WsDemoTag });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { WsCatalog, useCatalogChapters, WsTrashStore, WsDemoTag };
