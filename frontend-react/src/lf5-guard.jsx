import React from "react";
import { I } from "./icons.jsx";
import { LF2_BOOK } from "./lf2-data.jsx";
import { LF3_CLUES } from "./lf3-data.jsx";
import { LF3_TABS, Lf3Arcs, Lf3Canon, Lf3Clues, Lf3Focus, Lf3Ledger, Lf3Threads, PRI3 } from "./lf3-guard.jsx";

/* global React, I, LF2_BOOK, LF3_CLUES, PRI3, LF3_TABS, Lf3Ledger, Lf3Threads, Lf3Arcs, Lf3Canon, Lf3Clues, Lf3Focus */
/* ==========================================================
   长篇控制塔 v5 · 守护台外壳（fork 自 v4）
   战情板分两组：
     ① 可装入交接 —— 漂移/逾期/停滞/空降/断链/泄气，逐条凝成 AI 随身契约
     ② 创作建议   —— 线索公平性/连续性/人物弧，不进交接，回正文处理
   让「契约 = 第一组」这件事在板上一眼可见；焦点条也只盯第一组。
   ========================================================== */

const LF5_BOARD_LOAD = ["conflict", "overdue", "stall", "orphan", "causal", "dip"];

function Lf5IssueCard({ it, i, focus, sel, onSelect, onAct }) {
  return (
    <article className={`lf3-issue tone-${it.tone} ${focus ? "lf4-issue-focus" : ""} ${sel && sel.type === it.ref.type && String(sel.id) === String(it.ref.id) ? "is-sel" : ""}`} onClick={() => onSelect(it.ref)}>
      <span className="lf3-issue-ic">{React.createElement(I[it.icon] || I.Dot, { size: 16 })}</span>
      <div className="lf3-issue-body">
        <div className="lf3-issue-top">
          <span className="lf3-issue-label">{it.label}</span>
          {focus && <span className="lf4-focus-badge"><I.Zap size={9} />焦点条</span>}
          <span className={`lf3-sev sev-${it.sev}`}>{PRI3[it.sev]}</span>
        </div>
        <div className="lf3-issue-title">{it.title}</div>
        <div className="lf3-issue-meta">{it.meta}</div>
      </div>
      <button className="lf3-issue-act" onClick={(e) => { e.stopPropagation(); onAct(it); }}>{it.action}<I.ArrowRight size={13} /></button>
    </article>
  );
}

function Lf5Board({ issues, doneIds, sel, onSelect, onAct }) {
  const pending = issues.filter(it => !doneIds.has(it.id));
  const done = issues.filter(it => doneIds.has(it.id));
  const load = pending.filter(it => LF5_BOARD_LOAD.includes(it.kind));
  const advise = pending.filter(it => !LF5_BOARD_LOAD.includes(it.kind));
  return (
    <div>
      <div className="lf3-board-h">
        <span className="lf3-zone-tag"><I.Zap size={13} /> 战情板 · 按急迫度</span>
        <span className="text-sm text-muted tab-num">{pending.length}<small> / {issues.length}</small></span>
      </div>

      {/* ① 可装入交接 = 本轮契约 */}
      <div className="lf5-board-sech is-load">
        <span className="lf5-board-sech-l"><I.ArrowRight size={12} /> 可装入交接 · 凝成第 {LF2_BOOK.now + 1} 章契约</span>
        <span className="lf5-board-sech-n">{load.length}</span>
      </div>
      <p className="lf3-board-lead">越靠上越急 · 每条一键装入交接，焦点条已替你顶起最急的一条。</p>
      <div className="lf3-issues">
        {load.map((it, i) => <Lf5IssueCard key={it.id} it={it} i={i} focus={i === 0} sel={sel} onSelect={onSelect} onAct={onAct} />)}
        {load.length === 0 && <div className="lf3-issues-clear"><I.CheckCircle size={18} /> 失控已全部装入交接 —— 契约就绪，可交接 AI 生成第 {LF2_BOOK.now + 1} 章。</div>}
      </div>

      {/* ② 创作建议 = 不进交接，回正文处理 */}
      {advise.length > 0 && <>
        <div className="lf5-board-sech is-advise">
          <span className="lf5-board-sech-l"><I.Eye size={12} /> 创作建议 · 不进交接 · 回正文处理</span>
          <span className="lf5-board-sech-n">{advise.length}</span>
        </div>
        <p className="lf3-board-lead">这些不靠「钉进下一章」解决，而是回到正文相应章节去补 —— 不阻塞本轮交接。</p>
        <div className="lf3-issues lf5-advise">
          {advise.map((it, i) => <Lf5IssueCard key={it.id} it={it} i={i} focus={false} sel={sel} onSelect={onSelect} onAct={onAct} />)}
        </div>
      </>}

      {done.length > 0 && (
        <div className="lf3-done-row">
          <span className="lf3-done-h">已装入交接 · {done.length}</span>
          {done.map(it => <span key={it.id} className="lf3-done-chip" onClick={() => onSelect(it.ref)}><I.Check size={11} />{it.label}</span>)}
        </div>
      )}
    </div>
  );
}

function Lf5Guard({ tab, setTab, issues, doneIds, d, loops, canon, now, sel, onSelect, onAct, onPinLoop, onSchedule, onResolveLoop, onResolveCanon, onPinCanon, onWrite }) {
  const pending = issues.filter(it => !doneIds.has(it.id));
  const isFocus = sel && ["chapter", "risk", "orphan", "causal"].includes(sel.type);
  const badges = {
    board: pending.filter(it => LF5_BOARD_LOAD.includes(it.kind)).length,
    ledger: d.overdue.length,
    threads: d.stalledThreads.length,
    canon: d.conflicts.length,
    clues: LF3_CLUES.filter(c => !c.fair && !c.pending).length,
  };
  return (
    <section className="lf3-guard">
      <div className="lf3-guard-tabs">
        {LF3_TABS.map(t => (
          <button key={t.id} className={`lf3-gtab ${tab === t.id && !isFocus ? "is-active" : ""}`} onClick={() => { onSelect(null); setTab(t.id); }}>
            {React.createElement(I[t.icon], { size: 14 })}{t.label}
            {badges[t.id] > 0 && <span className="lf3-gtab-badge">{badges[t.id]}</span>}
          </button>
        ))}
      </div>
      <div className="lf3-guard-body">
        {isFocus ? <Lf3Focus sel={sel} loops={loops} now={now} onSelect={onSelect} onWrite={onWrite} /> : <>
        {tab === "board" && <Lf5Board issues={issues} doneIds={doneIds} sel={sel} onSelect={onSelect} onAct={onAct} />}
        {tab === "ledger" && <Lf3Ledger loops={loops} now={now} sel={sel} onSelect={onSelect} onPin={onPinLoop} onSchedule={onSchedule} onResolve={onResolveLoop} onWrite={onWrite} />}
        {tab === "threads" && <Lf3Threads now={now} sel={sel} onSelect={onSelect} onWrite={onWrite} />}
        {tab === "arcs" && <Lf3Arcs sel={sel} onSelect={onSelect} />}
        {tab === "canon" && <Lf3Canon canon={canon} sel={sel} onSelect={onSelect} onResolve={onResolveCanon} onPin={onPinCanon} onWrite={onWrite} />}
        {tab === "clues" && <Lf3Clues sel={sel} onSelect={onSelect} now={now} onWrite={onWrite} />}
        </>}
      </div>
    </section>
  );
}

Object.assign(window, { Lf5Board, Lf5Guard });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { Lf5Board, Lf5Guard };
