import React from "react";
import { I } from "./icons.jsx";
import { TweakRadio, TweakSection, TweakSlider, TweakToggle } from "./tweaks-panel.jsx";
import { WsCatalog, WsDemoTag } from "./ws-catalog.jsx";
import { scnQueueLoad, scnRunLoad, scnQueueSave, scnReQC, scnRun, scnCreateCards, scnRunSave, scnAdoptToDoc, scnPickList, scnHydrateFromBackend, scnBackendQueueSids } from "./ws-scene-run.jsx";
import { WsWorks } from "./ws-works.jsx";

/* global React, I */
const { useState: useSt8, useEffect: useEf8, useRef: useRef8, useMemo: useMemo8 } = React;

/* ==========================================================
   场景工作台 — Scene Workbench  (refactor v2)
   One-screen closed loop:  流程在上 · 正文居中 · 裁决在下
   ┌──────────┬─────────────────────────────────┬──────────┐
   │ 运行队列  │  Pipeline strip (live)          │ 证据      │
   │          │  ─────────────────────────       │ · 质检    │
   │          │  正文 / 起草过程 (reading stage) │ · 戏剧卡  │
   │          │  ─────────────────────────       │ · 开销    │
   │          │  裁决条 (accept / send-back / dx)│ · 归档    │
   └──────────┴─────────────────────────────────┴──────────┘
   The centre re-skins by the picked scene's state:
     queued → 预检   running → 起草直播   ready → 复核裁决   archived → 定稿
   ========================================================== */

const SC_STAGES = [
  { id: "preflight", name: "预检" },
  { id: "draft",     name: "起草" },
  { id: "qc",        name: "质检" },
  { id: "rewrite",   name: "二改" },
  { id: "verify",    name: "校核" },
  { id: "archive",   name: "归档" },
];

/* ---- Drama-beat tints, used to colour the inline highlights ---- */
const BEAT_META = {
  goal:     { label: "Goal · 目标",     tone: "sage"    },
  conflict: { label: "Conflict · 冲突", tone: "crimson" },
  setback:  { label: "Setback · 挫折",  tone: "gold"    },
  exit:     { label: "Exit · 出口",     tone: "slate"   },
};

/* ===================== Scene content ===================== */

const SC_DATA = {
  q1: {
    n: "CH 08 · SC 03", title: "夜班修复台 · 二次发现", kind: "主动场景",
    state: "running", stageIdx: 3, progress: 0.62, attempt: 4,
    eta: "0:40", elapsed: "1:24", model: "Sonnet → Haiku",
    targetWords: "1800–2000",
    brief: [
      { beat: "goal",     text: "林岑完成最后一片残片的归档，确认夜间值守的秩序。" },
      { beat: "conflict", text: "湿度读数与昨日完全相同——一个本不该出现的巧合。" },
      { beat: "setback",  text: "备份单上的字迹属于已故的父亲。" },
      { beat: "exit",     text: "她合上恒温箱，决定明早调取父亲的旧档。" },
    ],
    draft: [
      { id: "p1", beat: "goal", parts: [{ text: "林岑把今天的最后一片残片放进恒温箱时，馆里的钟已经过了十一点。" }] },
      { id: "p2", parts: [
        { text: "她从来不喜欢这一段时间。十一点之后，老馆的中央空调会进入夜间模式，" },
        { risk: "repeat", sev: "mid", text: "机器声变得安静，安静到", tip: "句式重复率偏高（22%）——「安静，安静到」回响过重" },
        { text: "她能听见自己的手指敲在键盘上的回响。" },
      ]},
      { id: "p3", beat: "conflict", parts: [
        { text: "盐钟箱内壁的湿度计是 47%。她记下来——" },
        { risk: "pace", sev: "mid", text: "和昨天同一时刻完全一样。", tip: "情绪转折偏快：发现异常到警觉之间缺少呼吸" },
      ]},
      { id: "p4", parts: [{ text: "她想，这种不变本来应该让她安心。" }] },
      { id: "p5", beat: "setback", parts: [
        { text: "可备份单背后那行小字，是父亲的笔迹。" },
      ]},
    ],
    metrics: [
      { label: "短句率",   pct: 72, target: 70, val: "72%", tone: "ok" },
      { label: "参考相似", pct: 42, target: 65, val: "0.42", tone: "ok" },
      { label: "句式重复", pct: 22, target: 15, val: "22%", tone: "warn" },
    ],
    alignment: [
      { beat: "goal",     para: "p1", status: "ok",   note: "目标已在首段落点" },
      { beat: "conflict", para: "p3", status: "ok",   note: "冲突在第 3 段引入" },
      { beat: "setback",  para: "p5", status: "warn", note: "挫折出现得偏早" },
      { beat: "exit",     para: null, status: "pend", note: "出口尚未写出" },
    ],
    cost: [
      { k: "起草",  v: "Sonnet · 32s" },
      { k: "质检",  v: "Sonnet · 12s" },
      { k: "二改",  v: "Haiku · 进行中" },
      { k: "Token", v: "28,400", mono: true },
    ],
    attempts: [
      { n: 4, time: "本次 · 进行中", result: "running", tone: "crimson", note: "二次改写中" },
      { n: 3, time: "05-17 22:14", result: "质检阻断", tone: "rose", note: "句式重复 31%",
        cmp: {
          verdict: "句式重复率 31% 超阈值（目标 ≤15%），质检自动阻断并退回改写。",
          metrics: [
            { label: "句式重复", was: "31%", now: "22%", better: true },
            { label: "短句率",   was: "78%", now: "72%", better: true },
            { label: "参考相似", was: "0.40", now: "0.42", better: false },
          ],
          before: { text: "夜里很安静，安静到能听见钟摆，安静到连她的呼吸都被放大。", risk: "「安静，安静到」三连回响" },
          after:  { text: "十一点之后，老馆的中央空调进入夜间模式，机器声变得安静，安静到她能听见自己敲键盘的回响。" },
        } },
      { n: 2, time: "05-17 17:30", result: "作者中断", tone: "gold", note: "节奏不对",
        cmp: { verdict: "作者在起草阶段手动中断：开场推进过快，想保留更多铺垫。" } },
      { n: 1, time: "05-17 09:05", result: "弃稿", tone: "slate", note: "开场偏离戏剧卡",
        cmp: { verdict: "首段未落点 Goal，质检判定偏离戏剧卡，整稿弃用。" } },
    ],
    log: [
      { t: "13:42:08", who: "system", text: "预检通过：戏剧卡 6/6 · 角色 3 · 参考画像 1" },
      { t: "13:42:12", who: "sonnet", text: "起草开始 · 目标 1800–2000 字" },
      { t: "13:42:44", who: "sonnet", text: "起草完成 1850 字 · 用时 32s" },
      { t: "13:42:46", who: "qc",     text: "质检开始 · 6 项检查器" },
      { t: "13:42:52", who: "qc",     text: "通过：戏剧卡对齐 · 参考相似 0.42 · 设定一致" },
      { t: "13:42:52", who: "qc",     text: "风险（中）：情绪转折偏快 · 句式重复 22%" },
      { t: "13:42:53", who: "haiku",  text: "二次改写开始 · 针对 2 项中风险" },
      { t: "13:43:10", who: "haiku",  text: "改写 1/2：拆解「安静，安静到」回响…" },
    ],
  },

  q4: {
    n: "CH 07 · SC 04", title: "亮起来的感应灯", kind: "反应场景",
    state: "ready", stageIdx: 4, progress: 1, attempt: 2,
    eta: null, elapsed: "2:08", model: "Sonnet · 一次通过",
    targetWords: "1600–1800",
    verdict: { qc: "通过", risks: "1 项低风险", align: "戏剧卡 4/4 对齐", words: 1724 },
    brief: [
      { beat: "goal",     text: "林岑想在闭馆前确认走廊尽头那扇门是否被人动过。" },
      { beat: "conflict", text: "门是锁着的，但门缝下透出的光在她离开后熄灭了。" },
      { beat: "setback",  text: "监控录像里，那段时间是一片空白。" },
      { beat: "exit",     text: "她把这件事记进只有自己能看的那本册子。" },
    ],
    draft: [
      { id: "p1", beat: "goal", parts: [
        { text: "闭馆铃响过两遍，林岑没有立刻走。她沿着西侧走廊往里去，鞋底在水磨石上敲出一串不紧不慢的回声，像有人跟在她身后，却始终慢半拍。" },
      ]},
      { id: "p2", parts: [
        { text: "走廊尽头是档案三库的门。白天它总是开着的，此刻却关得严严实实。她伸手按了按，门是锁着的——这本身没什么奇怪。" },
      ]},
      { id: "p3", beat: "conflict", parts: [
        { text: "奇怪的是门缝。门缝下有一道极细的光，暖黄色，是库房里那盏老式白炽灯的颜色。她记得很清楚，下午四点她亲手关掉了那盏灯。" },
      ]},
      { id: "p4", parts: [
        { text: "她站在原地数了十下。数到第七下的时候，那道光灭了。没有脚步声，没有开关的咔哒声，光就那样从门缝里退了出去，像潮水退过沙滩。" },
      ]},
      { id: "p5", beat: "setback", parts: [
        { text: "第二天她调了监控。走廊尽头那一段，从二十一点零四分到二十一点零九分，画面是一片均匀的灰。" },
        { risk: "soft", sev: "low", text: "不是黑，是灰，像有人在镜头前轻轻呵了一口气。", tip: "比喻偏软：可考虑更克制的收尾" },
      ]},
      { id: "p6", beat: "exit", parts: [
        { text: "她没有声张。她把日期、时间、还有那道暖黄色的光，记进了那本只有自己能翻开的小册子里，合上，放回抽屉最底层。" },
      ]},
    ],
    metrics: [
      { label: "短句率",   pct: 64, target: 70, val: "64%", tone: "ok" },
      { label: "参考相似", pct: 38, target: 65, val: "0.38", tone: "ok" },
      { label: "句式重复", pct: 11, target: 15, val: "11%", tone: "ok" },
    ],
    alignment: [
      { beat: "goal",     para: "p1", status: "ok", note: "目标在首段确立" },
      { beat: "conflict", para: "p3", status: "ok", note: "冲突自然引入" },
      { beat: "setback",  para: "p5", status: "ok", note: "挫折落在监控空白" },
      { beat: "exit",     para: "p6", status: "ok", note: "出口与下一场入口对齐" },
    ],
    cost: [
      { k: "起草",  v: "Sonnet · 41s" },
      { k: "质检",  v: "Sonnet · 14s" },
      { k: "校核",  v: "Sonnet · 9s" },
      { k: "Token", v: "31,900", mono: true },
    ],
    attempts: [
      { n: 2, time: "本次 · 待复核", result: "待裁决", tone: "gold", note: "质检通过 · 1 项低风险" },
      { n: 1, time: "05-16 14:20", result: "作者中断", tone: "slate", note: "想换叙事视角",
        cmp: {
          verdict: "作者中断第 1 版：原用全知视角，决定改回林岑限知视角以保留悬念。",
          metrics: [
            { label: "参考相似", was: "0.55", now: "0.38", better: true },
            { label: "句式重复", was: "14%", now: "11%", better: true },
          ],
          before: { text: "档案三库的门后，馆长正借着白炽灯翻看一卷旧磁带——这一点林岑并不知道。", risk: "全知视角泄底" },
          after:  { text: "门缝下有一道极细的光，暖黄色。她记得很清楚，下午四点她亲手关掉了那盏灯。" },
        } },
    ],
    log: [
      { t: "09:01:02", who: "system", text: "预检通过：戏剧卡 6/6 · 角色 2 · 参考画像 1" },
      { t: "09:01:08", who: "sonnet", text: "起草完成 1724 字 · 用时 41s" },
      { t: "09:01:23", who: "qc",     text: "质检通过 · 仅 1 项低风险（比喻偏软）" },
      { t: "09:01:31", who: "sonnet", text: "校核通过 · 出口与 SC 05 入口对齐" },
    ],
  },

  q5: {
    n: "CH 07 · SC 03", title: "三号档案箱 · 终稿", kind: "主动场景",
    state: "archived", stageIdx: 5, progress: 1, attempt: 3,
    eta: null, elapsed: "—", model: "已写回章节场景卡",
    archivedAt: "2026-05-17 09:05",
    draft: [
      { id: "p1", beat: "goal", parts: [{ text: "三号档案箱在地下室待了十一年，今天终于被搬上了修复台。林岑戴上手套，像迎接一位久别的客人。" }] },
      { id: "p2", parts: [{ text: "箱子里没有她预想中的纸张。只有一卷磁带，和一张写着六个数字的便签。" }] },
      { id: "p3", beat: "exit", parts: [{ text: "她把六个数字念了三遍，记住了，然后把便签按原样放了回去。" }] },
    ],
    metrics: [
      { label: "短句率",   pct: 68, target: 70, val: "68%", tone: "ok" },
      { label: "参考相似", pct: 44, target: 65, val: "0.44", tone: "ok" },
      { label: "句式重复", pct: 13, target: 15, val: "13%", tone: "ok" },
    ],
    alignment: [
      { beat: "goal", para: "p1", status: "ok", note: "目标确立" },
      { beat: "exit", para: "p3", status: "ok", note: "出口已对齐" },
    ],
    cost: [
      { k: "字数",  v: "1,690" },
      { k: "尝试",  v: "3 次" },
      { k: "归档",  v: "writer_brief_json" },
    ],
    attempts: [
      { n: 3, time: "05-17 09:05", result: "采纳归档", tone: "sage", note: "定稿写回场景卡" },
      { n: 2, time: "05-16 21:40", result: "退回重写", tone: "gold", note: "结尾六个数字要留白",
        cmp: { verdict: "作者退回第 2 版：结尾把六个数字直接念了出来，要求改成只留悬念。" } },
      { n: 1, time: "05-16 11:02", result: "质检阻断", tone: "rose", note: "信息密度过高",
        cmp: {
          verdict: "质检阻断第 1 版：单段同时引入磁带、便签、数字三件物，信息密度超标。",
          before: { text: "箱子里有一卷磁带、一张写着六个数字的便签、还有半张烧焦的照片和一枚铜钥匙。", risk: "一段四件物" },
          after:  { text: "箱子里没有她预想中的纸张。只有一卷磁带，和一张写着六个数字的便签。" },
        } },
    ],
    log: [],
  },
};

