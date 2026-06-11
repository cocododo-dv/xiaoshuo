/* global React, ReactDOM, I */
/* ==========================================================
   WsReview — 待办收件箱 · 案头
   A calm triage desk. Aggregates the things that need the
   writer's *call* from across the workbench — decisions,
   risks, QC notes, ideation gaps, margin notes — sorted by
   urgency, each with provenance, context and rationale.
   "处理完就回去写。"
   ========================================================== */

const RV_KINDS = {
  decision: { label: "决策", tone: "crimson", icon: "GitBranch",     hint: "需要你拍板" },
  risk:     { label: "风险", tone: "rose",    icon: "AlertTriangle", hint: "可能出错" },
  qc:       { label: "质检", tone: "slate",   icon: "Microscope",    hint: "质量建议" },
  idea:     { label: "构思", tone: "gold",    icon: "Snowflake",     hint: "待补内容" },
  note:     { label: "批注", tone: "sage",    icon: "FileText",      hint: "你的批注" },
};

/* priority: 1 = 优先处理 · 2/3 = 其余 */
const RV_SEED = [
  {
    id: "r1", kind: "decision", priority: 1,
    title: "参考画像「冷峻短句」是否应用到本项目",
    where: "风格参考 · 三天前学完", source: "风格参考", time: "3 天前",
    detail: "要点：句子尽量短于 14 字、少形容词、以动词收尾、删去解释性从句。应用后将作为写作房间的默认润色基线，可随时关闭。",
    preview: { before: "她久久地凝望着窗外那片渐渐暗下来的天色。", after: "她望着窗外。天色暗了。" },
    actions: [
      { label: "应用到本项目", intent: "primary", op: "resolve" },
      { label: "先去改造", intent: "ghost", op: "nav", to: "styleref" },
      { label: "丢弃", intent: "quiet", op: "resolve" },
    ],
  },
  {
    id: "r3", kind: "qc", priority: 2,
    title: "第 7 章节奏过快，建议补一段反应场景",
    where: "第 7 章 · SC 03 之后", source: "文学质检", time: "昨天",
    detail: "连续三个主动场景之间没有喘息，读者情绪曲线缺少回落。建议在 SC 03 后插入 200–400 字的反应节拍，让林岑消化「钥匙」的发现。采纳会直接在目录第 7 章 SC 03 后插入一个待写的反应场。",
    actions: [
      { label: "去章节编排看结构", intent: "primary", op: "nav", to: "author" },
      { label: "采纳 · 插入反应场", intent: "ghost", op: "resolve", effect: { type: "insertScene", ch: "ch07", at: 3, scene: { title: "回廊喘息 · 反应拍", kind: "反应", state: "todo", goal: "让林岑消化「钥匙」的发现", obstacle: "夜班时间所剩无几", turn: "（待规划）" } } },
      { label: "忽略", intent: "quiet", op: "resolve" },
    ],
  },
  {
    id: "r4", kind: "idea", priority: 2,
    title: "角色全档案 · 还差「师父周岚」",
    where: "雪花构思 · 第 08 步", source: "构思", time: "昨天",
    detail: "周岚的全档案仍有四项空缺，缺它会影响第 6–8 章的动机一致性。",
    checklist: ["成长创伤", "对外面具", "内在真我", "与林岑的羁绊曲线"],
    actions: [
      { label: "去补全", intent: "primary", op: "nav", to: "snowflake", step: "profile" },
      { label: "稍后再说", intent: "quiet", op: "snooze" },
    ],
  },
  {
    id: "r5", kind: "decision", priority: 2,
    title: "第 6 章标题在两个候选间未定",
    where: "第 6 章 · 标题", source: "章节编排", time: "2 天前",
    detail: "「周岚的钥匙」直白点题、呼应线索；「她留下的钥匙」更含蓄、留悬念。选定后会直接改写目录里第 6 章的标题。",
    options: ["周岚的钥匙", "她留下的钥匙"],
    actions: [
      { label: "用「周岚的钥匙」", intent: "primary", op: "resolve", effect: { type: "renameChapter", ch: "ch06", title: "周岚的钥匙" } },
      { label: "用「她留下的钥匙」", intent: "ghost", op: "resolve", effect: { type: "renameChapter", ch: "ch06", title: "她留下的钥匙" } },
      { label: "再想想", intent: "quiet", op: "snooze" },
    ],
  },
  {
    id: "r6", kind: "risk", priority: 2,
    title: "时间线：第 3 章与第 5 章季节描写不一致",
    where: "第 3 章 → 第 5 章", source: "时间线", time: "3 天前",
    detail: "第 3 章写「初秋的潮气」，第 5 章却出现「初夏蝉鸣」，但两章间隔仅约十天。需统一季节锚点。",
    actions: [
      { label: "打开时间线", intent: "primary", op: "nav", to: "library" },
      { label: "标记为已核", intent: "quiet", op: "resolve" },
    ],
  },
  {
    id: "r7", kind: "note", priority: 3,
    title: "批注 · 「潮声」意象是否前后呼应",
    where: "第 8 章 · 第 12 段", source: "写作房间", time: "今天",
    detail: "你给这段留过一条批注：开篇用「潮声」作记忆触发，结尾是否应让它再次响起，形成回环？",
    actions: [
      { label: "回到该段", intent: "primary", op: "nav", to: "writer", scene: "ch08s3" },
      { label: "标记已读", intent: "quiet", op: "resolve" },
    ],
  },
  {
    id: "r8", kind: "qc", priority: 3,
    title: "全书「潮汐」一词出现 47 次，可能过载",
    where: "全书 · 用词", source: "文学质检", time: "今天",
    detail: "核心意象高频复现有记忆点，但密度偏高易显刻意。可在非关键段落用「水位」「退潮」等近义替换 8–10 处。",
    actions: [
      { label: "在深改姿态里看", intent: "primary", op: "nav", to: "writer", posture: "deep" },
      { label: "知道了", intent: "quiet", op: "resolve" },
    ],
  },
];

