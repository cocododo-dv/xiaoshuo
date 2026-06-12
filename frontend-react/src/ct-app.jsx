import React from "react";
import ReactDOM from "react-dom";
import { I } from "./icons.jsx";
import { CT_LAYERS, CT_STATE, CT_TRACK, ctBlastRadius, ctLayer, ctLayerName } from "./ct-data.jsx";
import { CTStructureMap, CTWeaveMap } from "./ct-map.jsx";
import { CTContinuity, CTDownstream, CTInspector, CTQualityMatrix, CTSpinePanel } from "./ct-panels.jsx";
import { CTLiveEdit, CT_INITIAL_SIGNALS, ctDerive } from "./ct-edit.jsx";
import { WsWorks } from "./ws-works.jsx";

/* global React, ReactDOM, I, CT_LAYERS, CT_TRACK, CT_STATE,
   CTStructureMap, CTSpinePanel, CTInspector, CTQualityMatrix, CTContinuity, CTDownstream, CTLiveEdit,
   CT_INITIAL_SIGNALS, ctDerive, ctBlastRadius, ctLayer */
/* ==========================================================
   构思控制塔 — 应用壳层（signals 单一数据源 + 实时派生）
   ========================================================== */
const { useState: useAS, useEffect: useAE, useMemo: useAM } = React;

const CT_TABS = [
  { id: "map",        label: "结构图谱", icon: "GitBranch" },
  { id: "weave",      label: "织线图谱", icon: "Activity" },
  { id: "quality",    label: "质量矩阵", icon: "Grid" },
  { id: "continuity", label: "连续性",   icon: "ShieldCheck" },
  { id: "downstream", label: "下游交付", icon: "Layout" },
];
const CT_EDITABLE = ["outline", "backstory", "characters"];

/* 工作台 → 控制塔同源叠加：用逐步工作台的真实 state / 需复核 / 实时五维健康度，
   覆盖控制塔的静态种子；可编辑层(04/06/07)与 09 场景仍走 ctDerive 的 what-if 引擎。 */
const CT_WB_STATE = { done: "approved", active: "active", warn: "draft", skip: "draft", todo: "draft" };
/* 全部 10 层都用工作台的实时五维健康度；正在 what-if 实时编辑的那一层除外
  （给模拟信号留出推演空间，关闭编辑即回到真实值）。空白层诚实归零。 */
function ctApplyWorkbench(d, wb, skipKey) {
  if (!wb || !wb.per) return d;
  const layers = d.layers.map(l => {
    const w = wb.per[l.key];
    if (!w) return l;
    const state = w.stale ? "stale" : (CT_WB_STATE[w.state] || l.state);
    const out = { ...l, state };
    if (w.stale) {
      const names = w.staleAncestors.map(a => (ctLayerName ? ctLayerName(a) : a)).join("、");
      out.staleReason = `上游 ${names} 在本层确认后已改动，需同步复核一致性。`;
    } else {
      delete out.staleReason;
    }
    if (l.key !== skipKey) {
      out.health = w.hasContent
        ? { score: w.score, dims: { ...l.health.dims, ...w.dims } }
        : { score: 0, dims: Object.fromEntries(Object.keys(l.health.dims).map(k => [k, 0])), empty: true };
    }
    return out;
  });
  const layerMap = Object.fromEntries(layers.map(l => [l.key, l]));
  const metrics = {
    ...d.metrics,
    health: Math.round(layers.reduce((a, l) => a + l.health.score, 0) / layers.length),
    approved: layers.filter(l => l.state === "approved").length,
    stale: layers.filter(l => l.state === "stale").length,
  };
  return { ...d, layers, layerMap, metrics };
}

