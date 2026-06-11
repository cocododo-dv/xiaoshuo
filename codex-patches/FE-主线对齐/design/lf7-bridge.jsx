/* global window */
/* ==========================================================
   lf7-bridge — 控制塔 ↔ 工作台联动桥（P0 深改）
   ----------------------------------------------------------
   解决三个链路断点：
   ① 统一拍板对象：塔里的设定冲突 = 待办收件箱里的同一条
      待裁决事项（lf7PendingCanon → ws-review 实时派生；
      任一侧裁决，另一侧同步消失）。
   ② 拍板动作产物化：塔的「补铺垫 / 补前因 / 裁决偏离」
      不再只是 toast —— onceTask 把可追踪任务投进收件箱。
   ③ 归档写回：第 9 章草稿归档时落进 WsCatalog 单一真相源
      （state: draft），成稿中心 / 流程图 / 主页随之可见。
   持久化按作品隔离（wsKey），事件 lf:bridge-changed。
   ========================================================== */

const LF7_LS = "lf7_bridge_v1";
const lf7Key = () => (window.wsKey ? window.wsKey(LF7_LS) : LF7_LS);
const lf7IsTide = () => { try { return !window.WsWorks || window.WsWorks.activeId() === "tide"; } catch (e) { return true; } };

function lf7Load() { try { return JSON.parse(localStorage.getItem(lf7Key())) || {}; } catch (e) { return {}; } }
function lf7Save(patch) {
  const st = { ...lf7Load(), ...patch };
  try { localStorage.setItem(lf7Key(), JSON.stringify(st)); } catch (e) {}
  try { window.dispatchEvent(new CustomEvent("lf:bridge-changed")); } catch (e) {}
  try { window.dispatchEvent(new CustomEvent("ws:review-changed")); } catch (e) {}
}

const Lf7Bridge = {
  state: lf7Load,
  /* —— 设定裁决：塔或收件箱任一侧统一并锁定 —— */
  ruleCanon(id, value) {
    const st = lf7Load();
    lf7Save({ canonRuled: { ...(st.canonRuled || {}), [id]: { value: value || null, at: Date.now() } } });
  },
  isRuled(id) { return !!((lf7Load().canonRuled || {})[id]); },
  ruled() { return lf7Load().canonRuled || {}; },
  /* —— 归档时新发现的冲突（如 c7「三楼/地下」）跨会话保留 —— */
  addCanonConflict(entry) {
    const st = lf7Load();
    const ex = st.extraCanon || [];
    if (ex.some(c => c.id === entry.id)) return;
    lf7Save({ extraCanon: [...ex, entry] });
  },
  extraCanon() { return lf7Load().extraCanon || []; },
  /* —— 拍板产物化：同一事项只投递一次待办 —— */
  onceTask(key, payload) {
    const st = lf7Load();
    const done = st.tasked || {};
    if (done[key]) return false;
    if (window.rvPush) window.rvPush(payload);
    lf7Save({ tasked: { ...done, [key]: Date.now() } });
    return true;
  },
  /* —— 归档登记 —— */
  isArchived(ch) { return !!((lf7Load().archived || {})[ch]); },
  markArchived(ch) { const st = lf7Load(); lf7Save({ archived: { ...(st.archived || {}), [ch]: Date.now() } }); },
  /* —— 演示闭环复位：撤销第 9 章下发/归档，目录与起草台队列一并清理，可重新走一轮 —— */
  resetLoop9() {
    try {
      if (window.WsCatalog) {
        const chs = window.WsCatalog.get();
        const ch9 = chs.find(c => parseInt(c.n, 10) === 9);
        if (ch9) {
          (ch9.scenes || []).forEach(s => {
            if (!s.sid) return;
            ["scn-run:", "wr-doc:", "wr-notes:"].forEach(p => {
              try { localStorage.removeItem(window.wsKey ? window.wsKey(p + s.sid) : p + s.sid); } catch (e) {}
            });
          });
          window.WsCatalog.set(chs.filter(c => parseInt(c.n, 10) !== 9));
        }
        if (window.scnQueueLoad && window.scnQueueSave) window.scnQueueSave(window.scnQueueLoad().filter(sid => !/^ch09/.test(sid)));
      }
    } catch (e) {}
    const st = lf7Load();
    const archived = { ...(st.archived || {}) };
    delete archived["9"]; delete archived[9];
    lf7Save({ handoff9: null, archived });
  },
};

