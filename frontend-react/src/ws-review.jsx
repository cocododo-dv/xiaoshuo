import React from "react";
import ReactDOM from "react-dom";
import { I } from "./icons.jsx";
import { apiGet, apiPost } from "./lib/client.js";
import { WsWorks, wsKey } from "./ws-works.jsx";
import { WsCatalog } from "./ws-catalog.jsx";

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
const RV_BAND = { 1: { label: "优先处理", hint: "需要你尽快拍板" }, 2: { label: "其余待办", hint: "建议与提示，得空再看" } };

/* ==========================================================
   store —— FE-ALIGN Phase 5：接真后端统一收件箱。
   GET /api/v1/review-items?state=open|snoozed&project_id=…
   = 持久卡 ∪ 实时派生卡（派生由后端从工作台真相现算：
   不可划掉 / 修好自动消失 / 指纹变化复浮现）。
   resolve 的 effect 在后端同一事务执行（D4）；视图通过
   window.rvResolveAction 钩子告知本次点击的动作，store 把
   action_index 带给 resolve 端点。
   「今日已处理 N 件」是 UI 偏好级计数，留 localStorage。
   ========================================================== */
const RV_DONE_LS = "ws_review_done_v1";
const RV_MIGRATED_LS = "ws_review_migrated_v1";
const RV_LEGACY_LS = "ws_review_v1";

const rvActiveId = () => { try { return WsWorks ? WsWorks.activeId() : null; } catch (e) { return null; } };

