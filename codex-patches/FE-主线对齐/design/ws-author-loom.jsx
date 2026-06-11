/* global React, I, ARR_ACTS, ARR_THREAD_ROLE */

/* ==========================================================
   线索织布机 — Thread Loom
   全书级伏笔/线索追踪：每条线索从「新引」到「收束」横跨所有章节，
   编织成一张图。一眼看出哪些线索引入了却没有收束（虚线 = 未收束）。
   数据来源：每章 threads[{name, role}]，role ∈ 新引/承接/延续/收束。
   ========================================================== */

const ARR_ROLE_KEY = { "新引": "new", "承接": "carry", "延续": "cont", "收束": "close" };

/* derive a per-thread lifecycle across the whole book */
function arrDeriveThreads(chapters, numOf) {
  const map = new Map();
  chapters.forEach((c, ci) => {
    (c.threads || []).forEach((t) => {
      if (!map.has(t.name)) map.set(t.name, { name: t.name, app: [] });
      map.get(t.name).app.push({ chId: c.id, ci, role: t.role, num: numOf[c.id] });
    });
  });
  const threads = [...map.values()].map((t) => {
    const app = t.app.sort((a, b) => a.ci - b.ci);
    const first = app[0], last = app[app.length - 1];
    const closes = app.filter((a) => a.role === "收束");
    const closed = closes.length > 0;
    const closeAt = closed ? closes[closes.length - 1] : null;
    // role at introduction (for the row accent) — fall back to first role
    const intro = app.find((a) => a.role === "新引") || first;
    return {
      name: t.name, app, first, last,
      closed, closeAt,
      span: last.ci - first.ci,
      introCi: intro.ci,
    };
  });
  // weave order: by introduction chapter, then longest span first (cascading)
  threads.sort((a, b) => a.first.ci - b.first.ci || b.span - a.span || a.name.localeCompare(b.name));
  return threads;
}

/* act bands spanning their chapter columns (acts are contiguous in seed data) */
function arrActSpans(chapters) {
  return ARR_ACTS.map((a) => {
    const idxs = chapters.map((c, i) => (c.act === a.id ? i : -1)).filter((i) => i >= 0);
    if (!idxs.length) return null;
    return { a, from: Math.min(...idxs), to: Math.max(...idxs) };
  }).filter(Boolean);
}

function ArrLoomNode({ role, onJump, label }) {
  const key = ARR_ROLE_KEY[role] || "cont";
  return (
    <button className={`loom-node role-${key}`} title={label} onClick={(e) => { e.stopPropagation(); onJump && onJump(); }} aria-label={label}>
      <span className="loom-node-mark" />
    </button>
  );
}

/* micro thread strip — the whole-book trajectory of one thread, with
   the current chapter highlighted. Echoes a loom row inside chapter detail. */
function ArrThreadMini({ thread, n, curCi }) {
  const { first, last, closed } = thread;
  const appAt = {};
  thread.app.forEach((a) => { appAt[a.ci] = a; });
  return (
    <div className="tmini" style={{ "--tmini-cols": n }}>
      {Array.from({ length: n }).map((_, ci) => {
        const a = appAt[ci];
        const solidL = ci > first.ci && ci <= last.ci;
        const solidR = ci >= first.ci && ci < last.ci;
        const openContL = !closed && ci > last.ci;
        const key = a ? (ARR_ROLE_KEY[a.role] || "cont") : null;
        const cur = ci === curCi;
        return (
          <span key={ci} className={`tmini-cell ${cur ? "is-cur" : ""}`}>
            {solidL && <i className="tmini-line l" />}
            {solidR && <i className="tmini-line r" />}
            {(!closed && ci === last.ci && ci < n - 1) && <i className="tmini-line r dash" />}
            {openContL && <i className="tmini-line l dash" />}
            {(openContL && ci < n - 1) && <i className="tmini-line r dash" />}
            {key && <i className={`tmini-node role-${key}`} />}
          </span>
        );
      })}
    </div>
  );
}

