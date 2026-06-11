import React from "react";
import { I } from "./icons.jsx";
import { LF2_BOOK, LF2_CHAPTERS, LF2_NEXT } from "./lf2-data.jsx";
import { LF3_AUDIT, LF3_BUDGET_CAP, LF3_RETRIEVE } from "./lf3-data.jsx";

/* global React, I, LF2_BOOK, LF2_NEXT, LF2_CHAPTERS, LF3_RETRIEVE, LF3_AUDIT, LF3_BUDGET_CAP */
/* ==========================================================
   右侧控制台（机器房 · AI 的一侧）
   顶：AI 工作记忆衰减条。
   主：分段切换「交接简报（含记忆预算）」/「草稿审计」。
   交接简报 = 强约束(占预算·永在场) vs 可检索池(进向量库·召回·不占预算)。
   草稿审计 = 逐条比对 + 正文证据句 + 新引入待归档（闭环后半环）。
   ========================================================== */
const FACT_COST = 60;

function Lf3ConsolePane(props) {
  const { consoleTab, setConsoleTab, hasDraft, d, now, onRepin } = props;
  return (
    <aside className="lf3-console">
      <Lf3Memory d={d} now={now} onRepin={onRepin} />
      <div className="lf3-seg">
        <button className={`lf3-seg-btn ${consoleTab === "brief" ? "is-active" : ""}`} onClick={() => setConsoleTab("brief")}>
          <I.ArrowRight size={14} /> 交接简报
        </button>
        <button className={`lf3-seg-btn ${consoleTab === "audit" ? "is-active" : ""}`} disabled={!hasDraft} onClick={() => hasDraft && setConsoleTab("audit")}>
          <I.ShieldCheck size={14} /> 草稿审计 {hasDraft && <span className="lf3-seg-dot" />}
        </button>
      </div>
      {consoleTab === "brief" ? <Lf3Brief {...props} /> : <Lf3Audit {...props} />}
    </aside>
  );
}

/* ---------- AI 工作记忆衰减 ---------- */
function Lf3Memory({ d, now, onRepin }) {
  const total = LF2_BOOK.total;
  const horizon = d.horizon;
  const fadingByCh = {};
  d.fading.forEach(f => { (fadingByCh[f.ch] = fadingByCh[f.ch] || []).push(f); });
  return (
    <div className="lf3-mem">
      <div className="lf3-mem-h">
        <span className="lf3-mem-ic"><I.Cpu size={17} /></span>
        <div><div className="lf3-mem-eyebrow">AI 工作记忆</div><div className="lf3-mem-title">它此刻到底记得什么</div></div>
      </div>
      <div className="lf3-mem-strip">
        {LF2_CHAPTERS.map(c => {
          const within = c.n >= horizon && c.n <= now;
          const future = c.n > now;
          const cls = future ? "is-future" : within ? "is-in" : "is-fade";
          const opacity = future ? 1 : within ? 1 : Math.max(0.3, 0.85 - (horizon - c.n) * 0.16);
          const crit = (fadingByCh[c.n] || []).length;
          return (<div key={c.n} className="lf3-mem-cell" title={`第 ${c.n} 章`}><span className={`lf3-mem-bar ${cls}`} style={{ opacity }} />{crit > 0 && <span className="lf3-mem-flag" />}</div>);
        })}
        <div className="lf3-mem-now" style={{ left: `${(now / total) * 100}%` }} />
      </div>
      <div className="lf3-mem-scale"><span className="is-fade">← 正在淡出</span><span className="is-in">视野内（最近 {d.win} 章）</span><span>未写 →</span></div>
      <p className="lf3-mem-note">AI 一次只读得进最近 <b>{d.win}</b> 章（第 {horizon}–{now} 章）。更早的内容正在离开它的上下文——{d.fading.length > 0 ? <>其中 <b className="tone-rose">{d.fading.length}</b> 项关键设定/悬念<b className="tone-rose">可能已被遗忘</b>。</> : <>关键设定均已钉入，记忆稳固。</>}</p>
      {d.fading.length > 0 && (<>
        <div className="lf3-mem-fade">
          {d.fading.map(f => <div key={f.kind + f.id} className="lf3-mem-fade-li"><span className="lf3-mem-fade-dot" /><span>{f.text}</span><span className="lf3-mem-fade-ch">第 {f.ch} 章</span></div>)}
        </div>
        <button className="lf3-mem-repin" onClick={onRepin}><I.Lock size={14} /> 重新钉入淡出的 {d.fading.length} 项 → 强约束</button>
      </>)}
    </div>
  );
}