/* queue order + light rows for the not-detailed scenes */
const SC_QUEUE = [
  { id: "q1", state: "running",  progress: 0.62 },
  { id: "q2", state: "queued",   progress: 0, n: "CH 08 · SC 04", title: "馆长出现" },
  { id: "q3", state: "queued",   progress: 0, n: "CH 08 · SC 05", title: "走廊上的回声" },
  { id: "q4", state: "ready",    progress: 1 },
  { id: "q5", state: "archived", progress: 1 },
];

function sceneOf(id) {
  const q = SC_QUEUE.find(x => x.id === id);
  const d = SC_DATA[id];
  if (d) return { id, ...d };
  return { id, ...q, kind: "主动场景", brief: [], draft: [], metrics: [], alignment: [], cost: [], log: [] };
}

const STATE_LABEL = { running: "运行中", queued: "排队", ready: "待复核", archived: "已归档" };
const STATE_TONE  = { running: "crimson", queued: "slate", ready: "gold", archived: "sage" };

/* 「CH 08 · SC 03」→ 历史场景 id ch08s3（跳写作台深改用） */
function scnSidOf(n) {
  const m = /CH\s*(\d+)[^]*SC\s*(\d+)/.exec(n || "");
  return m ? `ch${m[1]}s${parseInt(m[2], 10)}` : null;
}

/* 章节编排「交给 AI」入列：从目录场景卡派生一条队列项 */
function scnFromCatalog(sid) {
  if (!sid || !WsCatalog) return null;
  const hit = WsCatalog.sceneById(sid);
  if (!hit) return null;
  const { chapter: c, scene: s, index } = hit;
  const beats = [];
  if (s.goal) beats.push({ beat: "goal", text: s.goal });
  if (s.obstacle) beats.push({ beat: "conflict", text: s.obstacle });
  if (s.turn) beats.push({ beat: "exit", text: s.turn });
  return {
    id: "cq-" + sid, sid, fromCard: true,
    n: `CH ${c.n} · SC ${String(index + 1).padStart(2, "0")}`,
    title: s.title, kind: (s.kind || "主动") + "场景",
    state: "queued", progress: 0, stageIdx: 0, attempt: 0,
    targetWords: "1500–1800",
    brief: beats, draft: [], metrics: [], alignment: [], cost: [], log: [],
  };
}

/* ============================ Main ============================ */

