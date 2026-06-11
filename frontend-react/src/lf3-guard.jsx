import React from "react";
import { I } from "./icons.jsx";
import { LF2_ACTS, LF2_ARCS, LF2_BOOK, LF2_CHAPTERS, LF2_CLR, LF2_RISKS, LF2_TARGET, LF2_THREADS, lf2ThreadLast, lf2ThreadStalled, lf2Tone } from "./lf2-data.jsx";
import { LF3_CAUSAL, LF3_CLUES, LF3_ORPHANS } from "./lf3-data.jsx";

/* global React, I, LF2_BOOK, LF2_TARGET, LF2_THREADS, LF2_ARCS, LF2_ACTS, LF2_CLR, LF2_RISKS, LF3_CLUES, LF3_ORPHANS, LF3_CAUSAL, lf2Tone, lf2ThreadLast, lf2ThreadStalled */
const { useState: useGuard } = React;
/* ==========================================================
   守护台（左下）：战情板 + 五透镜
   战情板 = 八类失控统一排序、一键拍板。
   透镜 = 伏笔债 / 故事线 / 人物弧 / 设定锚点 / 读者认知（公平性）的明细。
   ========================================================== */
const PRI3 = { high: "高", medium: "中", low: "低" };

const LF3_TABS = [
  { id: "board", label: "战情板", icon: "Zap" },
  { id: "ledger", label: "伏笔债", icon: "Target" },
  { id: "threads", label: "故事线", icon: "GitBranch" },
  { id: "arcs", label: "人物弧", icon: "Users" },
  { id: "canon", label: "设定锚点", icon: "ShieldCheck" },
  { id: "clues", label: "读者认知", icon: "Eye" },
];

