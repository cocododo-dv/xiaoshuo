import React from "react";
import { I } from "./icons.jsx";
import { LIB_CATS } from "./ws-library-data.jsx";
import { LIB_nextAction } from "./ws-library-derive.jsx";

/* global React, I, LIB_CATS, LIB_nextAction */
/* ==========================================================
   Library — 故事圣经总览 (landing dashboard)
   进入资料库的落地视图：健康度 · 待处理队列 · 最近更新 ·
   置顶 · 孤立条目 · 类别分布。所有卡片可点，直达对应档案。
   ========================================================== */

const OV_CAT = LIB_CATS.reduce((m, c) => { m[c.id] = c; return m; }, {});

function OvEntryRow({ e, sub, right, onSelect }) {
  return (
    <button className={`ov-row acc-${e.accent}`} onClick={() => onSelect(e.id)}>
      <span className="ov-row-glyph">{e.glyph}</span>
      <span className="ov-row-main">
        <span className="ov-row-name">{e.name}</span>
        <span className="ov-row-sub">{sub}</span>
      </span>
      {right}
      <I.ChevronRight className="ov-row-chev" size={15} />
    </button>
  );
}

/* 队列行：主区可点进入档案，右侧动作按钮就地推进状态 */
function OvQueueRow({ e, cta, onSelect, onAction }) {
  const act = LIB_nextAction(e);
  const Ic = act && (I[act.icon] || I.Check);
  return (
    <div className={`ov-qrow acc-${e.accent}`}>
      <button className="ov-qrow-main" onClick={() => onSelect(e.id)}>
        <span className="ov-row-glyph">{e.glyph}</span>
        <span className="ov-row-main">
          <span className="ov-row-name">{e.name}</span>
          <span className="ov-row-sub">{cta}</span>
        </span>
      </button>
      <span className={`pill pill-${e.state.tone}`}><span className="pill-dot" />{e.state.label}</span>
      {act && !act.disabled && act.patch && (
        <button className="ov-qrow-act" onClick={() => onAction(e.id, act.patch)} title={act.label}>
          <Ic size={13} /> {act.label}
        </button>
      )}
    </div>
  );
}