function WsSceneDemo({ go, t, demo = true }) {
  const tw = t || {};
  /* 初始化：持久化队列（按作品）+ 编排送来的入列请求 + 每场已持久化的运行结果 */
  const initRef = useRef8(null);
  if (!initRef.current) {
    const p = window.__scnEnqueue; window.__scnEnqueue = null;
    const sids = (scnQueueLoad ? scnQueueLoad() : []).slice();
    // 单场（写作台/编排「交给 AI」）与批量（构思物化后「去 AI 起草」）两种入列请求
    const pushFront = (sid) => { if (sid && !sids.includes(sid)) sids.unshift(sid); };
    if (p && Array.isArray(p.sids)) p.sids.slice().reverse().forEach(pushFront);
    if (p && p.sid) pushFront(p.sid);
    const items = sids.map(sid => scnFromCatalog(sid)).filter(Boolean);
    const runs0 = {};
    items.forEach(it => { const r = scnRunLoad ? scnRunLoad(it.sid) : null; if (r) runs0[it.id] = r; });
    if (scnQueueSave) scnQueueSave(items.map(i => i.sid));
    initRef.current = { items, runs0 };
  }
  const [extras, setExtras] = useSt8(initRef.current.items);
  const [runs, setRuns] = useSt8(initRef.current.runs0);
  const [picker, setPicker] = useSt8(false);
  const runSeq = useRef8({});
  const [pickedId, setPicked] = useSt8(() => (initRef.current.items[0] ? initRef.current.items[0].id : (demo ? "q1" : null)));
  const [outcomes, setOutcomes] = useSt8({});           // 演示项 id → "archived"
  const [activeBeat, setActiveBeat] = useSt8(null);     // highlighted beat in draft
  const [logOpen, setLogOpen] = useSt8(false);
  const [compare, setCompare] = useSt8(null);           // attempt object being compared
  const [dxDone, setDxDone] = useSt8(() => ({ ...(window.__sceneDxDone || {}) }));  // scene n → adopted-issue count (深改回传)

  const enqueueSid = (sid) => {
    const it = scnFromCatalog(sid);
    if (!it) return;
    setExtras(x => {
      if (x.some(y => y.id === it.id)) return x;
      const nx = [it, ...x];
      if (scnQueueSave) scnQueueSave(nx.map(i => i.sid));
      return nx;
    });
    const r = scnRunLoad ? scnRunLoad(sid) : null;
    if (r) setRuns(m => ({ ...m, ["cq-" + sid]: r }));
    else if (scnHydrateFromBackend) {
      // 本地无记录：尝试从后端 workbench 恢复既有产出（不覆盖期间跑起来的运行）
      scnHydrateFromBackend(sid)
        .then(hr => { if (hr) { setRuns(m => (m["cq-" + sid] ? m : { ...m, ["cq-" + sid]: hr })); if (scnRunSave) scnRunSave(sid, hr); } })
        .catch(() => {});
    }
    setPicked("cq-" + sid);
  };

  /* FE 补缝：本地没有 scn-run 记录的入列场，从后端 workbench 恢复运行态——
     换浏览器 / 后台完成的运行不再「消失」；已有本地记录或期间跑起来的不覆盖 */
  useEf8(() => {
    if (!scnHydrateFromBackend) return;
    let alive = true;
    (async () => {
      for (const it of initRef.current.items) {
        if (initRef.current.runs0[it.id]) continue;
        let r = null;
        try { r = await scnHydrateFromBackend(it.sid); } catch (e) {}
        if (!alive) return;
        if (!r) continue;
        setRuns(m => (m[it.id] ? m : { ...m, [it.id]: r }));
        if (scnRunSave) scnRunSave(it.sid, r);
      }
    })();
    return () => { alive = false; };
  }, []);

  /* 队列成员的后端恢复（贯通轮遗留 ①）：进过管线的场（scene-run-states）
     并入队列——本地队列在前、后端恢复在后；localStorage 队列由此退化为
     管线真相的读缓存，换浏览器队列成员不再是空的 */
  useEf8(() => {
    if (!scnBackendQueueSids) return;
    let alive = true;
    (async () => {
      let sids = [];
      try { sids = await scnBackendQueueSids(); } catch (e) {}
      if (!alive || !sids.length) return;
      setExtras(prev => {
        const have = new Set(prev.map(i => i.sid));
        const add = sids.filter(sid => !have.has(sid)).map(sid => scnFromCatalog(sid)).filter(Boolean);
        if (!add.length) return prev;
        const nx = [...prev, ...add];
        if (scnQueueSave) scnQueueSave(nx.map(i => i.sid));
        return nx;
      });
      /* 新并入的场恢复运行态；已在初始队列里的由上面的水合 effect 负责 */
      const fresh = sids.filter(sid => !initRef.current.items.some(i => i.sid === sid));
      for (const sid of fresh) {
        const id = "cq-" + sid;
        const local = scnRunLoad ? scnRunLoad(sid) : null;
        if (local) { setRuns(m => (m[id] ? m : { ...m, [id]: local })); continue; }
        if (!scnHydrateFromBackend) continue;
        let hr = null;
        try { hr = await scnHydrateFromBackend(sid); } catch (e) {}
        if (!alive) return;
        if (hr) { setRuns(m => (m[id] ? m : { ...m, [id]: hr })); if (scnRunSave) scnRunSave(sid, hr); }
      }
    })();
    return () => { alive = false; };
  }, []);

  useEf8(() => {
    const onDx = (e) => { const d = e.detail || {}; if (d.n) setDxDone(m => ({ ...m, [d.n]: d.count || 0 })); };
    window.addEventListener("ws:scene-deepdesk-done", onDx);
    const onEnq = (e) => { if ((e.detail || {}).sid) enqueueSid(e.detail.sid); };
    window.addEventListener("ws:scene-enqueue", onEnq);
    return () => { window.removeEventListener("ws:scene-deepdesk-done", onDx); window.removeEventListener("ws:scene-enqueue", onEnq); };
  }, []);

  /* 队列：目录来的场叠加运行态；演示项只在《潮汐档案》呈现 */
  const queue = useMemo8(() => {
    const ext = extras.map(x => {
      const r = runs[x.id];
      return r ? { ...x, state: r.state || "queued", progress: r.state === "running" ? (r.progress || 0) : (r.state === "queued" ? 0 : 1) } : x;
    });
    return demo ? [...ext, ...SC_QUEUE] : ext;
  }, [extras, runs, demo]);
  const sceneOfX = (id) => { const ex = extras.find(x => x.id === id); return ex || sceneOf(id); };

  /* 质检阈值随 Tweaks 即时生效（引擎从 window.__scnQcTh 读） */
  window.__scnQcTh = { short: tw.scnShort || 55, repeat: tw.scnRepeat || 30, long: tw.scnLong || 64 };

  const rawState = queue.find(q => q.id === pickedId)?.state;
  const isCard = !!(extras.find(x => x.id === pickedId));
  const effState = (!isCard && outcomes[pickedId] === "archived") ? "archived" : rawState;
  const scene = useMemo8(() => {
    const base = sceneOfX(pickedId);
    if (!base) return null;
    if (base.fromCard) {
      const r = runs[base.id];
      if (!r) return base;
      /* 阈值变动时对已生成稿实时重算质检（风险标记 / 指标 / 判词） */
      const reqc = (r.state === "ready" || r.state === "archived") && r.draft && scnReQC ? scnReQC(r.draft, base.kind) : null;
      const merged = {
        ...base, ...r, ...(reqc || {}),
        stageIdx: r.state === "running" ? 1 : r.state === "ready" ? 4 : r.state === "archived" ? 5 : 0,
        model: "Claude · 实时起草",
        elapsed: r.state === "running" ? "进行中" : "—",
        eta: r.state === "running" ? "片刻" : null,
        attempt: r.attempt || 1,
      };
      if (r.state === "running") merged.runBanner = { t: "起草进行中", s: `Claude · 第 ${r.attempt || 1} 次尝试 · 整稿返回后过质检` };
      return merged;
    }
    const dx = dxDone[base.n];
    const withDx = dx != null ? { ...base, dxCount: dx } : base;
    return outcomes[pickedId] === "archived" ? { ...withDx, state: "archived", justArchived: true } : withDx;
  }, [pickedId, outcomes, dxDone, extras, runs, tw.scnShort, tw.scnRepeat, tw.scnLong]);

  useEf8(() => { setActiveBeat(null); setLogOpen(rawState === "running" && tw.scnLog !== false); setCompare(null); }, [pickedId]);

  const counts = useMemo8(() => {
    const c = { running: 0, queued: 0, ready: 0, archived: 0 };
    queue.forEach(q => { c[(!extras.some(x => x.id === q.id) && outcomes[q.id] === "archived") ? "archived" : (q.state || "queued")]++; });
    return c;
  }, [outcomes, queue, extras]);

  /* —— 真·运行：起草 / 退回重写（同一条路，带指令） —— */
  const startRun = async (note) => {
    const sc = sceneOfX(pickedId);
    if (!sc || !sc.fromCard) return;
    const id = sc.id;
    const token = (runSeq.current[id] || 0) + 1; runSeq.current[id] = token;
    const attempt = ((runs[id] && runs[id].attempt) || 0) + 1;
    const prevText = runs[id] && runs[id].draft ? runs[id].draft.map(p => p.parts.map(x => x.text).join("")).join("\n") : "";
    const t0 = new Date().toTimeString().slice(0, 8);
    setRuns(m => ({ ...m, [id]: { ...(m[id] || {}), state: "running", progress: 0.06, attempt, error: null, needsCards: false,
      log: [{ t: t0, who: "system", text: `预检通过 · 第 ${attempt} 次尝试${note ? " · 改写指令已附" : ""}` }, { t: t0, who: "sonnet", text: "起草进行中……整稿返回后过质检" }] } }));
    const tick = setInterval(() => setRuns(m => {
      const cur = m[id];
      if (!cur || cur.state !== "running") { clearInterval(tick); return m; }
      return { ...m, [id]: { ...cur, progress: Math.min(0.92, (cur.progress || 0) + 0.045) } };
    }), 700);
    try {
      const res = await scnRun(sc, note, note ? prevText : "");
      clearInterval(tick);
      if (runSeq.current[id] !== token) return;
      setRuns(m => {
        const stamp = new Date().toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
        const prevAtt = ((m[id] && m[id].attempts) || []).map(a => a.time && a.time.startsWith("本次") ? { ...a, time: stamp, result: "退回重写", tone: "slate" } : a);
        const attempts = [{ n: attempt, time: "本次 · 待裁决", result: "待裁决", tone: "gold", note: note ? "按指令改写" : "初稿", cmp: note ? { verdict: "作者改写指令：" + note } : undefined }, ...prevAtt].slice(0, 8);
        const nr = { ...(m[id] || {}), ...res, state: "ready", progress: 1, attempt, attempts, at: Date.now() };
        if (scnRunSave) scnRunSave(sc.sid, nr);
        return { ...m, [id]: nr };
      });
    } catch (e) {
      clearInterval(tick);
      if (runSeq.current[id] !== token) return;
      // Fix C：缺声线/关系卡的阻断带 canCreateCards 标记 → 起草台据此显示「补齐声线卡并重试」
      setRuns(m => ({ ...m, [id]: { ...(m[id] || {}), state: "queued", progress: 0, error: (e && e.message) || "起草失败，请重试", needsCards: !!(e && e.canCreateCards) } }));
    }
  };
  // Fix C：一键补齐缺失的最小声线/关系卡(active)解阻预检，成功后自动续跑起草
  const createCards = async () => {
    const sc = sceneOfX(pickedId);
    if (!sc || !sc.fromCard) return;
    const id = sc.id;
    const t0 = new Date().toTimeString().slice(0, 8);
    setRuns(m => ({ ...m, [id]: { ...(m[id] || {}), state: "running", progress: 0.04, error: null, needsCards: false,
      log: [{ t: t0, who: "system", text: "正在补齐最小声线/关系卡……" }] } }));
    try {
      const res = await scnCreateCards(sc.sid);
      const made = ((res && res.created) || []).map(c => c.dependency_type).join("、") || "(已就绪)";
      setRuns(m => ({ ...m, [id]: { ...(m[id] || {}), log: [...((m[id] || {}).log || []), { t: new Date().toTimeString().slice(0, 8), who: "system", text: `已补齐：${made} · 自动续跑起草` }] } }));
      await startRun("");
    } catch (e) {
      setRuns(m => ({ ...m, [id]: { ...(m[id] || {}), state: "queued", progress: 0, error: (e && e.message) || "补齐声线卡失败，请重试", needsCards: false } }));
    }
  };
  const abortRun = () => {
    const sc = sceneOfX(pickedId);
    if (!sc || !sc.fromCard) return;
    runSeq.current[sc.id] = (runSeq.current[sc.id] || 0) + 1;
    setRuns(m => ({ ...m, [sc.id]: { ...(m[sc.id] || {}), state: "queued", progress: 0, error: "已中止 · 本次返回的结果将被丢弃" } }));
  };

  const onArchive = () => {
    const sc = sceneOfX(pickedId);
    if (sc && sc.fromCard) {
      const r = runs[sc.id];
      if (!r || !r.draft || r.state !== "ready") return;
      const res = scnAdoptToDoc(sc.sid, r.draft);
      if (!res.ok) { if (res.reason && res.reason !== "已取消") window.alert("归档失败：" + res.reason); return; }
      const nr = { ...r, state: "archived", justArchived: true, archivedAt: new Date().toLocaleString("zh-CN") };
      setRuns(m => ({ ...m, [sc.id]: nr }));
      if (scnRunSave) scnRunSave(sc.sid, nr);
      return;
    }
    setOutcomes(o => ({ ...o, [pickedId]: "archived" }));
  };

  /* 空队列（非演示作品）：引导入列 */
  if (!queue.length || !scene) {
    return (
      <div className="scn2" data-screen-label="scene" data-density={tw.scnDensity || "cozy"} style={{ "--scn-font": (tw.scnFont || 16) + "px" }}>
        <div style={{ gridColumn: "1 / -1", display: "grid", placeItems: "center", minHeight: "70vh", textAlign: "center" }}>
          <div style={{ maxWidth: 440, display: "grid", gap: 14, justifyItems: "center" }}>
            <I.Play size={26} style={{ color: "var(--ink-3)" }} />
            <div style={{ fontFamily: "var(--font-serif)", fontSize: 21, color: "var(--ink-1)" }}>运行队列还是空的</div>
            <p style={{ color: "var(--ink-3)", fontSize: 13.5, lineHeight: 1.9, margin: 0 }}>从章节目录挑一场入列，AI 会按场景卡（目标 / 阻碍 / 转折）和雪花构思起草，过质检后由你裁决。</p>
            <button className="btn btn-accent" onClick={() => setPicker(true)}><I.Plus size={14} /> 加入场景</button>
          </div>
        </div>
        {picker && <ScenePicker queued={extras.map(x => x.sid)} onPick={(sid) => { enqueueSid(sid); setPicker(false); }} onClose={() => setPicker(false)} />}
      </div>
    );
  }

  return (
    <div className="scn2" data-screen-label="scene"
      data-density={tw.scnDensity || "cozy"}
      data-beats={tw.scnBeats === false ? "off" : "on"}
      style={{ "--scn-font": (tw.scnFont || 16) + "px" }}>
      <SceneQueue
        queue={queue} sceneOfX={sceneOfX} demo={demo}
        pickedId={pickedId} setPicked={setPicked} counts={counts} outcomes={outcomes} dxDone={dxDone}
        onAdd={() => setPicker(true)}
      />

      <section className="scn2-stage" key={pickedId}>
        <SceneHead scene={scene} state={effState} onAbort={scene.fromCard ? abortRun : null} onRerun={scene.fromCard ? () => startRun("") : null} />
        <Pipeline scene={scene} state={effState} />
        <div className="scn2-stage-body">
          {effState === "queued"   && <Preflight scene={scene} />}
          {effState === "running"  && <RunningStage scene={scene} activeBeat={activeBeat} setActiveBeat={setActiveBeat} logOpen={logOpen} setLogOpen={setLogOpen} />}
          {effState === "ready"    && <ReviewStage scene={scene} activeBeat={activeBeat} setActiveBeat={setActiveBeat} />}
          {effState === "archived" && <ArchivedStage scene={scene} activeBeat={activeBeat} setActiveBeat={setActiveBeat} />}
        </div>
        <DecisionBar scene={scene} state={effState} go={go} onArchive={onArchive} onRun={startRun} onCreateCards={createCards} />
        {compare && <AttemptCompare attempt={compare} scene={scene} onClose={() => setCompare(null)} />}
      </section>

      <Evidence scene={scene} state={effState} activeBeat={activeBeat} setActiveBeat={setActiveBeat} onView={setCompare} />
      {picker && <ScenePicker queued={extras.map(x => x.sid)} onPick={(sid) => { enqueueSid(sid); setPicker(false); }} onClose={() => setPicker(false)} />}
    </div>
  );
}