function Lf3Guard({ tab, setTab, issues, doneIds, d, loops, canon, now, sel, onSelect, onAct, onPinLoop, onSchedule, onResolveLoop, onResolveCanon, onPinCanon, onWrite }) {
  const pending = issues.filter(it => !doneIds.has(it.id));
  const isFocus = sel && ["chapter", "risk", "orphan", "causal"].includes(sel.type);
  const badges = {
    board: pending.length,
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
        {tab === "board" && <Lf3Board issues={issues} doneIds={doneIds} sel={sel} onSelect={onSelect} onAct={onAct} />}
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

/* ---------- 战情板 ---------- */
function Lf3Board({ issues, doneIds, sel, onSelect, onAct }) {
  const pending = issues.filter(it => !doneIds.has(it.id));
  const done = issues.filter(it => doneIds.has(it.id));
  return (
    <div>
      <div className="lf3-board-h">
        <span className="lf3-zone-tag"><I.Zap size={13} /> 此刻最该你拍板的</span>
        <span className="text-sm text-muted tab-num">{pending.length}<small> / {issues.length}</small></span>
      </div>
      <p className="lf3-board-lead">八类长程失控统一排序——漂移 / 逾期 / 空降 / 断链 / 不公平最危险，越靠上越急。每条都能一键装入下一章交接。</p>
      <div className="lf3-issues">
        {pending.map(it => (
          <article key={it.id} className={`lf3-issue tone-${it.tone} ${sel && sel.type === it.ref.type && String(sel.id) === String(it.ref.id) ? "is-sel" : ""}`} onClick={() => onSelect(it.ref)}>
            <span className="lf3-issue-ic">{React.createElement(I[it.icon] || I.Dot, { size: 16 })}</span>
            <div className="lf3-issue-body">
              <div className="lf3-issue-top"><span className="lf3-issue-label">{it.label}</span><span className={`lf3-sev sev-${it.sev}`}>{PRI3[it.sev]}</span></div>
              <div className="lf3-issue-title">{it.title}</div>
              <div className="lf3-issue-meta">{it.meta}</div>
            </div>
            <button className="lf3-issue-act" onClick={(e) => { e.stopPropagation(); onAct(it); }}>{it.action}<I.ArrowRight size={13} /></button>
          </article>
        ))}
        {pending.length === 0 && <div className="lf3-issues-clear"><I.CheckCircle size={18} /> 全部拍板完毕——长程约束已装入第 {LF2_BOOK.now + 1} 章交接。</div>}
        {done.length > 0 && (
          <div className="lf3-done-row">
            <span className="lf3-done-h">已装入交接 · {done.length}</span>
            {done.map(it => <span key={it.id} className="lf3-done-chip" onClick={() => onSelect(it.ref)}><I.Check size={11} />{it.label}</span>)}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---------- 伏笔债 ---------- */
function Lf3Track({ loop, now, total }) {
  const overdue = loop.payoff != null && loop.payoff < now && loop.state === "open";
  const end = loop.payoff == null ? total : loop.payoff;
  const pct = (n) => `${((n - 0.5) / total) * 100}%`;
  const tone = overdue ? "rose" : loop.payoff == null ? "gold" : loop.state === "closing" ? "sage" : "slate";
  return (
    <div className={`lf3-track tone-${tone}`}>
      <div className="lf3-track-line" style={{ left: pct(loop.setup), right: `calc(100% - ${pct(end)})` }} />
      <div className="lf3-track-dot is-setup" style={{ left: pct(loop.setup) }} />
      <div className="lf3-track-now" style={{ left: `${(now / total) * 100}%` }} />
      {loop.payoff != null ? <div className={`lf3-track-dot is-pay ${overdue ? "is-od" : ""}`} style={{ left: pct(loop.payoff) }} /> : <div className="lf3-track-q" style={{ left: pct(total) }}>?</div>}
    </div>
  );
}

function Lf3Ledger({ loops, now, sel, onSelect, onPin, onSchedule, onResolve, onWrite }) {
  const open = loops.filter(l => l.state !== "closed");
  const rank = { high: 0, medium: 1, low: 2 };
  const sorted = [...open].sort((a, b) => {
    const ao = a.payoff != null && a.payoff < now && a.state === "open" ? -1 : 0;
    const bo = b.payoff != null && b.payoff < now && b.state === "open" ? -1 : 0;
    if (ao !== bo) return ao - bo;
    return rank[a.pri] - rank[b.pri];
  });
  return (
    <div>
      <p className="lf3-lens-intro">每一条都是对读者的承诺。<b>钉入交接</b>后，它随每次生成提醒 AI——不再写着写着就忘了回收。逾期的排在最前。</p>
      <ul className="lf3-led-list">
        {sorted.map(l => {
          const overdue = l.payoff != null && l.payoff < now && l.state === "open";
          const seld = sel && sel.type === "loop" && sel.id === l.id;
          return (
            <li key={l.id} className={`lf3-led ${seld ? "is-sel" : ""} ${overdue ? "is-od" : ""}`} onClick={() => onSelect({ type: "loop", id: l.id })}>
              <span className={`lf3-led-pri pri-${l.pri}`}>{PRI3[l.pri]}</span>
              <div style={{ minWidth: 0 }}>
                <div className="lf3-led-top">
                  <span className="lf3-led-title">{l.title}</span>
                  {overdue && <span className="pill pill-rose"><span className="pill-dot" />逾期</span>}
                  {l.state === "closing" && <span className="pill pill-sage"><span className="pill-dot" />回收中</span>}
                </div>
                <Lf3Track loop={l} now={now} total={LF2_BOOK.total} />
                <div className="lf3-led-meta">第 {l.setup} 章埋设 · {l.payoff != null ? `计划第 ${l.payoff} 章回收` : "未排定回收章"}</div>
              </div>
              <button className={`lf3-pin ${l.pinned ? "is-on" : ""}`} title={l.pinned ? "已钉入 AI 记忆" : "钉入 AI 记忆"} onClick={(e) => { e.stopPropagation(); onPin(l.id); }}>{l.pinned ? <I.Lock size={14} /> : <I.Unlock size={14} />}</button>
              {seld && (
                <div className="lf3-led-detail" onClick={(e) => e.stopPropagation()}>
                  <p className="lf3-led-note">{l.note}</p>
                  <div className="lf3-led-controls">
                    <span className="text-xs text-muted">计划回收章</span>
                    <select className="lf3-sched" value={l.payoff ?? ""} onChange={(e) => onSchedule(l.id, e.target.value === "" ? null : Number(e.target.value))}>
                      <option value="">未排定</option>
                      {Array.from({ length: LF2_BOOK.total }, (_, i) => i + 1).map(ch => <option key={ch} value={ch}>第 {ch} 章</option>)}
                    </select>
                    <button className="btn btn-accent btn-sm" onClick={() => onWrite(l.payoff || now + 1)}><I.Pen size={12} /> 去回收</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => onResolve(l.id)}><I.Check size={12} /> 已回收</button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ---------- 故事线 ---------- */
function Lf3Threads({ now, sel, onSelect, onWrite }) {
  return (
    <div>
      <p className="lf3-lens-intro">多线交织最容易"断更"。控制塔标出每条线最后被触及的章节——超过 3 章未推进即提示停滞。</p>
      <div className="lf3-thr-list">
        {LF2_THREADS.map(t => {
          const last = lf2ThreadLast(t), stalled = lf2ThreadStalled(t, now);
          const clr = LF2_CLR[t.color] || LF2_CLR.ink;
          const seld = sel && sel.type === "thread" && sel.id === t.id;
          return (
            <div key={t.id} className={`lf3-thr ${seld ? "is-sel" : ""}`} onClick={() => onSelect({ type: "thread", id: t.id })}>
              <div className="lf3-thr-head">
                <span className="lf3-thr-name"><i className="lf3-thr-dot" style={{ background: clr.c }} />{t.name}</span>
                {stalled ? <span className="pill pill-rose"><span className="pill-dot" />停滞 {now - last} 章</span> : <span className="pill pill-sage"><span className="pill-dot" />活跃</span>}
              </div>
              <div className="lf3-thr-track">
                {Array.from({ length: LF2_BOOK.total }, (_, i) => i + 1).map(ch => {
                  const on = t.segs.some(s => ch >= s[0] && ch <= s[1]);
                  const inStall = stalled && ch > last && ch <= now;
                  return <span key={ch} className={`lf3-thr-cell ${inStall ? "is-stall" : ""} ${ch === now ? "is-now" : ""}`} style={on ? { background: clr.c } : undefined} title={`第 ${ch} 章`} />;
                })}
              </div>
              <div className="lf3-thr-foot"><span className="text-sm text-muted">最后推进：第 {last} 章</span>{stalled && <button className="btn btn-quiet btn-sm" onClick={(e) => { e.stopPropagation(); onWrite(now + 1); }}>去推进 <I.ArrowRight size={12} /></button>}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ---------- 人物弧 ---------- */
function Lf3Arcs({ sel, onSelect }) {
  return (
    <div>
      <p className="lf3-lens-intro">每条曲线是一个人物沿章节推进的内部状态。平线 = 该角色停止成长，读者会失去投入。</p>
      <div className="lf3-arc-legend">
        {LF2_ARCS.map(a => (
          <button key={a.name} className={`lf3-arc-tag ${sel && sel.type === "arc" && sel.id === a.name ? "is-sel" : ""}`} style={{ "--ac": LF2_CLR[a.color].c }} onClick={() => onSelect({ type: "arc", id: a.name })}>
            <i className="lf3-arc-tag-dot" />{a.name}<small>{a.role}</small>{a.stalledFrom && <span className="lf3-arc-warn">停滞</span>}
          </button>
        ))}
      </div>
      <Lf3ArcChart arcs={LF2_ARCS} chapters={LF2_BOOK.total} now={LF2_BOOK.now} />
    </div>
  );
}

function Lf3ArcChart({ arcs, chapters, now }) {
  const W = 900, H = 280, PADL = 30, PADR = 22, PADT = 22, PADB = 28;
  const dx = (W - PADL - PADR) / (chapters - 1);
  const x = (ch) => PADL + (ch - 1) * dx;
  const y = (v) => H - PADB - v * (H - PADT - PADB);
  const nowX = x(now) + dx / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="lf3-arc-svg">
      {LF2_ACTS.map((a, i) => {
        const ax = Math.max(PADL, x(a.from) - dx / 2), ax2 = Math.min(W - PADR, x(a.to) + dx / 2);
        return (<g key={a.id}>{i % 2 === 1 && <rect x={ax} y={PADT - 6} width={ax2 - ax} height={H - PADT - PADB + 6} fill="var(--ink-4)" opacity="0.03" />}{i > 0 && <line x1={ax} x2={ax} y1={PADT - 6} y2={H - PADB} stroke="var(--line-2)" strokeWidth="1" strokeDasharray="1 4" opacity="0.6" />}<text x={(ax + ax2) / 2} y={11} fontSize="9.5" textAnchor="middle" fontFamily="var(--font-serif)" fontWeight="600" fill="var(--ink-4)">{a.name} · {a.sub}</text></g>);
      })}
      {[0.25, 0.5, 0.75].map(v => <line key={v} x1={PADL} x2={W - PADR} y1={y(v)} y2={y(v)} stroke="var(--line-1)" strokeWidth="1" strokeDasharray="2 4" />)}
      <rect x={nowX} y={PADT - 6} width={W - PADR - nowX} height={H - PADT - PADB + 6} fill="var(--ink-4)" opacity="0.05" />
      <line x1={nowX} x2={nowX} y1={PADT - 6} y2={H - PADB} stroke="var(--crimson)" strokeWidth="1.2" strokeDasharray="2 3" opacity="0.7" />
      {Array.from({ length: chapters }, (_, i) => i + 1).filter(c => c % 2 === 1 || c === chapters).map(ch => <text key={ch} x={x(ch)} y={H - PADB + 15} fontSize="9.5" fill="var(--ink-4)" textAnchor="middle" fontFamily="var(--font-mono)">{ch}</text>)}
      {arcs.map(a => {
        const clr = LF2_CLR[a.color].c;
        const dd = a.points.map((p, i) => `${i === 0 ? "M" : "L"} ${x(p.ch)} ${y(p.v)}`).join(" ");
        return (<g key={a.name}><path d={dd} stroke={clr} strokeWidth="2.4" fill="none" strokeLinejoin="round" strokeLinecap="round" />{a.points.map((p, i) => (<g key={i}><circle cx={x(p.ch)} cy={y(p.v)} r={p.current ? 5 : 3.2} fill={clr} stroke="var(--paper-0)" strokeWidth="2" />{p.label && <text x={x(p.ch)} y={y(p.v) - 9} fontSize="10" fill={clr} fontFamily="var(--font-serif)" textAnchor="middle" fontWeight="600">{p.label}</text>}</g>))}</g>);
      })}
    </svg>
  );
}

/* ---------- 设定锚点 ---------- */
function Lf3Canon({ canon, sel, onSelect, onResolve, onPin, onWrite }) {
  const otherRisks = (LF2_RISKS || []).filter(r => !r.drift && !r.canon);
  return (
    <div>
      <p className="lf3-lens-intro"><b>设定锚点</b>是 AI 不许自相矛盾的既定事实。标「漂移」的是最近一次生成新引入的冲突——长篇里最隐蔽的塌方。统一后即锁进交接记忆。</p>
      <ul className="lf3-canon-list">
        {[...canon].sort((a, b) => (a.status === "conflict" ? 0 : 1) - (b.status === "conflict" ? 0 : 1)).map(c => {
          const conflict = c.status === "conflict";
          const seld = sel && sel.type === "canon" && sel.id === c.id;
          return (
            <li key={c.id} className={`lf3-canon ${conflict ? "is-conflict" : ""} ${seld ? "is-sel" : ""}`} onClick={() => onSelect({ type: "canon", id: c.id })}>
              <span className={`lf3-canon-ic ${conflict ? "is-conflict" : ""}`}>{conflict ? <I.AlertTriangle size={14} /> : <I.Lock size={14} />}</span>
              <div style={{ minWidth: 0 }}>
                <div className="lf3-canon-top"><span className="lf3-canon-subject">{c.subject}</span><span className="lf3-canon-eq">=</span><span className="lf3-canon-value">{c.value}</span>{c.critical && <span className="lf3-canon-star"><I.Star size={11} /></span>}</div>
                <div className="lf3-canon-meta">第 {c.source} 章确立{conflict && <span className="lf3-canon-drift"><I.Cpu size={11} /> 第 {c.conflictCh} 章{c.drift ? "漂移" : "冲突"}</span>}{c.fresh && <span style={{ color: "var(--crimson)" }}>本轮新发现</span>}</div>
              </div>
              {conflict ? <button className="lf3-canon-act" onClick={(e) => { e.stopPropagation(); onResolve(c.id); }}>统一并锁定</button> : <button className={`lf3-pin ${c.pinned ? "is-on" : ""}`} onClick={(e) => { e.stopPropagation(); onPin(c.id); }}>{c.pinned ? <I.Lock size={14} /> : <I.Unlock size={14} />}</button>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ---------- 读者认知（悬疑公平性） ---------- */
function Lf3Clues({ sel, onSelect, now, onWrite }) {
  const total = LF2_BOOK.total;
  const pct = (n) => `${((n - 0.5) / total) * 100}%`;
  return (
    <div>
      <p className="lf3-lens-intro">悬疑长篇的命门：<b>读者已知 / 角色已知 / 真相</b> 三者错位即「戏剧反讽」，揭晓前是否提前埋了可推理的线索即「公平性」。AI 最爱直接揭晓而忘了铺。</p>
      <ul className="lf3-clue-list">
        {LF3_CLUES.map(c => {
          const seld = sel && sel.type === "clue" && sel.id === c.id;
          const verdict = c.pending ? "pending" : c.fair ? "fair" : "unfair";
          return (
            <li key={c.id} className={`lf3-clue ${!c.fair && !c.pending ? "is-unfair" : ""} ${seld ? "is-sel" : ""}`} onClick={() => onSelect({ type: "clue", id: c.id })}>
              <div className="lf3-clue-q"><I.Eye size={14} style={{ color: "var(--ink-3)" }} />{c.q}</div>
              <div className="lf3-clue-truth">真相：<b>{c.truth}</b> · 已知角色：{c.knows.join("、")}</div>
              <div className="lf3-fairbar">
                <span className="lf3-fairbar-k">铺设 → 揭晓</span>
                <div className="lf3-fairtrack">
                  {c.planted != null && c.reveal != null && <span className="lf3-fairtrack-seg lf3-fairtrack-plant" style={{ left: pct(c.planted), width: `calc(${pct(c.reveal)} - ${pct(c.planted)})` }} />}
                  {c.planted != null && <span className="lf3-fairtrack-tick" style={{ left: pct(c.planted) }}>{c.planted}</span>}
                  {c.reveal != null && <span className="lf3-fairtrack-seg lf3-fairtrack-reveal" style={{ left: pct(c.reveal) }} />}
                  {c.reveal != null && <span className="lf3-fairtrack-tick" style={{ left: `calc(${pct(c.reveal)} + 10px)`, color: "var(--crimson)" }}>{c.reveal}↑</span>}
                  {c.planted == null && <span className="lf3-fairtrack-tick" style={{ left: "10px", color: "var(--rose)" }}>未铺设</span>}
                </div>
              </div>
              <div className={`lf3-clue-verdict is-${verdict}`}>
                {verdict === "fair" && <span><I.ShieldCheck size={13} style={{verticalAlign:"-2px"}} /> 公平 · 揭晓前已在第{c.planted}章铺设线索</span>}
                {verdict === "pending" && <span><I.Clock size={13} style={{verticalAlign:"-2px"}} /> 悬置中 · 线索已埋（第{c.planted}章），尚未揭晓</span>}
                {verdict === "unfair" && <><I.AlertTriangle size={13} /> {c.note}</>}
              </div>
              {seld && verdict === "unfair" && (
                <div className="lf3-led-detail" onClick={(e) => e.stopPropagation()}>
                  <div className="lf3-led-controls"><button className="btn btn-accent btn-sm" onClick={() => onWrite(now + 1)}><I.Pen size={12} /> 去埋线索（第 {now + 1} 章）</button></div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ---------- 焦点详情（章节 / 风险 / 空降 / 断链 —— 无专属透镜的元素） ---------- */
function Lf3FocusBlock({ label, items, empty, tone }) {
  return (
    <div className="lf3-focus-block">
      <div className={`lf3-focus-block-h tone-${tone}`}>{label}</div>
      {items.length === 0 ? <div className="lf3-focus-block-empty">{empty}</div> : <ul>{items.map((t, i) => <li key={i}>{t}</li>)}</ul>}
    </div>
  );
}

function Lf3Focus({ sel, loops, now, onSelect, onWrite }) {
  const back = <button className="lf3-focus-back" onClick={() => onSelect(null)}><I.ChevronLeft size={14} /> 返回</button>;

  if (sel.type === "chapter") {
    const c = LF2_CHAPTERS.find(x => x.n === sel.id);
    const opens = loops.filter(l => l.setup === c.n);
    const closes = loops.filter(l => l.payoff === c.n);
    const active = LF2_THREADS.filter(t => t.segs.some(s => c.n >= s[0] && c.n <= s[1]));
    const risks = LF2_RISKS.filter(r => r.ch === c.n);
    const tgt = LF2_TARGET[c.n - 1];
    return (
      <div className="lf3-focus">
        <div className="lf3-focus-head">
          <span className="lf3-focus-ic"><I.BookOpen size={16} /></span>
          <div><div className="lf3-focus-eyebrow">第 {String(c.n).padStart(2, "0")} 章</div><div className="lf3-focus-title">{c.title}</div></div>
          <span className={`pill pill-${c.planned ? "slate" : c.current ? "rose" : "sage"}`}><span className="pill-dot" />{c.planned ? "待写" : c.current ? "进行中" : "已落稿"}</span>
        </div>
        {!c.planned && <div className="lf3-focus-stats"><div><b>{c.words.toLocaleString()}</b><span>字</span></div><div><b className={`tone-${lf2Tone(c.pace)}`}>{c.pace.toFixed(2)}</b><span>实际张力</span></div><div><b>{tgt.toFixed(2)}</b><span>目标张力</span></div></div>}
        {c.beat && <div className="lf3-focus-beat"><I.MapPin size={13} /> 结构节拍：{c.beat}</div>}
        <Lf3FocusBlock label="在场故事线" tone="slate" items={active.map(t => t.short)} empty="无活跃故事线" />
        {opens.length > 0 && <Lf3FocusBlock label="本章埋设伏笔" tone="gold" items={opens.map(l => l.title)} empty="" />}
        {closes.length > 0 && <Lf3FocusBlock label="本章回收伏笔" tone="sage" items={closes.map(l => l.title)} empty="" />}
        {risks.length > 0 && <Lf3FocusBlock label="本章连续性风险" tone="rose" items={risks.map(r => r.text)} empty="" />}
        <div className="lf3-focus-actions"><button className="btn btn-accent btn-sm" onClick={() => onWrite(c.n)}><I.Pen size={13} /> {c.planned ? "开始写作" : "去深改"}</button>{back}</div>
      </div>
    );
  }

  if (sel.type === "risk") {
    const r = LF2_RISKS.find(x => x.id === sel.id);
    if (!r) return <div className="lf3-focus">{back}</div>;
    return (
      <div className="lf3-focus">
        <div className="lf3-focus-head">
          <span className="lf3-focus-ic"><I.ShieldCheck size={16} /></span>
          <div><div className="lf3-focus-eyebrow">连续性 · {r.type}</div><div className="lf3-focus-title">跨章节{r.type}风险</div></div>
          <span className={`pill pill-${r.sev === "high" ? "rose" : r.sev === "medium" ? "gold" : "slate"}`}><span className="pill-dot" />{PRI3[r.sev]}</span>
        </div>
        <p className="lf3-focus-note">{r.text}</p>
        {r.fix && <div className="lf3-focus-fix"><I.Check size={14} /> 建议：{r.fix}</div>}
        <div className="lf3-focus-actions"><button className="btn btn-accent btn-sm" onClick={() => onWrite(r.ch)}><I.Pen size={13} /> 前往第 {r.ch} 章</button>{back}</div>
      </div>
    );
  }

  if (sel.type === "orphan") {
    const o = LF3_ORPHANS.find(x => x.id === sel.id);
    if (!o) return <div className="lf3-focus">{back}</div>;
    return (
      <div className="lf3-focus">
        <div className="lf3-focus-head">
          <span className="lf3-focus-ic" style={{ background: "var(--crimson-wash)", color: "var(--crimson)" }}><I.Zap size={16} /></span>
          <div><div className="lf3-focus-eyebrow">空降回收 · 有揭示无铺垫</div><div className="lf3-focus-title">{o.reveal}</div></div>
          <span className="pill pill-crimson"><span className="pill-dot" />第 {o.revealCh} 章</span>
        </div>
        <p className="lf3-focus-note">{o.why}</p>
        <div className="lf3-focus-fix"><I.Check size={14} /> 建议：{o.fix}</div>
        <div className="lf3-focus-actions"><button className="btn btn-accent btn-sm" onClick={() => onWrite(Math.max(1, o.revealCh - 1))}><I.Pen size={13} /> 去前序章节补铺垫</button>{back}</div>
      </div>
    );
  }

  if (sel.type === "causal") {
    const k = LF3_CAUSAL.find(x => x.id === sel.id);
    if (!k) return <div className="lf3-focus">{back}</div>;
    return (
      <div className="lf3-focus">
        <div className="lf3-focus-head">
          <span className="lf3-focus-ic" style={{ background: "var(--rose-wash)", color: "var(--rose)" }}><I.GitBranch size={16} /></span>
          <div><div className="lf3-focus-eyebrow">因果断链 · 承重事件缺前因</div><div className="lf3-focus-title">{k.effect}</div></div>
          <span className="pill pill-rose"><span className="pill-dot" />第 {k.effectCh} 章</span>
        </div>
        <div className="lf3-focus-block"><div className="lf3-focus-block-h tone-slate">因 → 果</div><ul><li>因：{k.cause}{k.causeCh ? `（第 ${k.causeCh} 章）` : "（全书缺失）"}</li><li>果：{k.effect}（第 {k.effectCh} 章）</li></ul></div>
        <p className="lf3-focus-note">{k.why}</p>
        <div className="lf3-focus-fix"><I.Check size={14} /> 建议：{k.fix}</div>
        <div className="lf3-focus-actions"><button className="btn btn-accent btn-sm" onClick={() => onWrite(k.effectCh - 1)}><I.Pen size={13} /> 去补承重因</button>{back}</div>
      </div>
    );
  }
  return <div className="lf3-focus">{back}</div>;
}

Object.assign(window, { Lf3Guard, Lf3Track, PRI3, Lf3Board, Lf3Ledger, Lf3Threads, Lf3Arcs, Lf3Canon, Lf3Clues, Lf3Focus, LF3_TABS });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { Lf3Guard, Lf3Track, PRI3, Lf3Board, Lf3Ledger, Lf3Threads, Lf3Arcs, Lf3Canon, Lf3Clues, Lf3Focus, LF3_TABS };