function rvAgo(t) {
  const m = Math.floor((Date.now() - t) / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return m + " 分钟前";
  const h = Math.floor(m / 60);
  if (h < 24) return h + " 小时前";
  return Math.floor(h / 24) + " 天前";
}

/* 后端卡片 → 视图条目（形状=契约附录卡片形状） */
function rvAdapt(card) {
  const occurred = card.occurred_at ? Date.parse(card.occurred_at) : NaN;
  return {
    id: card.id,
    kind: card.kind || "note",
    priority: card.priority || 2,
    title: card.title,
    where: card.where || "",
    source: card.source || "",
    time: card.live ? "实时" : (Number.isNaN(occurred) ? "" : rvAgo(occurred)),
    detail: card.detail || "",
    preview: card.preview || undefined,
    checklist: card.checklist || undefined,
    options: card.options || undefined,
    live: !!card.live,
    actions: (card.actions || []).map(a => ({
      label: a.label,
      intent: a.intent || "ghost",
      op: a.op === "nav" ? "nav" : a.op === "snooze" ? "snooze" : a.op === "bridge" ? "bridge" : "resolve",
      to: a.nav_to || a.to,
      step: a.nav_step || a.step,
      scene: a.nav_scene || a.scene,
      posture: a.nav_posture || a.posture,
      canonId: a.canon_id || a.canonId,
      /* 后端 effect 不在前端执行（D4）；保留占位对象让视图的
         needsChoice 守卫（带效果的卡不允许批量划掉）继续生效 */
      effect: a.effect ? { type: "__backend__" } : undefined,
    })),
  };
}

/* 视图/调用方条目 → 后端卡片载荷（rvPush 用） */
function rvToPayload(item) {
  return {
    project_id: rvActiveId(),
    kind: item.kind || "note",
    priority: item.priority || 2,
    title: item.title,
    source: item.source || "",
    where: item.where || "",
    detail: item.detail || "",
    preview: item.preview,
    checklist: item.checklist,
    options: item.options,
    dedupe_key: item.dedupeKey || item.dedupe_key,
    actions: (item.actions || [{ label: "知道了", intent: "quiet", op: "resolve" }]).map(a => ({
      label: a.label,
      intent: a.intent,
      op: a.op,
      nav_to: a.to,
      nav_step: a.step,
      nav_scene: a.scene,
      nav_posture: a.posture,
      effect: a.effect && a.effect.type !== "__backend__" ? a.effect : undefined,
    })),
  };
}

let rvCache = { open: [], snoozed: [] };
const rvResolvedSet = new Set();          // 本会话内已处理 id（rvIsResolved 用）
const rvPendingAction = {};               // id → 本次点击的 action_index（resolve 携带）

function rvEmit() { try { window.dispatchEvent(new CustomEvent("ws:review-changed")); } catch (e) {} }

let rvFetching = null;
function rvFetch() {
  const pid = rvActiveId();
  if (!pid || pid === "__loading__") return Promise.resolve();
  if (rvFetching) return rvFetching;
  rvFetching = (async () => {
    try {
      await rvMigrateLegacy(pid);
      const [open, snoozed] = await Promise.all([
        apiGet(`/api/v1/review-items?state=open&project_id=${encodeURIComponent(pid)}`),
        apiGet(`/api/v1/review-items?state=snoozed&project_id=${encodeURIComponent(pid)}`),
      ]);
      rvCache = {
        open: ((open && open.items) || []).map(rvAdapt),
        snoozed: ((snoozed && snoozed.items) || []).map(rvAdapt),
      };
      rvEmit();
    } catch (e) {
      console.warn("[WsReview] 拉取收件箱失败:", e);
    } finally {
      rvFetching = null;
    }
  })();
  return rvFetching;
}

let rvFetchTimer = null;
function rvFetchDebounced() {
  clearTimeout(rvFetchTimer);
  rvFetchTimer = setTimeout(() => { rvFetch(); }, 600);
}

/* 一次性迁移：旧 localStorage 的 custom 项上行（resolved/snoozed 状态迁不动则丢弃——卡片可再生） */
async function rvMigrateLegacy(pid) {
  try {
    const flagKey = RV_MIGRATED_LS + "::" + pid;
    if (localStorage.getItem(flagKey)) return;
    const raw = localStorage.getItem((wsKey ? wsKey(RV_LEGACY_LS) : RV_LEGACY_LS));
    const st = raw ? JSON.parse(raw) : null;
    const custom = (st && st.custom) || [];
    for (const it of custom) {
      if (!it || !it.title) continue;
      try { await apiPost("/api/v1/review-items", rvToPayload(it)); } catch (e) {}
    }
    localStorage.setItem(flagKey, new Date().toISOString());
  } catch (e) {}
}

function rvCustomList() { return rvCache.open.filter(i => !i.live); }

function rvPush(item) {
  const payload = rvToPayload(item || {});
  apiPost("/api/v1/review-items", payload).then(() => rvFetch()).catch((e) => {
    console.warn("[WsReview] 投递待办失败:", e);
  });
  return "pending"; // 旧签名返回 id；真实 id 由刷新后的列表供给
}

function rvOpenItems() {
  return rvCache.open.slice().sort((a, b) => (a.priority === 1 ? 0 : 1) - (b.priority === 1 ? 0 : 1));
}
function rvSnoozedList() { return rvCache.snoozed; }

const rvToday = () => new Date().toISOString().slice(0, 10);
function rvDoneState() {
  try { return JSON.parse(localStorage.getItem(RV_DONE_LS)) || {}; } catch (e) { return {}; }
}
function rvDoneToday() { const st = rvDoneState(); return st.d === rvToday() ? (st.n || 0) : 0; }
function rvBumpDone(delta) {
  try { localStorage.setItem(RV_DONE_LS, JSON.stringify({ d: rvToday(), n: Math.max(0, rvDoneToday() + delta) })); } catch (e) {}
}

/* 视图在执行动作时经此钩子告知「点了哪个动作」（act() 的单行接缝） */
function rvResolveAction(item, action) {
  if (!item || !action) return;
  const index = (item.actions || []).indexOf(action);
  if (index >= 0) rvPendingAction[item.id] = index;
}

function rvMarkResolved(ids) {
  const pid = rvActiveId();
  (ids || []).forEach(id => rvResolvedSet.add(id));
  rvCache = { ...rvCache, open: rvCache.open.filter(i => !ids.includes(i.id)) };
  rvBumpDone((ids || []).length);
  rvEmit();
  (async () => {
    for (const id of ids || []) {
      const body = { project_id: pid };
      if (rvPendingAction[id] != null) { body.action_index = rvPendingAction[id]; delete rvPendingAction[id]; }
      try { await apiPost(`/api/v1/review-items/${encodeURIComponent(id)}/resolve`, body); }
      catch (e) {
        try { window.alert((e && e.message) || "处理失败。"); } catch (e2) {}
      }
    }
    rvFetch();
  })();
}

function rvUnresolve(ids) {
  (ids || []).forEach(id => rvResolvedSet.delete(id));
  rvBumpDone(-(ids || []).length);
  (async () => {
    for (const id of ids || []) {
      try { await apiPost(`/api/v1/review-items/${encodeURIComponent(id)}/unresolve`, {}); } catch (e) {}
    }
    rvFetch();
  })();
}

function rvMarkSnoozed(id) {
  const pid = rvActiveId();
  const it = rvCache.open.find(x => x.id === id);
  rvCache = {
    open: rvCache.open.filter(x => x.id !== id),
    snoozed: it ? [it, ...rvCache.snoozed] : rvCache.snoozed,
  };
  rvEmit();
  apiPost(`/api/v1/review-items/${encodeURIComponent(id)}/snooze`, { project_id: pid })
    .then(() => rvFetch())
    .catch(() => rvFetch());
}

function rvUnsnooze(id) {
  const pid = rvActiveId();
  apiPost(`/api/v1/review-items/${encodeURIComponent(id)}/unsnooze`, { project_id: pid })
    .then(() => rvFetch())
    .catch(() => rvFetch());
}

function rvIsResolved(id) { return rvResolvedSet.has(id); }
function rvBadge() { const n = rvCache.open.filter(i => i.priority === 1).length; return n > 0 ? String(n) : null; }

function useReviewBadge() {
  const [, force] = React.useState(0);
  React.useEffect(() => {
    const bump = () => force(n => n + 1);
    window.addEventListener("ws:review-changed", bump);
    window.addEventListener("ws:work-changed", bump);
    window.addEventListener("ws:snow-saved", bump);   // 派生项跟雪花存盘同步
    window.addEventListener("lf:bridge-changed", bump); // 控制塔裁决同步
    const un = WsCatalog ? WsCatalog.subscribe(bump) : null;  // 目录变动同步
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

/* 启动装载 + 真相变动时刷新（派生卡在后端现算，目录/作品切换都可能改变它们） */
try { rvFetch(); } catch (e) {}
window.addEventListener("ws:work-changed", () => { try { rvFetchDebounced(); } catch (e) {} });
window.addEventListener("ws:trash-changed", () => { try { rvFetchDebounced(); } catch (e) {} });
try { if (WsCatalog) WsCatalog.subscribe(() => rvFetchDebounced()); } catch (e) {}
/* 进入待办视图时刷新一轮（外部投递的卡即时可见） */
window.addEventListener("hashchange", () => {
  try { if ((location.hash || "").includes("review")) rvFetchDebounced(); } catch (e) {}
});
Object.assign(window, { rvResolveAction });


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

  /* FE-ALIGN P6 接缝：store 改为异步后端装载后，缓存更新（后端刷新/外部投递）
     需同步进视图列表 —— 原型是同步 localStorage 读，无需此订阅 */
  React.useEffect(() => {
    const sync = () => { setItems(rvOpenItems()); setSnoozed(rvSnoozedList()); };
    window.addEventListener("ws:review-changed", sync);
    return () => window.removeEventListener("ws:review-changed", sync);
  }, []);

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
    if (!eff || !WsCatalog) return null;
    try {
      if (eff.type === "renameChapter") {
        const old = WsCatalog.get().find(c => c.id === eff.ch);
        if (!old) return null;
        const inverse = { type: "renameChapter", ch: eff.ch, title: old.title };
        WsCatalog.set(WsCatalog.get().map(c => c.id === eff.ch ? { ...c, title: eff.title } : c));
        return inverse;
      }
      if (eff.type === "insertScene") {
        const ch = WsCatalog.get().find(c => c.id === eff.ch);
        if (!ch) return null;
        const at = Math.max(0, Math.min(eff.at != null ? eff.at : ch.scenes.length, ch.scenes.length));
        WsCatalog.set(WsCatalog.get().map(c => c.id !== eff.ch ? c : { ...c, scenes: [...c.scenes.slice(0, at), { ...eff.scene }, ...c.scenes.slice(at)] }));
        return { type: "removeSceneAt", ch: eff.ch, at };
      }
      if (eff.type === "removeSceneAt") {
        WsCatalog.set(WsCatalog.get().map(c => c.id !== eff.ch ? c : { ...c, scenes: c.scenes.filter((_, i) => i !== eff.at) }));
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
      /* AI 起草台深链（管线 blocked 稿卡片）：入列惯用法——挂载读 __scnEnqueue，
         已挂载走 ws:scene-enqueue 事件（与写作台 forkAI / 构思「去 AI 起草」同源） */
      if (a.to === "scene" && a.scene) window.__scnEnqueue = { sid: a.scene };
      go(a.to);
      /* 带上下文深链：雪花步骤 / 写作器场景 / 深改姿态（与命令面板同一套事件） */
      if (a.step) setTimeout(() => window.dispatchEvent(new CustomEvent("ws:snow-step", { detail: a.step })), 60);
      if (a.scene && a.to === "scene") setTimeout(() => window.dispatchEvent(new CustomEvent("ws:scene-enqueue", { detail: { sid: a.scene } })), 80);
      else if (a.scene) setTimeout(() => window.dispatchEvent(new CustomEvent("ws:writer-scene", { detail: a.scene })), 60);
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
      /* FE-ALIGN P5 接缝：effect 已后端化（D4），store 需要知道点了哪个动作 */
      if (window.rvResolveAction) { try { window.rvResolveAction(item, a); } catch (e) {} }
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

Object.assign(window, { WsReview, RV_KINDS, rvOpenItems, rvMarkResolved, rvPush, rvCustomList, rvIsResolved, useReviewBadge });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { WsReview, RV_KINDS, rvOpenItems, rvMarkResolved, rvPush, rvCustomList, rvIsResolved, useReviewBadge };
