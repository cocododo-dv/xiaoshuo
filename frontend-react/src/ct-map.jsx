import React from "react";
import { I } from "./icons.jsx";
import { CT_LAYERS, CT_STATE, CT_TRACK, ctBlastRadius, ctLayer } from "./ct-data.jsx";
import { WsWorks, wsKey } from "./ws-works.jsx";

/* global React, I, CT_LAYERS, CT_TRACK, CT_STATE, ctLayer, ctBlastRadius */
/* ==========================================================
   构思控制塔 — 结构图谱 (fractal dependency DAG + blast radius)
   ========================================================== */
const { useState: useMS } = React;

/* 固定坐标布局：脊柱居中，情节链走左、角色链走右，下端汇入「整理」。 */
const CT_NODE_W = 216;
const CT_NODE_H = 58;
const CT_MAP_W = 580;
const CT_MAP_H = 736;
const CT_POS = {
  audience:    { x: 182, y: 14 },
  logline:     { x: 182, y: 100 },
  paragraph:   { x: 182, y: 186 },   // 脊柱
  characters:  { x: 348, y: 290 },
  synopsis:    { x: 16,  y: 290 },
  backstory:   { x: 348, y: 376 },
  outline:     { x: 16,  y: 376 },
  profile:     { x: 348, y: 462 },
  scenes:      { x: 16,  y: 462 },
  planning:    { x: 16,  y: 558 },
  materialize: { x: 182, y: 652 },
};
const CT_MAT_NODE = { key: "materialize", num: "→", name: "整理成章节结构", track: "plot" };

function ctCenter(key) {
  const p = CT_POS[key];
  return { cx: p.x + CT_NODE_W / 2, cy: p.y + CT_NODE_H / 2, x: p.x, y: p.y };
}
/* 所有依赖边 */
function ctEdges() {
  const edges = [];
  CT_LAYERS.forEach(l => l.feeds.forEach(f => edges.push({ from: l.key, to: f })));
  return edges;
}
/* 一条边的贝塞尔路径：从源节点底/侧 → 目标节点顶/侧 */
function ctEdgePath(from, to) {
  const a = ctCenter(from), b = ctCenter(to);
  const ax = a.cx, ay = a.y + CT_NODE_H;          // 源底部中点
  const bx = b.cx, by = b.y;                        // 目标顶部中点
  const dy = Math.max(28, (by - ay) * 0.5);
  return `M ${ax} ${ay} C ${ax} ${ay + dy}, ${bx} ${by - dy}, ${bx} ${by}`;
}

