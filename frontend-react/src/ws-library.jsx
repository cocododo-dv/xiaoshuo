import React from "react";
import { I } from "./icons.jsx";
import { WsTrashStore } from "./ws-catalog.jsx";
import { LIB_BY_ID, LIB_CATS, LIB_ENTRIES } from "./ws-library-data.jsx";
import { LIB_REL_TYPES, LIB_SORTS, LIB_buildBacklinks, LIB_connections, LIB_degree, LIB_groupConnections, LIB_health, LIB_isCited, LIB_nextAction, LIB_sortWithPin } from "./ws-library-derive.jsx";
import { LibGraph } from "./ws-library-graph.jsx";
import { LibTimeline } from "./ws-library-timeline.jsx";
import { LibOverview } from "./ws-library-overview.jsx";
import { DossierCreate, DossierEdit, LIB_applyEdit, LIB_deleteEntry, LIB_loadAdds, LIB_loadEdits, LIB_newEntry, LIB_persist, LIB_persistAdds, LIB_seedOn } from "./ws-library-edit.jsx";
import { WsWorks } from "./ws-works.jsx";

/* global React, I, LIB_CATS, LIB_ENTRIES, LIB_BY_ID, LibGraph, LibTimeline, LibOverview, LIB_loadEdits, LIB_persist, LIB_applyEdit, DossierEdit, DossierCreate, LIB_loadAdds, LIB_persistAdds, LIB_newEntry, LIB_buildBacklinks, LIB_connections, LIB_degree, LIB_health, LIB_SORTS, LIB_sortWithPin, LIB_isCited, LIB_nextAction, LIB_groupConnections, LIB_REL_TYPES */
const { useState: useLb, useMemo: useLbMemo, useRef: useLbRef, useEffect: useLbEffect } = React;

/* ==========================================================
   Library — 档案库 (master-detail codex)
   ========================================================== */

const ACC = (a) => `acc-${a || "ink"}`;
const CAT_META = LIB_CATS.reduce((m, c) => { m[c.id] = c; return m; }, {});

