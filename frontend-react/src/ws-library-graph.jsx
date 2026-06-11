import React from "react";
import { I } from "./icons.jsx";
import { LIB_BY_ID, LIB_CATS, LIB_ENTRIES } from "./ws-library-data.jsx";
import { LIB_REL_TYPES, LIB_relType } from "./ws-library-derive.jsx";

/* global React, I, LIB_CATS, LIB_ENTRIES, LIB_BY_ID, LIB_relType, LIB_REL_TYPES */
const { useMemo: useGMemo, useState: useGSt, useRef: useGRef } = React;

/* ==========================================================
   Library — 关系图谱 (lightweight force-directed map)
   Layout is computed once, deterministically, on mount.
   ========================================================== */

const GCAT = LIB_CATS.reduce((m, c) => { m[c.id] = c; return m; }, {});
const GW = 1000, GH = 660;

/* build undirected, de-duplicated edge list from entry.links */
function buildEdges(entries, byId) {
  const seen = new Set();
  const edges = [];
  entries.forEach(e => {
    (e.links || []).forEach(l => {
      if (!byId[l.id]) return;
      const key = [e.id, l.id].sort().join("|");
      if (seen.has(key)) return;
      seen.add(key);
      edges.push({ a: e.id, b: l.id, rel: l.rel, typeId: LIB_relType(l).id });
    });
  });
  return edges;
}

/* simple force simulation → {id: {x,y}} */
function computeLayout(edges, entries) {
  const nodes = entries.map(e => ({ id: e.id, cat: e.cat }));
  const idx = {};
  nodes.forEach((n, i) => { idx[n.id] = i; });

  // deterministic seed: cluster by category around a ring
  const catAngle = {};
  LIB_CATS.forEach((c, i) => { catAngle[c.id] = (i / LIB_CATS.length) * Math.PI * 2; });
  const catCount = {};
  const pos = nodes.map(n => {
    const k = (catCount[n.cat] = (catCount[n.cat] || 0) + 1);
    const base = catAngle[n.cat];
    const a = base + (k * 0.7);
    const r = 150 + (k % 4) * 46;
    return { x: GW / 2 + Math.cos(a) * r, y: GH / 2 + Math.sin(a) * r };
  });

  const REP = 1650, SPRING = 0.045, L = 120, CENTER = 0.012, STEP = 0.9, MAXMOVE = 26;
  const CAT_COHESION = 0.021;
  const ITERS = 520;
  for (let it = 0; it < ITERS; it++) {
    const fx = new Array(nodes.length).fill(0);
    const fy = new Array(nodes.length).fill(0);
    // per-category centroid (loose clustering → readable regions)
    const cc = {}, cn = {};
    for (let i = 0; i < nodes.length; i++) {
      const c = nodes[i].cat;
      if (!cc[c]) { cc[c] = { x: 0, y: 0 }; cn[c] = 0; }
      cc[c].x += pos[i].x; cc[c].y += pos[i].y; cn[c]++;
    }
    Object.keys(cc).forEach(c => { cc[c].x /= cn[c]; cc[c].y /= cn[c]; });
    // repulsion (all pairs)
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y;
        let d2 = dx * dx + dy * dy || 0.01;
        let d = Math.sqrt(d2);
        const f = REP / d2;
        const ux = dx / d, uy = dy / d;
        fx[i] += ux * f; fy[i] += uy * f;
        fx[j] -= ux * f; fy[j] -= uy * f;
      }
      // centering + same-category cohesion
      fx[i] += (GW / 2 - pos[i].x) * CENTER;
      fy[i] += (GH / 2 - pos[i].y) * CENTER;
      const ctr = cc[nodes[i].cat];
      fx[i] += (ctr.x - pos[i].x) * CAT_COHESION;
      fy[i] += (ctr.y - pos[i].y) * CAT_COHESION;
    }
    // springs
    edges.forEach(e => {
      const a = idx[e.a], b = idx[e.b];
      let dx = pos[b].x - pos[a].x, dy = pos[b].y - pos[a].y;
      let d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const diff = (d - L) * SPRING;
      const ux = dx / d, uy = dy / d;
      fx[a] += ux * diff; fy[a] += uy * diff;
      fx[b] -= ux * diff; fy[b] -= uy * diff;
    });
    // integrate
    for (let i = 0; i < nodes.length; i++) {
      let mx = fx[i] * STEP, my = fy[i] * STEP;
      const m = Math.sqrt(mx * mx + my * my);
      if (m > MAXMOVE) { mx = mx / m * MAXMOVE; my = my / m * MAXMOVE; }
      pos[i].x += mx; pos[i].y += my;
    }
  }

  // normalize to fit viewport with padding
  const pad = 56;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  pos.forEach(p => { minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x); minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y); });
  const sx = (GW - pad * 2) / (maxX - minX || 1);
  const sy = (GH - pad * 2) / (maxY - minY || 1);
  const s = Math.min(sx, sy);
  const offX = (GW - (maxX - minX) * s) / 2;
  const offY = (GH - (maxY - minY) * s) / 2;
  const out = {};
  nodes.forEach((n, i) => {
    out[n.id] = { x: pad / 2 + offX + (pos[i].x - minX) * s, y: pad / 2 + offY + (pos[i].y - minY) * s };
  });
  return out;
}