/* 把已裁决应用到 canon 种子（塔挂载时调用）：
   已裁决 → 锁定 + 钉入；归档新增的冲突（extraCanon）一并并入 */
function lf7ApplyCanon(seed) {
  const ruled = lf7Load().canonRuled || {};
  const extras = (lf7Load().extraCanon || []).filter(x => !seed.some(c => c.id === x.id));
  return [...seed, ...extras].map(c =>
    ruled[c.id] && c.status === "conflict"
      ? { ...c, status: "locked", pinned: true, drift: false, fresh: false }
      : c
  );
}

/* 待裁决设定冲突 —— 待办收件箱的实时派生源（与塔同一事实） */
function lf7PendingCanon() {
  if (!lf7IsTide()) return [];
  const base = window.LF2_CANON || [];
  const ruled = lf7Load().canonRuled || {};
  const extras = (lf7Load().extraCanon || []).filter(x => !base.some(c => c.id === x.id));
  return [...base, ...extras].filter(c => c.status === "conflict" && !ruled[c.id]);
}

/* 塔台化：交接 = 把第 9 章按契约拆成 3 场、入列 AI 起草台（唯一执行器）。
   塔不再直接生成正文 —— 场内质检归起草台，跨章审计归塔。 */
const LF7_CH9_PLAN = {
  id: "ch09", act: "act2", n: "09", title: "登记簿与脚印", state: "writing",
  tension: 0.66, pov: "林岑", time: "D18 · 夜", place: "档案学院 · 地下档案室",
  words: { cur: 0, target: 5200 },
  entry: "林岑借督察随行的名义，再次进入档案学院。",
  exit: "第二组脚印有了主人轮廓，抽屉还没有打开。",
  align: true,
  promise: "第二组脚印终于有了主人轮廓，而 No.31 仍未开口。",
  drama: {
    promise: "第二组脚印终于有了主人轮廓，而 No.31 仍未开口。",
    spine: "控制塔下发交接契约 · AI 起草台逐场起草。",
    arc: "由「单独求证」转向「与周岚被迫同行」。",
    problem: "档案箱里那张旧照片，是谁放进去的？",
    aftertaste: "她把盐钟扣回掌心。",
    ending: "章末留下未开的抽屉。",
    forbidden: "—",
    notes: "由控制塔交接下发：逐场起草完成后回塔做章级审计。",
  },
  threads: [{ name: "第二组脚印", role: "回收" }, { name: "旧照片", role: "新引" }],
  scenes: [
    { title: "借阅登记簿", kind: "主动", state: "todo", contract: ["ho-c1", "ho-c3"], goal: "以督察随行名义换取借阅权限", obstacle: "登记需留实名与年龄（锚点：林岑 28 岁）", turn: "她在年龄栏写下「28」，描深了那个 8" },
    { title: "档案室对峙", kind: "主动", state: "todo", contract: ["ho-c4", "ho-c2", "ho-l1"], goal: "让周岚打开三号档案箱（锚点：地下档案室）", obstacle: "周岚只给看目录，不给开箱", turn: "箱内出现替换件，和一张没有说明的旧照片" },
    { title: "楼梯间 · 三楼转角", kind: "主动", state: "todo", contract: ["ho-l6", "ho-c5", "ho-arc-阿恪"], goal: "核对第二组脚印（到期承诺：逾期回收）", obstacle: "夜班迅查将至", turn: "鞋码比父亲小半号——有人在他之后下过楼" },
  ],
};

