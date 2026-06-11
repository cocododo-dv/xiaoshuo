/* global React, I, LF2_NEXT, LF3_RETRIEVE, LF3_BUDGET_CAP, FACT_COST, Lf3Memory, Lf3Audit */
/* ==========================================================
   长篇控制塔 v4 · 控制台（软化版）
   把工程师语言（token / 预算 / RAG / 向量库）软化成作者语言：
     强约束  → 随身带（每次生成都在 AI 脑子里）
     可检索池 → 存档库（写到相关情节才翻出来）
   token 数字降为安静的技术注脚。记忆衰减条与草稿审计复用 v3。
   ========================================================== */

function Lf4ConsolePane(props) {
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
      {consoleTab === "brief" ? <Lf4Brief {...props} /> : <Lf3Audit {...props} />}
    </aside>
  );
}

function Lf4Brief({ brief, pinnedFacts, onToggleMode, onPromoteFact, onCopy, onPreview, onGenerate, gen }) {
  const promoted = LF3_RETRIEVE.filter(f => pinnedFacts.has(f.id));
  const enforce = brief.enforce;
  const used = brief.used + promoted.length * FACT_COST;
  const cap = LF3_BUDGET_CAP;
  const pct = Math.min(100, Math.round((used / cap) * 100));
  const over = used > cap;
  const carryN = enforce.length + promoted.length;
  const segs = [...enforce.map(it => ({ tone: it.tone, cost: it.cost })), ...promoted.map(() => ({ tone: "slate", cost: FACT_COST }))];
  const pool = [
    ...brief.retrieve.map(it => ({ id: it.id, text: it.text, sub: it.label + " · " + it.source, kind: "brief" })),
    ...LF3_RETRIEVE.filter(f => !pinnedFacts.has(f.id)).map(f => ({ id: f.id, text: f.text, sub: f.reason, kind: "fact" })),
  ];

  return (
    <>
      <div className="lf3-con-scroll">
        <div className="lf3-brief-head">
          <span className="lf3-brief-title text-serif">第 {brief.next} 章 · AI 的随身记忆</span>
          <span className="lf3-brief-seam">交接线</span>
        </div>
        <p className="lf3-brief-lead">AI 一次记不住整本书。下面是写第 {brief.next} 章绝不能违反的——我替你分两类：<b style={{ color: "var(--con-gold)" }}>随身带</b>每次都在它脑子里；其余放进<b style={{ color: "var(--con-slate)" }}>存档库</b>，写到相关情节才翻出来。</p>

        {/* 随身记忆容量 */}
        <div className="lf3-budget">
          <div className="lf3-budget-top">
            <span className="lf3-budget-label"><I.Cpu size={13} /> 随身记忆 · 容量有限</span>
            <span className={`lf3-budget-num ${over ? "is-over" : ""}`}><b>{carryN}</b> <small>条随身 · {pct}% 满</small></span>
          </div>
          <div className="lf3-budget-bar">{segs.map((s, i) => <span key={i} className={`lf3-budget-seg tone-${s.tone}`} style={{ width: `${(s.cost / cap) * 100}%` }} />)}</div>
          <p className="lf3-budget-foot">{over
            ? <span style={{ color: "var(--con-rose)" }}>随身记忆装不下了——把不那么关键的几条移到存档库，给最该守住的腾位置。</span>
            : <>{carryN} 条随身记忆每次生成都在场，占容量 {pct}%；其余写到相关情节才自动翻出，不占容量。<span style={{ opacity: .6 }}>（约 {used.toLocaleString()}/{cap.toLocaleString()} tok）</span></>}</p>
        </div>

        {/* 随身带 · 按记忆层分组 */}
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
                    <button className="lf3-ho-toggle" disabled={it.lock} onClick={() => !it.lock && onToggleMode(it.id)} title={it.lock ? "核心约束 · 必须随身" : "移到存档库 · 写到才翻出"}>{it.lock ? "锁定" : "↓ 存档"}</button>
                  </div>
                </div>
              ))}
            </div>
          );
        })}

        {/* 存档库 */}
        <div className="lf3-pool">
          <div className="lf3-pool-h"><I.Database size={13} /> 存档库 · 不占随身容量</div>
          <p className="lf3-pool-lead">存着整本书的其余设定，AI 写到相关情节时自动翻出。点「↑ 随身」让它每次都在场。</p>
          {pool.map(p => (
            <div key={p.id} className="lf3-pool-item">
              <span className="lf3-pool-dot" />
              <span className="lf3-pool-text">{p.text}<small>{p.sub}</small></span>
              <button className="lf3-pool-promote" onClick={() => p.kind === "fact" ? onPromoteFact(p.id) : onToggleMode(p.id)}>↑ 随身</button>
            </div>
          ))}
        </div>
      </div>

      <div className="lf3-con-foot">
        <p className="lf3-con-note"><b>{carryN}</b> 条随身记忆随第 {brief.next} 章交接下发起草台，逐场预检在场 · {pool.length} 条留存档库按需翻出。</p>
        <div className="lf3-con-btns">
          <button className="lf3-cbtn is-ghost" onClick={onCopy}><I.FileText size={14} /></button>
          <button className="lf3-cbtn is-go" disabled={gen !== "idle"} onClick={onGenerate}>{gen === "generating" ? <><I.Refresh size={14} className="lf3-spin" /> 下发中…</> : <><I.Cpu size={14} /> 交接 · 下发起草台 · 第 {brief.next} 章</>}</button>
        </div>
        <button className="lf3-con-preview" onClick={onPreview}><I.Eye size={12} /> 预览 AI 这次实际会读到的全部</button>
      </div>
    </>
  );
}

Object.assign(window, { Lf4ConsolePane, Lf4Brief });