function ControlTower({ onOpenStep, go }) {
  const embedded = !!onOpenStep;
  const [tab, setTab] = useAS("map");
  const [selected, setSelected] = useAS("paragraph");
  const [armed, setArmed] = useAS(null);
  const [editing, setEditing] = useAS(null);     // 正在实时编辑的层 key
  const [toast, setToast] = useAS(null);
  const [signals, setSignals] = useAS(() => JSON.parse(JSON.stringify(CT_INITIAL_SIGNALS)));
  const openStep = (k) => { if (k && k !== "materialize" && onOpenStep) onOpenStep(k); };
  const writeScene = (s) => {
    const sid = s && s.id;
    if (go) {
      go("writer");
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent("ws:writer-scene", { detail: sid }));
        window.dispatchEvent(new CustomEvent("ws:snow-source", { detail: s }));
      }, 60);
    } else console.log("write scene in writer room:", sid);
  };

  /* 单一数据源：signals → ctDerive 派生，再叠加工作台真实状态（同源） */
  const [wb, setWb] = useAS(() => (window.s2ReadWorkbench ? window.s2ReadWorkbench() : null));
  useAE(() => {
    const refresh = () => setWb(window.s2ReadWorkbench ? window.s2ReadWorkbench() : null);
    window.addEventListener("ws:snow-saved", refresh);
    window.addEventListener("storage", refresh);
    return () => { window.removeEventListener("ws:snow-saved", refresh); window.removeEventListener("storage", refresh); };
  }, []);
  const derived = useAM(() => ctDerive(signals), [signals]);
  const { layers, layerMap, continuity, spine, metrics } = useAM(() => ctApplyWorkbench(derived, wb, editing), [derived, wb, editing]);

  const select = (k) => {
    if (k && k !== "materialize") {
      setSelected(k);
      setArmed(null);
      if (editing) setEditing(CT_EDITABLE.includes(k) ? k : null);
    }
  };
  const arm = (k) => { setArmed(k); setEditing(null); if (k) setSelected(k); };
  const startEdit = (k) => { setEditing(k); setArmed(null); setSelected(k); };
  const setSignal = (layerKey, fieldKey, value) => {
    setSignals(prev => ({ ...prev, [layerKey]: { ...prev[layerKey], [fieldKey]: value } }));
  };
  const cascade = (k) => {
    const blast = [...ctBlastRadius(k)].filter(x => x !== "materialize");
    setToast(`已排队级联重生成 ${blast.length} 个下游层 · 等待逐层确认`);
    setArmed(null);
    setTimeout(() => setToast(null), 4200);
  };

  useAE(() => { document.documentElement.setAttribute("data-theme", "light"); }, []);
  /* 深链：雪花顶栏「整理为章节结构」等入口直接打开某个页签 */
  useAE(() => {
    const onTab = (e) => { if (e.detail && CT_TABS.some(t => t.id === e.detail)) setTab(e.detail); };
    window.addEventListener("ws:ct-tab", onTab);
    return () => window.removeEventListener("ws:ct-tab", onTab);
  }, []);

  const headerMetrics = [
    { label: "结构强度", val: metrics.health, suffix: "", tone: "ink", big: true },
    { label: "已确认层", val: `${metrics.approved}`, suffix: "/10", tone: "sage" },
    { label: "连续性告警", val: metrics.alerts, suffix: "", tone: metrics.alerts ? "rose" : "sage" },
    { label: "待复核", val: metrics.stale, suffix: "", tone: "gold" },
  ];

  const editableHint = CT_EDITABLE;

  return (
    <div className="ct-root">
      <header className="ct-header">
        <div className="ct-brand">
          {!embedded && <span className="ct-brand-mark">汐</span>}
          <div className="ct-brand-text">
            <div className="ct-brand-eyebrow">构思 · 控制塔</div>
            <h1 className="ct-brand-title">{WsWorks ? WsWorks.active().title : "潮汐档案"} · 雪花结构总览</h1>
          </div>
        </div>
        <div className="ct-metrics">
          {headerMetrics.map(m => (
            <div key={m.label} className={`ct-metric ${m.big ? "is-big" : ""}`}>
              <span key={m.val} className={`ct-metric-val tone-${m.tone} ct-metric-pop`}>{m.val}<small>{m.suffix}</small></span>
              <span className="ct-metric-label">{m.label}</span>
            </div>
          ))}
        </div>
        <div className="ct-header-actions">
          <div className="ct-viewtoggle" role="tablist">
            <button className="is-active" role="tab"><I.Grid size={13} /> 总览</button>
            <button role="tab" onClick={() => openStep(selected)} title="在逐步工作台中打开当前层"><I.Layers size={13} /> 逐步</button>
          </div>
          <button className="btn btn-accent btn-sm" onClick={() => setTab("downstream")}><I.Layout size={13} /> 整理成章节结构</button>
        </div>
      </header>

      <nav className="ct-tabs">
        {CT_TABS.map(t => (
          <button key={t.id} className={`ct-tab ${tab === t.id ? "is-active" : ""}`} onClick={() => setTab(t.id)}>
            {React.createElement(I[t.icon], { size: 14 })}{t.label}
            {t.id === "continuity" && metrics.alerts > 0 && <span className="ct-tab-badge">{metrics.alerts}</span>}
          </button>
        ))}
        <div className="ct-tabs-hint"><I.Info size={12} /> 一屏俯视全部 10 层 · 依赖 · 健康度 · 脊柱绑定</div>
      </nav>

      <div className="ct-body">
        <main className="ct-main">
          {tab === "map" && <CTStructureMap layers={layers} selected={selected} onSelect={select} armed={armed} onArm={arm} />}
          {tab === "weave" && <CTWeaveMap onOpenStep={openStep} />}
          {tab === "quality" && <CTQualityMatrix layers={layers} onSelect={select} />}
          {tab === "continuity" && <CTContinuity items={continuity} onSelect={select} />}
          {tab === "downstream" && <CTDownstream layerMap={layerMap} onSelect={(k) => { setTab("map"); select(k); }} onWriteScene={writeScene} onOpenStep={openStep} />}
        </main>

        <aside className="ct-rail">
          <CTSpinePanel spine={spine} onJump={(k) => { setTab("map"); select(k); }} />
          {editing ? (
            <CTLiveEdit layerKey={editing} signals={signals} onSignal={setSignal}
              layerMap={layerMap} continuity={continuity} spine={spine}
              onClose={() => setEditing(null)} onSelect={select} onOpenStep={openStep} />
          ) : (
            <CTInspector layer={layerMap[selected]} armed={armed} onArm={arm}
              onSelect={select} onCascade={cascade}
              editable={editableHint.includes(selected)} onEdit={startEdit} onOpenStep={openStep} />
          )}
        </aside>
      </div>

      {toast && <div className="ct-toast"><span className="ct-toast-dot"><I.Refresh size={13} /></span>{toast}</div>}
    </div>
  );
}

Object.assign(window, { ControlTower });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { ControlTower };