function CTStructureMap({ layers, selected, onSelect, armed, onArm }) {
  const [hover, setHover] = useMS(null);
  const blast = armed ? ctBlastRadius(armed) : new Set();
  const edges = ctEdges();
  const liveMap = Object.fromEntries((layers || CT_LAYERS).map(l => [l.key, l]));

  /* 边高亮：armed 模式下属于影响链；否则连着 hover 或 selected。
     节点变暗只在 hover 时发生（持久选中不应让整张图变灰）。 */
  const focusKey = hover || selected;
  const edgeActive = (e) => {
    if (armed) return (e.from === armed || blast.has(e.from)) && (blast.has(e.to) || e.to === "materialize" && blast.has("materialize"));
    if (!focusKey) return false;
    return e.from === focusKey || e.to === focusKey;
  };
  const isNeighbor = (k) => hover && (k === hover
    || (ctLayer(hover) || {}).feeds?.includes(k)
    || (ctLayer(k) || {}).feeds?.includes(hover));

  const allNodes = [...(layers || CT_LAYERS), CT_MAT_NODE];

  return (
    <div className="ct-map-wrap">
      <div className="ct-map" style={{ width: CT_MAP_W, height: CT_MAP_H }}>
        <svg className="ct-edges" width={CT_MAP_W} height={CT_MAP_H} viewBox={`0 0 ${CT_MAP_W} ${CT_MAP_H}`}>
          <defs>
            <marker id="ct-arrow" markerWidth="7" markerHeight="7" refX="5.5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="var(--line-3)" />
            </marker>
            <marker id="ct-arrow-hot" markerWidth="8" markerHeight="8" refX="5.5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill="var(--crimson)" />
            </marker>
          </defs>
          {edges.map((e, i) => {
            const active = edgeActive(e);
            const spineEdge = e.from === "paragraph";
            return (
              <path key={i} d={ctEdgePath(e.from, e.to)} fill="none"
                className={`ct-edge ${active ? "is-active" : ""} ${spineEdge ? "is-spine" : ""}`}
                stroke={active ? "var(--crimson)" : spineEdge ? "var(--gold-soft)" : "var(--line-2)"}
                strokeWidth={active ? 2.2 : spineEdge ? 1.6 : 1.2}
                strokeDasharray={armed && blast.has(e.to) ? "5 4" : "none"}
                markerEnd={`url(#${active ? "ct-arrow-hot" : "ct-arrow"})`}
                opacity={hover && !active && !armed ? 0.32 : 1} />
            );
          })}
        </svg>

        {allNodes.map(l => {
          const pos = CT_POS[l.key];
          const isMat = l.key === "materialize";
          const inBlast = blast.has(l.key);
          const isArmed = armed === l.key;
          return (
            <CTNode key={l.key} layer={l} pos={pos} isMat={isMat}
              selected={selected === l.key} inBlast={inBlast} isArmed={isArmed}
              dimmed={armed ? (!inBlast && !isArmed) : (hover ? !isNeighbor(l.key) : false)}
              onSelect={() => onSelect(l.key)}
              onArm={() => onArm(isArmed ? null : l.key)}
              onHover={setHover} />
          );
        })}
      </div>

      <div className="ct-map-legend">
        <span className="ct-leg-item"><span className="ct-leg-dot" style={{ background: "var(--crimson)" }} />情节链</span>
        <span className="ct-leg-item"><span className="ct-leg-dot" style={{ background: "var(--gold)" }} />角色链</span>
        <span className="ct-leg-item"><span className="ct-leg-dot" style={{ background: "var(--slate)" }} />定位</span>
        <span className="ct-leg-sep" />
        <span className="ct-leg-item"><span className="ct-leg-line is-spine" />脊柱派生</span>
        <span className="ct-leg-item"><span className="ct-leg-line is-hot" />影响链</span>
      </div>
    </div>
  );
}

function CTNode({ layer, pos, isMat, selected, inBlast, isArmed, dimmed, onSelect, onArm, onHover }) {
  const trk = CT_TRACK[layer.track] || CT_TRACK.plot;
  const st = CT_STATE[layer.state] || CT_STATE.empty;
  const isSpine = layer.isSpine;

  if (isMat) {
    return (
      <div className={`ct-node ct-node-mat ${inBlast ? "is-blast" : ""} ${dimmed ? "is-dim" : ""}`}
        style={{ left: pos.x, top: pos.y, width: CT_NODE_W, height: CT_NODE_H }}>
        <I.Layout size={15} />
        <div className="ct-node-mat-body">
          <span className="ct-node-mat-name">整理成章节结构</span>
          <span className="ct-node-mat-sub">下游交付 · ChapterGoal / SceneCard</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`ct-node ${selected ? "is-sel" : ""} ${isSpine ? "is-spine" : ""} ${inBlast ? "is-blast" : ""} ${isArmed ? "is-armed" : ""} ${dimmed ? "is-dim" : ""}`}
      style={{ left: pos.x, top: pos.y, width: CT_NODE_W, height: CT_NODE_H, "--trk": trk.color }}
      onClick={onSelect}
      onMouseEnter={() => onHover(layer.key)}
      onMouseLeave={() => onHover(null)}
    >
      <span className="ct-node-rail" style={{ background: trk.color }} />
      <span className="ct-node-num">{layer.num}</span>
      <div className="ct-node-body">
        <div className="ct-node-top">
          <span className="ct-node-name">{layer.name}</span>
          {isSpine && <I.Activity size={12} className="ct-node-spine-ic" />}
        </div>
        <div className="ct-node-meta">
          <span className="ct-node-state" style={{ color: st.dot }}><span className="ct-node-state-dot" style={{ background: st.dot }} />{st.label}</span>
          <span className="ct-node-health">
            <span className="ct-node-hbar"><span style={{ width: `${layer.health.score}%`, background: ctHealthColor(layer.health.score) }} /></span>
            <span className="ct-node-hnum">{layer.health.score}</span>
          </span>
        </div>
      </div>
      {inBlast && <span className="ct-node-blast-tag">受影响</span>}
      <button className="ct-node-arm" title="模拟修改本层，查看下游影响"
        onClick={(e) => { e.stopPropagation(); onArm(); }}>
        {isArmed ? <I.Refresh size={12} /> : <I.Zap size={12} />}
      </button>
    </div>
  );
}

