import React from "react";
import ReactDOM from "react-dom";
import { I } from "./icons.jsx";
import { LF2_ACTS, LF2_BOOK, LF2_CANON, LF2_CHAPTERS, LF2_LOOPS, LF2_NEXT, LF2_TARGET, LF2_THREADS, lf2Derive, lf2SyncFromCatalog } from "./lf2-data.jsx";
import { LF3_AUDIT, LF3_CAUSAL, LF3_ORPHANS, lf3Brief, lf3Issues } from "./lf3-data.jsx";
import { Lf3Atlas } from "./lf3-atlas.jsx";
import { Lf3Audit, Lf3Memory } from "./lf3-console.jsx";
import { Lf3Generating, Lf3Preview } from "./lf3-app.jsx";
import { Lf4Brief } from "./lf4-console.jsx";
import { Lf5Guard } from "./lf5-guard.jsx";
import { lf7ApplyCanon, Lf7Bridge, lf7Dispatch9, lf7ArchiveCh9 } from "./lf7-bridge.jsx";
import { WsCatalog, WsDemoTag } from "./ws-catalog.jsx";
import { WsWorks } from "./ws-works.jsx";

/* global React, ReactDOM, I, LF2_BOOK, LF2_NEXT, LF2_LOOPS, LF2_CANON, LF2_TARGET, LF2_CHAPTERS, LF2_ACTS, LF2_THREADS, LF3_AUDIT, LF3_ORPHANS, LF3_CAUSAL,
   lf2Derive, lf3Issues, lf3Brief, Lf3Atlas, Lf5Guard, Lf3Memory, Lf4Brief, Lf3Audit, Lf3Generating, Lf3Preview */
const { useState: useApp6, useMemo: useMemo6, useEffect: useEffect6 } = React;

const LF6_HEART = ["规划", "交接", "生成", "审计", "归档"];
const LF6_TABMAP = { drift: "canon", overdue: "ledger", stall: "threads", fade: "board" };
const LF6_ACTIONABLE = ["conflict", "overdue", "stall", "orphan", "causal", "dip"];

/* 尊重「减少动效」偏好：逐条弹窗直接出终态，不做逐条揭示 */
const LF6_REDUCED = () => typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ============================================================
   微缩天际线 — 全书航图的环境化形态（一眼定位整本书）
   ============================================================ */