const RV_BAND = { 1: { label: "优先处理", hint: "需要你尽快拍板" }, 2: { label: "其余待办", hint: "建议与提示，得空再看" } };

/* ==========================================================
   持久化 store —— 按作品隔离，处理/稍后状态跨刷新保留；
   徽标订阅式更新（ws:review-changed）。种子仅属于「潮汐档案」，
   其它作品从空收件箱开始。
   ========================================================== */
const RV_LS = "ws_review_v1";
const rvKey = () => (window.wsKey ? window.wsKey(RV_LS) : RV_LS);
const rvSeed = () => { try { return window.WsWorks && window.WsWorks.activeId() !== "tide" ? [] : RV_SEED; } catch (e) { return RV_SEED; } };
function rvLoad() { try { return JSON.parse(localStorage.getItem(rvKey())) || {}; } catch (e) { return {}; } }
function rvSave(patch) {
  const st = { ...rvLoad(), ...patch };
  try { localStorage.setItem(rvKey(), JSON.stringify(st)); } catch (e) {}
  try { window.dispatchEvent(new CustomEvent("ws:review-changed")); } catch (e) {}
}
/* —— 投递 API：任何模块都可以往当前作品的收件箱里塞一条待办 ——
   rvPush({ kind, priority, title, where, source, detail, actions?, effectPayload? })
   持久化在 st.custom（按作品隔离），与种子条目走同一条处理/稍后/撤销流。 */