function LibGraph({ selId, onSelect, onOpen, entries, byId }) {
  const ents = entries || LIB_ENTRIES;
  const bid = byId || LIB_BY_ID;
  const edges = useGMemo(() => buildEdges(ents, bid), [ents, bid]);
  const layout = useGMemo(() => computeLayout(edges, ents), [edges, ents]);
  /* 连接度：决定节点大小与默认标签可见性 */
  const deg = useGMemo(() => {
    const d = {};
    edges.forEach(e => { d[e.a] = (d[e.a] || 0) + 1; d[e.b] = (d[e.b] || 0) + 1; });
    return d;
  }, [edges]);
  const nodeR = (id, isSel) => {
    const r = Math.min(27, 14 + Math.sqrt(deg[id] || 0) * 4.2);
    return isSel ? r + 3 : r;
  };
  const [hover, setHover] = useGSt(null);

  /* ---- 自定义节点位置（拖拽重排，本地记忆） ---- */
  const [posOv, setPosOv] = useGSt(() => {
    try { return JSON.parse(localStorage.getItem(window.wsKey ? window.wsKey("ws-lib-graph-pos-v1") : "ws-lib-graph-pos-v1") || "{}"); }
    catch (e) { return {}; }
  });
  const persistPos = (next) => { try { localStorage.setItem(window.wsKey ? window.wsKey("ws-lib-graph-pos-v1") : "ws-lib-graph-pos-v1", JSON.stringify(next)); } catch (e) {} };
  const pos = useGMemo(() => ({ ...layout, ...posOv }), [layout, posOv]);
  const hasCustom = Object.keys(posOv).length > 0;
  const resetLayout = () => { setPosOv({}); persistPos({}); };

  const focus = hover || selId;
  // neighbours of the focused node
  const neighbours = useGMemo(() => {
    const set = new Set();
    if (!focus) return set;
    edges.forEach(e => {
      if (e.a === focus) set.add(e.b);
      if (e.b === focus) set.add(e.a);
    });
    return set;
  }, [focus, edges]);

  const sel = bid[selId];

  /* ---- 类别筛选 ---- */
  const [offCats, setOffCats] = useGSt(() => new Set());
  const catOn = (id) => !offCats.has(id);
  const toggleCat = (id) => setOffCats(prev => {
    const n = new Set(prev);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });
  /* ---- 关系类型筛选 ---- */
  const [offRels, setOffRels] = useGSt(() => new Set());
  const relOn = (id) => !offRels.has(id);
  const toggleRel = (id) => setOffRels(prev => {
    const n = new Set(prev);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });
  /* ---- 搜索 / 定位 + 按类别控制标签 ---- */
  const [query, setQuery] = useGSt("");
  const [labelCats, setLabelCats] = useGSt(() => new Set(LIB_CATS.map(c => c.id)));
  const labelOn = (id) => labelCats.has(id);
  const toggleLabelCat = (id) => setLabelCats(prev => {
    const n = new Set(prev);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });
  const allLabelsOn = labelCats.size >= LIB_CATS.length;
  const toggleAllLabels = () => setLabelCats(allLabelsOn ? new Set() : new Set(LIB_CATS.map(c => c.id)));
  /* 整组一键开/关：类别可见性 + 关系类型 */
  const allCatsOn = offCats.size === 0;
  const toggleAllCats = () => setOffCats(allCatsOn ? new Set(LIB_CATS.map(c => c.id)) : new Set());
  const allRelsOn = offRels.size === 0;
  const toggleAllRels = () => setOffRels(allRelsOn ? new Set(LIB_REL_TYPES.map(t => t.id)) : new Set());
  const q = query.trim().toLowerCase();
  const matchSet = useGMemo(() => {
    const s = new Set();
    if (!q) return s;
    ents.forEach(e => {
      const hay = [e.name, e.code, e.kind, ...(e.tags || [])].join(" ").toLowerCase();
      if (hay.includes(q)) s.add(e.id);
    });
    return s;
  }, [q, ents]);
  const nodeVisible = (e) => catOn(e.cat);
  const edgeVisible = (e) => catOn(bid[e.a]?.cat) && catOn(bid[e.b]?.cat) && relOn(e.typeId);

  /* 选中节点的关系类型分布 */
  const selRelBreakdown = useGMemo(() => {
    if (!selId) return [];
    const cnt = {};
    edges.forEach(e => {
      if (e.a !== selId && e.b !== selId) return;
      cnt[e.typeId] = (cnt[e.typeId] || 0) + 1;
    });
    return LIB_REL_TYPES.map(t => ({ t, n: cnt[t.id] || 0 })).filter(x => x.n);
  }, [selId, edges]);

  /* ---- 缩放 / 平移 ---- */
  const svgRef = useGRef(null);
  const [view, setView] = useGSt({ k: 1, tx: 0, ty: 0 });
  const drag = useGRef(null);
  const ndrag = useGRef(null);
  const clickGuard = useGRef(false);

  const toSvg = (clientX, clientY) => {
    const r = svgRef.current.getBoundingClientRect();
    return { x: (clientX - r.left) / r.width * GW, y: (clientY - r.top) / r.height * GH };
  };
  /* 屏幕坐标 → 缩放/平移后的局部坐标（节点所在坐标系） */
  const toLocal = (clientX, clientY) => {
    const s = toSvg(clientX, clientY);
    return { x: (s.x - view.tx) / view.k, y: (s.y - view.ty) / view.k };
  };
  const onWheel = (ev) => {
    ev.preventDefault();
    const { x, y } = toSvg(ev.clientX, ev.clientY);
    setView(v => {
      const k = Math.min(3, Math.max(0.5, v.k * (ev.deltaY < 0 ? 1.12 : 1 / 1.12)));
      return { k, tx: x - (x - v.tx) * (k / v.k), ty: y - (y - v.ty) * (k / v.k) };
    });
  };
  const onDown = (ev) => {
    if (ev.button !== 0) return;
    drag.current = { sx: ev.clientX, sy: ev.clientY, tx: view.tx, ty: view.ty, moved: false };
  };
  const onMove = (ev) => {
    if (ndrag.current) {
      const loc = toLocal(ev.clientX, ev.clientY);
      const id = ndrag.current.id;
      const np = { x: loc.x + ndrag.current.ox, y: loc.y + ndrag.current.oy };
      ndrag.current.moved = true;
      setPosOv(prev => ({ ...prev, [id]: np }));
      return;
    }
    if (!drag.current) return;
    const r = svgRef.current.getBoundingClientRect();
    const dx = (ev.clientX - drag.current.sx) / r.width * GW;
    const dy = (ev.clientY - drag.current.sy) / r.height * GH;
    if (Math.abs(ev.clientX - drag.current.sx) + Math.abs(ev.clientY - drag.current.sy) > 3) drag.current.moved = true;
    setView(v => ({ ...v, tx: drag.current.tx + dx, ty: drag.current.ty + dy }));
  };
  const endDrag = () => {
    if (ndrag.current && ndrag.current.moved) {
      clickGuard.current = true;
      setPosOv(prev => { persistPos(prev); return prev; });
    }
    ndrag.current = null;
    drag.current = null;
  };
  /* 开始拖拽某个节点 */
  const startNodeDrag = (ev, id) => {
    ev.stopPropagation();
    if (ev.button !== 0) return;
    const loc = toLocal(ev.clientX, ev.clientY);
    const cur = pos[id];
    ndrag.current = { id, ox: cur.x - loc.x, oy: cur.y - loc.y, moved: false };
  };
  const onBgClick = () => { if (!drag.current || !drag.current.moved) onSelect(null); };
  const zoomBy = (f) => setView(v => {
    const k = Math.min(3, Math.max(0.5, v.k * f));
    return { k, tx: GW / 2 - (GW / 2 - v.tx) * (k / v.k), ty: GH / 2 - (GH / 2 - v.ty) * (k / v.k) };
  });
  const resetView = () => setView({ k: 1, tx: 0, ty: 0 });

  const isLit = (id) => {
    if (focus) return id === focus || neighbours.has(id);
    if (q) return matchSet.has(id);
    return true;
  };
  const edgeLit = (e) => {
    if (focus) return e.a === focus || e.b === focus;
    if (q) return matchSet.has(e.a) || matchSet.has(e.b);
    return true;
  };
  /* 标签按类别控制：聚焦/搜索时始终补全相关项，其余跟随该类别开关 */
  const showLabel = (id, cat) => {
    if (!isLit(id)) return false;
    if (focus) return true;
    if (q) return matchSet.has(id);
    return labelCats.has(cat);
  };

  return (
    <div className="lib2-graph">
      {/* ---- toolbar: 搜索 / 标签 / 图例筛选 ---- */}
      <div className="lib2-graph-bar">
        <div className="graph-search">
          <span className="graph-search-ic"><I.Search size={14} /></span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="在图谱中查找…"
            spellCheck={false}
          />
          {query && (
            <button className="graph-search-clear" onClick={() => setQuery("")} title="清空"><I.X size={12} /></button>
          )}
        </div>
        <div className="graph-legends">
          <div className="graph-legend-grp">
            <button className="graph-legend-cap" onClick={toggleAllCats} title={allCatsOn ? "隐藏全部类别" : "显示全部类别"}>类别</button>
            <div className="graph-legend">
              {LIB_CATS.map(c => (
                <span key={c.id} className={`graph-catchip acc-${c.accent} ${catOn(c.id) ? "" : "is-hidden"}`}>
                  <button
                    className="graph-catchip-vis"
                    onClick={() => toggleCat(c.id)}
                    title={catOn(c.id) ? "隐藏该类节点" : "显示该类节点"}
                  >
                    <span className="dot" />{c.label}
                  </button>
                  <button
                    className={`graph-catchip-lbl ${labelOn(c.id) ? "is-on" : ""}`}
                    onClick={() => toggleLabelCat(c.id)}
                    disabled={!catOn(c.id)}
                    title={labelOn(c.id) ? "隐藏该类文字标签" : "显示该类文字标签"}
                  >
                    <I.Type size={11} />
                  </button>
                </span>
              ))}
              <button
                className="graph-catchip-all"
                onClick={toggleAllLabels}
                title={allLabelsOn ? "隐藏全部文字标签" : "显示全部文字标签"}
              >
                <I.Type size={11} /> {allLabelsOn ? "标签全开" : "标签"}
              </button>
            </div>
          </div>
          <div className="graph-legend-grp">
            <button className="graph-legend-cap" onClick={toggleAllRels} title={allRelsOn ? "隐藏全部关系" : "显示全部关系"}>关系</button>
            <div className="graph-legend">
              {LIB_REL_TYPES.map(rt => (
                <button
                  key={rt.id}
                  className={`graph-legend-item graph-legend-rel acc-${rt.accent} ${relOn(rt.id) ? "" : "is-off"}`}
                  onClick={() => toggleRel(rt.id)}
                  title={rt.hint}
                >
                  <span className="bar" />{rt.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="lib2-graph-stage">
      <svg
        ref={svgRef}
        className="lib2-graph-svg"
        viewBox={`0 0 ${GW} ${GH}`}
        preserveAspectRatio="xMidYMid meet"
        onWheel={onWheel}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
        style={{ cursor: drag.current ? "grabbing" : "grab" }}
      >
        {/* background catcher for deselect */}
        <rect x="0" y="0" width={GW} height={GH} fill="transparent" onClick={onBgClick} />
        <g transform={`translate(${view.tx} ${view.ty}) scale(${view.k})`}>
        {/* edges */}
        <g>
          {edges.map((e, i) => {
            if (!edgeVisible(e)) return null;
            const p = pos[e.a], q2 = pos[e.b];
            const lit = edgeLit(e);
            return (
              <line key={i} x1={p.x} y1={p.y} x2={q2.x} y2={q2.y}
                className={`graph-edge rel-${e.typeId} ${lit ? "is-lit" : "is-faint"}`} />
            );
          })}
        </g>
        {/* edge labels for focused node */}
        {focus && (
          <g>
            {edges.filter(e => edgeLit(e) && edgeVisible(e)).map((e, i) => {
              const other = e.a === focus ? e.b : e.a;
              const p = pos[focus], q2 = pos[other];
              const mx = (p.x + q2.x) / 2, my = (p.y + q2.y) / 2;
              return (
                <text key={i} x={mx} y={my - 4} className="graph-edge-label" textAnchor="middle">{e.rel}</text>
              );
            })}
          </g>
        )}
        {/* nodes */}
        <g>
          {ents.map(e => {
            if (!nodeVisible(e)) return null;
            const p = pos[e.id];
            const lit = isLit(e.id);
            const isSel = e.id === selId;
            const r = nodeR(e.id, isSel);
            const gf = Math.round(r * 0.82);
            return (
              <g key={e.id}
                className={`graph-node acc-${e.accent} ${lit ? "is-lit" : "is-dim"} ${isSel ? "is-sel" : ""} ${q && matchSet.has(e.id) ? "is-match" : ""}`}
                transform={`translate(${p.x} ${p.y})`}
                onMouseEnter={() => setHover(e.id)}
                onMouseLeave={() => setHover(null)}
                onMouseDown={(ev) => startNodeDrag(ev, e.id)}
                onClick={(ev) => { ev.stopPropagation(); if (clickGuard.current) { clickGuard.current = false; return; } onSelect(e.id); }}
                style={{ cursor: ndrag.current && ndrag.current.id === e.id ? "grabbing" : "grab" }}>
                <circle className="graph-node-halo" r={r + 7} />
                <circle className="graph-node-dot" r={r} />
                <text className="graph-node-glyph" textAnchor="middle" dy={Math.round(gf * 0.34)} fontSize={gf}>{e.glyph}</text>
                {showLabel(e.id, e.cat) && (
                  <text className="graph-node-label" textAnchor="middle" y={r + 15}>{e.name}</text>
                )}
              </g>
            );
          })}
        </g>
        </g>
      </svg>

      {/* zoom controls */}
      <div className="graph-zoom">
        <button onClick={() => zoomBy(1.2)} title="放大"><I.Plus size={15} /></button>
        <button onClick={() => zoomBy(1 / 1.2)} title="缩小">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M5 12h14" /></svg>
        </button>
        <button onClick={resetView} title="复位视图"><I.Refresh size={14} /></button>
        {hasCustom && <button className="graph-zoom-layout" onClick={resetLayout} title="复位布局（清除拖拽）"><I.Grid size={14} /></button>}
      </div>

      {/* focused node panel */}
      {sel && (
        <div className={`graph-panel acc-${sel.accent}`}>
          <div className="graph-panel-head">
            <span className="graph-panel-glyph">{sel.glyph}</span>
            <div className="graph-panel-main">
              <div className="graph-panel-code">{sel.code}</div>
              <div className="graph-panel-name">{sel.name}</div>
              <div className="graph-panel-sub">{sel.kind}</div>
            </div>
          </div>
          <div className="graph-panel-rel">
            <I.Compass size={12} /> {neighbours.size} 项关联
          </div>
          {selRelBreakdown.length > 0 && (
            <div className="graph-panel-types">
              {selRelBreakdown.map(({ t, n }) => (
                <span key={t.id} className={`rel-chip rel-chip-sm acc-${t.accent}`} title={t.hint}>
                  <span className="bar" />{t.label}<b>{n}</b>
                </span>
              ))}
            </div>
          )}
          <button className="btn btn-primary btn-sm" onClick={() => onOpen(sel.id)}>
            <I.BookOpen size={13} /> 查看完整档案
          </button>
        </div>
      )}

      {q && (
        <div className="graph-searchstat">
          {matchSet.size > 0 ? <>命中 <b>{matchSet.size}</b> 个 · 其余已淡出</> : <>没有匹配「{query}」的档案</>}
        </div>
      )}

      <div className="graph-hint"><I.Info size={12} /> 滚轮缩放 · 拖空白平移 · 拖节点重排 · 点图例筛选</div>
      </div>
    </div>
  );
}

Object.assign(window, { LibGraph });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { LibGraph };