function ctHealthColor(s) {
  if (s >= 80) return "var(--sage)";
  if (s >= 65) return "var(--gold)";
  return "var(--rose)";
}

/* ==========================================================
   构思控制塔 — 全书织线缩略图 (book-level weave & pacing)
   读取逐步工作台第 09 步的真实场景数据（localStorage，回退到种子），
   把画布上的「织线 + 节奏」诊断放大到一屏俯视全书。
   ========================================================== */
function ctReadScenes() {
  /* 种子只属于「潮汐档案」；其它作品空列表时不再回退到别人的小说 */
  const isTide = (() => { try { return !WsWorks || WsWorks.activeId() === "tide"; } catch (e) { return true; } })();
  const seed = (isTide && window.S2_SCENE_SEED) ? JSON.parse(JSON.stringify(window.S2_SCENE_SEED)) : { lines: [], list: [] };
  let premise = isTide && window.S2_PREMISE ? { ...window.S2_PREMISE } : { f: "", t: "" };
  try {
    const stored = JSON.parse(localStorage.getItem(wsKey ? wsKey("ws_snow_state_v2") : "ws_snow_state_v2") || "{}");
    const s = stored && stored.scaffolds && stored.scaffolds.scenes;
    if (s) {
      if (Array.isArray(s.list) && s.list.length) seed.list = s.list;
      if (Array.isArray(s.lines) && s.lines.length) seed.lines = s.lines;
    }
    const para = stored && stored.scaffolds && stored.scaffolds.paragraph;
    if (para && ((para.premiseF || "").trim() || (para.premiseT || "").trim())) premise = { f: (para.premiseF || "").trim(), t: (para.premiseT || "").trim() };
  } catch (e) {}
  seed.premise = premise;
  return seed;
}

const CT_WV_KIND = { main: "主线", thread: "线索", sub: "支线" };