function rvAgo(t) {
  const m = Math.floor((Date.now() - t) / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return m + " 分钟前";
  const h = Math.floor(m / 60);
  if (h < 24) return h + " 小时前";
  return Math.floor(h / 24) + " 天前";
}
function rvCustomList() {
  const st = rvLoad();
  return (st.custom || []).map(it => ({ ...it, time: rvAgo(it.at || Date.now()) }));
}
function rvPush(item) {
  const st = rvLoad();
  const it = {
    id: "c" + Date.now().toString(36) + Math.floor(Math.random() * 1e3).toString(36),
    at: Date.now(),
    kind: "note", priority: 2,
    actions: [{ label: "知道了", intent: "quiet", op: "resolve" }],
    ...item,
  };
  rvSave({ custom: [it, ...(st.custom || [])].slice(0, 50) });
  return it.id;
}
function rvAllItems() { return [...rvDerived(), ...rvCustomList(), ...rvSeed()]; }
/* —— 实时派生待办：直接从工作台真相（雪花 / 起草台 / 章节目录）算出来。
   修好即自动消失；不能被「无动作划掉」（live: true），只能去源头处理或稍后。
   id 带内容指纹：状况变化后会作为新条目重新浮现（即使曾稍后）。 —— */
function rvDerived() {
  const out = [];
  const stepName = (k) => { const s = (window.S2_STEPS || []).find(x => x.key === k); return s ? `${s.num} ${s.name}` : k; };
  /* 1）雪花 · 上游已改需复核 */
  try {
    const wb = window.s2ReadWorkbench ? window.s2ReadWorkbench() : null;
    if (wb && wb.per) Object.keys(wb.per).forEach(k => {
      const v = wb.per[k];
      if (!v || !v.stale) return;
      out.push({
        id: `lv-stale-${k}`, live: true, kind: "idea", priority: 1,
        title: `雪花「${stepName(k)}」上游已改 · 需复核`,
        where: `构思 · ${stepName(k)}`, source: "雪花构思", time: "实时",
        detail: `上游 ${(v.staleAncestors || []).map(stepName).join("、")} 在本步确认后发生改动。回去核对一致性后点「已复核」，这条会自动消失。`,
        actions: [{ label: "去复核", intent: "primary", op: "nav", to: "snowflake", step: k }, { label: "稍后再说", intent: "quiet", op: "snooze" }],
      });
    });
  } catch (e) {}
  /* 2）雪花 · 09 织线诊断 + 10 逐场覆盖率 */
  try {
    const st = window.s2ExportState ? window.s2ExportState() : null;
    const sc = st && st.scaffolds;
    const list = (sc && sc.scenes && sc.scenes.list) || [];
    if (list.length) {
      const noCru = list.filter(s => !(s.crucible || "").trim()).length;
      const pacing = window.s2PacingRuns ? window.s2PacingRuns(list) : { tight: [] };
      const tightMax = pacing.tight.length ? Math.max(...pacing.tight.map(r => r.len)) : 0;
      const probs = [];
      if (noCru) probs.push(`${noCru} 场缺坎埚（冲突）`);
      if (tightMax >= 3) probs.push(`连续 ${tightMax} 场主动、节奏紧绷`);
      if (probs.length) out.push({
        id: `lv-scenes-${noCru}-${tightMax}`, live: true, kind: "qc", priority: 2,
        title: `09 场景列表有 ${probs.length} 处结构问题`,
        where: "构思 · 09 场景列表", source: "织线诊断", time: "实时",
        detail: probs.join("；") + "。这些诊断与 09 画布上的同源，修好即自动消失。",
        actions: [{ label: "去 09 修", intent: "primary", op: "nav", to: "snowflake", step: "scenes" }, { label: "稍后再说", intent: "quiet", op: "snooze" }],
      });
      const plans = (sc.planning && sc.planning.plans) || {};
      const F = ["goal", "conflict", "setback", "reaction", "dilemma", "decision"];
      const planned = list.filter(s => { const p = plans[s.id]; return p && F.some(f => (p[f] || "").trim()); }).length;
      if (planned < list.length) out.push({
        id: `lv-plan-${planned}-${list.length}`, live: true, kind: "idea", priority: 2,
        title: `10 场景规划还差 ${list.length - planned} 场`,
        where: "构思 · 10 场景规划", source: "雪花构思", time: "实时",
        detail: `09 共 ${list.length} 场，已逐场规划 ${planned} 场。每场五分钟；规划全了，物化出的章节卡才带完整 GCS / RDD。`,
        actions: [{ label: "去 10 规划", intent: "primary", op: "nav", to: "snowflake", step: "planning" }, { label: "稍后再说", intent: "quiet", op: "snooze" }],
      });
    }
  } catch (e) {}
  /* 3）起草台 · AI 稿待裁决 */
  try {
    (window.scnQueueLoad ? window.scnQueueLoad() : []).forEach(sid => {
      const r = window.scnRunLoad ? window.scnRunLoad(sid) : null;
      if (!r || r.state !== "ready") return;
      const hit = window.WsCatalog ? window.WsCatalog.sceneById(sid) : null;
      const title = hit ? hit.scene.title : sid;
      out.push({
        id: `lv-run-${sid}-${r.attempt || 1}`, live: true, kind: "decision", priority: 1,
        title: `AI 稿待裁决：「${title}」`,
        where: hit ? `第 ${hit.chapter.n} 章 · ${title}` : title, source: "AI 起草台", time: "实时",
        detail: `第 ${r.attempt || 1} 次尝试${r.verdict ? ` · ${r.verdict.words} 字 · 质检${r.verdict.qc}` : " · 已过质检"}。采纳归档 / 退回重写 / 送深改，三选一。`,
        actions: [{ label: "去裁决", intent: "primary", op: "nav", to: "scene" }, { label: "稍后再说", intent: "quiet", op: "snooze" }],
      });
    });
  } catch (e) {}
  /* 4）长篇控制塔 · 设定冲突待裁决（与塔同一事实：任一侧裁决，另一侧同步消失） */
  try {
    (window.lf7PendingCanon ? window.lf7PendingCanon() : []).forEach(c => {
      const canRule = c.value && c.value !== "（待统一）";
      out.push({
        id: `lv-canon-${c.id}`, live: true, kind: c.drift ? "risk" : "decision", priority: c.drift ? 1 : 2,
        title: `设定冲突待裁决：${c.subject}`,
        where: `长篇控制塔 · 第 ${c.conflictCh} 章`, source: "长篇控制塔", time: "实时",
        detail: `${c.conflictText}。` + (canRule
          ? `控制塔建议以第 ${c.source} 章为准（${c.subject} = ${c.value}）；裁决后会锁定为设定锚点，装进下一章交接契约的强约束，塔里的同一条也会同步消失。`
          : `这条还没有可直接采纳的统一值，去控制塔裁决。`),
        actions: [
          ...(canRule ? [{ label: `统一为「${c.value}」并锁定`, intent: "primary", op: "bridge", canonId: c.id }] : []),
          { label: canRule ? "去控制塔细看" : "去控制塔裁决", intent: canRule ? "ghost" : "primary", op: "nav", to: "longform" },
          { label: "稍后再说", intent: "quiet", op: "snooze" },
        ],
      });
    });
  } catch (e) {}
  /* 5）目录 · 审阅中章节 / 全场已成稿可送审 */
  try {
    (window.WsCatalog ? window.WsCatalog.get() : []).forEach(c => {
      if (c.state === "review") {
        out.push({
          id: `lv-rev-${c.id}`, live: true, kind: "decision", priority: 1,
          title: `第 ${c.n} 章《${c.title}》待你批准`,
          where: `成稿中心 · 第 ${c.n} 章`, source: "成稿中心", time: "实时",
          detail: `本章 ${(c.scenes || []).length} 场、${((c.words && c.words.cur) || 0).toLocaleString()} 字，正在审阅中。批准为终稿，或退回小修。`,
          actions: [{ label: "去审阅", intent: "primary", op: "nav", to: "manuscripts" }, { label: "稍后再说", intent: "quiet", op: "snooze" }],
        });
      } else if (c.state === "writing") {
        const sc = c.scenes || [];
        if (sc.length && sc.every(s => s.state === "done"))
        {
          /* 塔台化：由控制塔下发的章（第 9 章）全场成稿后，先过章级审计再谈送审 */
          const tower9 = (() => { try { return parseInt(c.n, 10) === 9 && window.Lf7Bridge && !window.Lf7Bridge.isArchived(9) && !!window.Lf7Bridge.state().handoff9; } catch (e) { return false; } })();
          if (tower9) out.push({
            id: `lv-aud-${c.id}`, live: true, kind: "decision", priority: 1,
            title: `第 ${c.n} 章全场成稿 · 待控制塔章级审计`,
            where: `长篇控制塔 · 第 ${c.n} 章`, source: "长篇控制塔", time: "实时",
            detail: "起草台的逐场质检只管场内质量；跨场连续性（设定漂移 / 承诺回收 / 公平性）由控制塔章级审计把关。审计通过并归档后，本章才进成稿中心送审。",
            actions: [{ label: "去控制塔审计", intent: "primary", op: "nav", to: "longform" }, { label: "稍后再说", intent: "quiet", op: "snooze" }],
          });
          else out.push({
          id: `lv-sub-${c.id}`, live: true, kind: "qc", priority: 2,
          title: `第 ${c.n} 章全部场景已成稿 · 可送审`,
          where: `成稿中心 · 第 ${c.n} 章`, source: "成稿中心", time: "实时",
          detail: `《${c.title}》的 ${sc.length} 场全部完成。在成稿中心送入审阅，进入批准流程。`,
          actions: [{ label: "去送审", intent: "primary", op: "nav", to: "manuscripts" }, { label: "稍后再说", intent: "quiet", op: "snooze" }],
          });
        }
      }
    });
  } catch (e) {}
  return out;
}

function rvOpenItems() {
  const st = rvLoad();
  const gone = new Set([...(st.resolved || []), ...(st.snoozed || [])]);
  // 稳定排序：优先处理带在前，同带内保持投递/种子顺序
  return rvAllItems().filter(i => !gone.has(i.id))
    .sort((a, b) => (a.priority === 1 ? 0 : 1) - (b.priority === 1 ? 0 : 1));
}
function rvSnoozedList() {
  const st = rvLoad();
  const ids = new Set(st.snoozed || []);
  return rvAllItems().filter(i => ids.has(i.id));
}
const rvToday = () => new Date().toISOString().slice(0, 10);
function rvDoneToday() { const st = rvLoad(); return st.doneD === rvToday() ? (st.doneN || 0) : 0; }
function rvMarkResolved(ids) {
  const st = rvLoad();
  rvSave({
    resolved: [...new Set([...(st.resolved || []), ...ids])],
    snoozed: (st.snoozed || []).filter(x => !ids.includes(x)),
    doneD: rvToday(), doneN: rvDoneToday() + ids.length,
  });
}
function rvUnresolve(ids) {
  const st = rvLoad();
  rvSave({ resolved: (st.resolved || []).filter(x => !ids.includes(x)), doneD: rvToday(), doneN: Math.max(0, rvDoneToday() - ids.length) });
}
function rvMarkSnoozed(id) { const st = rvLoad(); rvSave({ snoozed: [...new Set([...(st.snoozed || []), id])] }); }
function rvUnsnooze(id) { const st = rvLoad(); rvSave({ snoozed: (st.snoozed || []).filter(x => x !== id) }); }
function rvIsResolved(id) { const st = rvLoad(); return (st.resolved || []).indexOf(id) >= 0; }
function rvBadge() { const n = rvOpenItems().filter(i => i.priority === 1).length; return n > 0 ? String(n) : null; }
function useReviewBadge() {
  const [, force] = React.useState(0);
  React.useEffect(() => {
    const bump = () => force(n => n + 1);
    window.addEventListener("ws:review-changed", bump);
    window.addEventListener("ws:work-changed", bump);
    window.addEventListener("ws:snow-saved", bump);   // 派生项跟雪花存盘同步
    window.addEventListener("lf:bridge-changed", bump); // 控制塔裁决同步
    const un = window.WsCatalog ? window.WsCatalog.subscribe(bump) : null;  // 目录变动同步
    return () => {
      window.removeEventListener("ws:review-changed", bump);
      window.removeEventListener("ws:work-changed", bump);
      window.removeEventListener("ws:snow-saved", bump);
      window.removeEventListener("lf:bridge-changed", bump);
      if (un) un();
    };
  }, []);
  return rvBadge();
}

function WsReview({ go }) {
  const [items, setItems] = React.useState(rvOpenItems);
  const [snoozed, setSnoozed] = React.useState(rvSnoozedList);
  const [filter, setFilter] = React.useState("all");
  const [openId, setOpenId] = React.useState(() => { const l = rvOpenItems(); return l[0] ? l[0].id : null; });
  const [removing, setRemoving] = React.useState(null);
  const [toast, setToast] = React.useState(null);
  const [doneToday, setDoneToday] = React.useState(rvDoneToday);
  const [showSnoozed, setShowSnoozed] = React.useState(false);
  const [selId, setSelId] = React.useState(() => { const l = rvOpenItems(); return l[0] ? l[0].id : null; });
  const [kbd, setKbd] = React.useState(false); // 是否用过键盘（点亮快捷键提示）

  React.useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 5200);
    return () => clearTimeout(id);
  }, [toast]);

  const counts = React.useMemo(() => {
    const c = { all: items.length };
    Object.keys(RV_KINDS).forEach(k => { c[k] = items.filter(i => i.kind === k).length; });
    return c;
  }, [items]);

  const resolve = (id) => {
    setRemoving(id);
    setTimeout(() => {
      setItems(prev => {
        const index = prev.findIndex(x => x.id === id);
        if (index < 0) return prev;
        setToast({ entries: [{ item: prev[index], index }], verb: "已处理" });
        return prev.filter(x => x.id !== id);
      });
      rvMarkResolved([id]);
      setDoneToday(n => n + 1);
      setRemoving(null);
    }, 300);
  };

  // 一键收尾：把当前筛选下的待办全部标记完成（整批可撤销）
  const resolveAll = () => {
    const pool = (filter === "all" ? items : items.filter(i => i.kind === filter));
    const ids = pool.filter(i => !needsChoice(i)).map(x => x.id);
    const skipped = pool.length - ids.length;
    if (!ids.length) { if (skipped) setToast({ entries: [], verb: "跳过", note: `${skipped} 条需要你拍板或去源头处理，不能批量划掉` }); return; }
    setRemoving("__all__");
    setTimeout(() => {
      setItems(prev => {
        const entries = ids.map(id => ({ item: prev.find(x => x.id === id), index: prev.findIndex(x => x.id === id) }))
          .filter(e => e.item).sort((a, b) => a.index - b.index);
        setToast({ entries, verb: "已处理" });
        return prev.filter(x => !ids.includes(x.id));
      });
      rvMarkResolved(ids);
      setDoneToday(n => n + ids.length);
      setRemoving(null);
    }, 300);
  };

  const snooze = (id) => {
    setRemoving(id);
    setTimeout(() => {
      setItems(prev => {
        const it = prev.find(x => x.id === id);
        if (it) setSnoozed(s => [it, ...s]);
        return prev.filter(x => x.id !== id);
      });
      rvMarkSnoozed(id);
      setRemoving(null);
    }, 300);
  };

  const unsnooze = (id) => {
    setSnoozed(prev => {
      const it = prev.find(x => x.id === id);
      if (it) setItems(list => [...list, it].sort((a, b) => a.priority - b.priority));
      return prev.filter(x => x.id !== id);
    });
    rvUnsnooze(id);
  };

  const undo = () => {
    if (!toast) return;
    const entries = toast.entries || [];
    /* 先回滚已应用到目录的效果，再恢复待办项 */
    entries.forEach(e => {
      const inv = inversesRef.current[e.item.id];
      if (inv) { runEffect(inv); delete inversesRef.current[e.item.id]; }
    });
    setItems(prev => {
      const next = [...prev];
      entries.slice().sort((a, b) => a.index - b.index).forEach(e => {
        next.splice(Math.min(e.index, next.length), 0, e.item);
      });
      return next;
    });
    rvUnresolve(entries.map(e => e.item.id));
    setDoneToday(n => Math.max(0, n - entries.length));
    setToast(null);
  };

  /* —— 待办动作的真实效果：写穿目录单一真相源，返回逆操作供撤销 —— */
  const inversesRef = React.useRef({});
  const runEffect = (eff) => {
    if (!eff || !window.WsCatalog) return null;
    try {
      if (eff.type === "renameChapter") {
        const old = window.WsCatalog.get().find(c => c.id === eff.ch);
        if (!old) return null;
        const inverse = { type: "renameChapter", ch: eff.ch, title: old.title };
        window.WsCatalog.set(window.WsCatalog.get().map(c => c.id === eff.ch ? { ...c, title: eff.title } : c));
        return inverse;
      }
      if (eff.type === "insertScene") {
        const ch = window.WsCatalog.get().find(c => c.id === eff.ch);
        if (!ch) return null;
        const at = Math.max(0, Math.min(eff.at != null ? eff.at : ch.scenes.length, ch.scenes.length));
        window.WsCatalog.set(window.WsCatalog.get().map(c => c.id !== eff.ch ? c : { ...c, scenes: [...c.scenes.slice(0, at), { ...eff.scene }, ...c.scenes.slice(at)] }));
        return { type: "removeSceneAt", ch: eff.ch, at };
      }
      if (eff.type === "removeSceneAt") {
        window.WsCatalog.set(window.WsCatalog.get().map(c => c.id !== eff.ch ? c : { ...c, scenes: c.scenes.filter((_, i) => i !== eff.at) }));
        return null;
      }
    } catch (e) {}
    return null;
  };

  /* 决策类待办（带真实效果或候选项）与实时派生项不允许被“无决策地划掉”：
     派生项只能去源头处理（修好自动消失）或稍后；快捷键 E / 全部处理完遇到它们改为展开 */
  const needsChoice = (it) => !!(it && (it.live || (it.actions || []).some(a => a.effect) || it.options));

  const act = (item, a) => {
    if (a.op === "nav" && a.to) {
      go(a.to);
      /* 带上下文深链：雪花步骤 / 写作器场景 / 深改姿态（与命令面板同一套事件） */
      if (a.step) setTimeout(() => window.dispatchEvent(new CustomEvent("ws:snow-step", { detail: a.step })), 60);
      if (a.scene) setTimeout(() => window.dispatchEvent(new CustomEvent("ws:writer-scene", { detail: a.scene })), 60);
      if (a.posture) setTimeout(() => window.dispatchEvent(new CustomEvent("ws:writer-posture", { detail: a.posture })), 110);
    }
    else if (a.op === "snooze") snooze(item.id);
    else if (a.op === "bridge") {
      /* 控制塔联动：裁决写入桥，塔与收件箱两侧同步 */
      try { if (window.Lf7Bridge && a.canonId) window.Lf7Bridge.ruleCanon(a.canonId); } catch (e) {}
      resolve(item.id);
    }
    else {
      const inverse = runEffect(a.effect);
      if (inverse) inversesRef.current[item.id] = inverse;
      resolve(item.id);
    }
  };

  const visible = filter === "all" ? items : items.filter(i => i.kind === filter);
  const decisionsLeft = items.filter(i => i.priority === 1).length;
  const allClear = items.length === 0;

  // keep selection valid when the filter / list changes
  React.useEffect(() => {
    if (!visible.some(x => x.id === selId)) setSelId(visible[0] ? visible[0].id : null);
  }, [filter, items]); // eslint-disable-line

  const ensureVisible = (id) => {
    const el = document.querySelector(`.rv-item[data-id="${id}"]`);
    const scroller = el && el.closest(".ws-content");
    if (!el || !scroller) return;
    const er = el.getBoundingClientRect(), sr = scroller.getBoundingClientRect();
    if (er.top < sr.top + 16) scroller.scrollTop -= (sr.top + 16 - er.top);
    else if (er.bottom > sr.bottom - 16) scroller.scrollTop += (er.bottom - (sr.bottom - 16));
  };

  // keyboard: j/k 浏览 · ↵ 展开 · e 处理 · s 稍后 · u 撤销
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target.tagName || "").toLowerCase();
      if (tag === "input" || tag === "textarea" || e.target.isContentEditable) return;
      if (!visible.length && e.key !== "u") return;
      const idx = Math.max(0, visible.findIndex(x => x.id === selId));
      const move = (d) => {
        const n = visible[(idx + d + visible.length) % visible.length];
        if (n) { setSelId(n.id); setKbd(true); requestAnimationFrame(() => ensureVisible(n.id)); }
      };
      switch (e.key) {
        case "j": case "ArrowDown": e.preventDefault(); setKbd(true); move(1); break;
        case "k": case "ArrowUp": e.preventDefault(); setKbd(true); move(-1); break;
        case "o": case "Enter": case " ":
          e.preventDefault(); setKbd(true); setOpenId(o => o === selId ? null : selId); break;
        case "e": {
          e.preventDefault(); setKbd(true);
          const cur = visible[idx];
          if (cur && needsChoice(cur)) { setOpenId(cur.id); break; } // 决策项：展开让你选，不默认划掉
          const next = visible[idx + 1] || visible[idx - 1];
          if (selId) resolve(selId);
          if (next) setSelId(next.id);
          break;
        }
        case "s": {
          e.preventDefault(); setKbd(true);
          const next = visible[idx + 1] || visible[idx - 1];
          if (selId) snooze(selId);
          if (next) setSelId(next.id);
          break;
        }
        case "u": e.preventDefault(); setKbd(true); undo(); break;
        default: break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, selId, toast]); // eslint-disable-line

  // band-aware render: insert a band header when the priority-band changes
  let lastBand = null;
  const rows = [];
  visible.forEach(it => {
    const band = it.priority === 1 ? 1 : 2;
    if (filter === "all" && band !== lastBand) {
      rows.push(<RvBand key={`b${band}`} band={band} />);
      lastBand = band;
    }
    rows.push(
      <RvItem key={it.id} item={it} selected={selId === it.id && kbd}
        open={openId === it.id} removing={removing === it.id || removing === "__all__"}
        onToggle={() => { setSelId(it.id); setOpenId(o => o === it.id ? null : it.id); }}
        onAct={(a) => act(it, a)} />
    );
  });

  const chips = [{ k: "all", label: "全部" }, ...Object.entries(RV_KINDS).map(([k, m]) => ({ k, label: m.label, tone: m.tone }))];

  return (
    <div className="ws-page ws-view rv">
      <header className="rv-head">
        <div className="rv-eyebrow"><I.Inbox size={13} /> 案头 · 需要你拍板的</div>
        <h1 className="rv-title">待办收件箱</h1>
        <p className="rv-sub">
          {allClear
            ? "都处理完了，回写作房间继续吧。"
            : <>今晚 <b>{items.length}</b> 条待处理{decisionsLeft ? <>，其中 <b className="rv-em">{decisionsLeft}</b> 条需要尽快决策</> : ""}。处理完就回去写。</>}
        </p>
      </header>

      {!allClear && (
        <div className="rv-toolbar">
          <div className="rv-chips" role="tablist" aria-label="按类型筛选">
            {chips.map(c => {
              const n = counts[c.k] || 0;
              if (c.k !== "all" && n === 0) return null;
              return (
                <button key={c.k} role="tab" aria-selected={filter === c.k}
                  className={`rv-chip ${filter === c.k ? "is-active" : ""} ${c.tone ? `t-${c.tone}` : ""}`}
                  onClick={() => setFilter(c.k)}>
                  {c.tone && <span className="rv-chip-dot" />}
                  <span>{c.label}</span>
                  <span className="rv-chip-n">{n}</span>
                </button>
              );
            })}
          </div>
          <div className="rv-toolbar-right">
            <div className="rv-progress" title="今日已处理">
              <I.CheckCircle size={14} /> 今日已处理 <b>{doneToday}</b>
            </div>
            {visible.length > 1 && (
              <button className="rv-clear-all" onClick={resolveAll}
                title={filter === "all" ? "把全部待办标记完成" : "把这一类待办标记完成"}>
                <I.Check size={14} /> 全部处理完
              </button>
            )}
          </div>
        </div>
      )}

      {!allClear && (
        <div className={`rv-kbd-hint ${kbd ? "is-lit" : ""}`} aria-hidden="true">
          <kbd>J</kbd><kbd>K</kbd><span>浏览</span>
          <kbd>↵</kbd><span>展开</span>
          <kbd>E</kbd><span>处理</span>
          <kbd>S</kbd><span>稍后</span>
          <kbd>U</kbd><span>撤销</span>
        </div>
      )}

      {allClear ? (
        <RvEmpty hasSnoozed={snoozed.length > 0} go={go} />
      ) : (
        <div className="rv-list">
          {rows}
          {visible.length === 0 && (
            <div className="rv-none">这一类暂时没有待办。<button className="rv-link" onClick={() => setFilter("all")}>看全部</button></div>
          )}
        </div>
      )}

      {snoozed.length > 0 && (
        <div className="rv-snoozed">
          <button className="rv-snoozed-head" onClick={() => setShowSnoozed(s => !s)}>
            <I.Clock size={14} />
            <span>稍后处理</span>
            <span className="rv-snoozed-n">{snoozed.length}</span>
            <span className="rv-snoozed-chev" data-open={showSnoozed}><I.ChevronDown size={15} /></span>
          </button>
          {showSnoozed && (
            <div className="rv-snoozed-list">
              {snoozed.map(it => {
                const m = RV_KINDS[it.kind];
                return (
                  <div key={it.id} className="rv-snoozed-item">
                    <span className={`pill pill-${m.tone} text-xs`}><span className="pill-dot" />{m.label}</span>
                    <span className="rv-snoozed-title">{it.title}</span>
                    <button className="btn btn-quiet btn-sm" onClick={() => unsnooze(it.id)}><I.Refresh size={13} /> 恢复</button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {toast && ReactDOM.createPortal(
        <div className="rv-toast" role="status">
          <span className="rv-toast-tick"><I.Check size={14} /></span>
          <span className="rv-toast-text">
            {toast.note
              ? toast.note
              : toast.entries && toast.entries.length === 1
                ? <>{toast.verb}「{toast.entries[0].item.title}」</>
                : <>{toast.verb} {toast.entries ? toast.entries.length : 0} 条待办</>}
          </span>
          {(!toast.note) && <button className="rv-toast-undo" onClick={undo}><I.Refresh size={13} /> 撤销</button>}
        </div>, document.body)}
    </div>
  );
}

function RvBand({ band }) {
  const b = RV_BAND[band];
  return (
    <div className={`rv-band b-${band}`}>
      <span className="rv-band-label">{b.label}</span>
      <span className="rv-band-hint">{b.hint}</span>
      <span className="rv-band-rule" />
    </div>
  );
}

function RvItem({ item, open, removing, selected, onToggle, onAct }) {
  const m = RV_KINDS[item.kind];
  const Ic = I[m.icon] || I.Dot;
  return (
    <article data-id={item.id} className={`rv-item t-${m.tone} ${open ? "is-open" : ""} ${removing ? "is-removing" : ""} ${selected ? "is-sel" : ""} ${item.priority === 1 ? "is-hot" : ""}`}>
      <span className="rv-spine" aria-hidden="true" />
      <div className="rv-body">
        <button className="rv-row" onClick={onToggle} aria-expanded={open}>
          <span className="rv-kind"><Ic size={15} /></span>
          <div className="rv-row-main">
            <div className="rv-meta">
              <span className={`pill pill-${m.tone} text-xs`}><span className="pill-dot" />{m.label}</span>
              <span className="rv-where">{item.where}</span>
            </div>
            <h3 className="rv-item-title">{item.title}</h3>
          </div>
          <span className="rv-time">{item.time}</span>
          <span className="rv-chev" data-open={open}><I.ChevronDown size={16} /></span>
        </button>

        <div className="rv-detail" data-open={open}>
          <div className="rv-detail-inner">
            <p className="rv-detail-text">{item.detail}</p>

            {item.preview && (
              <div className="rv-preview">
                <div className="rv-preview-row"><span className="rv-preview-tag">原</span><span className="rv-preview-old">{item.preview.before}</span></div>
                <div className="rv-preview-row"><span className="rv-preview-tag is-new">改</span><span className="rv-preview-new">{item.preview.after}</span></div>
              </div>
            )}

            {item.checklist && (
              <ul className="rv-checklist">
                {item.checklist.map((c, i) => <li key={i}><I.Circle size={11} /> {c}</li>)}
              </ul>
            )}

            {item.options && (
              <div className="rv-options">
                {item.options.map((o, i) => <span key={i} className="rv-option">{o}</span>)}
              </div>
            )}

            <div className="rv-src"><I.ArrowRight size={12} /> 来自 {item.source}</div>
          </div>
        </div>

        <div className="rv-actions">
          {item.actions.map((a, i) => {
            const cls = a.intent === "primary" ? "btn btn-accent btn-sm"
              : a.intent === "ghost" ? "btn btn-ghost btn-sm" : "btn btn-quiet btn-sm";
            return <button key={i} className={cls} onClick={() => onAct(a)}>{a.label}</button>;
          })}
        </div>
      </div>
    </article>
  );
}

function RvEmpty({ hasSnoozed, go }) {
  return (
    <div className="rv-empty">
      <div className="rv-empty-mark"><I.CheckCircle size={30} /></div>
      <div className="rv-empty-title">收件箱清空了</div>
      <p className="rv-empty-sub">{hasSnoozed ? "当前待办都处理完了，还有几条在「稍后处理」里等着。" : "需要你拍板的都处理完了，回到写作房间继续吧。"}</p>
      <button className="btn btn-accent btn-lg" onClick={() => go("writer")}><I.Pen size={16} /> 进入写作房间</button>
    </div>
  );
}

Object.assign(window, { WsReview, RV_SEED, RV_KINDS, rvOpenItems, rvMarkResolved, rvPush, rvCustomList, rvIsResolved, useReviewBadge });