function WsLibrary({ go }) {
  const [query, setQuery]   = useLb("");
  const [cat, setCat]       = useLb("all");
  const [selId, setSelId]   = useLb(null);          /* null → 总览落地页 */
  const [vmode, setVmode]   = useLb("files");
  const [sort, setSort]     = useLb("recent");
  const [edits, setEdits]   = useLb(() => LIB_loadEdits());
  const [adds, setAdds]     = useLb(() => LIB_loadAdds());
  const [editing, setEditing] = useLb(false);
  const [creating, setCreating] = useLb(false);
  const searchRef = useLbRef(null);
  const pendingEdit = useLbRef(null);   /* 新建后自动进入编辑态的目标 id */

  /* single source of truth — (种子按作品门控 + 用户新建) 再叠加编辑覆盖层 */
  const rawEntries = useLbMemo(() => [...(LIB_seedOn && !LIB_seedOn() ? [] : LIB_ENTRIES), ...adds], [adds]);
  const entries    = useLbMemo(() => rawEntries.map(e => LIB_applyEdit(e, edits)), [rawEntries, edits]);
  const byId       = useLbMemo(() => entries.reduce((m, e) => { m[e.id] = e; return m; }, {}), [entries]);
  const backlinks  = useLbMemo(() => LIB_buildBacklinks(entries), [entries]);
  const health     = useLbMemo(() => LIB_health(entries), [entries]);

  /* counts per category, respecting the live query (entries 已是合并后数据) */
  const matches = useLbMemo(() => {
    const q = query.trim().toLowerCase();
    return entries.filter(e => {
      if (!q) return true;
      const hay = [e.name, e.summary, e.blurb, e.kind, e.code, ...(e.tags || [])].join(" ").toLowerCase();
      return hay.includes(q);
    });
  }, [query, entries]);

  const counts = useLbMemo(() => {
    const c = { all: matches.length };
    LIB_CATS.forEach(k => { c[k.id] = matches.filter(e => e.cat === k.id).length; });
    return c;
  }, [matches]);

  const filtered = useLbMemo(
    () => matches.filter(e => cat === "all" || e.cat === cat),
    [matches, cat]
  );

  /* grouped for rendering; each group sorted (置顶优先) */
  const groups = useLbMemo(() => {
    const mk = (id, items) => ({ cat: id, items: LIB_sortWithPin(items, sort) });
    if (cat !== "all") return [mk(cat, filtered)];
    return LIB_CATS
      .map(k => mk(k.id, filtered.filter(e => e.cat === k.id)))
      .filter(g => g.items.length);
  }, [filtered, cat, sort]);

  /* flat visible order = exactly what's rendered (for keyboard nav) */
  const visible = useLbMemo(() => groups.flatMap(g => g.items), [groups]);

  const sel = selId ? byId[selId] : null;
  const mergedSel = sel;   /* entries 已合并编辑覆盖 */
  const selConns = useLbMemo(
    () => (sel ? LIB_connections(sel, byId, backlinks) : []),
    [sel, byId, backlinks]
  );

  /* 上一条 / 下一条（沿当前可见列表顺序翻阅） */
  const selIdx = useLbMemo(() => visible.findIndex(e => e.id === selId), [visible, selId]);
  const prevEntry = selIdx > 0 ? visible[selIdx - 1] : null;
  const nextEntry = selIdx >= 0 && selIdx < visible.length - 1 ? visible[selIdx + 1] : null;

  /* 选中变化：默认退出编辑态；若是刚新建的条目则进入编辑态 */
  useLbEffect(() => {
    if (pendingEdit.current && pendingEdit.current === selId) {
      pendingEdit.current = null;
      setEditing(true);
    } else {
      setEditing(false);
    }
  }, [selId]);

  const saveEdit = (patch) => {
    const next = { ...edits, [selId]: { ...(edits[selId] || {}), ...patch } };
    setEdits(next); LIB_persist(next); setEditing(false);
  };
  const resetEdit = () => {
    const next = { ...edits }; delete next[selId];
    setEdits(next); LIB_persist(next); setEditing(false);
  };

  /* 直接对任意条目打补丁（状态推进 / 置顶开关），持久化并实时联动各视图 */
  const patchEntry = (id, patch) => {
    const next = { ...edits, [id]: { ...(edits[id] || {}), ...patch } };
    setEdits(next); LIB_persist(next);
  };

  /* 新建档案 */
  const startCreate = () => { setCreating(true); setSelId(null); setEditing(false); };
  const doCreate = (catId, name) => {
    const ne = LIB_newEntry(catId, name);
    const next = [...adds, ne];
    setAdds(next); LIB_persistAdds(next);
    pendingEdit.current = ne.id;
    setCreating(false); setSelId(ne.id);
  };
  /* 删除用户新建的档案（Q2 修复：真删后端，否则 refetch 后复活） */
  const deleteEntry = (id) => {
    const base = byId[id];
    const next = adds.filter(a => a.id !== id);
    setAdds(next); LIB_persistAdds(next);
    if (edits[id]) { const e2 = { ...edits }; delete e2[id]; setEdits(e2); LIB_persist(e2); }
    if (base) LIB_deleteEntry(base);
    setSelId(null); setEditing(false);
  };

  /* follow a cross-link: select + reveal in the list */
  const navTo = (id) => {
    if (!byId[id]) return;
    setCreating(false);
    setSelId(id);
    setQuery("");
    setCat("all");
  };
  const goOverview = () => { setSelId(null); setCreating(false); setEditing(false); };
  /* 轻量选择：保持当前筛选/搜索，用于上一条/下一条翻阅 */
  const selectId = (id) => { setCreating(false); setSelId(id); };

  /* 外部跳转：从正文写作点击实体 → 打开对应档案 */
  useLbEffect(() => {
    const open = (id) => { if (!id) return; setVmode("files"); setCreating(false); setQuery(""); setCat("all"); setSelId(id); };
    if (window.__libTarget) { const id = window.__libTarget; window.__libTarget = null; open(id); }
    const h = (e) => open(e.detail);
    window.addEventListener("ws:lib-open", h);
    return () => window.removeEventListener("ws:lib-open", h);
  }, []);

  /* keyboard: ↑/↓ moves through the visible list */
  useLbEffect(() => {
    const onKey = (ev) => {
      if (document.activeElement === searchRef.current) return;
      if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
      if (!visible.length) return;
      ev.preventDefault();
      const idx = visible.findIndex(e => e.id === selId);
      const next = ev.key === "ArrowDown"
        ? Math.min(visible.length - 1, idx < 0 ? 0 : idx + 1)
        : Math.max(0, idx < 0 ? 0 : idx - 1);
      setSelId(visible[next].id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, selId]);

  return (
    <div className="lib2 page" data-screen-label="library">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <div className="page-eyebrow">档案库</div>
            <h1 className="page-title">{(WsWorks ? WsWorks.active().title : "潮汐档案")} · 故事圣经</h1>
            <p className="page-subtitle">人物、世界、大事记、参考与知识，全部互相关联。改动这里会影响后续的候选生成。</p>
          </div>
          <div className="flex gap-2" style={{ alignItems: "center" }}>
            <div className="lib2-seg" role="tablist">
              <button className={`lib2-seg-btn ${vmode === "files" ? "is-active" : ""}`} onClick={() => setVmode("files")}>
                <I.Layout size={14} /> 档案
              </button>
              <button className={`lib2-seg-btn ${vmode === "graph" ? "is-active" : ""}`} onClick={() => setVmode("graph")}>
                <I.Compass size={14} /> 图谱
              </button>
              <button className={`lib2-seg-btn ${vmode === "timeline" ? "is-active" : ""}`} onClick={() => setVmode("timeline")}>
                <I.Clock size={14} /> 时间线
              </button>
            </div>
            <button className="btn btn-accent" onClick={() => { setVmode("files"); startCreate(); }}><I.Plus size={14} /> 新建档案</button>
          </div>
        </header>

        <div className="lib2-bar">
          <button className="lib2-stat" onClick={() => { setVmode("files"); goOverview(); }} title="返回总览">
            <div className="lib2-stat-n">{health.total}<span className="unit">份</span></div>
            <div className="lib2-stat-k">档案条目</div>
          </button>
          <button className="lib2-stat" onClick={() => { setVmode("graph"); }} title="在图谱中查看关联">
            <div className="lib2-stat-n">{health.linksN}</div>
            <div className="lib2-stat-k">交叉关联</div>
          </button>
          <div className="lib2-stat" role="status" title="被正文章节引用的档案数">
            <div className="lib2-stat-n">{health.cited}</div>
            <div className="lib2-stat-k">被正文引用</div>
          </div>
          <button className="lib2-stat lib2-stat-accent" onClick={() => { setVmode("files"); goOverview(); }} title="查看待处理队列">
            <div className="lib2-stat-n">{health.buckets.pending + health.buckets.active}</div>
            <div className="lib2-stat-k">待你处理</div>
          </button>
        </div>

        {entries.length === 0 && !creating ? (
          <div className="lib2-shell" style={{ display: "grid", placeItems: "center", minHeight: "46vh" }}>
            <div style={{ textAlign: "center", maxWidth: 420, display: "grid", gap: 12, justifyItems: "center" }}>
              <div style={{ fontFamily: "var(--font-serif)", fontSize: 20, color: "var(--ink-1)" }}>这部作品的档案库还是空的</div>
              <p style={{ color: "var(--ink-3)", fontSize: 14, lineHeight: 1.8, margin: 0 }}>人物、地点、术语在这里登记后，写作器里会自动高亮并可随写随查。</p>
              <button className="btn btn-accent" onClick={() => { setVmode("files"); startCreate(); }}><I.Plus size={14} /> 新建第一份档案</button>
            </div>
          </div>
        ) : vmode === "graph" ? (
          <LibGraph
            entries={entries} byId={byId} backlinks={backlinks}
            selId={selId}
            onSelect={setSelId}
            onOpen={(id) => { setSelId(id); setCreating(false); setCat("all"); setQuery(""); setVmode("files"); }}
          />
        ) : vmode === "timeline" ? (
          <LibTimeline
            entries={entries} byId={byId}
            selId={selId}
            onSelect={setSelId}
            onOpen={(id) => { setSelId(id); setCreating(false); setCat("all"); setQuery(""); setVmode("files"); }}
          />
        ) : (
        <div className="lib2-shell">
          {/* ---- index ---- */}
          <aside className="lib2-index">
            <button className={`lib2-overview-btn ${selId === null && !creating ? "is-active" : ""}`} onClick={goOverview}>
              <span className="lib2-overview-ic"><I.Activity size={15} /></span>
              <span className="lib2-overview-tx">
                <span className="t">故事圣经总览</span>
                <span className="s">健康度 · 待办 · 最近更新</span>
              </span>
              {(health.buckets.pending + health.buckets.active) > 0 && (
                <span className="lib2-overview-badge">{health.buckets.pending + health.buckets.active}</span>
              )}
            </button>

            <div className="lib2-search">
              <span className="lib2-search-ic"><I.Search size={15} /></span>
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="搜索人物、地点、术语…"
                spellCheck={false}
              />
              {query && (
                <button className="lib2-search-clear" onClick={() => setQuery("")} title="清空">
                  <I.X size={14} />
                </button>
              )}
            </div>

            <div className="lib2-cats">
              <button className={`lib2-cat ${cat === "all" ? "is-active" : ""}`} onClick={() => setCat("all")}>
                全部<span className="lib2-cat-count">{counts.all}</span>
              </button>
              {LIB_CATS.map(k => (
                <button key={k.id} className={`lib2-cat ${cat === k.id ? "is-active" : ""}`} onClick={() => setCat(k.id)}>
                  {k.label}<span className="lib2-cat-count">{counts[k.id]}</span>
                </button>
              ))}
            </div>

            <div className="lib2-sortbar">
              <span className="lib2-sortbar-k"><I.Filter size={11} /> 排序</span>
              {Object.keys(LIB_SORTS).map(k => (
                <button key={k} className={`lib2-sort ${sort === k ? "is-active" : ""}`} onClick={() => setSort(k)}>
                  {LIB_SORTS[k].label}
                </button>
              ))}
            </div>

            <div className="lib2-list">
              {visible.length === 0 && (
                <div className="lib2-empty">
                  <I.Search size={22} />
                  <div>没有匹配「{query}」的档案</div>
                </div>
              )}
              {groups.map(g => (
                <div key={g.cat}>
                  {cat === "all" && (
                    <div className="lib2-group-label">
                      {CAT_META[g.cat].label}
                      <span className="n">{g.items.length}</span>
                    </div>
                  )}
                  {g.items.map(e => {
                    return (
                    <button
                      key={e.id}
                      className={`lib2-item ${ACC(e.accent)} ${selId === e.id ? "is-active" : ""}`}
                      onClick={() => { setCreating(false); setSelId(e.id); }}
                    >
                      <span className="lib2-item-glyph">{e.glyph}</span>
                      <span className="lib2-item-main">
                        <span className="lib2-item-name">
                          {e.name}
                          {e.pinned && <I.Star className="pin" size={11} />}
                          {e.user && <span className="lib2-item-mine" title="我新建的">新</span>}
                        </span>
                        <span className="lib2-item-sub">{e.summary || CAT_META[e.cat].label}</span>
                      </span>
                      <span className="lib2-item-dot" />
                    </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </aside>

          {/* ---- detail ---- */}
          <section className="lib2-detail">
            {creating ? (
              <DossierCreate onCreate={doCreate} onCancel={() => setCreating(false)} />
            ) : selId === null ? (
              <LibOverview
                health={health} byId={byId}
                onSelect={(id) => { setCreating(false); setSelId(id); }}
                onPickCat={(c) => { setCat(c); setSelId(null); }}
                onGoGraph={() => setVmode("graph")}
                onNew={startCreate}
                onAction={(id, patch) => patchEntry(id, patch)}
              />
            ) : mergedSel ? (
              editing
                ? <DossierEdit entry={mergedSel} allEntries={entries} byId={byId} onSave={saveEdit} onCancel={() => setEditing(false)} onReset={resetEdit} dirty={!!edits[selId]} />
                : (
                  <React.Fragment>
                    <div className="dossier-nav">
                      <button className="dossier-nav-home" onClick={goOverview}><I.Activity size={13} /> 总览</button>
                      <span className="dossier-nav-sep">/</span>
                      <button className="dossier-nav-cat" onClick={() => { setCat(mergedSel.cat); }}>{CAT_META[mergedSel.cat].label}</button>
                      <span className="dossier-nav-spacer" />
                      <button className="dossier-nav-btn" disabled={!prevEntry} onClick={() => prevEntry && selectId(prevEntry.id)} title={prevEntry ? "上一条：" + prevEntry.name : "已是第一条"}>
                        <I.ChevronLeft size={15} />
                      </button>
                      {selIdx >= 0 && <span className="dossier-nav-pos">{selIdx + 1} / {visible.length}</span>}
                      <button className="dossier-nav-btn" disabled={!nextEntry} onClick={() => nextEntry && selectId(nextEntry.id)} title={nextEntry ? "下一条：" + nextEntry.name : "已是最后一条"}>
                        <I.ChevronRight size={15} />
                      </button>
                    </div>
                    <Dossier entry={mergedSel} conns={selConns} byId={byId} onNav={navTo} go={go} onEdit={() => setEditing(true)} onDelete={mergedSel.user ? () => deleteEntry(selId) : null} onAction={(patch) => patchEntry(selId, patch)} onTogglePin={() => patchEntry(selId, { pinned: !mergedSel.pinned })} dirty={!!edits[selId]} />
                  </React.Fragment>
                )
            ) : (
              <div className="lib2-empty" style={{ padding: 80 }}>
                <I.BookOpen size={26} />
                <div>从左侧选择一份档案</div>
              </div>
            )}
          </section>
        </div>
        )}
      </div>
    </div>
  );
}

/* ---------------- Dossier ---------------- */
function Dossier({ entry: e, conns, byId, onNav, go, onEdit, onDelete, onAction, onTogglePin, dirty }) {
  const Ic = I[CAT_META[e.cat].icon] || I.Dot;
  const realChaps = (e.appears || []).filter(a => a && a !== "—");
  const cs = conns || [];
  const relGroups = LIB_groupConnections(cs);
  return (
    <div className={ACC(e.accent)} key={e.id}>
      <header className="dossier-head">
        <div className="dossier-glyph">{e.glyph}</div>
        <div className="dossier-head-main">
          <div className="dossier-code">{e.code}</div>
          <h2 className="dossier-name">
            {e.name}
            {e.state && <span className={`pill pill-${e.state.tone}`}><span className="pill-dot" />{e.state.label}</span>}
            {dirty && <span className="pill pill-gold"><span className="pill-dot" />已修改</span>}
          </h2>
          <div className="dossier-kind"><Ic size={13} style={{ verticalAlign: -2, marginRight: 5 }} />{e.kind}</div>
        </div>
        <div className="dossier-head-actions">
          <button
            className={`dossier-pin ${e.pinned ? "is-on" : ""}`}
            onClick={onTogglePin}
            title={e.pinned ? "取消置顶" : "置顶到总览"}
          >
            <I.Star size={14} /> {e.pinned ? "已置顶" : "置顶"}
          </button>
        </div>
      </header>

      <div className="dossier-body">
        {e.blurb ? (
          <section className="dossier-section">
            <div className="dossier-h"><I.Quote size={13} /> 简述</div>
            <p className="dossier-blurb">{e.blurb}</p>
          </section>
        ) : (
          <section className="dossier-section">
            <div className="dossier-newhint"><I.Edit size={14} /> 这份档案还很空，点「编辑档案」补充简述、关键信息与关联。</div>
          </section>
        )}

        {e.arc && e.arc.from !== "—" && (
          <section className="dossier-section">
            <div className="dossier-h"><I.ArrowRight size={13} /> 角色弧</div>
            <div className="dossier-arc">
              <div className="arc-node"><span className="lbl">起</span><span className="val">{e.arc.from}</span></div>
              <div className="arc-flow"><I.ChevronRight size={16} /></div>
              <div className="arc-node"><span className="lbl">终</span><span className="val">{e.arc.to}</span></div>
              <div className="arc-note">{e.arc.note}</div>
            </div>
          </section>
        )}

        {typeof e.progress === "number" && (
          <section className="dossier-section">
            <div className="dossier-h"><I.Clock size={13} /> 学习进度</div>
            <div className="dossier-prog">
              <div className="dossier-prog-track"><div className="dossier-prog-fill" style={{ width: `${Math.round(e.progress * 100)}%` }} /></div>
              <div className="dossier-prog-label"><span>正在学习该参考书</span><span>{Math.round(e.progress * 100)}%</span></div>
            </div>
          </section>
        )}

        {e.facts && e.facts.length > 0 && (
          <section className="dossier-section">
            <div className="dossier-h"><I.Info size={13} /> 关键信息</div>
            <div className="dossier-facts">
              {e.facts.map((f, i) => (
                <div key={i} className="dossier-fact"><span className="k">{f.k}</span><span className="v">{f.v}</span></div>
              ))}
            </div>
          </section>
        )}

        {e.tags && e.tags.length > 0 && (
          <section className="dossier-section">
            <div className="dossier-h"><I.Tag size={13} /> 标签</div>
            <div className="dossier-tags">
              {e.tags.map(t => <span key={t} className="dossier-tag"><span className="dot" />{t}</span>)}
            </div>
          </section>
        )}

        {cs.length > 0 && (
          <section className="dossier-section">
            <div className="dossier-h"><I.Compass size={13} /> 关系网络 · {cs.length}</div>
            <div className="rel-summary">
              {relGroups.map(g => {
                const Ti = I[g.type.icon] || I.Dot;
                return (
                  <span key={g.type.id} className={`rel-chip acc-${g.type.accent}`} title={g.type.hint}>
                    <Ti size={11} />{g.type.label}<b>{g.items.length}</b>
                  </span>
                );
              })}
            </div>
            <div className="rel-groups">
              {relGroups.map(g => {
                const Ti = I[g.type.icon] || I.Dot;
                return (
                  <div key={g.type.id} className={`rel-group acc-${g.type.accent}`}>
                    <div className="rel-group-h">
                      <span className="rel-group-ic"><Ti size={12} /></span>
                      <span className="rel-group-label">{g.type.label}</span>
                      <span className="rel-group-hint">{g.type.hint}</span>
                      <span className="rel-group-n">{g.items.length}</span>
                    </div>
                    <div className="dossier-links">
                      {g.items.map((l, i) => {
                        const t = byId[l.id];
                        if (!t) return null;
                        return (
                          <button key={i} className={`dossier-link ${ACC(t.accent)}`} onClick={() => onNav(l.id)}>
                            <span className="dossier-link-glyph">{t.glyph}</span>
                            <span className="dossier-link-main">
                              <span className="dossier-link-name">{t.name}</span>
                              <span className="dossier-link-rel">
                                {l.dir === "in" && <span className="dossier-link-dir" title="反向关联">被引</span>}
                                {l.rel}
                              </span>
                            </span>
                            <span className="dossier-link-cat">{CAT_META[t.cat].label}</span>
                            <I.ChevronRight className="chev" size={16} />
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {realChaps.length > 0 && (
          <section className="dossier-section">
            <div className="dossier-h"><I.BookOpen size={13} /> 出现于</div>
            <div className="dossier-chaps">
              {realChaps.map((c, i) => (
                <span key={i} className="dossier-chap"><I.FileText size={12} />{c}</span>
              ))}
            </div>
          </section>
        )}
      </div>

      <footer className="dossier-foot">
        <button className="btn btn-quiet btn-sm" onClick={onEdit}><I.Edit size={13} /> 编辑档案</button>
        <DossierAction entry={e} onAction={onAction} go={go} />
        <span className="spacer" />
        {onDelete && (
          <button className="btn btn-quiet btn-sm dossier-del" onClick={() => { if (confirm("删除这份档案？此操作不可撤销。")) onDelete(); }}><I.Trash size={13} /> 删除</button>
        )}
        {realChaps.some(c => /CH\d/.test(c)) && (
          <button className="btn btn-ghost btn-sm" onClick={() => { window.__writerEntityTarget = e.id; if (go) go("writer"); else window.dispatchEvent(new CustomEvent("ws:writer-locate", { detail: e.id })); }}><I.Pen size={13} /> 在正文中定位</button>
        )}
      </footer>
    </div>
  );
}

/* contextual primary action by category / state — 真正推进状态 */
function DossierAction({ entry: e, onAction }) {
  const act = LIB_nextAction(e);
  if (!act) {
    if (!e.state) return <span className="btn btn-primary btn-sm" aria-label="全文已展开"><I.Eye size={13} /> 全文已展开</span>;
    return null;
  }
  const Ic = I[act.icon] || I.Check;
  const cls = act.kind === "accent" ? "btn-accent" : act.kind === "primary" ? "btn-primary" : "btn-ghost";
  if (act.disabled) {
    return <button className="btn btn-ghost btn-sm" disabled><Ic size={13} /> {act.label}</button>;
  }
  return (
    <button className={`btn ${cls} btn-sm`} onClick={() => onAction && act.patch && onAction(act.patch)}>
      <Ic size={13} /> {act.label}
    </button>
  );
}

/* ---------- Trash — 真实回收站（WsTrashStore，按作品隔离） ---------- */
function wsTrashAgo(t) {
  const d = Date.now() - (t || 0);
  const m = Math.floor(d / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return m + " 分钟前";
  const h = Math.floor(m / 60);
  if (h < 24) return h + " 小时前";
  return Math.floor(h / 24) + " 天前";
}
function WsTrash() {
  const [, force] = React.useState(0);
  React.useEffect(() => (WsTrashStore ? WsTrashStore.subscribe(() => force(n => n + 1)) : undefined), []);
  const items = WsTrashStore ? WsTrashStore.list() : [];

  const restore = (id) => {
    const ok = WsTrashStore.restore(id);
    if (!ok) window.alert("恢复失败：原章节已不存在，且当前作品没有可承接的章节。");
  };
  const purge = (id) => {
    if (window.confirm("彻底删除？该条目（含其正文与旁注）将无法找回。")) WsTrashStore.purge(id);
  };
  const clearAll = () => {
    if (items.length && window.confirm(`清空回收站？${items.length} 条内容将无法找回。`)) WsTrashStore.clear();
  };

  return (
    <div className="page" data-screen-label="trash">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <div className="page-eyebrow">回收站</div>
            <h1 className="page-title">被回收的内容</h1>
            <p className="page-subtitle">删除的场景会带着正文进到这里，可以恢复回原章节；在书架里删除的整部作品也会进到这里，可以整体找回。</p>
          </div>
          {items.length > 0 && <button className="btn btn-ghost" onClick={clearAll}>清空</button>}
        </header>
        {items.length === 0 ? (
          <div className="card" style={{ display: "grid", placeItems: "center", padding: "64px 24px", textAlign: "center" }}>
            <div style={{ display: "grid", gap: 10, justifyItems: "center", color: "var(--ink-3)" }}>
              <I.Trash size={28} />
              <div style={{ fontFamily: "var(--font-serif)", fontSize: 18, color: "var(--ink-1)" }}>回收站是空的</div>
              <div style={{ fontSize: 13 }}>在写作器大纲里删除的场景、在书架里删除的作品，都会出现在这里，可随时恢复。</div>
            </div>
          </div>
        ) : (
          <div className="card" style={{ padding: 0 }}>
            <table className="lib-table">
              <thead>
                <tr><th>类型</th><th>标题</th><th>回收时间</th><th style={{ width: 180 }}></th></tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id}>
                    <td><span className="pill text-xs">{it.kind || "内容"}</span></td>
                    <td className="text-serif fw-600">{it.title}</td>
                    <td className="text-muted text-sm">{wsTrashAgo(it.removedAt)}</td>
                    <td>
                      <div className="flex gap-2">
                        <button className="btn btn-quiet btn-sm" onClick={() => restore(it.id)}>恢复</button>
                        <button className="btn btn-quiet btn-sm" onClick={() => purge(it.id)}>永久删除</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

Object.assign(window, { WsLibrary, WsTrash });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { WsLibrary, WsTrash };