/* ---------- 交接简报 + 记忆预算 ---------- */
function Lf3Brief({ brief, pinnedFacts, onToggleMode, onPromoteFact, onDemoteFact, onCopy, onPreview, onGenerate, gen }) {
  const promoted = LF3_RETRIEVE.filter(f => pinnedFacts.has(f.id));
  const enforce = brief.enforce;
  const used = brief.used + promoted.length * FACT_COST;
  const cap = LF3_BUDGET_CAP;
  const pctUsed = Math.min(100, (used / cap) * 100);
  const over = used > cap;
  // 预算条分段
  const segs = [...enforce.map(it => ({ tone: it.tone, cost: it.cost })), ...promoted.map(() => ({ tone: "slate", cost: FACT_COST }))];
  // 可检索池 = 简报里被下放的条目 + 未提升的世界事实
  const pool = [
    ...brief.retrieve.map(it => ({ id: it.id, text: it.text, sub: it.label + " · " + it.source, kind: "brief" })),
    ...LF3_RETRIEVE.filter(f => !pinnedFacts.has(f.id)).map(f => ({ id: f.id, text: f.text, sub: f.reason, kind: "fact" })),
  ];

  return (
    <>
      <div className="lf3-con-scroll">
        <div className="lf3-brief-head">
          <span className="lf3-brief-title text-serif">第 {brief.next} 章 · 长程约束记忆</span>
          <span className="lf3-brief-seam">交接线</span>
        </div>
        <p className="lf3-brief-lead">这些是 AI 上下文外、但写第 {brief.next} 章绝不能违反的长程约束。<b style={{ color: "var(--con-gold)" }}>强约束</b>随每次生成永在场；其余下放<b style={{ color: "var(--con-slate)" }}>可检索池</b>，相关时才从全书向量库召回。</p>

        {/* 预算条 */}
        <div className="lf3-budget">
          <div className="lf3-budget-top">
            <span className="lf3-budget-label"><I.Coins size={13} /> 长程记忆预算</span>
            <span className={`lf3-budget-num ${over ? "is-over" : ""}`}><b>{used.toLocaleString()}</b> <small>/ {cap.toLocaleString()} tok</small></span>
          </div>
          <div className="lf3-budget-bar">{segs.map((s, i) => <span key={i} className={`lf3-budget-seg tone-${s.tone}`} style={{ width: `${(s.cost / cap) * 100}%` }} />)}</div>
          <p className="lf3-budget-foot">{over ? <span style={{ color: "var(--con-rose)" }}>超出预算 {used - cap} tok——把不那么关键的强约束下放到可检索池，给最该守住的腾位置。</span> : <>{enforce.length + promoted.length} 条强约束占用 {pctUsed.toFixed(0)}% 预算 · 其余靠 RAG 按需召回，不占上下文。</>}</p>
        </div>

        {/* 强约束 · 按记忆层分组 */}
        {brief.strata.map(s => {
          const items = s.items.filter(it => it.mode === "enforce");
          if (!items.length) return null;
          return (
            <div key={s.key} className="lf3-stratum">
              <div className="lf3-stratum-h">{React.createElement(I[s.icon] || I.Dot, { size: 12 })}{s.title}</div>
              {items.map(it => (
                <div key={it.id} className={`lf3-ho tone-${it.tone} ${it.lock ? "is-locked" : ""}`}>
                  <div style={{ minWidth: 0 }}>
                    <div className="lf3-ho-text">{it.text}</div>
                    <div className="lf3-ho-src"><span className="lf3-ho-tag">{it.label}</span>{it.source}</div>
                  </div>
                  <div className="lf3-ho-right">
                    <span className="lf3-ho-cost">{it.cost} tok</span>
                    <button className="lf3-ho-toggle" disabled={it.lock} onClick={() => !it.lock && onToggleMode(it.id)} title={it.lock ? "核心约束 · 必须强制" : "下放到可检索池"}>{it.lock ? "锁定" : "↓ 检索"}</button>
                  </div>
                </div>
              ))}
            </div>
          );
        })}

        {/* 可检索池 */}
        <div className="lf3-pool">
          <div className="lf3-pool-h"><I.Database size={13} /> 可检索池 · 不占预算</div>
          <p className="lf3-pool-lead">存于全书向量库，写到相关情节时自动召回。点「↑ 强约束」可提升为永在场。</p>
          {pool.map(p => (
            <div key={p.id} className="lf3-pool-item">
              <span className="lf3-pool-dot" />
              <span className="lf3-pool-text">{p.text}<small>{p.sub}</small></span>
              <button className="lf3-pool-promote" onClick={() => p.kind === "fact" ? onPromoteFact(p.id) : onToggleMode(p.id)}>↑ 强约束</button>
            </div>
          ))}
        </div>
      </div>

      <div className="lf3-con-foot">
        <p className="lf3-con-note"><b>{enforce.length + promoted.length}</b> 条强约束随第 {brief.next} 章生成下发 · {pool.length} 条留向量库按需召回。</p>
        <div className="lf3-con-btns">
          <button className="lf3-cbtn is-ghost" onClick={onCopy}><I.FileText size={14} /></button>
          <button className="lf3-cbtn is-go" disabled={gen !== "idle"} onClick={onGenerate}>{gen === "generating" ? <><I.Refresh size={14} className="lf3-spin" /> 生成中…</> : <><I.Cpu size={14} /> 交接给 AI · 生成第 {brief.next} 章</>}</button>
        </div>
        <button className="lf3-con-preview" onClick={onPreview}><I.Eye size={12} /> 预览 AI 将收到的完整上下文</button>
      </div>
    </>
  );
}