function lf7Dispatch9() {
  if (!lf7IsTide() || !window.WsCatalog) return null;
  if (Lf7Bridge.isArchived(9)) return null;
  try {
    const chs = window.WsCatalog.get();
    const i = chs.findIndex(c => parseInt(c.n, 10) === 9);
    const existing = i >= 0 ? chs[i] : null;
    /* 已经下发过 / 已有实质内容的第 9 章不重复覆盖 */
    if (!(existing && existing.state !== "planned")) {
      const plan = { ...LF7_CH9_PLAN, scenes: LF7_CH9_PLAN.scenes.map(s => ({ ...s })) };
      window.WsCatalog.set(i >= 0 ? chs.map((c, j) => (j === i ? plan : c)) : [...chs, plan]);
    }
    /* 入列起草台（唯一执行器）：取回盖戳后的 sid 送进队列 */
    const ch9 = window.WsCatalog.get().find(c => parseInt(c.n, 10) === 9);
    const sids = ch9 ? (ch9.scenes || []).map(s => s.sid).filter(Boolean) : [];
    if (window.scnQueueLoad && window.scnQueueSave) {
      const q = window.scnQueueLoad();
      window.scnQueueSave([...sids.filter(x => !q.includes(x)), ...q]);
    }
    lf7Save({ handoff9: { at: Date.now(), sids } });
    return { sids, ch: 9 };
  } catch (e) { return null; }
}

/* 归档写回：章级审计通过后，第 9 章在目录里置为草稿（进成稿中心待审）。
   若从未下发过（旧路径），退而插入静态演示章。 */
const LF7_CH9 = {
  id: "ch09", act: "act2", n: "09", title: "登记簿与脚印", state: "draft",
  tension: 0.66, pov: "林岑", time: "D18 · 夜", place: "档案学院 · 地下档案室",
  words: { cur: 5230, target: 5200 },
  entry: "林岑借督察随行的名义，再次进入档案学院。",
  exit: "第二组脚印有了主人轮廓，抽屉还没有打开。",
  align: true,
  promise: "第二组脚印终于有了主人轮廓，而 No.31 仍未开口。",
  drama: {
    promise: "第二组脚印终于有了主人轮廓，而 No.31 仍未开口。",
    spine: "AI 按交接契约整章起草，控制塔逐条审计后归档。",
    arc: "由「单独求证」转向「与周岚被迫同行」。",
    problem: "档案箱里那张旧照片，是谁放进去的？",
    aftertaste: "她把盐钟扣回掌心。",
    ending: "章末留下未开的抽屉。",
    forbidden: "—",
    notes: "控制塔归档：偏离「三楼/地下档案室」已裁决并送下一轮交接复核。",
  },
  threads: [{ name: "第二组脚印", role: "回收" }, { name: "旧照片", role: "新引" }],
  scenes: [
    { title: "借阅登记簿", kind: "主动", state: "done", words: 1680, goal: "以督察随行名义换取借阅权限", obstacle: "登记需留实名与年龄", turn: "她在年龄栏写下「28」，描深了那个 8" },
    { title: "档案室对峙", kind: "主动", state: "done", words: 1890, goal: "让周岚打开三号档案箱", obstacle: "周岚只给看目录，不给开箱", turn: "箱内出现替换件，和一张没有说明的旧照片" },
    { title: "楼梯间 · 三楼转角", kind: "主动", state: "done", words: 1660, goal: "核对第二组脚印", obstacle: "夜班巡查将至", turn: "鞋码比父亲小半号——有人在他之后下过楼" },
  ],
};

function lf7ArchiveCh9() {
  if (!lf7IsTide() || !window.WsCatalog) return false;
  if (Lf7Bridge.isArchived(9)) return false;
  try {
    const chs = window.WsCatalog.get();
    const i = chs.findIndex(c => parseInt(c.n, 10) === 9);
    if (i >= 0 && chs[i].state !== "planned") {
      /* 塔台化路径：起草台逐场写完的第 9 章，章级审计通过后置为草稿（进成稿中心待审） */
      window.WsCatalog.set(chs.map((c, j) => (j === i ? {
        ...c, state: "draft", current: false,
        drama: { ...(c.drama || {}), notes: "控制塔章级审计通过后归档；「三楼/地下」漂移已裁决并送下一轮交接复核。" },
      } : c)));
      Lf7Bridge.markArchived(9);
      return true;
    }
    /* 旧路径兑底：从未下发过时插入静态演示章 */
    const next = i >= 0
      ? chs.map((c, j) => (j === i ? { ...LF7_CH9 } : c))
      : [...chs, { ...LF7_CH9 }];
    window.WsCatalog.set(next);
    Lf7Bridge.markArchived(9);
    return true;
  } catch (e) { return false; }
}

Object.assign(window, { Lf7Bridge, lf7ApplyCanon, lf7PendingCanon, lf7ArchiveCh9, lf7Dispatch9 });