function ArrThreadLoom({ chapters, numOf, onOpen }) {
  const { useState: useStL, useMemo: useMemoL } = React;
  const [hover, setHover] = useStL(null);
  const threads = useMemoL(() => arrDeriveThreads(chapters, numOf), [chapters, numOf]);
  const bands = useMemoL(() => arrActSpans(chapters), [chapters]);
  const n = chapters.length;
  const openCount = threads.filter((t) => !t.closed).length;
  const closedCount = threads.length - openCount;
  const longest = threads.reduce((m, t) => (t.span > (m ? m.span : -1) ? t : m), null);

  const gridVars = { "--loom-cols": n };

  return (
    <div className="loom">
      <div className="loom-summary">
        <span className="loom-sum-item"><strong className="tab-num">{threads.length}</strong> 条线索</span>
        <span className="loom-sum-sep" />
        <span className={`loom-sum-item ${openCount ? "is-open" : "is-clear"}`}>
          <i className="loom-sum-dot" /><strong className="tab-num">{openCount}</strong> 未收束
        </span>
        <span className="loom-sum-item is-closed">
          <i className="loom-sum-dot" /><strong className="tab-num">{closedCount}</strong> 已收束
        </span>
        {longest && (
          <span className="loom-sum-item loom-sum-long">
            最长跨度 · <b>{longest.name}</b> <span className="tab-num">{longest.span + 1} 章</span>
          </span>
        )}
        <span className="loom-legend">
          <span><i className="loom-lg role-new" />引入</span>
          <span><i className="loom-lg role-carry" />承接</span>
          <span><i className="loom-lg role-cont" />延续</span>
          <span><i className="loom-lg role-close" />收束</span>
          <span><i className="loom-lg-dash" />未收束</span>
        </span>
      </div>

      <div className="loom-grid" style={gridVars}>
        {/* act bands */}
        <div className="loom-row loom-acts">
          <div className="loom-name loom-name-corner">卷 · 章</div>
          {bands.map((b) => (
            <div key={b.a.id} className={`loom-act tone-${b.a.tone}`} style={{ gridColumn: `${b.from + 2} / ${b.to + 3}` }}>
              <span className="loom-act-n">{b.a.n}</span><span className="loom-act-name">{b.a.name}</span>
            </div>
          ))}
        </div>

        {/* chapter number header */}
        <div className="loom-row loom-head">
          <div className="loom-name loom-name-head">线索</div>
          {chapters.map((c, ci) => (
            <button key={c.id} className={`loom-colhead ${c.current ? "is-current" : ""}`} style={{ gridColumn: ci + 2 }}
              onClick={() => onOpen(c.id)} title={`第 ${numOf[c.id]} 章 · ${c.title}`}>
              {numOf[c.id]}
            </button>
          ))}
        </div>

        {/* thread rows */}
        {threads.map((t) => {
          const roleAt = {};
          t.app.forEach((a) => { roleAt[a.ci] = a; });
          const dim = hover && hover !== t.name;
          return (
            <div key={t.name} className={`loom-row loom-thread ${dim ? "is-dim" : ""} ${hover === t.name ? "is-hot" : ""} ${t.closed ? "is-closed" : "is-open"}`}
              onMouseEnter={() => setHover(t.name)} onMouseLeave={() => setHover(null)}>
              <div className="loom-name">
                <span className="loom-name-text text-serif">{t.name}</span>
                <span className={`loom-chip ${t.closed ? "is-closed" : "is-open"}`}>
                  {t.closed ? `收于 ${t.closeAt.num}` : "未收束"}
                </span>
              </div>
              {chapters.map((c, ci) => {
                const a = roleAt[ci];
                const within = ci >= t.first.ci && ci <= t.last.ci;
                const solidL = ci > t.first.ci && ci <= t.last.ci;
                const solidR = ci >= t.first.ci && ci < t.last.ci;
                const openCont = !t.closed && ci > t.last.ci;        // dashed tail to book end
                const openL = openCont || (!t.closed && ci === t.last.ci && ci < n - 1);
                return (
                  <div key={c.id} className={`loom-cell ${within ? "is-within" : ""}`} style={{ gridColumn: ci + 2 }}>
                    {solidL && <span className="loom-line loom-line-l" />}
                    {solidR && <span className="loom-line loom-line-r" />}
                    {/* open continuation: dashed right-half from last node onward */}
                    {(!t.closed && ci === t.last.ci && ci < n - 1) && <span className="loom-line loom-line-r is-dash" />}
                    {openCont && <span className="loom-line loom-line-l is-dash" />}
                    {(openCont && ci < n - 1) && <span className="loom-line loom-line-r is-dash" />}
                    {a && <ArrLoomNode role={a.role} label={`第 ${a.num} 章 · ${a.role}`} onJump={() => onOpen(c.id)} />}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

Object.assign(window, { arrDeriveThreads, arrActSpans, ArrThreadLoom, ArrThreadMini });