/* ---------- 草稿审计（闭环后半环） ---------- */
function Lf3Audit({ audit, fixDone, onFix, newDone, onArchiveNew, onArchive, archivable }) {
  const a = audit || LF3_AUDIT;
  const honoredN = a.honored.length;
  const driftN = a.drifted.length;
  const newN = a.introduced.length;
  const resolvedDrift = a.drifted.filter(d => fixDone.has(d.id)).length;
  return (
    <>
      <div className="lf3-con-scroll">
        <div className="lf3-audit-verdict">
          <div className="lf3-audit-score"><b>{honoredN}<small style={{ fontSize: 16, color: "var(--con-ink-3)" }}>/{honoredN + driftN}</small></b><span>守约</span></div>
          <div className="lf3-audit-verdict-body">
            <div className="lf3-audit-verdict-title">第 {a.ch} 章草稿 · 已比对交接契约</div>
            <div className="lf3-audit-tally">
              <span className="lf3-tally is-ok"><I.Check size={11} /> {honoredN} 守住</span>
              <span className="lf3-tally is-warn"><I.AlertTriangle size={11} /> {driftN} 偏离</span>
              <span className="lf3-tally is-new"><I.Plus size={11} /> {newN} 新引入</span>
            </div>
          </div>
        </div>

        {/* 已守住 */}
        <div className="lf3-audit-sec-h is-ok"><I.ShieldCheck size={14} /> 已守住 · 附正文证据<span className="lf3-audit-sec-count">{honoredN}</span></div>
        {a.honored.map(h => (
          <div key={h.id} className="lf3-honored">
            <span className="lf3-honored-tick"><I.Check size={12} /></span>
            <div className="lf3-honored-body">
              <div className="lf3-honored-top"><span className={`lf3-honored-tag ${h.key ? "is-key" : ""}`}>{h.label}</span><span className="lf3-honored-text">{h.text}</span></div>
              <div className="lf3-honored-ev">「{h.evidence}」</div>
              <div className="lf3-honored-at">{h.at}</div>
            </div>
          </div>
        ))}

        {/* 偏离 */}
        <div className="lf3-audit-sec-h is-warn"><I.AlertTriangle size={14} /> 偏离 · 需你裁决<span className="lf3-audit-sec-count">{resolvedDrift}/{driftN} 已处理</span></div>
        {a.drifted.map(dr => {
          const done = fixDone.has(dr.id);
          return (
            <div key={dr.id} className={`lf3-drift tone-${dr.tone}`}>
              <div className="lf3-drift-top"><span className="lf3-drift-tag">{dr.label}</span><span className="lf3-drift-what">{dr.what}</span></div>
              <div className="lf3-drift-detail">{dr.detail}</div>
              <div className="lf3-drift-line">「{dr.line}」</div>
              <div className="lf3-drift-at">{dr.at}</div>
              <div className="lf3-drift-fixes">
                {done ? <button className="lf3-fix is-done"><I.Check size={12} /> 已处理 · 已送入下一轮</button> : dr.fixes.map((f, i) => <button key={i} className={`lf3-fix ${i === 0 ? "is-primary" : ""}`} onClick={() => onFix(dr.id, i)}>{f}</button>)}
              </div>
            </div>
          );
        })}

        {/* 新引入待归档 */}
        <div className="lf3-audit-sec-h is-new"><I.Plus size={14} /> 本章新引入 · 待归档<span className="lf3-audit-sec-count">{a.introduced.filter(n => newDone.has(n.id)).length}/{newN}</span></div>
        <p className="lf3-pool-lead" style={{ marginBottom: 10 }}>AI 本章新造的设定 / 承诺 / 地点。不归档，下一章可能继续沿用或与全书冲突。</p>
        {a.introduced.map(n => {
          const done = newDone.has(n.id);
          return (
            <div key={n.id} className={`lf3-new tone-${n.tone}`}>
              <span className="lf3-new-kind">{n.kind}</span>
              <span className="lf3-new-text">{n.text}</span>
              <p className="lf3-new-note">{n.note}</p>
              <div className="lf3-new-actions">
                {done ? <button className="lf3-fix is-done"><I.Check size={12} /> 已归档</button> : n.actions.map((act, i) => <button key={i} className="lf3-fix is-primary" onClick={() => onArchiveNew(n.id, i)}>{act}</button>)}
              </div>
            </div>
          );
        })}
      </div>

      <div className="lf3-con-foot">
        <p className="lf3-con-note">控制塔已替你记住整本书：交接 → 生成 → <b style={{ color: "var(--con-sage)" }}>审计</b> → 归档 → 下一轮。</p>
        <div className="lf3-con-btns">
          <button className="lf3-cbtn is-go" onClick={onArchive}><I.ArrowRight size={14} /> 归档并进入第 {a.ch + 1} 章交接</button>
        </div>
      </div>
    </>
  );
}

Object.assign(window, { Lf3ConsolePane, Lf3Memory, Lf3Brief, Lf3Audit, FACT_COST });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { Lf3ConsolePane, Lf3Memory, Lf3Brief, Lf3Audit, FACT_COST };