function LibOverview({ health, byId, onSelect, onPickCat, onGoGraph, onNew, onAction }) {
  const { total, linksN, cited, buckets, queue, recent, pinned, isolated, byCat, readiness, stated } = health;
  const maxCat = Math.max(1, ...byCat.map(c => c.n));

  return (
    <div className="ov" data-screen-label="library-overview">
      {/* ---- hero: 健康度 ---- */}
      <section className="ov-hero">
        <div className="ov-hero-l">
          <div className="ov-hero-eyebrow"><I.Activity size={13} /> 故事圣经 · 状态总览</div>
          <h2 className="ov-hero-title">{total} 份档案，{linksN} 条关联在彼此呼应</h2>
          <p className="ov-hero-sub">
            {queue.length > 0
              ? <>有 <b>{queue.length}</b> 份档案在等你处理，{cited} 份已被正文引用。</>
              : <>所有档案都已就绪，{cited} 份已被正文引用。可以安心写作。</>}
          </p>
          <div className="ov-hero-actions">
            <button className="btn btn-accent btn-sm" onClick={onNew}><I.Plus size={13} /> 新建档案</button>
            <button className="btn btn-ghost btn-sm" onClick={onGoGraph}><I.Compass size={13} /> 看关系图谱</button>
          </div>
        </div>
        <div className="ov-hero-r">
          <div className="ov-ring" style={{ "--p": readiness }}>
            <div className="ov-ring-mid">
              <div className="ov-ring-n">{readiness}<span>%</span></div>
              <div className="ov-ring-k">就绪度</div>
            </div>
          </div>
          <div className="ov-buckets">
            <span className="ov-bk"><span className="d done" />已就绪 {buckets.done}</span>
            <span className="ov-bk"><span className="d active" />进行中 {buckets.active}</span>
            <span className="ov-bk"><span className="d pending" />待处理 {buckets.pending}</span>
          </div>
        </div>
      </section>

      <div className="ov-grid">
        {/* ---- 待处理队列 ---- */}
        <section className="ov-card ov-span-2">
          <div className="ov-card-h">
            <span className="ov-card-t"><I.Inbox size={14} /> 待你处理</span>
            <span className="ov-card-n">{queue.length}</span>
          </div>
          {queue.length === 0 ? (
            <div className="ov-empty"><I.CheckCircle size={22} /><div>队列已清空，没有待办</div></div>
          ) : (
            <div className="ov-queue">
              {queue.map(({ e, cta }) => (
                <OvQueueRow key={e.id} e={e} cta={cta} onSelect={onSelect} onAction={onAction} />
              ))}
            </div>
          )}
        </section>

        {/* ---- 类别分布 ---- */}
        <section className="ov-card">
          <div className="ov-card-h"><span className="ov-card-t"><I.Layers size={14} /> 类别分布</span></div>
          <div className="ov-cats">
            {byCat.map(({ cat, n }) => {
              const Ic = I[cat.icon] || I.Dot;
              return (
                <button key={cat.id} className={`ov-catbar acc-${cat.accent}`} onClick={() => onPickCat(cat.id)}>
                  <span className="ov-catbar-ic"><Ic size={13} /></span>
                  <span className="ov-catbar-label">{cat.label}</span>
                  <span className="ov-catbar-track"><span className="ov-catbar-fill" style={{ width: `${(n / maxCat) * 100}%` }} /></span>
                  <span className="ov-catbar-n">{n}</span>
                </button>
              );
            })}
          </div>
        </section>

        {/* ---- 最近更新 ---- */}
        <section className="ov-card">
          <div className="ov-card-h"><span className="ov-card-t"><I.Clock size={14} /> 最近更新</span></div>
          <div className="ov-list">
            {recent.map(e => (
              <OvEntryRow key={e.id} e={e} sub={OV_CAT[e.cat].label + " · " + e.updated} onSelect={onSelect} />
            ))}
          </div>
        </section>

        {/* ---- 置顶 ---- */}
        <section className="ov-card">
          <div className="ov-card-h">
            <span className="ov-card-t"><I.Star size={14} /> 置顶</span>
            <span className="ov-card-n">{pinned.length}</span>
          </div>
          {pinned.length === 0 ? (
            <div className="ov-empty ov-empty-sm"><div>还没有置顶的档案</div></div>
          ) : (
            <div className="ov-list">
              {pinned.map(e => (
                <OvEntryRow key={e.id} e={e} sub={e.summary || OV_CAT[e.cat].label} onSelect={onSelect} />
              ))}
            </div>
          )}
        </section>

        {/* ---- 孤立条目 (hygiene) ---- */}
        <section className={`ov-card ${isolated.length ? "ov-card-warn" : ""}`}>
          <div className="ov-card-h">
            <span className="ov-card-t">
              {isolated.length ? <I.AlertTriangle size={14} /> : <I.CheckCircle size={14} />} 孤立档案
            </span>
            <span className="ov-card-n">{isolated.length}</span>
          </div>
          {isolated.length === 0 ? (
            <div className="ov-empty ov-empty-sm"><div>每份档案都有关联，结构很健康</div></div>
          ) : (
            <>
              <p className="ov-warn-note">这些档案还没有任何关联，建议补上关系，让它们融入故事网络。</p>
              <div className="ov-chips">
                {isolated.map(e => (
                  <button key={e.id} className={`ov-chip acc-${e.accent}`} onClick={() => onSelect(e.id)}>
                    <span className="ov-chip-glyph">{e.glyph}</span>{e.name}
                  </button>
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

Object.assign(window, { LibOverview });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { LibOverview };
