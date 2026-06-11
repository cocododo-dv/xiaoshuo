import React from "react";
import { I } from "./icons.jsx";
import { LIB_BY_ID, LIB_CATS, LIB_ENTRIES } from "./ws-library-data.jsx";

/* global React, I, LIB_CATS, LIB_ENTRIES, LIB_BY_ID */
const { useMemo: useTlMemo } = React;

/* ==========================================================
   Library — 叙事时间线
   两条轨道：世界纪年（大事记） + 章节脉络（出场矩阵）
   ========================================================== */

const TLCAT = LIB_CATS.reduce((m, c) => { m[c.id] = c; return m; }, {});

/* extract a chapter token like "CH02" from an appears string */
function chapOf(s) {
  const m = /CH\s*0*(\d+)/i.exec(s);
  return m ? "CH" + String(m[1]).padStart(2, "0") : null;
}

function LibTimeline({ selId, onSelect, onOpen, entries, byId }) {
  const ents = entries || LIB_ENTRIES;
  const bid = byId || LIB_BY_ID;
  /* world chronology — dated events, ascending */
  const eras = useTlMemo(() => {
    return ents
      .filter(e => e.cat === "events")
      .map(e => {
        const y = (/\d{4}/.exec(e.kind) || /\d{4}/.exec((e.facts[0] || {}).v || ""))?.[0];
        return { e, year: y ? parseInt(y, 10) : 9999 };
      })
      .sort((a, b) => a.year - b.year);
  }, [ents]);

  /* chapter spine — CHxx → entries that appear there */
  const chapters = useTlMemo(() => {
    const map = {};
    ents.forEach(e => {
      const chs = new Set();
      (e.appears || []).forEach(a => { const c = chapOf(a); if (c) chs.add(c); });
      chs.forEach(c => { (map[c] = map[c] || []).push(e); });
    });
    return Object.keys(map).sort().map(c => ({ ch: c, items: map[c] }));
  }, [ents]);

  /* entries with no chapter anchor but present throughout */
  const ambient = useTlMemo(() => {
    return ents.filter(e =>
      (e.appears || []).some(a => ["贯穿", "环境", "全稿"].includes(a)) &&
      !(e.appears || []).some(a => chapOf(a))
    );
  }, [ents]);

  return (
    <div className="lib2-timeline">
      {/* ---- world chronology ---- */}
      <section className="tl-section">
        <div className="tl-h"><I.Clock size={13} /> 世界纪年 · 故事内时间</div>
        <div className="tl-era">
          {eras.map(({ e, year }, i) => (
            <React.Fragment key={e.id}>
              <button
                className={`tl-event acc-${e.accent} ${selId === e.id ? "is-sel" : ""}`}
                onClick={() => onSelect(e.id)}
                onDoubleClick={() => onOpen(e.id)}
                title="点击选中 · 双击展开档案"
              >
                <span className="tl-event-year">{year !== 9999 ? year : "现在"}</span>
                <span className="tl-event-name">{e.name}</span>
                <span className="tl-event-sum">{e.summary}</span>
                <span className="tl-event-glyphs">
                  {(e.links || []).slice(0, 4).map(l => {
                    const t = bid[l.id]; if (!t) return null;
                    return <span key={l.id} className={`tl-mini acc-${t.accent}`} title={t.name}>{t.glyph}</span>;
                  })}
                </span>
              </button>
              {i < eras.length && <span className="tl-arrow"><I.ChevronRight size={20} /></span>}
            </React.Fragment>
          ))}
          {/* terminal: the manuscript present */}
          <div className="tl-now">
            <span className="tl-now-dot"><I.Pen size={16} /></span>
            <span className="tl-event-year">现在</span>
            <span className="tl-event-name">正文进行中</span>
            <span className="tl-event-sum">CH01 – CH08</span>
          </div>
        </div>
      </section>

      {/* ---- chapter spine ---- */}
      <section className="tl-section">
        <div className="tl-h"><I.BookOpen size={13} /> 章节脉络 · 各章出场</div>
        <div className="tl-chaps">
          {chapters.map(({ ch, items }) => (
            <div className="tl-chap" key={ch}>
              <div className="tl-chap-head">
                <span className="tl-chap-no">{ch}</span>
                <span className="tl-chap-n">{items.length}</span>
              </div>
              <div className="tl-chap-list">
                {items.map(e => (
                  <button
                    key={e.id}
                    className={`tl-chip acc-${e.accent} ${selId === e.id ? "is-sel" : ""}`}
                    onClick={() => onSelect(e.id)}
                    onDoubleClick={() => onOpen(e.id)}
                    title={`${e.name} · ${e.kind} — 点击选中，双击展开档案`}
                  >
                    <span className="tl-chip-glyph">{e.glyph}</span>
                    <span className="tl-chip-name">{e.name}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ---- ambient (throughout) ---- */}
      {ambient.length > 0 && (
        <section className="tl-section">
          <div className="tl-h"><I.Layers size={13} /> 贯穿全书 · 无固定章节</div>
          <div className="tl-ambient">
            {ambient.map(e => (
              <button
                key={e.id}
                className={`tl-chip acc-${e.accent} ${selId === e.id ? "is-sel" : ""}`}
                onClick={() => onSelect(e.id)}
                onDoubleClick={() => onOpen(e.id)}
                title={`${e.name} · ${e.kind}`}
              >
                <span className="tl-chip-glyph">{e.glyph}</span>
                <span className="tl-chip-name">{e.name}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <div className="tl-hint"><I.Info size={12} /> 单击选中并联动档案，双击直接展开完整档案</div>
    </div>
  );
}

Object.assign(window, { LibTimeline });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { LibTimeline };