function Lf6Skyline({ open, onToggle, d, atlasProps }) {
  const chapters = LF2_CHAPTERS, target = LF2_TARGET;
  const now = d.now, horizon = d.horizon, C = chapters.length;
  const written = chapters.filter(c => !c.planned);

  const chips = [
    { key: "drift", label: "漂移", n: d.driftConflicts.length, tone: "rose" },
    { key: "overdue", label: "逾期", n: d.overdue.length, tone: "rose" },
    { key: "orphan", label: "空降", n: (LF3_ORPHANS || []).length, tone: "crimson" },
    { key: "fade", label: "淡出", n: d.fading.length, tone: "gold" },
  ].filter(c => c.n > 0);

  if (open) {
    return (
      <div className="lf6-sky is-open">
        <div className="lf6-sky-collapse-row">
          <button className="lf6-sky-expand" onClick={onToggle}><I.ChevronDown size={14} /> 收起为天际线</button>
        </div>
        <Lf3Atlas {...atlasProps} />
      </div>
    );
  }

  // —— 微缩 SVG ——
  const W = 1000, H = 56, PADL = 8, PADR = 8;
  const plotW = W - PADL - PADR, col = plotW / C;
  const cx = (n) => PADL + (n - 0.5) * col;
  const bnd = (n) => PADL + n * col;
  const tTop = 7, tBot = 31, yT = (v) => tBot - Math.max(0, Math.min(1, v)) * (tBot - tTop);
  const chY = 39, chH = 13;
  const nowX = bnd(now), horizonX = bnd(horizon - 1);
  const tgtPts = chapters.map(c => `${cx(c.n)},${yT(target[c.n - 1])}`).join(" ");
  const actPts = written.map(c => `${cx(c.n)},${yT(c.pace)}`).join(" ");

  return (
    <div className="lf6-sky">
      <div className="lf6-sky-bar">
        <div className="lf6-sky-id">
          <span className="lf3-zone-tag"><I.BookOpen size={13} /> 纸上的书</span>
          <div>
            <h2>全书航图</h2>
            <p>{written.length}/{LF2_BOOK.total} 章 · 现在第 {now} 章</p>
          </div>
        </div>

        <div className="lf6-sky-strip">
          <svg viewBox={`0 0 ${W} ${H}`} className="lf6-sky-svg" preserveAspectRatio="none" role="img" aria-label="全书天际线">
            {/* AI 视野前 / 现在后 的明暗 */}
            <rect x={PADL} y="0" width={Math.max(0, horizonX - PADL)} height={H} fill="var(--slate)" opacity="0.05" />
            <rect x={nowX} y="0" width={W - PADR - nowX} height={H} fill="var(--ink-4)" opacity="0.06" />
            {/* 理想 / 实际张力 */}
            <polyline points={tgtPts} fill="none" stroke="var(--ink-4)" strokeWidth="1.2" strokeDasharray="3 3" opacity="0.6" />
            <polyline points={actPts} fill="none" stroke="var(--crimson)" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
            {written.map(c => <circle key={c.n} cx={cx(c.n)} cy={yT(c.pace)} r={c.current ? 2.6 : 1.8} fill="var(--crimson)" />)}
            {/* 章节刻度 */}
            {chapters.map(c => {
              const x = cx(c.n) - (col - 3) / 2, w = col - 3;
              return (
                <g key={c.n}>
                  <rect x={x} y={chY} width={w} height={chH} rx="2.5"
                    fill={c.planned ? "transparent" : c.current ? "var(--crimson-wash)" : "var(--paper-0)"}
                    stroke={c.current ? "var(--crimson)" : "var(--line-2)"} strokeWidth={c.current ? 1.4 : 0.8}
                    strokeDasharray={c.planned ? "2 2" : "none"} />
                  {!c.planned && <rect x={x + 1.5} y={chY + chH - 4} width={(w - 3) * Math.min(1, (c.words || 0) / 6300)} height="2.5" rx="1.2" fill={c.current ? "var(--crimson)" : "var(--ink-4)"} />}
                  {c.beat && <circle cx={cx(c.n)} cy={chY - 3} r="1.7" fill="var(--gold)" />}
                </g>
              );
            })}
            {/* 空降标记 */}
            {(LF3_ORPHANS || []).map(o => (
              <polygon key={o.id} points={`${cx(o.revealCh)},${chY - 6} ${cx(o.revealCh) + 3.2},${chY - 1} ${cx(o.revealCh) - 3.2},${chY - 1}`} fill="var(--crimson)" />
            ))}
            {/* AI 视野起点 */}
            {horizon > 1 && <line x1={horizonX} x2={horizonX} y1="2" y2={H - 2} stroke="var(--slate)" strokeWidth="1" strokeDasharray="1 3" opacity="0.6" />}
            {/* 现在·交接线 */}
            <line x1={nowX} x2={nowX} y1="0" y2={H} stroke="var(--crimson)" strokeWidth="1.5" strokeDasharray="2 2" />
          </svg>
        </div>

        <div className="lf6-sky-right">
          <div className="lf6-sky-chips">
            {chips.length === 0
              ? <span className="lf6-sky-chip tone-sage" style={{ background: "var(--sage-wash)", color: "var(--sage)" }}><I.CheckCircle size={11} /> 全书健康</span>
              : chips.map(c => <span key={c.key} className={`lf6-sky-chip tone-${c.tone}`}>{c.label}<b>{c.n}</b></span>)}
          </div>
          <button className="lf6-sky-expand" onClick={onToggle}>展开全图 <I.ChevronDown size={14} /></button>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   AI 工作记忆 · 紧凑可展开（默认收起，把版面让给随身契约）
   ============================================================ */
function Lf6Mem({ d, onRepin }) {
  const [open, setOpen] = useApp6(false);
  const fading = d.fading.length;
  const horizon = d.horizon, now = d.now;
  return (
    <div className={`lf6-mem ${open ? "is-open" : ""}`}>
      <button className="lf6-mem-head" onClick={() => setOpen(o => !o)}>
        <span className="lf6-mem-ic"><I.Cpu size={14} /></span>
        <span className="lf6-mem-mini" aria-hidden="true">
          {LF2_CHAPTERS.map(c => {
            const within = c.n >= horizon && c.n <= now, future = c.n > now;
            const cls = future ? "is-future" : within ? "is-in" : "is-fade";
            return <i key={c.n} className={`lf6-mm-cell ${cls}`} />;
          })}
        </span>
        <span className="lf6-mem-sum"><b>AI 工作记忆</b>{fading > 0 ? <em> · {fading} 项淡出</em> : <span className="is-stable"> · 记忆稳固</span>}</span>
        <I.ChevronDown size={14} className={`lf6-mem-chev ${open ? "is-open" : ""}`} />
      </button>
      {!open && fading > 0 && <button className="lf6-mem-repin-mini" onClick={(e) => { e.stopPropagation(); onRepin(); }}><I.Lock size={12} /> 重新钉入淡出的 {fading} 项 → 强约束</button>}
      {open && <div className="lf6-mem-detail"><Lf3Memory d={d} now={now} onRepin={onRepin} /></div>}
    </div>
  );
}

/* ============================================================
   生成 · 把随身记忆逐条钉进 AI 的脑子（v6 专属，可核对）
   ============================================================ */
function Lf6Generating({ brief }) {
  const items = brief.enforce;
  const [n, setN] = useApp6(() => LF6_REDUCED() ? items.length : 0);
  useEffect6(() => {
    if (LF6_REDUCED() || n >= items.length) return;
    const t = setTimeout(() => setN(x => x + 1), Math.max(130, 1400 / Math.max(1, items.length)));
    return () => clearTimeout(t);
  }, [n, items.length]);
  const done = n >= items.length;
  return (
    <div className="lf3-gen-scrim">
      <div className="lf3-gen-card lf6-gen-card">
        <div className="lf3-gen-orb"><I.Cpu size={26} /></div>
        <div className="lf6-gen-title">正在把 <b>{items.length}</b> 条随身记忆封进交接契约<br />下发第 {brief.next} 章 → AI 起草台…</div>
        <div className="lf6-gen-list">
          {items.map((it, i) => (
            <div key={it.id} className={`lf6-gen-li tone-${it.tone} ${i < n ? "is-in" : ""}`}>
              <span className="lf6-gen-tick">{i < n ? <I.Check size={11} /> : <span className="lf6-gen-load" />}</span>
              <span className="lf6-gen-li-text">{it.text}</span>
              <span className="lf6-gen-li-tag">{it.label}</span>
            </div>
          ))}
        </div>
        <div className="lf6-gen-foot">{done
          ? <><I.Sparkles size={12} /> 契约已封装 · 第 {brief.next} 章正拆场入列起草台…</>
          : <><span className="lf6-gen-load" /> 正在封装第 {n}/{items.length} 条 · 存档库另按需召回</>}</div>
      </div>
    </div>
  );
}

/* ============================================================
   审计 · 把草稿逐条比对交接契约（与生成钉入首尾呼应）
   ============================================================ */
function Lf6Auditing({ audit, onClose }) {
  const items = [
    ...audit.honored.map(h => ({ id: h.id, text: h.text, label: h.label, verdict: "ok" })),
    ...audit.drifted.map(dr => ({ id: dr.id, text: dr.what, label: dr.label, verdict: "warn" })),
  ];
  const [n, setN] = useApp6(() => LF6_REDUCED() ? items.length : 0);
  useEffect6(() => {
    if (LF6_REDUCED() || n >= items.length) return;
    const t = setTimeout(() => setN(x => x + 1), Math.max(150, 1500 / Math.max(1, items.length)));
    return () => clearTimeout(t);
  }, [n, items.length]);
  const done = n >= items.length;
  const okN = audit.honored.length, warnN = audit.drifted.length, newN = audit.introduced.length;
  return (
    <div className="lf3-gen-scrim" onClick={done ? onClose : undefined}>
      <div className="lf3-gen-card lf6-gen-card lf6-aud-card" onClick={(e) => e.stopPropagation()}>
        <div className="lf3-gen-orb lf6-aud-orb"><I.ShieldCheck size={26} /></div>
        <div className="lf6-gen-title">控制塔正把第 {audit.ch} 章草稿<br />逐条比对交接的 <b>{items.length}</b> 条契约…</div>
        <div className="lf6-gen-list">
          {items.map((it, i) => (
            <div key={it.id} className={`lf6-gen-li lf6-aud-li v-${it.verdict} ${i < n ? "is-in" : ""}`}>
              <span className="lf6-gen-tick">{i < n ? (it.verdict === "ok" ? <I.Check size={11} /> : <I.AlertTriangle size={10} />) : <span className="lf6-gen-load" />}</span>
              <span className="lf6-gen-li-text">{it.text}</span>
              <span className="lf6-gen-li-tag">{i < n ? (it.verdict === "ok" ? "守住" : "偏离") : it.label}</span>
            </div>
          ))}
        </div>
        {done ? (
          <div className="lf6-aud-foot">
            <div className="lf6-aud-tally">
              <span className="is-ok"><I.Check size={11} /> {okN} 守住</span>
              <span className="is-warn"><I.AlertTriangle size={11} /> {warnN} 偏离需裁决</span>
              <span className="is-new"><I.Plus size={11} /> {newN} 新引入</span>
            </div>
            <button className="lf6-aud-btn" onClick={onClose}>查看逐条审计 · 裁决偏离 <I.ArrowRight size={13} /></button>
          </div>
        ) : <div className="lf6-gen-foot"><span className="lf6-gen-load" /> 正在比对第 {n}/{items.length} 条 · 逐句回湯正文证据</div>}
      </div>
    </div>
  );
}

/* ============================================================
   归档 · 逐条收口并入全书记忆（闭环四幕第四幕）
   ============================================================ */
function Lf6Archiving({ audit, onDone }) {
  const items = [
    { id: "recover", text: "楼梯间的第二组脚印", sub: "逾期悬念 · 本章已回收", tag: "回收结清", tone: "sage", icon: "Check" },
    ...audit.introduced.map(nn => ({
      id: nn.id, text: nn.text, sub: nn.kind + " · 本章新引入",
      tag: nn.tone === "rose" ? "并入设定 · 下一轮复核" : (nn.tone === "gold" ? "排期回收" : "锁定为锚点"),
      tone: nn.tone, icon: nn.tone === "rose" ? "AlertTriangle" : (nn.tone === "gold" ? "Clock" : "Lock"),
    })),
  ];
  const [n, setN] = useApp6(() => LF6_REDUCED() ? items.length : 0);
  useEffect6(() => {
    if (LF6_REDUCED() || n >= items.length) return;
    const t = setTimeout(() => setN(x => x + 1), Math.max(180, 1400 / Math.max(1, items.length)));
    return () => clearTimeout(t);
  }, [n, items.length]);
  const done = n >= items.length;
  return (
    <div className="lf3-gen-scrim" onClick={done ? onDone : undefined}>
      <div className="lf3-gen-card lf6-gen-card lf6-arc-card" onClick={(e) => e.stopPropagation()}>
        <div className="lf3-gen-orb lf6-arc-orb"><I.Save size={24} /></div>
        <div className="lf6-gen-title">第 {audit.ch} 章归档收口<br />逐条并入全书记忆、复位下一轮…</div>
        <div className="lf6-gen-list">
          {items.map((it, i) => (
            <div key={it.id} className={`lf6-gen-li lf6-arc-li tone-${it.tone} ${i < n ? "is-in" : ""}`}>
              <span className="lf6-gen-tick">{i < n ? React.createElement(I[it.icon] || I.Check, { size: 11 }) : <span className="lf6-gen-load" />}</span>
              <span className="lf6-gen-li-text">{it.text}<small>{it.sub}</small></span>
              <span className="lf6-gen-li-tag">{i < n ? it.tag : "…"}</span>
            </div>
          ))}
        </div>
        {done ? (
          <div className="lf6-aud-foot">
            <div className="lf6-arc-sum"><I.CheckCircle size={13} /> 全书记忆已更新 · 第 {audit.ch + 1} 章交接已就绪</div>
            <button className="lf6-arc-btn" onClick={onDone}>完成归档 · 进入第 {audit.ch + 1} 章交接 <I.ArrowRight size={13} /></button>
          </div>
        ) : <div className="lf6-gen-foot"><span className="lf6-gen-load" /> 正在收口第 {n}/{items.length} 项…</div>}
      </div>
    </div>
  );
}

/* ============================================================
   长篇控制塔 v6 · Tower
   ============================================================ */
function Lf6Tower({ go, standalone }) {
  const [loops, setLoops] = useApp6(() => JSON.parse(JSON.stringify(LF2_LOOPS)));
  const [canon, setCanon] = useApp6(() => {
    const seed = JSON.parse(JSON.stringify(LF2_CANON));
    return lf7ApplyCanon ? lf7ApplyCanon(seed) : seed;  // 应用已裁决（收件箱 / 上一轮归档）
  });
  const [sel, setSel] = useApp6(null);
  const [tab, setTab] = useApp6("board");
  const [doneIds, setDoneIds] = useApp6(() => new Set());
  const [modes, setModes] = useApp6(() => ({}));
  const [pinnedFacts, setPinnedFacts] = useApp6(() => new Set());
  const [consoleTab, setConsoleTab] = useApp6("brief");
  const [hasDraft, setHasDraft] = useApp6(false);
  const [gen, setGen] = useApp6("idle");
  const [fixDone, setFixDone] = useApp6(() => new Set());
  const [newDone, setNewDone] = useApp6(() => new Set());
  const [scan, setScan] = useApp6("idle");
  const [preview, setPreview] = useApp6(false);
  const [toast, setToast] = useApp6(null);
  const [theme, setTheme] = useApp6("day");
  const [loadPing, setLoadPing] = useApp6(0);
  const [auditPlay, setAuditPlay] = useApp6(false);
  const [archivePlay, setArchivePlay] = useApp6(false);
  const [skyOpen, setSkyOpen] = useApp6(() => { try { return localStorage.getItem("lf6-sky") === "1"; } catch (e) { return false; } });
  const [arm, setArm] = useApp6(null); // 闸门二次确认："gen" 带病下发 / "arc" 带病归档
  const [, setCatPing] = useApp6(0);   // 订阅目录：起草台逐场成稿时塔上进度实时刷新

  useEffect6(() => {
    const bump = () => setCatPing(p => p + 1);
    const un = WsCatalog ? WsCatalog.subscribe(bump) : null;
    window.addEventListener("lf:bridge-changed", bump);
    return () => { if (un) un(); window.removeEventListener("lf:bridge-changed", bump); };
  }, []);

  /* FE-ALIGN 缺口A：loops/canon 原先只在 useState 初始化器里对 LF2_* 做一次性深拷贝，
     之后从不消费后端同步 —— 懒一步打开 / 切换作品后塔台读的是旧的静态种子。
     这里挂载即主动水合锚点(anchors)/审计(audit)，并订阅 lf2:tower-synced 把 loops/canon
     重置为最新全局，订阅 lf3:audit-synced 触发重渲染（空降/因果/线索经 ESM live binding 刷新）。 */
  useEffect6(() => {
    try { window.lf2SyncFromTower && window.lf2SyncFromTower(); } catch (e) {}
    try { window.lf3SyncFromAudit && window.lf3SyncFromAudit(); } catch (e) {}
    const reseat = () => {
      setLoops(JSON.parse(JSON.stringify(LF2_LOOPS)));
      const seed = JSON.parse(JSON.stringify(LF2_CANON));
      setCanon(lf7ApplyCanon ? lf7ApplyCanon(seed) : seed);
    };
    const bumpAudit = () => setCatPing(p => p + 1);
    window.addEventListener("lf2:tower-synced", reseat);
    window.addEventListener("lf3:audit-synced", bumpAudit);
    return () => {
      window.removeEventListener("lf2:tower-synced", reseat);
      window.removeEventListener("lf3:audit-synced", bumpAudit);
    };
  }, []);

  /* 收件箱侧裁决 → 塔内同步锁定（同一拍板对象，裁决一处两处消失） */
  useEffect6(() => {
    const sync = () => {
      const ruled = Lf7Bridge ? Lf7Bridge.ruled() : {};
      setCanon(cs => {
        let changed = false;
        const next = cs.map(c => (c.status === "conflict" && ruled[c.id]) ? (changed = true, { ...c, status: "locked", pinned: true, drift: false, fresh: false }) : c);
        return changed ? next : cs;
      });
    };
    window.addEventListener("lf:bridge-changed", sync);
    return () => window.removeEventListener("lf:bridge-changed", sync);
  }, []);

  useEffect6(() => { if (standalone) document.documentElement.setAttribute("data-theme", theme === "night" ? "dark" : "light"); }, [theme, standalone]);
  const toggleSky = () => setSkyOpen(o => { const v = !o; try { localStorage.setItem("lf6-sky", v ? "1" : "0"); } catch (e) {} return v; });

  const d = useMemo6(() => lf2Derive(loops, canon), [loops, canon]);
  const issues = useMemo6(() => lf3Issues(d, loops, canon), [d, loops, canon]);
  const brief = useMemo6(() => lf3Brief(loops, canon, modes), [loops, canon, modes]);

  const flash = (msg) => { setToast(msg); clearTimeout(flash._t); flash._t = setTimeout(() => setToast(null), 3400); };

  const TAB_OF = { loop: "ledger", thread: "threads", arc: "arcs", canon: "canon", clue: "clues", orphan: "board", causal: "board", risk: "board" };
  const select = (ref) => { setSel(ref); if (ref && TAB_OF[ref.type]) setTab(TAB_OF[ref.type]); };

  /* FE-ALIGN F4 授权接缝：塔内操作经 lf2LoopOp/lf2CanonOp 写回后端锚点库 */
  const pinLoop = (id) => { setLoops(ls => ls.map(l => l.id === id ? { ...l, pinned: !l.pinned } : l)); try { window.lf2LoopOp && window.lf2LoopOp("pin", id); } catch (e) {} };
  const ensurePinLoop = (id) => { setLoops(ls => ls.map(l => l.id === id ? { ...l, pinned: true } : l)); try { window.lf2LoopOp && window.lf2LoopOp("ensurePin", id); } catch (e) {} };
  const schedule = (id, ch) => { setLoops(ls => ls.map(l => l.id === id ? { ...l, payoff: ch } : l)); try { window.lf2LoopOp && window.lf2LoopOp("schedule", id, ch); } catch (e) {} };
  const resolveLoop = (id) => { setLoops(ls => ls.map(l => l.id === id ? { ...l, state: "closed", pinned: false } : l)); setSel(null); flash("已标记回收，悬念债结清"); try { window.lf2LoopOp && window.lf2LoopOp("resolve", id); } catch (e) {} };
  const resolveCanon = (id) => {
    setCanon(cs => cs.map(c => c.id === id ? { ...c, status: "locked", pinned: true } : c));
    try { if (Lf7Bridge) Lf7Bridge.ruleCanon(id); } catch (e) {}  // 同步消掉收件箱里的同一条
    try { window.lf2CanonOp && window.lf2CanonOp("lock", id); } catch (e) {}
  };
  const pinCanon = (id) => { setCanon(cs => cs.map(c => c.id === id ? { ...c, pinned: !c.pinned } : c)); try { window.lf2CanonOp && window.lf2CanonOp("pin", id); } catch (e) {} };

  const markLoaded = (id) => { setDoneIds(s => new Set(s).add(id)); setLoadPing(p => p + 1); };

  const act = (it) => {
    if (it.kind === "conflict") {
      markLoaded(it.id); resolveCanon(it.ref.id); select(it.ref);
      flash(`已统一并锁定「${(canon.find(c => c.id === it.ref.id) || {}).subject}」→ 装入第 ${LF2_NEXT} 章强约束`);
    } else if (it.kind === "overdue") {
      markLoaded(it.id); ensurePinLoop(it.ref.id);
      flash(`逾期悬念已钉入第 ${LF2_NEXT} 章强约束，将提醒 AI 回收`);
    } else if (it.kind === "stall") {
      markLoaded(it.id); flash(`停滞线索已装入交接，AI 将在第 ${LF2_NEXT} 章推进它`);
    } else if (it.kind === "orphan") {
      markLoaded(it.id);
      const o = (LF3_ORPHANS || []).find(x => x.id === it.ref.id);
      if (o && Lf7Bridge) Lf7Bridge.onceTask("task-orph-" + o.id, {
        kind: "qc", priority: 2,
        title: `补铺垫：${o.reveal}`,
        where: `第 1–${o.revealCh - 1} 章 · 回写前文`, source: "长篇控制塔",
        detail: `${o.why} 修复建议：${o.fix}`,
        actions: [
          { label: "去章节编排定位", intent: "primary", op: "nav", to: "author" },
          { label: "回写作台修改", intent: "ghost", op: "nav", to: "writer" },
          { label: "知道了", intent: "quiet", op: "resolve" },
        ],
      });
      flash("已列入下一轮交接，并投进待办收件箱：在揭示章之前补铺垫");
    } else if (it.kind === "causal") {
      markLoaded(it.id);
      const k = (typeof LF3_CAUSAL !== "undefined" ? LF3_CAUSAL : []).find(x => x.id === it.ref.id);
      if (k && Lf7Bridge) Lf7Bridge.onceTask("task-caus-" + k.id, {
        kind: "qc", priority: 2,
        title: `补前因：${k.effect}`,
        where: `第 ${k.effectCh} 章之前 · 承重因果`, source: "长篇控制塔",
        detail: `${k.why} 修复建议：${k.fix}`,
        actions: [
          { label: "去章节编排定位", intent: "primary", op: "nav", to: "author" },
          { label: "回写作台修改", intent: "ghost", op: "nav", to: "writer" },
          { label: "知道了", intent: "quiet", op: "resolve" },
        ],
      });
      flash("断链已记入交接，并投进待办收件箱：在前序章节补上承重因");
    } else if (it.kind === "fair") {
      select(it.ref); setTab("clues"); flash("公平性问题已定位——在揭晓前补可推理线索");
    } else if (it.kind === "continuity") {
      select(it.ref);
    } else if (it.kind === "dip") {
      markLoaded(it.id); flash(`已设为第 ${LF2_NEXT} 章张力基准`);
    } else if (it.kind === "arc") {
      select(it.ref); setTab("arcs");
    }
  };

  const toggleMode = (id) => setModes(m => ({ ...m, [id]: (m[id] === "retrieve" ? "enforce" : "retrieve") }));
  const promoteFact = (id) => { setPinnedFacts(s => new Set(s).add(id)); flash("已提升为强约束 · 将占用记忆预算、随每次生成在场"); };

  const repin = () => {
    setLoops(ls => ls.map(l => d.fading.some(f => f.kind === "loop" && f.id === l.id) ? { ...l, pinned: true } : l));
    setCanon(cs => cs.map(c => d.fading.some(f => f.kind === "canon" && f.id === c.id) ? { ...c, pinned: true } : c));
    flash(`已把 ${d.fading.length} 项淡出的关键内容重新钉为强约束`);
  };

  const generate = () => {
    if (gen !== "idle") return;
    if (archived9) { flash("第 9 章已审计归档进目录——本轮闭环完成；下一章交接的演示数据从这里重新开始"); return; }
    if (handoff9) { flash("第 9 章已在起草台执行中——去起草台逐场起草，或等全部成稿后回塔审计"); return; }
    /* 闸门：契约未就绪时不默认放行，需显式二次确认「带病下发」 */
    if (!contractReady && arm !== "gen") {
      setArm("gen");
      flash(`契约还有 ${contractTotal - loadedN} 项未拍板——建议先清空左侧失控项；再点一次仍可带病下发起草台`);
      return;
    }
    setArm(null);
    setGen("generating");
    /* 塔台化：塔不再直接生成正文 —— 把契约封装、第 9 章拆成 3 场入列 AI 起草台（唯一执行器） */
    setTimeout(() => {
      let res = null;
      try { res = lf7Dispatch9 ? lf7Dispatch9() : null; } catch (e) {}
      setGen("idle");
      flash(res
        ? `第 ${LF2_NEXT} 章已按契约拆成 ${res.sids.length} 场、入列 AI 起草台 —— ${brief.enforce.length} 条强约束随每场预检在场`
        : `交接契约已封装 · 第 ${LF2_NEXT} 章待起草台接手`);
    }, 1900);
  };

  /* FE-ALIGN H2 授权接缝：真实审计回执（确定性扫描）——本章有正文时替换静态演示 */
  const [realAud, setRealAud] = useApp6(null);
  useEffect6(() => {
    let on = true;
    const pull = () => { try { if (Lf7Bridge && Lf7Bridge.auditReceipt) Lf7Bridge.auditReceipt(LF2_NEXT).then(r => { if (on) setRealAud(r); }).catch(() => {}); } catch (e) {} };
    pull();
    window.addEventListener("lf:bridge-changed", pull);
    return () => { on = false; window.removeEventListener("lf:bridge-changed", pull); };
  }, []);

  /* 章级审计：起草台交齐全部场次后，由你在塔上启动（先刷新真实回执，再跑 D13 违约裁定） */
  const beginAudit = () => {
    try {
      if (Lf7Bridge && Lf7Bridge.auditReceipt) {
        Lf7Bridge.auditReceipt(LF2_NEXT).then(r => {
          setRealAud(r);
          // FE-ALIGN P2(D13)：本章有真实回执时，跑后端违约级裁定（LLM 关则诚实降级）
          if (r && Lf7Bridge.adjudicateDraft) {
            Lf7Bridge.adjudicateDraft(LF2_NEXT).then(adj => {
              if (!adj) return;
              if (adj.skipped) {
                if (adj.reason === "llm_disabled") flash("违约级裁定需启用 LLM —— 去「系统设置 · AI 模型」启用后可在控制塔重跑逐条裁定；确定性回执仍如实显示检出/未检出。");
                else if (adj.reason === "error" && adj.error) flash(adj.error);
                return;
              }
              setRealAud(prev => prev ? { ...prev, drifted: adj.drifted || [] } : prev);
              if ((adj.drifted || []).length) flash(`已比对交接契约：检出 ${adj.drifted.length} 处违约（已落审计并产裁决卡）`);
            }).catch(() => {});
          }
        }).catch(() => {});
      }
    } catch (e) {}
    setHasDraft(true); setConsoleTab("audit"); setAuditPlay(true);
  };

  /* 演示捷径：不想真跑三次生成时，把余下场次标记成稿 */
  const simulate = () => {
    try {
      if (!WsCatalog) return;
      const fill = [1680, 1890, 1660];
      WsCatalog.set(WsCatalog.get().map(c => {
        if (parseInt(c.n, 10) !== 9) return c;
        const scenes = (c.scenes || []).map((s, i) => s.state === "done" ? s : { ...s, state: "done", words: s.words || fill[i] || 1500 });
        const cur = scenes.reduce((a, s) => a + (s.words || 0), 0);
        return { ...c, scenes, words: { ...c.words, cur } };
      }));
      flash("演示：起草台余下场次已标记成稿 —— 可开始章级审计");
    } catch (e) {}
  };

  const fixDrift = (id) => {
    setFixDone(s => new Set(s).add(id));
    /* FE-ALIGN P2(D13)：真实违约（adjudicate-draft 产物）→ 走后端裁决（accept_fix），
       收件箱里的同一条裁决卡同步消失；finding 已落库，无需再造演示 onceTask。 */
    const real = (aud.drifted || []).find(x => x.id === id && x.real && x.finding_id);
    if (real) {
      try { if (Lf7Bridge) Lf7Bridge.ruleCanon(real.finding_id, ""); } catch (e) {}
      flash("已裁决该违约（accept_fix）· 回写正文后这条即结清，收件箱同一条同步消失");
      return;
    }
    /* 裁决产物化（演示回落）：不只 toast，生成可追踪的修复任务进待办收件箱 */
    try {
      if (Lf7Bridge && id === "d1") Lf7Bridge.onceTask("task-aud-d1", {
        kind: "qc", priority: 2,
        title: "回写第 9 章：办公室位置统一为「地下档案室」",
        where: "第 9 章 · 段 12", source: "长篇控制塔 · 草稿审计",
        detail: "第 9 章草稿写「三楼档案室」，与第 6 章确立的「地下档案室」冲突。裁决已记录；回写正文后这条即可划掉。",
        actions: [{ label: "回写作台修改", intent: "primary", op: "nav", to: "writer" }, { label: "知道了", intent: "quiet", op: "resolve" }],
      });
      if (Lf7Bridge && id === "d2") Lf7Bridge.onceTask("task-aud-d2", {
        kind: "idea", priority: 2,
        title: "第 10 章给阿恪一次成长点（选择或代价）",
        where: "第 10 章 · 规划", source: "长篇控制塔 · 草稿审计",
        detail: "阿恪自第 6 章起弧线持平，本章仅电话出场。已钉入下一轮交接；规划第 10 章时给他一次有代价的选择。",
        actions: [{ label: "去章节编排", intent: "primary", op: "nav", to: "author" }, { label: "知道了", intent: "quiet", op: "resolve" }],
      });
    } catch (e) {}
    flash("已裁决并送入下一轮交接复核 · 修复任务已投进待办收件箱");
  };
  const archiveNew = (id) => {
    setNewDone(s => new Set(s).add(id));
    if (id === "n1") setCanon(cs => cs.some(c => c.id === "c7") ? cs : [...cs, { id: "c7", subject: "周岚 · 办公室", value: "地下档案室", source: 6, status: "conflict", drift: true, conflictCh: 9, conflictText: "第 9 章「三楼档案室」与第 6 章「地下档案室」不一致", critical: false, pinned: false, fresh: true }]);
    if (id === "n3") setCanon(cs => cs.some(c => c.id === "c8") ? cs : [...cs, { id: "c8", subject: "父亲 · 工牌编号", value: "A-7", source: 9, status: "locked", critical: false, pinned: true }]);
    flash("已归档进设定锚点 · 进入下一轮的全书记忆");
  };

  const archive = () => {
    setLoops(ls => ls.map(l => l.id === "l6" ? { ...l, state: "closed", pinned: false } : l));
    setCanon(cs => cs.some(c => c.id === "c7") ? cs : [...cs, { id: "c7", subject: "周岚 · 办公室", value: "地下档案室", source: 6, status: "conflict", drift: true, conflictCh: 9, conflictText: "第 9 章「三楼档案室」与第 6 章「地下档案室」不一致", critical: false, pinned: false, fresh: true }]);
    /* 归档写回：草稿落进章节目录（成稿中心 / 流程图 / 主页同源可见）；
       新发现的冲突跨会话登记，待办收件箱同步出现同一条待裁决 */
    let wrote = false;
    try {
      if (Lf7Bridge) Lf7Bridge.addCanonConflict({ id: "c7", subject: "周岚 · 办公室", value: "地下档案室", source: 6, status: "conflict", drift: true, conflictCh: 9, conflictText: "第 9 章「三楼档案室」与第 6 章「地下档案室」不一致", critical: false, pinned: false, fresh: true });
      wrote = lf7ArchiveCh9 ? lf7ArchiveCh9() : false;
    } catch (e) {}
    setHasDraft(false); setConsoleTab("brief"); setFixDone(new Set()); setNewDone(new Set()); setAuditPlay(false); setArm(null);
    setSel({ type: "canon", id: "c7" }); setTab("canon");
    flash(wrote
      ? "第 9 章已归档并写入章节目录（成稿中心可见）· 「三楼/地下」漂移已送入下一轮交接与待办收件箱"
      : "第 9 章已归档 · 逾期脚印已回收 · 新发现的「三楼/地下」漂移已送入下一轮交接");
  };

  const copy = () => flash("强约束提示词已复制到剪贴板");
  /* 归档闸门：还有偏离未裁决 / 新引入未归档时，需显式二次确认「带病归档」 */
  const startArchive = () => {
    const introPending = aud.introduced.filter(x => !newDone.has(x.id)).length;
    if ((driftPending > 0 || introPending > 0) && arm !== "arc") {
      setArm("arc");
      setConsoleTab("audit");
      flash(`仍有 ${driftPending} 项偏离未裁决、${introPending} 项新引入未归档——再点一次将带病归档，未决项顺延下一轮`);
      return;
    }
    setArm(null);
    setArchivePlay(true);
  };
  const write = (ch) => { flash(`正在第 ${ch} 章打开写作台…`); if (go) setTimeout(() => go("writer"), 500); };

  /* 演示闭环复位：可重新走一轮「规划→交接→生成→审计→归档」 */
  const resetLoop = () => {
    try { if (Lf7Bridge) Lf7Bridge.resetLoop9(); } catch (e) {}
    try { if (lf2SyncFromCatalog) lf2SyncFromCatalog(); } catch (e) {}
    setHasDraft(false); setConsoleTab("brief"); setFixDone(new Set()); setNewDone(new Set()); setArm(null);
    flash("演示已复位：第 9 章回到待交接，可重新走一轮闭环");
  };

  const runScan = () => {
    if (scan === "scanning") return;
    setScan("scanning");
    setTimeout(() => { setScan("idle"); flash(`已重扫全书 ${LF2_BOOK.written} 章 · ${d.driftConflicts.length} 处漂移 · ${d.overdue.length} 处逾期 · ${(LF3_ORPHANS || []).length} 处空降 · ${d.fading.length} 项记忆淡出`); }, 1700);
  };

  /* 拍板有进展时解除「带病」闸门的武装 */
  useEffect6(() => { setArm(null); }, [doneIds, fixDone, newDone]);

  // —— 派生量 ——
  /* 塔台化：起草台执行进度（塔只看不写正文） */
  const archived9 = !!(Lf7Bridge && Lf7Bridge.isArchived(9));
  const handoff9 = !archived9 && !!(Lf7Bridge && Lf7Bridge.state().handoff9);
  const ch9 = (() => { try { return handoff9 ? ((WsCatalog ? WsCatalog.get() : []).find(c => parseInt(c.n, 10) === 9) || null) : null; } catch (e) { return null; } })();
  const sc9 = ch9 ? (ch9.scenes || []) : [];
  const done9 = sc9.filter(s => s.state === "done").length;
  const dispatched = handoff9 && sc9.length > 0 && done9 < sc9.length;
  const auditReady = handoff9 && sc9.length > 0 && done9 === sc9.length && !hasDraft;

  const heartIdx = gen === "generating" ? 1 : (hasDraft || auditReady) ? 3 : dispatched ? 2 : 1;
  const pending = issues.filter(it => !doneIds.has(it.id));
  const pendingActionable = issues.filter(it => LF6_ACTIONABLE.includes(it.kind) && !doneIds.has(it.id)).length;
  const loadedN = doneIds.size;
  const contractTotal = loadedN + pendingActionable;
  const contractPct = contractTotal ? Math.round((loadedN / contractTotal) * 100) : 100;
  const contractReady = pendingActionable === 0;
  const loadablePending = pending.filter(it => LF6_ACTIONABLE.includes(it.kind));
  const advisoryPending = pending.filter(it => !LF6_ACTIONABLE.includes(it.kind));
  const top = loadablePending[0] || null;
  const promotedN = pinnedFacts.size;
  const readyN = brief.enforce.length + promotedN;
  const memUsed = brief.used + promotedN * 60;
  const memPct = Math.min(100, Math.round((memUsed / brief.cap) * 100));

  const chips = [
    { key: "drift", label: "漂移", n: d.driftConflicts.length, tone: "rose" },
    { key: "overdue", label: "逾期", n: d.overdue.length, tone: "rose" },
    { key: "stall", label: "停滞", n: d.stalledThreads.length, tone: "gold" },
    { key: "fade", label: "淡出", n: d.fading.length, tone: "rose" },
  ].filter(c => c.n > 0);

  const reads = [
    { label: "总进度", val: d.progress.written, suffix: `/${d.progress.total}`, tone: "ink" },
    { label: "字数", val: (d.progress.words / 10000).toFixed(1), suffix: "万", tone: "ink" },
    { label: "张力健康", val: d.tensionHealth, tone: d.tensionHealth >= 80 ? "sage" : d.tensionHealth >= 65 ? "gold" : "rose" },
  ];

  const aud = realAud || LF3_AUDIT; // H2：真实回执优先（本章有正文时），否则静态演示
  const driftPending = aud.drifted.filter(x => !fixDone.has(x.id)).length;
  const jumpChip = (c) => {
    if (c.key === "fade") { flash(`${d.fading.length} 项关键设定/悬念正在淡出 AI 上下文 —— 右侧机器房「AI 工作记忆」可一键重新钉入。`); return; }
    setSel(null); setTab(LF6_TABMAP[c.key] || "board");
  };

  const atlasProps = {
    chapters: LF2_CHAPTERS, threads: LF2_THREADS, loops: loops.filter(l => l.state !== "closed"),
    canon, now: d.now, horizon: d.horizon, acts: LF2_ACTS, selected: sel, onSelect: select, scanning: scan === "scanning",
  };

  return (
    <div className="lf3-root lf6-root" onClick={() => setSel(null)}>
      {/* ===== 指挥栏 ===== */}
      <header className="lf3-cmd lf6-cmd" onClick={(e) => e.stopPropagation()}>
        <div className="lf3-brand">
          <span className="lf3-brand-mark"><I.Radar size={20} /></span>
          <div>
            <div className="lf3-brand-eyebrow" style={{ display: "flex", alignItems: "center", gap: 8 }}>长篇 · 控制塔 {WsDemoTag && <WsDemoTag note="悬念债 / 锚点 / 线 / 弧（锚点库）、空降 / 断链 / 认知态（审计层）、记忆预算池（faded 锚点）均为后端真实数据；章级审计回执在本章有正文时为确定性扫描真回执（契约 / 产出 / 锚点在场）；违约级判定经后端 chapter_audit_adjudicate 节点接真（LLM 启用则逐条落审计 + 产裁决卡，未启用则诚实降级只声明检出 / 未检出）。无正文的演示章仍回落静态审计动画。" />}</div>
            <div className="lf3-brand-title">{WsWorks ? WsWorks.active().title : "潮汐档案"}<span className="lf3-brand-genre">{WsWorks ? WsWorks.active().genre : "悬疑 · 长篇"}</span></div>
          </div>
        </div>

        <div className="lf6-heart-quiet">
          {LF6_HEART.map((s, i) => (
            <React.Fragment key={s}>
              {i > 0 && <span className={`lf6-hq-link ${i <= heartIdx ? "is-done" : ""}`} />}
              <div className={`lf6-hq-node ${i < heartIdx ? "is-done" : ""} ${i === heartIdx ? "is-on" : ""}`}>
                <span className="lf6-hq-dot">{i < heartIdx ? <I.Check size={11} /> : i + 1}</span>
                <span className="lf6-hq-label">第 {LF2_NEXT} 章 · {s}中</span>
              </div>
            </React.Fragment>
          ))}
        </div>

        <div className="lf3-cmd-right">
          <div className="lf3-vitals">
            {reads.map((m) => (
              <div key={m.label} className={`lf3-vital tone-${m.tone} ${m.tone === "rose" ? "is-alarm" : ""}`}>
                <span className="lf3-vital-val">{m.val}{m.suffix && <small>{m.suffix}</small>}</span>
                <span className="lf3-vital-label">{m.label}</span>
              </div>
            ))}
          </div>
          {standalone && <button className="lf3-iconbtn" onClick={() => setTheme(t => t === "night" ? "day" : "night")} title="切换昼夜">{theme === "night" ? <I.Sun size={16} /> : <I.Moon size={16} />}</button>}
          <button className="lf3-iconbtn" disabled={scan === "scanning"} onClick={runScan} title="重新分析全书">{scan === "scanning" ? <I.Refresh size={16} className="lf3-spin" /> : <I.Refresh size={16} />}</button>
        </div>
      </header>

      {/* ===== 脊 · 此刻焦点条（骑在交接线上） ===== */}
      <div className="lf6-spine" onClick={(e) => e.stopPropagation()}>
        {/* 左 · 你的一侧 */}
        <div className="lf6-spine-l">
          {gen === "generating" ? (
            <>
              <span className="lf6-now-ic tone-crimson"><I.Cpu size={18} /></span>
              <div className="lf6-now-body">
                <div className="lf6-now-eyebrow">此刻 · 交接中</div>
                <div className="lf6-now-title">正把 {readyN} 条随身约束封进契约，下发第 {LF2_NEXT} 章到 AI 起草台…</div>
              </div>
            </>
          ) : hasDraft ? (
            <>
              <span className={`lf6-now-ic ${driftPending ? "tone-rose" : "tone-sage"}`}>{driftPending ? <I.AlertTriangle size={18} /> : <I.CheckCircle size={18} />}</span>
              <div className="lf6-now-body">
                <div className="lf6-now-eyebrow">此刻 · 审计<span className="lf6-now-tag">第 {aud.ch} 章草稿 vs 契约</span></div>
                <div className="lf6-now-title">{driftPending ? <>守住 <b style={{ color: "var(--sage)" }}>{aud.honored.length}</b> 条 · 仍有 <b>{driftPending}</b> 项偏离需你裁决</> : <>偏离已全部裁决，可归档闭环</>}</div>
              </div>
              <button className="lf6-now-act is-ghost" onClick={() => { setConsoleTab("audit"); setAuditPlay(true); }}>查看审计<I.ArrowRight size={13} /></button>
            </>
          ) : auditReady ? (
            <>
              <span className="lf6-now-ic tone-gold"><I.ShieldCheck size={18} /></span>
              <div className="lf6-now-body">
                <div className="lf6-now-eyebrow">此刻 · 起草台已交稿<span className="lf6-now-tag">第 9 章 · {done9}/{sc9.length} 场成稿</span></div>
                <div className="lf6-now-title">场内质检已过——跨场连续性只有塔能看，开始逐条比对契约</div>
              </div>
              <button className="lf6-now-act is-rose" onClick={beginAudit}>开始章级审计<I.ArrowRight size={13} /></button>
            </>
          ) : dispatched ? (
            <>
              <span className="lf6-now-ic tone-slate"><I.Cpu size={18} /></span>
              <div className="lf6-now-body">
                <div className="lf6-now-eyebrow">此刻 · 生成在起草台<span className="lf6-now-tag">契约随场在场</span></div>
                <div className="lf6-now-title">第 9 章已拆成 {sc9.length} 场逐场起草 · {done9}/{sc9.length} 场已成稿</div>
              </div>
              <button className="lf6-now-act is-ghost" onClick={() => go && go("scene")}>前往起草台<I.ArrowRight size={13} /></button>
            </>
          ) : archived9 ? (
            <>
              <span className="lf6-now-ic tone-sage"><I.CheckCircle size={18} /></span>
              <div className="lf6-now-body">
                <div className="lf6-now-eyebrow">本轮闭环已完成<span className="lf6-now-tag is-sage">第 9 章 · 已审计归档</span></div>
                <div className="lf6-now-title">第 9 章草稿已进成稿中心待审 —— 下一章交接的演示从重置开始</div>
              </div>
              <button className="lf6-now-act is-ghost" onClick={() => go && go("manuscripts")}>去成稿中心<I.ArrowRight size={13} /></button>
            </>
          ) : top ? (
            <>
              <span className={`lf6-now-ic tone-${top.tone === "crimson" ? "crimson" : top.sev === "high" ? "rose" : top.sev === "medium" ? "gold" : "slate"}`}>{React.createElement(I[top.icon] || I.Zap, { size: 18 })}</span>
              <div className="lf6-now-body">
                <div className="lf6-now-eyebrow">此刻最该你拍板的<span className="lf6-now-tag">{top.label} · {top.meta.split(" · ")[0]}</span></div>
                <div className="lf6-now-title">{top.title}</div>
              </div>
              {chips.length > 0 && (
                <div className="lf6-chips">
                  {chips.slice(0, 3).map(c => (
                    <button key={c.key} className={`lf6-chip tone-${c.tone}`} onClick={() => jumpChip(c)} title={`查看${c.label}`}>
                      <span className="lf6-chip-dot" />{c.label}<b>{c.n}</b>
                    </button>
                  ))}
                </div>
              )}
              <button className={`lf6-now-act ${top.sev === "high" ? "is-rose" : ""}`} onClick={() => act(top)}>{top.action}<I.ArrowRight size={13} /></button>
            </>
          ) : (
            <>
              <span className="lf6-now-ic tone-sage"><I.CheckCircle size={18} /></span>
              <div className="lf6-now-body">
                <div className="lf6-now-eyebrow">此刻 · 失控已清空{advisoryPending.length > 0 && <span className="lf6-now-tag is-sage">另有 {advisoryPending.length} 条创作建议</span>}</div>
                <div className="lf6-now-title"><b style={{ color: "var(--sage)" }}>{readyN}</b> 条随身约束已就位 —— 契约就绪，可交接生成</div>
              </div>
              {advisoryPending.length > 0 && <button className="lf6-now-act is-ghost" onClick={() => { setSel(null); setTab("board"); }}>看创作建议<I.ArrowRight size={13} /></button>}
            </>
          )}
        </div>

        {/* 右 · AI 的一侧（跨过交接线 = 交接动作） */}
        <div className="lf6-spine-r">
          <span className="lf6-seam-flag" key={loadPing}><I.ArrowRight size={10} /> 交接</span>
          {gen === "generating" ? (
            <>
              <div className="lf6-go-body">
                <div className="lf6-go-eyebrow">交接起草台</div>
                <div className="lf6-go-line"><b>{readyN}</b> 条随身约束封装进契约，随每场预检在场…</div>
              </div>
              <button className="lf6-go-btn" disabled><I.Refresh size={14} className="lf3-spin" /> 下发中</button>
            </>
          ) : hasDraft ? (
            <>
              <div className="lf6-go-body">
                <div className="lf6-go-eyebrow">闭环 · 归档</div>
                <div className="lf6-go-line">归档后：逾期回收、漂移并入设定，第 9 章进成稿中心待审</div>
              </div>
              <button className="lf6-go-btn is-archive" onClick={startArchive}><I.ArrowRight size={14} /> {arm === "arc" ? "仍要归档（带病）" : `归档 · 进第 ${aud.ch + 1} 章`}</button>
            </>
          ) : auditReady ? (
            <>
              <div className="lf6-go-body">
                <div className="lf6-go-eyebrow">闭环 · 审计</div>
                <div className="lf6-go-line">审计通过才可归档进目录、送成稿中心</div>
              </div>
              <button className="lf6-go-btn is-ready" onClick={beginAudit}><I.ShieldCheck size={14} /> 章级审计 · 第 9 章</button>
            </>
          ) : dispatched ? (
            <>
              <div className="lf6-go-body">
                <div className="lf6-go-eyebrow">执行 · AI 起草台</div>
                <div className="lf6-go-meter">
                  <div className="lf6-go-bar"><i style={{ width: `${Math.round((done9 / Math.max(1, sc9.length)) * 100)}%` }} /></div>
                  <span className="lf6-go-bar-n">{done9}/{sc9.length} 场成稿</span>
                </div>
              </div>
              <button className="lf6-go-btn" onClick={() => go && go("scene")}><I.ArrowRight size={14} /> 去起草台逐场起草</button>
            </>
          ) : archived9 ? (
            <>
              <div className="lf6-go-body">
                <div className="lf6-go-eyebrow">演示 · 重新走一轮</div>
                <div className="lf6-go-line">复位第 9 章的下发与归档，重新体验完整闭环</div>
              </div>
              <button className="lf6-go-btn" onClick={resetLoop}><I.Refresh size={14} /> 重置本轮演示</button>
            </>
          ) : (
            <>
              <div className="lf6-go-body">
                <div className="lf6-go-eyebrow">交接 · 第 {brief.next} 章 · 随身契约</div>
                <div className="lf6-go-meter">
                  <div className={`lf6-go-bar ${contractReady ? "is-done" : ""}`}><i style={{ width: `${contractPct}%` }} /></div>
                  <span className="lf6-go-bar-n">{contractReady ? `${contractTotal} 项已拍板` : `${loadedN}/${contractTotal} · 还差 ${contractTotal - loadedN}`}</span>
                </div>
              </div>
              <button className={`lf6-go-btn ${contractReady ? "is-ready" : ""}`} onClick={generate}><I.Cpu size={14} /> {arm === "gen" ? `仍要下发（差 ${contractTotal - loadedN} 项）` : `交接 · 下发起草台`}</button>
            </>
          )}
        </div>
      </div>

      {/* ===== 中缝解说（产品概念锚点）+ 可点契约入口 ===== */}
      <div className="lf6-seam-note" onClick={(e) => e.stopPropagation()}>
        <div className="lf6-seam-note-l"><I.Info size={12} /> AI 一次读不进整本书 —— 塔只做四件事：<b>规划契约 · 下发起草台 · 章级审计 · 守门归档</b>；正文只在起草台与写作台产出。</div>
        <div className="lf6-seam-note-r">
          {dispatched && <button className="lf6-seam-note-link" onClick={simulate}>演示 · 模拟起草台完成 <I.Check size={11} /></button>}
          <button className="lf6-seam-note-link" onClick={() => setConsoleTab("brief")}>查看交接契约 <I.ArrowRight size={11} /></button>
        </div>
      </div>

      {/* ===== 主体 · 两侧 ===== */}
      <div className="lf6-body" onClick={(e) => e.stopPropagation()}>
        {/* 左 · 纸（诊断台） */}
        <div className="lf6-paper">
          <Lf6Skyline open={skyOpen} onToggle={toggleSky} d={d} atlasProps={atlasProps} />
          <div className="lf6-board-wrap">
            <Lf5Guard tab={tab} setTab={setTab} issues={issues} doneIds={doneIds} d={d} loops={loops} canon={canon} now={d.now}
              sel={sel} onSelect={select} onAct={act} onPinLoop={pinLoop} onSchedule={schedule} onResolveLoop={resolveLoop}
              onResolveCanon={resolveCanon} onPinCanon={pinCanon} onWrite={write} />
          </div>
        </div>

        {/* 右 · 深墨机器房 */}
        <aside className="lf6-machine">
          <div className="lf6-machine-id">
            <span className="lf3-zone-tag"><I.Cpu size={13} /> AI 的一侧 · 机器房</span>
            <small>第 {LF2_NEXT} 章交接</small>
          </div>
          <Lf6Mem d={d} onRepin={repin} />
          <div className="lf3-seg">
            <button className={`lf3-seg-btn ${consoleTab === "brief" ? "is-active" : ""}`} onClick={() => setConsoleTab("brief")}>
              <I.ArrowRight size={14} /> 交接契约
            </button>
            <button className={`lf3-seg-btn ${consoleTab === "audit" ? "is-active" : ""}`} disabled={!hasDraft} onClick={() => hasDraft && setConsoleTab("audit")}>
              <I.ShieldCheck size={14} /> 草稿审计 {hasDraft && <span className="lf3-seg-dot" />}
            </button>
          </div>
          {consoleTab === "brief"
            ? <Lf4Brief brief={brief} pinnedFacts={pinnedFacts} onToggleMode={toggleMode} onPromoteFact={promoteFact} onCopy={copy} onPreview={() => setPreview(true)} onGenerate={generate} gen={gen} />
            : <Lf3Audit audit={aud} fixDone={fixDone} onFix={fixDrift} newDone={newDone} onArchiveNew={archiveNew} onArchive={startArchive} />}
        </aside>
      </div>

      {toast && ReactDOM.createPortal(<div className="lf3-toast"><span className="lf3-toast-dot"><I.Check size={13} /></span>{toast}</div>, document.body)}
      {gen === "generating" && ReactDOM.createPortal(<Lf6Generating brief={brief} />, document.body)}
      {auditPlay && hasDraft && ReactDOM.createPortal(<Lf6Auditing audit={aud} onClose={() => setAuditPlay(false)} />, document.body)}
      {archivePlay && ReactDOM.createPortal(<Lf6Archiving audit={aud} onDone={() => { setArchivePlay(false); archive(); }} />, document.body)}
      {preview && ReactDOM.createPortal(<Lf3Preview brief={brief} pinnedFacts={pinnedFacts} onClose={() => setPreview(false)} />, document.body)}
    </div>
  );
}

/* 非潮汐作品：控制塔的悬念债 / 设定锚点 / 故事线还没有数据，
   给引导态而不是把另一部书的演示数据硬塞过来。 */
function Lf6Empty({ go }) {
  const work = WsWorks ? WsWorks.active() : { title: "这部作品" };
  const rows = [
    ["Radar", "悬念债", "每个埋下的钩子何时回收，逾期会被点名"],
    ["Anchor", "设定锚点", "人物年龄、物件、时间线等不许漂移的既定事实"],
    ["GitBranch", "故事线", "主线副线的在场区段，停滞会被标黄"],
  ];
  return (
    <div className="page" data-screen-label="longform · empty">
      <div style={{ display: "grid", placeItems: "center", minHeight: "70vh", textAlign: "center" }}>
        <div style={{ maxWidth: 520, display: "grid", gap: 16, justifyItems: "center" }}>
          <div style={{ fontFamily: "var(--font-serif)", fontSize: 22, color: "var(--ink-1)" }}>《{work.title}》的控制塔还没有点亮</div>
          <p style={{ color: "var(--ink-3)", fontSize: 14, lineHeight: 1.8, margin: 0 }}>
            长篇控制塔替 AI 记住整本书。等这部作品写到第 3–4 章、埋下第一批钩子之后，它会开始追踪：
          </p>
          <div style={{ display: "grid", gap: 10, textAlign: "left", width: "100%" }}>
            {rows.map(([ic, t, d]) => {
              const Ic = I[ic] || I.Dot;
              return (
                <div key={t} style={{ display: "flex", gap: 12, alignItems: "flex-start", padding: "12px 14px", border: "1px solid var(--line-1)", borderRadius: 12, background: "var(--paper-1)" }}>
                  <span style={{ color: "var(--crimson)", marginTop: 2 }}><Ic size={16} /></span>
                  <span><b style={{ color: "var(--ink-1)", fontSize: 14 }}>{t}</b><span style={{ color: "var(--ink-3)", fontSize: 13 }}> — {d}</span></span>
                </div>
              );
            })}
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn btn-accent" onClick={() => go && go("writer")}><I.Pen size={15} /> 回去写作</button>
            <button className="btn btn-ghost" onClick={() => go && go("author")}>去章节编排</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function WsLongform6(props) {
  /* FE-ALIGN F4：有后端锚点数据的作品点亮全塔（tide 由 seed 维护）；
     还没有锚点的作品保持引导态。
     网关时序修复：挂载主动水合 anchors，并订阅 lf2:tower-synced / ws:work-changed
     强制重判「引导态 vs 控制塔」——否则非 tide 作品的锚点异步到达后，网关已渲染
     引导态且不会自动切回全塔。Lf6Tower 按 activeId key，换作品时干净重挂。 */
  const [, lf6Force] = useApp6(0);
  useEffect6(() => {
    try { window.lf2SyncFromTower && window.lf2SyncFromTower(); } catch (e) {}
    const bump = () => lf6Force(x => x + 1);
    window.addEventListener("lf2:tower-synced", bump);
    window.addEventListener("ws:work-changed", bump);
    return () => { window.removeEventListener("lf2:tower-synced", bump); window.removeEventListener("ws:work-changed", bump); };
  }, []);
  const activeId = (() => { try { return WsWorks ? WsWorks.activeId() : "tide"; } catch (e) { return "tide"; } })();
  const isTide = activeId === "tide";
  const hasTower = isTide || (() => { try { return !!(window.lf2HasTowerData && window.lf2HasTowerData()); } catch (e) { return false; } })();
  if (!hasTower) return <Lf6Empty go={props.go} />;
  if (lf2SyncFromCatalog) lf2SyncFromCatalog();  // 章节/进度与目录同源
  return <Lf6Tower key={activeId} {...props} />;
}
Object.assign(window, { Lf6Tower, WsLongform6, Lf6Skyline });

/* ESM 导出（Phase 1 机械追加；window.* 赋值过渡期保留） */
export { Lf6Tower, WsLongform6, Lf6Skyline };