function CTWeaveMap({ onOpenStep }) {
  const [hiLine, setHiLine] = useMS(null);
  const scenes = ctReadScenes();
  const list = scenes.list || [];
  const lines = scenes.lines || [];
  const pacing = window.s2PacingRuns ? window.s2PacingRuns(list) : { runs: [], tight: [], slack: [] };
  const stats = window.s2LineStats ? window.s2LineStats(list, lines) : [];
  const premise = scenes.premise || window.S2_PREMISE || { f: "", t: "" };
  const tightMax = pacing.tight.length ? Math.max(...pacing.tight.map(r => r.len)) : 0;
  const slackMax = pacing.slack.length ? Math.max(...pacing.slack.map(r => r.len)) : 0;
  const noCru = list.filter(s => !(s.crucible || "").trim()).length;
  const disTone = (sp) => (sp === "灾二" ? "gold" : "crimson");

  if (!list.length) {
    return (
      <div className="ct-weave ct-weave-empty">
        <I.Activity size={26} />
        <p>尚未拆分场景。织线缩略图会随 09 场景列表实时更新。</p>
        <button className="btn btn-primary btn-sm" onClick={() => onOpenStep && onOpenStep("scenes")}><I.Layers size={13} /> 去 09 · 场景列表</button>
      </div>
    );
  }

  return (
    <div className="ct-weave">
      <div className="ct-panel-h">
        <div className="ct-panel-h-ic"><I.Activity size={16} /></div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="ct-panel-title">全书织线</div>
          <div className="ct-panel-sub">主线与支线如何编织 · 主动 / 反应如何呼吸 —— 一屏俯视全书 {list.length} 场</div>
        </div>
        <button className="btn btn-quiet btn-sm" onClick={() => onOpenStep && onOpenStep("scenes")}><I.Layers size={13} /> 在场景列表展开</button>
      </div>

      <div className="ct-premise">
        <span className="ct-premise-false">{premise.f}</span>
        <I.ArrowRight size={12} />
        <span className="ct-premise-true">{premise.t}</span>
        <span className="ct-wv-premise-tag">每条线都应折射它，否则是闲笔</span>
      </div>

      <div className="ct-wv-chart">
        <div className="ct-wv-row ct-wv-acts">
          <span className="ct-wv-rowlabel" />
          <div className="ct-wv-band">
            {list.map((s, i) => (
              <span key={i} className="ct-wv-acell">
                {s.spine ? <span className={`ct-wv-dis tone-${disTone(s.spine)}`}>{s.spine}</span> : null}
              </span>
            ))}
          </div>
        </div>

        <div className="ct-wv-row">
          <span className="ct-wv-rowlabel">节奏</span>
          <div className="ct-wv-band">
            {list.map((s, i) => (
              <span key={i}
                className={`ct-wv-rcell ${s.type === "proactive" ? "is-pro" : "is-rea"} ${hiLine && (s.line || "main") !== hiLine ? "is-dim" : ""}`}
                title={`${s.id} · ${s.type === "proactive" ? "主动 GCS" : "反应 RDD"}`} />
            ))}
          </div>
        </div>

        {stats.map(ln => (
          <div key={ln.id} className={`ct-wv-row ct-wv-lrow tone-${ln.tone} ${hiLine === ln.id ? "is-hi" : ""} ${hiLine && hiLine !== ln.id ? "is-faint" : ""}`}>
            <button className="ct-wv-rowlabel ct-wv-llabel" onClick={() => setHiLine(hiLine === ln.id ? null : ln.id)} title="点击高亮该线的场景">
              <span className="ct-wv-ldot" />
              <span className="ct-wv-lname">{ln.name}</span>
            </button>
            <div className="ct-wv-band">
              {list.map((s, i) => <span key={i} className={`ct-wv-cell ${(s.line || "main") === ln.id ? "is-on" : ""}`} title={s.id} />)}
            </div>
          </div>
        ))}

        <div className="ct-wv-row ct-wv-axis">
          <span className="ct-wv-rowlabel" />
          <div className="ct-wv-band">
            {list.map((s, i) => <span key={i} className="ct-wv-xcell">{(s.id || "").replace(/^S/, "")}</span>)}
          </div>
        </div>
      </div>

      <div className="ct-wv-readout">
        <div className="ct-wv-diag">
          <span className="ct-wv-diag-h">节奏诊断</span>
          {tightMax >= 3 ? <span className="ct-wv-flag tone-rose"><I.AlertTriangle size={10} /> 最长 {tightMax} 场连续主动 · 张力紧绷</span> : null}
          {slackMax >= 3 ? <span className="ct-wv-flag tone-gold"><I.AlertTriangle size={10} /> 最长 {slackMax} 场连续反应 · 节奏松弛</span> : null}
          {tightMax < 3 && slackMax < 3 ? <span className="ct-wv-flag tone-sage"><I.Check size={10} /> 主动 / 反应交替均匀</span> : null}
          {noCru ? <span className="ct-wv-flag tone-rose"><I.AlertTriangle size={10} /> {noCru} 场缺冲突</span> : <span className="ct-wv-flag tone-sage"><I.Check size={10} /> 场场有冲突</span>}
        </div>
        <div className="ct-wv-lstats">
          {stats.map(ln => (
            <div key={ln.id} className={`ct-wv-lstat tone-${ln.tone}`}>
              <span className="ct-wv-ldot" />
              <span className="ct-wv-lsname">{ln.name}</span>
              <span className="ct-wv-lskind">{CT_WV_KIND[ln.kind] || "支线"}</span>
              <span className="ct-wv-lscount">{ln.count}/{list.length} 场</span>
              {ln.clustered ? <span className="ct-wv-flag tone-gold"><I.AlertTriangle size={10} /> 扎堆</span> : null}
              {ln.noRefract ? <span className="ct-wv-flag tone-rose"><I.AlertTriangle size={10} /> 缺折射</span> : null}
              <span className="ct-wv-lsrefract">{ln.refract ? "「" + ln.refract + "」" : "—"}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { CTStructureMap, ctHealthColor, CTWeaveMap, ctReadScenes });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { CTStructureMap, ctHealthColor, CTWeaveMap, ctReadScenes };
