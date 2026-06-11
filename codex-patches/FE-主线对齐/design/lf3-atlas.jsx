/* global React, I, LF2_TARGET, LF2_ACTS, LF2_CLR, LF3_ORPHANS, lf2ThreadLast, lf2ThreadStalled */
const { useState: useAtlas3 } = React;
/* ==========================================================
   全书航图 v3 — 一屏俯瞰整本书的诊断仪器
   四泳道：章节 · 张力 · 伏笔航迹（含空降标记）· 故事线
   竖线「现在·交接线」= 既定 / 承诺的分界；「AI 视野起点」= 上下文边界。
   ========================================================== */
function Lf3Atlas({ chapters, threads, loops, canon, now, horizon, acts, selected, onSelect, scanning }) {
  const W = 1000, H = 452, PADL = 116, PADR = 26;
  const plotW = W - PADL - PADR;
  const C = chapters.length;
  const col = plotW / C;
  const cx = (ch) => PADL + (ch - 0.5) * col;
  const bnd = (ch) => PADL + ch * col;
  const nowX = bnd(now);
  const horizonX = bnd(horizon - 1);

  const cy0 = 46, chH = 44;
  const tT0 = 110, tT1 = 188;
  const yT = (v) => tT1 - Math.max(0, Math.min(1, v)) * (tT1 - tT0);
  const yLB = 320, tR0 = 346, rowH = 12, rowGap = 11;

  const sel = selected || {};
  const isSel = (type, id) => sel.type === type && String(sel.id) === String(id);
  const [hover, setHover] = useAtlas3(null);
  const [actId, setActId] = useAtlas3(null);
  const act = (acts || LF2_ACTS).find(a => a.id === actId) || null;
  const inAct = (ch) => !act || (ch >= act.from && ch <= act.to);
  const PRI = { high: "高", medium: "中", low: "低" };

  const written = chapters.filter(c => !c.planned);
  const tgtPts = chapters.map(c => `${cx(c.n)},${yT(LF2_TARGET[c.n - 1])}`).join(" ");
  const actPts = written.map(c => `${cx(c.n)},${yT(c.pace)}`);
  const actArea = `M ${cx(1)},${tT1} L ${actPts.join(" L ")} L ${cx(written.length)},${tT1} Z`;

  const lsorted = [...loops].map(l => ({ ...l, end: l.payoff == null ? C : l.payoff }))
    .sort((a, b) => (b.end - b.setup) - (a.end - a.setup));

  return (
    <div className={`lf3-atlas ${scanning ? "is-scanning" : ""}`}>
      <div className="lf3-atlas-head">
        <div className="lf3-atlas-title">
          <span className="lf3-zone-tag"><I.BookOpen size={13} /> 纸上的书</span>
          <div>
            <h2 className="text-serif">全书航图</h2>
            <p>一屏俯瞰整本书的健康 · 点任意元素查看 / 装入交接</p>
          </div>
        </div>
        <div className="lf3-act-bar">
          <button className={`lf3-act ${!act ? "is-on" : ""}`} onClick={() => setActId(null)}><b>全书</b><small>{C} 章</small></button>
          {(acts || LF2_ACTS).map(a => (
            <button key={a.id} className={`lf3-act ${actId === a.id ? "is-on" : ""}`} onClick={() => setActId(actId === a.id ? null : a.id)}>
              <b>{a.name}·{a.sub}</b><small>{a.from}–{a.to}</small>
            </button>
          ))}
        </div>
      </div>

      <div className="lf3-atlas-plot">
        <svg viewBox={`0 0 ${W} ${H}`} className="lf3-atlas-svg" role="img" aria-label="全书航图">
          <defs>
            <pattern id="lf3Stall" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
              <rect width="6" height="6" fill="var(--paper-2)" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--rose)" strokeWidth="1.4" opacity="0.5" />
            </pattern>
            <marker id="lf3Arrow" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0 0 L6 3.5 L0 7 z" fill="var(--gold)" /></marker>
            <linearGradient id="lf3Fade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="var(--slate)" stopOpacity="0.10" /><stop offset="1" stopColor="var(--slate)" stopOpacity="0" /></linearGradient>
          </defs>

          <rect x={nowX} y={cy0 - 10} width={W - PADR - nowX} height={H - cy0} fill="var(--ink-4)" opacity="0.045" />
          <rect x={PADL} y={cy0 - 10} width={Math.max(0, horizonX - PADL)} height={H - cy0} fill="url(#lf3Fade)" />

          {(acts || LF2_ACTS).map((a, i) => {
            const ax = bnd(a.from - 1), aw = bnd(a.to) - bnd(a.from - 1);
            const on = act && act.id === a.id;
            return (
              <g key={a.id}>
                {(i % 2 === 1 || on) && <rect x={ax} y={cy0 - 10} width={aw} height={H - cy0 - 2} fill="var(--ink-4)" opacity={on ? 0.07 : 0.026} />}
                {i > 0 && <line x1={ax} x2={ax} y1={cy0 - 10} y2={H - 6} stroke="var(--line-2)" strokeWidth="1" strokeDasharray="1 4" opacity="0.7" />}
                <text x={ax + aw / 2} y={H - 3} fontSize="10" textAnchor="middle" fontFamily="var(--font-serif)" fontWeight="600" fill={on ? "var(--crimson)" : "var(--ink-4)"} opacity={act && !on ? 0.4 : 1}>{a.name} · {a.sub}</text>
              </g>
            );
          })}

          {[100, 200, 332].map(y => <line key={y} x1={18} x2={W - PADR} y1={y} y2={y} stroke="var(--line-1)" strokeWidth="1" />)}
          {[["章节", 70], ["张力", 150], ["伏笔债", 268], ["故事线", 392]].map(([t, y]) => (
            <text key={t} x={18} y={y} fontSize="12" fontWeight="700" fill="var(--ink-4)" fontFamily="var(--font-sans)" letterSpacing="0.04em">{t}</text>
          ))}

          {/* 章节带 */}
          {chapters.map(c => {
            const x = cx(c.n) - (col - 5) / 2, w = col - 5;
            const seld = isSel("chapter", c.n);
            const fill = c.planned ? "transparent" : (c.current ? "var(--crimson-wash)" : "var(--paper-0)");
            const stroke = seld ? "var(--crimson)" : c.current ? "var(--crimson)" : "var(--line-2)";
            return (
              <g key={c.n} onClick={(e) => { e.stopPropagation(); onSelect({ type: "chapter", id: c.n }); }}
                onMouseEnter={() => {
                  const opens = loops.filter(L => L.setup === c.n);
                  const closes = loops.filter(L => L.payoff === c.n && L.state !== "closed");
                  const active = threads.filter(t => t.segs.some(s => c.n >= s[0] && c.n <= s[1]));
                  setHover({ kind: "chapter", id: "c" + c.n, c, opens, closes, active, below: true, xPct: (cx(c.n) / W) * 100, yPct: ((cy0 + chH) / H) * 100 });
                }}
                onMouseLeave={() => setHover(h => (h && h.id === "c" + c.n ? null : h))}
                style={{ cursor: "pointer", transition: "opacity .2s" }} opacity={inAct(c.n) ? 1 : 0.26}>
                <rect x={x} y={cy0} width={w} height={chH} rx="5" fill={fill} stroke={stroke} strokeWidth={seld ? 2 : 1} strokeDasharray={c.planned ? "2 3" : "none"} />
                <text x={cx(c.n)} y={cy0 + 17} fontSize="11.5" fontWeight="700" textAnchor="middle" fill={c.planned ? "var(--ink-4)" : c.current ? "var(--crimson)" : "var(--ink-2)"} fontFamily="var(--font-mono)">{String(c.n).padStart(2, "0")}</text>
                {!c.planned && <rect x={x + 4} y={cy0 + chH - 9} width={(w - 8) * Math.min(1, (c.words || 0) / 6300)} height="4" rx="2" fill={c.current ? "var(--crimson)" : "var(--ink-3)"} opacity={c.current ? 1 : 0.5} />}
                {c.beat && (<g><circle cx={cx(c.n)} cy={cy0 - 7} r="3" fill="var(--gold)" /><text x={cx(c.n)} y={cy0 - 13} fontSize="9.5" textAnchor="middle" fill="var(--gold)" fontWeight="600">{c.beat}</text></g>)}
              </g>
            );
          })}

          {/* 张力 */}
          <polyline points={tgtPts} fill="none" stroke="var(--ink-4)" strokeWidth="1.5" strokeDasharray="3 4" opacity="0.7" />
          <path d={actArea} fill="var(--crimson-wash)" opacity="0.5" />
          <polyline points={actPts.join(" ")} fill="none" stroke="var(--crimson)" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" />
          {written.map(c => {
            const low = c.pace < LF2_TARGET[c.n - 1] - 0.06;
            return (<g key={c.n}><circle cx={cx(c.n)} cy={yT(c.pace)} r={c.current ? 4 : 3} fill="var(--crimson)" stroke="var(--paper-0)" strokeWidth="1.5" />{low && <path d={`M ${cx(c.n) - 4} ${yT(c.pace) + 9} L ${cx(c.n) + 4} ${yT(c.pace) + 9} L ${cx(c.n)} ${yT(c.pace) + 15} Z`} fill="var(--rose)" />}</g>);
          })}
          <text x={cx(C)} y={yT(LF2_TARGET[C - 1]) - 7} fontSize="10" textAnchor="end" fill="var(--ink-4)">理想</text>

          {/* 伏笔债航迹 */}
          <line x1={PADL} x2={W - PADR} y1={yLB} y2={yLB} stroke="var(--line-2)" strokeWidth="1" />
          {lsorted.map((l, i) => {
            const x1 = cx(l.setup);
            const unsched = l.payoff == null;
            const x2 = unsched ? (W - PADR - 4) : cx(l.payoff);
            const overdue = !unsched && l.payoff < now && l.state === "open";
            const tone = overdue ? "rose" : unsched ? "gold" : l.state === "closing" ? "sage" : "slate";
            const clr = LF2_CLR[tone].c;
            const apexY = yLB - (24 + i * 16);
            const ctrlY = 2 * apexY - yLB;
            const midX = (x1 + x2) / 2;
            const seld = isSel("loop", l.id);
            const hov = hover && hover.kind === "loop" && hover.id === l.id;
            const dim = hover && hover.kind === "loop" && hover.id !== l.id;
            const dash = overdue || unsched ? "4 4" : "none";
            return (
              <g key={l.id} onClick={(e) => { e.stopPropagation(); onSelect({ type: "loop", id: l.id }); }}
                onMouseEnter={() => setHover({ kind: "loop", id: l.id, l, overdue, unsched, xPct: (midX / W) * 100, yPct: (apexY / H) * 100 })}
                onMouseLeave={() => setHover(h => (h && h.id === l.id ? null : h))}
                style={{ cursor: "pointer", opacity: dim ? 0.32 : 1, transition: "opacity .2s" }}>
                <path d={`M ${x1} ${yLB} Q ${midX} ${ctrlY} ${x2} ${yLB}`} fill="none" stroke="transparent" strokeWidth="14" />
                <path d={`M ${x1} ${yLB} Q ${midX} ${ctrlY} ${x2} ${yLB}`} fill="none" stroke={clr} strokeWidth={seld || hov ? 2.6 : 1.8} strokeDasharray={dash} opacity={seld || hov ? 1 : 0.85} markerEnd={unsched ? "url(#lf3Arrow)" : undefined} />
                <circle cx={x1} cy={yLB} r={seld || hov ? 5 : 4} fill={clr} stroke="var(--paper-0)" strokeWidth="1.5" />
                {l.pinned && <circle cx={x1} cy={yLB} r="7.5" fill="none" stroke={clr} strokeWidth="1.2" opacity="0.6" />}
                {!unsched && <circle cx={x2} cy={yLB} r={seld || hov ? 5 : 4} fill={l.state === "closing" ? clr : "var(--paper-0)"} stroke={clr} strokeWidth="2" className={overdue ? "lf3-pulse" : ""} />}
                {(() => { const lbl = `${l.setup}${unsched ? "→?" : "→" + l.payoff}${overdue ? " ⚠" : ""}`; const w = lbl.length * 6.6 + 8; return (
                  <g transform={`translate(${midX}, ${apexY - 4})`}><rect x={-w / 2} y={-10} width={w} height={14} rx={7} fill="var(--paper-0)" stroke={clr} strokeWidth={seld || hov ? 1.3 : 0.8} opacity={seld || hov ? 1 : 0.92} /><text textAnchor="middle" y={0.5} fontSize="10" fontWeight="700" fill={clr} fontFamily="var(--font-mono)">{lbl}</text></g>
                ); })()}
              </g>
            );
          })}

          {/* 空降伏笔：有揭示无铺垫，在 reveal 章打一个朝下的危险标记 */}
          {(LF3_ORPHANS || []).map(o => {
            const x = cx(o.revealCh);
            const seld = isSel("orphan", o.id);
            const hov = hover && hover.kind === "orphan" && hover.id === o.id;
            return (
              <g key={o.id} onClick={(e) => { e.stopPropagation(); onSelect({ type: "orphan", id: o.id }); }}
                onMouseEnter={() => setHover({ kind: "orphan", id: o.id, o, xPct: (x / W) * 100, yPct: ((yLB + 6) / H) * 100, below: true })}
                onMouseLeave={() => setHover(h => (h && h.id === o.id ? null : h))} style={{ cursor: "pointer" }}>
                <line x1={x} x2={x} y1={yLB} y2={yLB - 14} stroke="var(--crimson)" strokeWidth={seld || hov ? 2 : 1.4} strokeDasharray="2 2" />
                <g transform={`translate(${x}, ${yLB - 14})`}>
                  <polygon points="0,-9 8,5 -8,5" fill={seld || hov ? "var(--crimson)" : "var(--crimson-wash)"} stroke="var(--crimson)" strokeWidth="1.2" />
                  <text x="0" y="2" fontSize="8" fontWeight="800" textAnchor="middle" fill={seld || hov ? "#fff" : "var(--crimson)"} fontFamily="var(--font-mono)">!</text>
                </g>
              </g>
            );
          })}

          {/* 故事线 */}
          {threads.map((t, i) => {
            const y = tR0 + i * (rowH + rowGap);
            const clr = LF2_CLR[t.color] || LF2_CLR.ink;
            const last = lf2ThreadLast(t);
            const stalled = lf2ThreadStalled(t, now);
            const seld = isSel("thread", t.id);
            return (
              <g key={t.id} onClick={(e) => { e.stopPropagation(); onSelect({ type: "thread", id: t.id }); }}
                onMouseEnter={() => setHover({ kind: "thread", id: "t" + t.id, t, last, stalled, xPct: (((PADL + bnd(t.segs[t.segs.length - 1][1])) / 2) / W) * 100, yPct: (y / H) * 100 })}
                onMouseLeave={() => setHover(h => (h && h.id === "t" + t.id ? null : h))} style={{ cursor: "pointer" }}>
                <text x={PADL - 10} y={y + rowH - 2} fontSize="10.5" textAnchor="end" fill={seld ? clr.c : "var(--ink-3)"} fontWeight={seld ? 700 : 500}>{t.short}</text>
                <rect x={PADL} y={y} width={plotW} height={rowH} rx="3" fill="var(--paper-0)" opacity="0.5" />
                {t.segs.map((s, j) => { const x = bnd(s[0] - 1) + 2.5, w = (s[1] - s[0] + 1) * col - 5; return <rect key={j} x={x} y={y} width={w} height={rowH} rx="3.5" fill={clr.w} stroke={clr.c} strokeWidth={seld ? 1.4 : 1} />; })}
                {stalled && (<g><rect x={bnd(last)} y={y} width={nowX - bnd(last)} height={rowH} rx="3" fill="url(#lf3Stall)" opacity="0.85" /><text x={(bnd(last) + nowX) / 2} y={y + rowH - 2} fontSize="9" textAnchor="middle" fill="var(--rose)" fontWeight="700">停滞</text></g>)}
              </g>
            );
          })}

          {/* AI 视野起点 */}
          {horizon > 1 && (<g>
            <line x1={horizonX} x2={horizonX} y1={26} y2={H - 8} stroke="var(--slate)" strokeWidth="1.1" strokeDasharray="1 4" opacity="0.6" />
            <g transform={`translate(${horizonX}, 20)`}><rect x="-2" y="-13" width="76" height="15" rx="7.5" fill="var(--slate-wash)" /><text x="36" y="-2.5" fontSize="9" fontWeight="700" textAnchor="middle" fill="var(--slate)">AI 视野起点</text></g>
          </g>)}

          {/* 现在 · 交接线 */}
          <line x1={nowX} x2={nowX} y1={20} y2={H - 8} stroke="var(--crimson)" strokeWidth="1.5" strokeDasharray="2 3" opacity="0.9" />
          <g transform={`translate(${nowX}, 11)`}><rect x="-40" y="-11" width="80" height="18" rx="9" fill="var(--crimson)" /><path d="M -4 7 L 4 7 L 0 12 Z" fill="var(--crimson)" /><text x="0" y="2" fontSize="10" fontWeight="700" textAnchor="middle" fill="#fff">现在 · 第 {now} 章</text></g>
        </svg>

        {hover && (() => {
          const posCls = `${hover.xPct > 62 ? "is-left" : hover.xPct < 18 ? "is-right" : ""} ${hover.below ? "is-below" : ""}`;
          const wrap = (inner) => (<div className={`lf3-pop ${posCls}`} style={{ left: `${hover.xPct}%`, top: `${hover.yPct}%` }}>{inner}</div>);
          if (hover.kind === "chapter") {
            const c = hover.c;
            const status = c.planned ? "待写" : c.current ? "进行中" : "已落稿";
            const low = !c.planned && c.pace < LF2_TARGET[c.n - 1] - 0.06;
            return wrap(<>
              <div className="lf3-pop-head"><span className="lf3-pop-pri">{String(c.n).padStart(2, "0")}</span><span className="lf3-pop-title">{c.title}</span>{c.beat && <span className="lf3-pop-pri" style={{ background: "var(--gold-wash)", color: "var(--gold)" }}>{c.beat}</span>}</div>
              <div className="lf3-pop-row">{c.planned ? <span>计划张力 <b>{LF2_TARGET[c.n - 1].toFixed(2)}</b></span> : <><span><b>{c.words.toLocaleString()}</b> 字</span><span>张力 <b>{c.pace.toFixed(2)}</b></span><span>目标 {LF2_TARGET[c.n - 1].toFixed(2)}</span></>}<span style={{ marginLeft: "auto", color: c.current ? "var(--crimson)" : "var(--ink-3)" }}>{status}</span></div>
              <div className="lf3-pop-tags">
                {hover.active.map(t => <span key={t.id} className="lf3-pop-tag">{t.short}</span>)}
                {hover.opens.map(L => <span key={L.id} className="lf3-pop-tag tone-gold">埋·{L.title.slice(0, 6)}</span>)}
                {hover.closes.map(L => <span key={L.id} className="lf3-pop-tag tone-sage">收·{L.title.slice(0, 6)}</span>)}
                {hover.active.length + hover.opens.length + hover.closes.length === 0 && <span className="lf3-pop-tag" style={{ background: "var(--paper-2)", color: "var(--ink-4)" }}>无活跃线索</span>}
              </div>
              <div className="lf3-pop-hint">{low ? "张力低于目标 · " : ""}点击 → 左下查看本章全部牵涉</div>
            </>);
          }
          if (hover.kind === "orphan") {
            const o = hover.o;
            return wrap(<>
              <div className="lf3-pop-head"><span className="lf3-pop-pri" style={{ background: "var(--crimson-wash)", color: "var(--crimson)" }}>空降</span><span className="lf3-pop-title">{o.reveal}</span></div>
              <p className="lf3-pop-note">{o.why}</p>
              <div className="lf3-pop-hint">第 {o.revealCh} 章揭示 · 全书无铺垫 · 点击去补</div>
            </>);
          }
          if (hover.kind === "thread") {
            const t = hover.t;
            const segTxt = t.segs.map(s => s[0] === s[1] ? s[0] : `${s[0]}–${s[1]}`).join("、");
            return wrap(<>
              <div className="lf3-pop-head"><span className="lf3-pop-pri" style={{ background: "color-mix(in srgb, " + (LF2_CLR[t.color] || LF2_CLR.ink).c + " 16%, var(--paper-0))", color: (LF2_CLR[t.color] || LF2_CLR.ink).c }}>线</span><span className="lf3-pop-title">{t.name}</span></div>
              <div className="lf3-pop-row"><span>在场 <b>{segTxt}</b> 章</span><span>最后 <b>第 {hover.last} 章</b></span><span style={{ marginLeft: "auto", color: hover.stalled ? "var(--rose)" : "var(--sage)" }}>{hover.stalled ? `停滞 ${now - hover.last} 章` : "活跃"}</span></div>
              {hover.stalled && <p className="lf3-pop-note">已 {now - hover.last} 章未触及，读者可能正在淡忘——建议下一章给它一个推进动作。</p>}
              <div className="lf3-pop-hint">点击 → 左下详情 / 装入交接</div>
            </>);
          }
          const l = hover.l;
          const pay = hover.unsched ? "未排定回收章" : `第 ${l.payoff} 章回收`;
          const status = hover.overdue ? "已逾期" : hover.unsched ? "待排期" : l.state === "closing" ? "回收中" : "未回收";
          return wrap(<>
            <div className="lf3-pop-head"><span className="lf3-pop-pri">{PRI[l.pri]}</span><span className="lf3-pop-title">{l.title}</span>{l.pinned && <span className="lf3-pop-pri" style={{ background: "var(--crimson-wash)", color: "var(--crimson)" }}>钉</span>}</div>
            <div className="lf3-pop-row"><span><b>第 {l.setup} 章</b> 埋设 → <b>{pay}</b></span><span style={{ marginLeft: "auto", color: hover.overdue ? "var(--rose)" : "var(--ink-3)" }}>{status}</span></div>
            {l.note && <p className="lf3-pop-note">{l.note}</p>}
            <div className="lf3-pop-hint">点击 → 左下详情 / 钉入交接</div>
          </>);
        })()}

        {scanning && <div className="lf3-scan-sweep" aria-hidden="true"><span className="lf3-scan-label"><I.Radar size={13} className="lf3-spin" /> 正在比对全书设定…</span></div>}
      </div>

      <div className="lf3-atlas-legend">
        <span><i className="lf3-lg-dot" style={{ background: "var(--crimson)" }} />已写张力</span>
        <span><i className="lf3-lg-dash" />理想张力</span>
        <span><i className="lf3-lg-arc" style={{ borderColor: "var(--slate)" }} />伏笔航迹</span>
        <span><i className="lf3-lg-arc lf3-lg-arc--od" style={{ borderColor: "var(--rose)" }} />逾期盘旋</span>
        <span><i className="lf3-lg-orphan"><I.AlertTriangle size={12} /></i>空降（无铺垫）</span>
        <span><i className="lf3-lg-seam" />现在 · 交接线</span>
      </div>
    </div>
  );
}

Object.assign(window, { Lf3Atlas });