/* ============================ Queue ============================ */

function SceneQueue({ queue, sceneOfX, pickedId, setPicked, counts, outcomes, dxDone, demo, onAdd }) {
  return (
    <aside className="scn2-queue">
      <header className="scn2-queue-head">
        <div className="page-eyebrow" style={{ margin: 0, display: "flex", alignItems: "center", gap: 8 }}>AI 起草台 {demo && WsDemoTag && <WsDemoTag note="队列里的 CH07/CH08 演示场是模拟数据；从目录加入的场景走后端 scenes run 真管线（预检 → 起草 → 双层质检，LLM 未就绪会给明确引导），归档写回你的正文。" />}</div>
        <h2 className="text-serif scn2-queue-title">运行队列</h2>
        <p className="scn2-queue-sub">从章节编排的场景卡入列 · 一场一裁</p>
      </header>

      <div className="scn2-stats">
        <QStat n={counts.running} label="运行" tone="crimson" />
        <QStat n={counts.queued}  label="排队" tone="slate" />
        <QStat n={counts.ready}   label="待审" tone="gold" />
        <QStat n={counts.archived} label="归档" tone="sage" />
      </div>

      <ul className="scn2-queue-list">
        {queue.map(q => {
          const s = sceneOfX(q.id);
          const st = outcomes[q.id] === "archived" ? "archived" : q.state;
          const active = pickedId === q.id;
          return (
            <li key={q.id}>
              <button className={`scn2-qrow ${active ? "is-active" : ""} s-${st}`} onClick={() => setPicked(q.id)}>
                <span className={`scn2-qrow-spine s-${st}`} />
                <div className="scn2-qrow-main">
                  <div className="scn2-qrow-top">
                    <span className="scn2-qrow-num">{s.n}</span>
                    <span className={`scn2-chip s-${st}`}>{st === "running" && <span className="scn2-chip-pulse" />}{STATE_LABEL[st]}</span>
                  </div>
                  <div className="scn2-qrow-title text-serif">{s.title}</div>
                  {dxDone && dxDone[s.n] != null && <span className="scn2-qrow-dx"><I.Microscope size={11} /> 已深改 · {dxDone[s.n]} 处</span>}
                  <div className="scn2-qrow-bar">
                    <div className={`scn2-qrow-fill s-${st}`} style={{ width: (st === "running" ? q.progress * 100 : 100) + "%" }} />
                  </div>
                </div>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="scn2-queue-foot">
        {demo && <button className="btn btn-ghost btn-sm" style={{ flex: 1 }} title="演示按钮">暂停队列</button>}
        <button className="btn btn-accent btn-sm" style={{ flex: 1 }} onClick={onAdd}><I.Plus size={13} /> 加入场景</button>
      </div>
    </aside>
  );
}

function QStat({ n, label, tone }) {
  return (
    <div className={`scn2-stat tone-${tone}`}>
      <div className="scn2-stat-num tab-num">{n}</div>
      <div className="scn2-stat-label">{label}</div>
    </div>
  );
}

/* ============================ Head ============================ */

function SceneHead({ scene, state, onAbort, onRerun }) {
  return (
    <header className="scn2-head">
      <div className="scn2-head-l">
        <div className="scn2-head-meta">
          <span className="scn2-head-num">{scene.n}</span>
          <span className="scn2-head-dot">·</span>
          <span>{scene.kind}</span>
          <span className={`scn2-state-tag tone-${STATE_TONE[state]}`}>
            {state === "running" && <span className="scn2-chip-pulse" />}
            {STATE_LABEL[state]}
          </span>
        </div>
        <h1 className="scn2-head-title text-serif">{scene.title}</h1>
        <div className="scn2-head-sub">
          {state === "running" && <span>第 {scene.attempt} 次尝试 · 用时 {scene.elapsed} · 预计 {scene.eta} 后可裁决</span>}
          {state === "ready"   && <span>第 {scene.attempt} 次尝试 · {scene.verdict?.words} 字 · {scene.model}</span>}
          {state === "queued"  && <span>预检就绪 · 目标 {scene.targetWords} 字</span>}
          {state === "archived" && <span>{scene.justArchived ? "刚刚写回章节场景卡" : "已写回 · " + (scene.archivedAt || "")}</span>}
        </div>
      </div>
      <div className="scn2-head-r">
        {!scene.fromCard && <button className="btn btn-quiet btn-sm"><I.FileText size={13} /> 戏剧卡</button>}
        {state === "running" && (onAbort ? <button className="btn btn-ghost btn-sm" onClick={onAbort}>中止</button> : <button className="btn btn-ghost btn-sm">中止</button>)}
        {(state === "running" || state === "ready") && (onRerun
          ? (state === "ready" && <button className="btn btn-ghost btn-sm" onClick={onRerun}><I.Refresh size={13} /> 重跑</button>)
          : <button className="btn btn-ghost btn-sm"><I.Refresh size={13} /> 重跑</button>)}
      </div>
    </header>
  );
}

/* ============================ Pipeline ============================ */

function Pipeline({ scene, state }) {
  const liveProgress = state === "running" ? scene.progress : 1;
  return (
    <div className="scn2-pipe">
      {SC_STAGES.map((stg, i) => {
        let st = "todo";
        if (i < scene.stageIdx) st = "done";
        else if (i === scene.stageIdx) st = state === "running" ? "active" : (state === "archived" || state === "ready" ? "done" : "active");
        if (state === "archived") st = "done";
        if (state === "queued" && i === 0) st = "active";
        if (state === "queued" && i > 0) st = "todo";
        return (
          <React.Fragment key={stg.id}>
            <div className={`scn2-pstep s-${st}`}>
              <span className="scn2-pmark">
                {st === "done" && <I.Check size={12} />}
                {st === "active" && (state === "running" ? <span className="scn2-spin" /> : <span className="scn2-pdot" />)}
                {st === "todo" && <span className="scn2-pidx">{i + 1}</span>}
              </span>
              <span className="scn2-pname">{stg.name}</span>
            </div>
            {i < SC_STAGES.length - 1 && (
              <span className={`scn2-pline ${i < scene.stageIdx ? "is-done" : ""}`}>
                {i === scene.stageIdx - 1 && state === "running" && <span className="scn2-pline-go" style={{ width: (liveProgress * 100) + "%" }} />}
              </span>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

/* ============================ Draft renderer ============================ */

function Draft({ scene, activeBeat, setActiveBeat, typing }) {
  return (
    <article className="scn2-draft text-serif">
      {scene.draft.map((p, i) => {
        const isBeat = !!p.beat;
        const isActive = activeBeat && p.beat === activeBeat;
        const last = typing && i === scene.draft.length - 1;
        return (
          <p
            key={p.id}
            className={`scn2-para ${isBeat ? "has-beat tone-" + BEAT_META[p.beat].tone : ""} ${isActive ? "is-lit" : ""}`}
            onMouseEnter={() => isBeat && setActiveBeat(p.beat)}
            onMouseLeave={() => isBeat && setActiveBeat(null)}
          >
            {isBeat && <span className={`scn2-beat-tab tone-${BEAT_META[p.beat].tone}`}>{BEAT_META[p.beat].label.split(" ")[0]}</span>}
            {p.parts.map((part, j) =>
              part.risk
                ? <mark key={j} className={`scn2-risk sev-${part.sev}`} data-tip={part.tip}>{part.text}</mark>
                : <span key={j}>{part.text}</span>
            )}
            {last && <span className="scn2-caret" />}
          </p>
        );
      })}
    </article>
  );
}

/* ============================ Preflight (queued) ============================ */

function Preflight({ scene }) {
  const briefBeats = (scene.brief || []).map(b => b.beat);
  /* 长程约束：预检时读控制塔的交接契约（强约束层）。
     若本场场景卡带 contract 指派（由塔下发时逐场分解），优先展示指派项 */
  const longRange = useMemo8(() => {
    try {
      if (WsWorks && WsWorks.activeId() !== "tide") return null;
      if (!window.lf3Brief || !window.LF2_LOOPS || !window.LF2_CANON) return null;
      const b = window.lf3Brief(window.LF2_LOOPS, window.LF2_CANON, {});
      if (!b || !b.enforce || !b.enforce.length) return null;
      let assigned = null;
      if (scene.sid && WsCatalog) {
        const hit = WsCatalog.sceneById(scene.sid);
        if (hit && Array.isArray(hit.scene.contract) && hit.scene.contract.length) {
          assigned = b.all.filter(it => hit.scene.contract.includes(it.id));
          if (!assigned.length) assigned = null;
        }
      }
      return { ...b, assigned };
    } catch (e) { return null; }
  }, [scene.sid]);
  const checks = scene.fromCard
    ? [
        { ok: briefBeats.includes("goal"),     text: "场景卡 · 目标已填" },
        { ok: briefBeats.includes("conflict"), text: "场景卡 · 阻碍已填" },
        { ok: briefBeats.includes("exit"),     text: "场景卡 · 出口已填" },
        { ok: false, text: "参考画像未绑定 · 可选" },
      ]
    : [
        { ok: true,  text: "戏剧卡完整 · 6/6 字段" },
        { ok: true,  text: "出场角色已绑定 · 3 位" },
        { ok: true,  text: "上一场出口已对齐入口" },
        { ok: false, text: "参考画像未绑定 · 可选" },
      ];
  if (longRange) checks.unshift({ ok: true, text: `控制塔交接契约已注入 · ${longRange.enforce.length} 条强约束随身在场` });
  return (
    <div className="scn2-pre scn2-scroll">
      <div className="scn2-pre-card">
        {scene.fromCard && (
          <div className="scn2-archived-note" style={{ marginBottom: 12 }}>
            <I.ArrowRight size={14} /> 由章节编排「交给 AI」入列 · 预检校验的就是这张场景卡
          </div>
        )}
        <div className="scn2-pre-eyebrow"><I.ShieldCheck size={14} /> 预检清单</div>
        <ul className="scn2-pre-list">
          {checks.map((c, i) => (
            <li key={i} className={c.ok ? "ok" : "opt"}>
              {c.ok ? <I.Check size={14} /> : <I.Circle size={13} />}
              <span>{c.text}</span>
            </li>
          ))}
        </ul>
        <div className="scn2-pre-brief">
          <div className="scn2-pre-eyebrow"><I.Compass size={14} /> 本场戏剧卡{scene.fromCard ? " · 与章节编排同一张" : ""}</div>
          <ul className="scn2-brief-list">
            {scene.brief.map((b, i) => (
              <li key={i}>
                <span className={`scn2-brief-tag tone-${BEAT_META[b.beat].tone}`}>{BEAT_META[b.beat].label.split(" ")[0]}</span>
                <span className="scn2-brief-text">{b.text}</span>
              </li>
            ))}
          </ul>
        </div>
        {longRange && (
          <div className="scn2-pre-brief">
            <div className="scn2-pre-eyebrow"><I.Radar size={14} /> 长程约束 · {longRange.assigned ? "本场指派（控制塔契约）" : "来自控制塔交接契约"}</div>
            <ul className="scn2-brief-list">
              {(longRange.assigned || longRange.enforce.slice(0, 4)).map((it) => (
                <li key={it.id}>
                  <span className={`scn2-brief-tag tone-${it.tone === "rose" ? "crimson" : (it.tone === "crimson" || it.tone === "gold" || it.tone === "sage" || it.tone === "slate") ? it.tone : "slate"}`}>{it.label}</span>
                  <span className="scn2-brief-text">{it.text}</span>
                </li>
              ))}
            </ul>
            <p style={{ margin: "10px 0 0", fontSize: 12, color: "var(--ink-3)" }}>
              {longRange.assigned
                ? `本场指派 ${longRange.assigned.length} 条；另有 ${Math.max(0, longRange.enforce.length - longRange.assigned.filter(it => it.mode === "enforce").length)} 条全章强约束随预检在场 —— 起草与质检都会逐条比对。`
                : `${longRange.enforce.length > 4 ? `另有 ${longRange.enforce.length - 4} 条强约束已随预检注入 · ` : ""}这些是全书层面不许漂移的设定与承诺，起草与质检都会逐条比对 —— 详见长篇控制塔。`}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/* ============================ Running (live) ============================ */

function RunningStage({ scene, activeBeat, setActiveBeat, logOpen, setLogOpen }) {
  const banner = scene.runBanner || { t: "二次改写进行中", s: `针对 2 项中风险 · Haiku · 预计 ${scene.eta}` };
  const reduce = useMemo8(() => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches, []);
  const [shown, setShown] = useSt8(reduce ? scene.log.length : 1);
  const scRef = useRef8(null);

  useEf8(() => {
    if (reduce) { setShown(scene.log.length); return; }
    setShown(1);
    let i = 1;
    const id = setInterval(() => {
      i += 1;
      setShown(Math.min(i, scene.log.length));
      if (i >= scene.log.length) clearInterval(id);
    }, 900);
    return () => clearInterval(id);
  }, [scene.id]);

  useEf8(() => {
    if (logOpen && scRef.current) scRef.current.scrollTop = scRef.current.scrollHeight;
  }, [shown, logOpen]);

  return (
    <div className="scn2-run">
      <div className="scn2-run-doc scn2-scroll">
        <div className="scn2-run-banner">
          <span className="scn2-spin scn2-spin-lg" />
          <div>
            <div className="scn2-run-banner-t">{banner.t}</div>
            <div className="scn2-run-banner-s">{banner.s}</div>
          </div>
          <div className="scn2-run-pct tab-num">{Math.round(scene.progress * 100)}%</div>
        </div>
        {scene.draft.length === 0 && (
          <p className="scn2-para" style={{ color: "var(--ink-3)" }}>Claude 正在按场景卡起草……整稿返回后先过本地质检（短句率 / 句式重复 / 超长句），再交给你裁决。</p>
        )}
        <Draft scene={scene} activeBeat={activeBeat} setActiveBeat={setActiveBeat} typing />
        <p className="scn2-draft-foot">起草稿 · {scene.targetWords} 字{scene.fromCard ? " · 整稿返回后过质检" : " · 正在按风险项改写…"}</p>
      </div>

      <div className={`scn2-console ${logOpen ? "is-open" : ""}`}>
        <button className="scn2-console-bar" onClick={() => setLogOpen(o => !o)}>
          <I.Activity size={13} />
          <span>运行日志</span>
          <span className="scn2-console-live"><span className="scn2-chip-pulse" />直播</span>
          <I.ChevronRight size={14} className="scn2-console-caret" />
        </button>
        {logOpen && (
          <ul className="scn2-log scn2-scroll" ref={scRef}>
            {scene.log.slice(0, shown).map((l, i) => (
              <li key={i} className="scn2-log-row">
                <span className="scn2-log-t">{l.t}</span>
                <span className={`scn2-log-who w-${l.who}`}>{l.who}</span>
                <span className="scn2-log-text">{l.text}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ============================ Review (ready) ============================ */

function ReviewStage({ scene, activeBeat, setActiveBeat }) {
  return (
    <div className="scn2-review scn2-scroll">
      <Draft scene={scene} activeBeat={activeBeat} setActiveBeat={setActiveBeat} />
      <p className="scn2-draft-foot">复核稿 · {scene.verdict?.words} 字 · 悬停高亮处查看风险，点右侧戏剧卡定位段落</p>
    </div>
  );
}

/* ============================ Archived ============================ */

function ArchivedStage({ scene, activeBeat, setActiveBeat }) {
  return (
    <div className="scn2-review scn2-scroll">
      {scene.justArchived && (
        <div className="scn2-archived-note">
          <I.Check size={15} /> {scene.fromCard
            ? <>已写入 <strong>{scene.n}</strong> 的正文文档（{scene.verdict ? scene.verdict.words : "—"} 字）· 场景卡已置「完成」· 字数已回写目录</>
            : <>已写回 <strong>{scene.n}</strong> 场景卡 · writer_brief_json 已更新</>}
        </div>
      )}
      <Draft scene={scene} activeBeat={activeBeat} setActiveBeat={setActiveBeat} />
      <p className="scn2-draft-foot">定稿 · 只读 · 如需局部打磨请送写作台深改</p>
    </div>
  );
}

/* ============================ Decision bar ============================ */

function DecisionBar({ scene, state, go, onArchive, onRun, onCreateCards }) {
  const [rework, setRework] = useSt8(false);
  const [note, setNote] = useSt8("");
  useEf8(() => { setRework(false); setNote(""); }, [scene.id]);

  const toWriterDeep = () => {
    const sid = scene.sid || scnSidOf(scene.n);
    go("writer");
    setTimeout(() => {
      if (sid) window.dispatchEvent(new CustomEvent("ws:writer-scene", { detail: sid }));
      window.dispatchEvent(new CustomEvent("ws:writer-posture", { detail: "deep" }));
    }, 80);
  };

  if (state === "queued") {
    if (scene.fromCard) {
      return (
        <div className="scn2-decide">
          <div className="scn2-decide-sum">
            {scene.error
              ? <><I.AlertTriangle size={14} style={{ color: "var(--crimson)" }} /> {scene.error}</>
              : <><I.Clock size={14} /> 预检就绪 · 会把雪花构思与场景卡一起喂给 Claude</>}
          </div>
          <div className="scn2-decide-acts">
            <button className="btn btn-quiet btn-sm" onClick={() => go("author")} title="场景卡在章节编排里维护">编辑场景卡</button>
            {scene.needsCards && onCreateCards
              ? <button className="btn btn-accent" onClick={() => onCreateCards()} title="确定性建出最小 active 声线/关系卡解阻，再自动续跑起草"><I.Refresh size={13} /> 补齐声线卡并重试</button>
              : <button className="btn btn-accent" onClick={() => onRun && onRun("")}><I.Play size={13} /> 开始起草</button>}
          </div>
        </div>
      );
    }
    return (
      <div className="scn2-decide">
        <div className="scn2-decide-sum"><I.Clock size={14} /> 预检就绪，可立即起草</div>
        <div className="scn2-decide-acts">
          <button className="btn btn-quiet btn-sm">编辑戏剧卡</button>
          <button className="btn btn-accent"><I.Play size={13} /> 开始运行</button>
        </div>
      </div>
    );
  }

  if (state === "running") {
    return (
      <div className="scn2-decide is-wait">
        <div className="scn2-decide-sum"><span className="scn2-spin" /> 运行中 · 完成校核后开放裁决</div>
        <div className="scn2-decide-acts">
          <button className="btn btn-ghost btn-sm" disabled>采纳并归档</button>
        </div>
      </div>
    );
  }

  if (state === "archived") {
    return (
      <div className="scn2-decide is-done">
        <div className="scn2-decide-sum"><I.Database size={14} /> {scene.fromCard ? "已写入正文文档 · 场景卡置「完成」" : "已归档至章节场景卡"}</div>
        <div className="scn2-decide-acts">
          {scene.fromCard && (
            <button className="btn btn-quiet btn-sm" onClick={() => { go("writer"); setTimeout(() => window.dispatchEvent(new CustomEvent("ws:writer-scene", { detail: scene.sid })), 80); }}><I.Pen size={13} /> 在写作器打开</button>
          )}
          <button className="btn btn-quiet btn-sm" onClick={() => go("manuscripts")}>在成稿中心查看</button>
          <button className="btn btn-ghost btn-sm" onClick={toWriterDeep}><I.Microscope size={13} /> 送写作台深改</button>
        </div>
      </div>
    );
  }

  // ready → the real decision moment
  const v = scene.verdict || {};
  return (
    <div className="scn2-decide-wrap">
      {rework && (
        <div className="scn2-rework">
          <div className="scn2-rework-head">
            <I.Refresh size={13} /><span>退回重写 · 给改写指令</span>
            <button className="scn2-rework-x" onClick={() => setRework(false)}><I.X size={13} /></button>
          </div>
          <div className="scn2-rework-chips">
            {["收一点结尾的比喻", "Setback 往后挪", "增强环境声细节", "压一压短句率"].map(c => (
              <button key={c} className="scn2-rework-chip" onClick={() => setNote(n => n ? n + "；" + c : c)}>{c}</button>
            ))}
          </div>
          <textarea
            className="scn2-rework-input" rows={2}
            placeholder="写给模型的具体改写指令，例如：保留第 5 段的节奏，但把最后一句的比喻收得更克制…"
            value={note} onChange={e => setNote(e.target.value)}
          />
          <div className="scn2-rework-foot">
            <span className="scn2-rework-hint">退回后将以同一场景卡重新生成，并保留为第 {scene.attempt + 1} 次尝试</span>
            <button className="btn btn-accent btn-sm" onClick={() => { if (scene.fromCard && onRun) { onRun(note); setRework(false); } }} disabled={scene.fromCard && !note.trim()}><I.Refresh size={13} /> 确认退回重写</button>
          </div>
        </div>
      )}
      <div className="scn2-decide is-ready">
        <div className="scn2-decide-verdict">
          <span className="scn2-verdict-badge"><I.ShieldCheck size={14} /> {v.qc}</span>
          <span className="scn2-verdict-meta">{v.align} · {v.risks}</span>
        </div>
        <div className="scn2-decide-acts">
          <button className="btn btn-ghost btn-sm" onClick={toWriterDeep}><I.Microscope size={13} /> 送写作台深改</button>
          <button className={`btn btn-quiet btn-sm ${rework ? "is-on" : ""}`} onClick={() => setRework(r => !r)}><I.Refresh size={13} /> 退回重写</button>
          <button className="btn btn-accent" onClick={onArchive}><I.Check size={14} /> 采纳并归档</button>
        </div>
      </div>
    </div>
  );
}

/* ============================ Evidence ============================ */

function Evidence({ scene, state, activeBeat, setActiveBeat, onView }) {
  const hasMetrics = scene.metrics && scene.metrics.length > 0;
  return (
    <aside className="scn2-evi scn2-scroll">
      {hasMetrics && (
        <section className="scn2-evi-block">
          <h3 className="scn2-evi-h"><I.ShieldCheck size={13} /> 质检指标</h3>
          <div className="scn2-meters">
            {scene.metrics.map((m, i) => (
              <div key={i} className="scn2-meter">
                <div className="scn2-meter-top">
                  <span className="scn2-meter-label">{m.label}</span>
                  <span className={`scn2-meter-val tab-num tone-${m.tone}`}>{m.val}</span>
                </div>
                <div className="scn2-meter-track">
                  <div className={`scn2-meter-fill tone-${m.tone}`} style={{ width: m.pct + "%" }} />
                  <span className="scn2-meter-target" style={{ left: m.target + "%" }} title={`目标 ${m.target}%`} />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {scene.alignment && scene.alignment.length > 0 && (
        <section className="scn2-evi-block">
          <h3 className="scn2-evi-h"><I.Compass size={13} /> 戏剧卡对齐</h3>
          <ul className="scn2-align">
            {scene.alignment.map((a, i) => {
              const meta = BEAT_META[a.beat];
              const lit = activeBeat === a.beat;
              const clickable = !!a.para;
              return (
                <li key={i}>
                  <button
                    className={`scn2-align-row st-${a.status} ${lit ? "is-lit" : ""} ${clickable ? "" : "is-static"}`}
                    onMouseEnter={() => clickable && setActiveBeat(a.beat)}
                    onMouseLeave={() => clickable && setActiveBeat(null)}
                  >
                    <span className={`scn2-align-dot tone-${meta.tone}`} />
                    <span className="scn2-align-body">
                      <span className="scn2-align-beat">{meta.label}</span>
                      <span className="scn2-align-note">{a.note}</span>
                    </span>
                    <span className={`scn2-align-mark st-${a.status}`}>
                      {a.status === "ok" && <I.Check size={12} />}
                      {a.status === "warn" && <I.AlertTriangle size={12} />}
                      {a.status === "pend" && "…"}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {scene.attempts && scene.attempts.length > 0 && (
        <section className="scn2-evi-block">
          <h3 className="scn2-evi-h"><I.Clock size={13} /> 尝试历史 · {scene.attempts.length}</h3>
          <ul className="scn2-tries">
            {scene.attempts.map((a, i) => (
              <li key={i} className={`scn2-try ${i === 0 ? "is-current" : ""}`}>
                <span className="scn2-try-n tab-num">#{a.n}</span>
                <span className="scn2-try-body">
                  <span className="scn2-try-top">
                    <span className="scn2-try-time">{a.time}</span>
                    <span className={`scn2-try-tag tone-${a.tone}`}>{a.result === "running" ? "进行中" : a.result}</span>
                  </span>
                  <span className="scn2-try-note">{a.note}</span>
                </span>
                {i !== 0 && <button className="scn2-try-view" onClick={() => onView(a)}>对比</button>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {scene.cost && scene.cost.length > 0 && (
        <section className="scn2-evi-block">
          <h3 className="scn2-evi-h"><I.Coins size={13} /> 本次开销</h3>
          <ul className="scn2-rows">
            {scene.cost.map((c, i) => (
              <li key={i}><span>{c.k}</span><strong className={c.mono ? "tab-num" : ""}>{c.v}</strong></li>
            ))}
          </ul>
        </section>
      )}

      {scene.dxCount != null && (
        <section className="scn2-evi-block">
          <h3 className="scn2-evi-h"><I.Microscope size={13} /> 深改记录</h3>
          <div className="scn2-dx">
            <div className="scn2-dx-top"><I.Check size={13} /> 写作台深改已采纳 {scene.dxCount} 处建议并回传</div>
            <ul className="scn2-rows">
              <li><span>逐句采纳</span><strong>{scene.dxCount} 处</strong></li>
              <li><span>低风险项</span><strong className="scn2-dx-ok">已清零</strong></li>
              <li><span>状态</span><strong>已同步本场质检</strong></li>
            </ul>
          </div>
        </section>
      )}

      <section className="scn2-evi-block">
        <h3 className="scn2-evi-h"><I.Database size={13} /> 归档去向</h3>
        <ul className="scn2-rows">
          <li><span>章节</span><strong>{scene.n?.split(" · ")[0]}</strong></li>
          <li><span>场景卡</span><strong>{scene.n?.split(" · ")[1]} · {scene.kind}</strong></li>
          {scene.fromCard ? (
            <React.Fragment>
              <li><span>写入</span><strong className="tab-num">wr-doc · 写作器正文</strong></li>
              <li><span>连带</span><strong>字数回写 + 场景卡置完成</strong></li>
            </React.Fragment>
          ) : (
            <li><span>写入字段</span><strong className="tab-num">writer_brief_json</strong></li>
          )}
          <li><span>策略</span><strong>{state === "archived" ? "已写入" : "裁决通过后写入"}</strong></li>
        </ul>
      </section>
    </aside>
  );
}

function AttemptCompare({ attempt, scene, onClose }) {
  const cmp = attempt.cmp || {};
  return (
    <div className="scn2-cmp" role="dialog" aria-modal="true">
      <div className="scn2-cmp-card">
        <header className="scn2-cmp-head">
          <div className="scn2-cmp-title">
            <span className="scn2-cmp-n tab-num">尝试 #{attempt.n}</span>
            <span className={`scn2-try-tag tone-${attempt.tone}`}>{attempt.result === "running" ? "进行中" : attempt.result}</span>
            <span className="scn2-cmp-time">{attempt.time}</span>
          </div>
          <button className="scn2-cmp-x" onClick={onClose} aria-label="关闭"><I.X size={16} /></button>
        </header>

        <div className="scn2-cmp-body scn2-scroll">
          {cmp.verdict && (
            <div className="scn2-cmp-verdict">
              <span className={`scn2-cmp-vdot tone-${attempt.tone}`} />
              <p>{cmp.verdict}</p>
            </div>
          )}

          {cmp.metrics && cmp.metrics.length > 0 && (
            <div className="scn2-cmp-metrics">
              <div className="scn2-cmp-sub">指标变化 · 该版 → 本次</div>
              <div className="scn2-cmp-mgrid">
                {cmp.metrics.map((m, i) => (
                  <div key={i} className="scn2-cmp-metric">
                    <span className="scn2-cmp-mlabel">{m.label}</span>
                    <span className="scn2-cmp-mflow">
                      <span className="scn2-cmp-was tab-num">{m.was}</span>
                      <span className={`scn2-cmp-arrow ${m.better ? "good" : "bad"}`}>{m.better ? "↓" : "↑"}</span>
                      <span className="scn2-cmp-now tab-num">{m.now}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {cmp.before && (
            <div className="scn2-cmp-diff">
              <div className="scn2-cmp-col is-before">
                <div className="scn2-cmp-coltag">该版问题段 · #{attempt.n}</div>
                <p className="text-serif scn2-cmp-text">{cmp.before.text}</p>
                {cmp.before.risk && <div className="scn2-cmp-risk"><I.AlertTriangle size={12} /> {cmp.before.risk}</div>}
              </div>
              <div className="scn2-cmp-arrow-col"><I.ArrowRight size={16} /></div>
              <div className="scn2-cmp-col is-after">
                <div className="scn2-cmp-coltag">本次 · 当前版</div>
                <p className="text-serif scn2-cmp-text">{cmp.after.text}</p>
                <div className="scn2-cmp-fixed"><I.Check size={12} /> 已修正</div>
              </div>
            </div>
          )}

          {!cmp.metrics && !cmp.before && (
            <div className="scn2-cmp-empty">该版未保留逐段记录，仅留结论与起草日志。</div>
          )}
        </div>

        <footer className="scn2-cmp-foot">
          <span className="scn2-cmp-hint">对照本次复核稿，决定是否回到该版重写</span>
          <div className="flex gap-2">
            <button className="btn btn-quiet btn-sm" onClick={onClose}>关闭</button>
            <button className="btn btn-ghost btn-sm"><I.Refresh size={13} /> 以该版为基础重写</button>
          </div>
        </footer>
      </div>
    </div>
  );
}

/* ============================ 选场入列 ============================ */
function ScenePicker({ queued, onPick, onClose }) {
  const chs = scnPickList ? scnPickList(queued) : [];
  const stLabel = { done: "已完成", writing: "在写", todo: "待写" };
  const batchOf = (c) => c.scenes.filter(s => !s.queued && s.sid && s.state !== "done");
  return (
    <div className="scn2-cmp" role="dialog" aria-modal="true">
      <div className="scn2-cmp-card" style={{ maxWidth: 620 }}>
        <header className="scn2-cmp-head">
          <div className="scn2-cmp-title">
            <span className="scn2-cmp-n">加入场景</span>
            <span className="scn2-cmp-time">从章节目录挑一场交给 AI 起草</span>
          </div>
          <button className="scn2-cmp-x" onClick={onClose} aria-label="关闭"><I.X size={16} /></button>
        </header>
        <div className="scn2-cmp-body scn2-scroll" style={{ display: "grid", gap: 14 }}>
          {!chs.length && (
            <div className="scn2-cmp-empty">章节目录还是空的——先在构思的「下游交付」把雪花整理成章节结构，或去章节编排建章。</div>
          )}
          {chs.map(c => {
            const batch = batchOf(c);
            return (
            <div key={c.id}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: "var(--ink-3)", flex: 1 }}>第 {c.n} 章 · {c.title}</span>
                {batch.length > 1 && (
                  <button className="btn btn-quiet btn-sm" onClick={() => batch.forEach(s => onPick(s.sid, true))} title="把本章未完成的场全部入列（不自动起草，逐场点开始）">
                    <I.Plus size={12} /> 整章入列 · {batch.length} 场
                  </button>
                )}
              </div>
              <div style={{ display: "grid", gap: 6 }}>
                {c.scenes.map(s => (
                  <button key={s.sid} className="scn2-pick-row" disabled={s.queued} onClick={() => onPick(s.sid)}>
                    <span className={`scn2-pick-kind ${s.kind === "反应" ? "is-rea" : "is-pro"}`}>{s.kind || "主动"}</span>
                    <span className="scn2-pick-title">{s.title}</span>
                    {s.hasDraft && <span className="scn2-pick-draft" title="这一场已有 AI 稿（入列后可直接裁决或重跑）"><I.Sparkles size={11} /> 有 AI 稿</span>}
                    {!s.ready && <span className="scn2-pick-warn" title="场景卡的目标还是占位——起草质量会打折"><I.AlertTriangle size={11} /> 卡未填全</span>}
                    <span className="scn2-pick-st">{s.queued ? "已在队列" : (stLabel[s.state] || s.state || "—")}</span>
                  </button>
                ))}
              </div>
            </div>
            );
          })}
        </div>
        <footer className="scn2-cmp-foot">
          <span className="scn2-cmp-hint">入列后点「开始起草」：Claude 读雪花构思 + 场景卡起草，过本地质检后由你裁决</span>
          <button className="btn btn-quiet btn-sm" onClick={onClose}>关闭</button>
        </footer>
      </div>
      <style>{`
.scn2-pick-row { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; padding: 9px 12px; border: 1px solid var(--line-1, #ddd); border-radius: 10px; background: var(--paper-0, #fff); cursor: pointer; font: inherit; }
.scn2-pick-row:hover:not([disabled]) { border-color: var(--ink-3); }
.scn2-pick-row[disabled] { opacity: 0.55; cursor: default; }
.scn2-pick-kind { flex: 0 0 auto; font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 999px; }
.scn2-pick-kind.is-pro { background: var(--crimson-wash); color: var(--crimson); }
.scn2-pick-kind.is-rea { background: var(--paper-1, #f3f2ef); color: var(--ink-2); }
.scn2-pick-title { flex: 1; min-width: 0; font-size: 13px; color: var(--ink-1); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.scn2-pick-warn { display: inline-flex; align-items: center; gap: 3px; font-size: 10.5px; font-weight: 700; color: var(--gold); flex: 0 0 auto; }
.scn2-pick-draft { display: inline-flex; align-items: center; gap: 3px; font-size: 10.5px; font-weight: 700; color: var(--sage); flex: 0 0 auto; }
.scn2-pick-st { flex: 0 0 auto; font-size: 11px; color: var(--ink-3); }
      `}</style>
    </div>
  );
}

function SceneTweaks({ t, setTweak }) {
  return (
    <>
      <TweakSection label="AI 起草台" />
      <TweakSlider label="正文字号" value={t.scnFont ?? 16} min={15} max={20} step={1} unit="px"
        onChange={(v) => setTweak("scnFont", v)} />
      <TweakRadio label="证据栏密度" value={t.scnDensity ?? "cozy"}
        options={[{ value: "cozy", label: "疏朗" }, { value: "compact", label: "紧凑" }]}
        onChange={(v) => setTweak("scnDensity", v)} />
      <TweakToggle label="戏剧卡边条" value={t.scnBeats !== false}
        onChange={(v) => setTweak("scnBeats", v)} />
      <TweakToggle label="运行日志默认展开" value={t.scnLog !== false}
        onChange={(v) => setTweak("scnLog", v)} />
      <TweakSection label="质检阈值 · 对已生成稿实时重算" />
      <TweakSlider label="短句率目标" value={t.scnShort ?? 55} min={30} max={85} step={5} unit="%"
        onChange={(v) => setTweak("scnShort", v)} />
      <TweakSlider label="句式重复上限" value={t.scnRepeat ?? 30} min={10} max={60} step={5} unit="%"
        onChange={(v) => setTweak("scnRepeat", v)} />
      <TweakSlider label="超长句阈值" value={t.scnLong ?? 64} min={40} max={120} step={4} unit="字"
        onChange={(v) => setTweak("scnLong", v)} />
    </>
  );
}

/* 运行队列：演示流水线只在《潮汐档案》呈现；任何作品都可从自己的章节目录
   加场入列——那是真实起草：Claude 读雪花构思 + 场景卡，质检后写回正文。 */
function WsScene(props) {
  const isTide = (() => { try { return !WsWorks || WsWorks.activeId() === "tide"; } catch (e) { return true; } })();
  if (isTide) return <WsSceneDemo {...props} demo={true} />;
  const hasCatalog = (() => { try { return WsCatalog && WsCatalog.get().length > 0; } catch (e) { return false; } })();
  if (hasCatalog) return <WsSceneDemo {...props} demo={false} />;
  const work = WsWorks ? WsWorks.active() : { title: "这部作品" };
  return (
    <div className="page" data-screen-label="scene · empty">
      <div style={{ display: "grid", placeItems: "center", minHeight: "70vh", textAlign: "center" }}>
        <div style={{ maxWidth: 460, display: "grid", gap: 14, justifyItems: "center" }}>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, color: "var(--ink-1)" }}>《{work.title}》还没有章节目录</div>
          <p style={{ color: "var(--ink-3)", fontSize: 14, lineHeight: 1.9, margin: 0 }}>
            AI 起草台按场景卡逐场起草：预检 → 起草 → 质检 → 裁决 → 写回正文。
            先在构思里把雪花「整理成章节结构」，或去章节编排建章、填好场景卡，再回来入列。
          </p>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn btn-accent" onClick={() => props.go && props.go("snowflake")}><I.Layout size={15} /> 去构思·下游交付</button>
            <button className="btn btn-ghost" onClick={() => props.go && props.go("author")}>去章节编排</button>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { WsScene, SceneTweaks });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { WsScene, SceneTweaks };
