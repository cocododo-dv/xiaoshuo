/* global React, I, arrDeriveThreads */

/* ==========================================================
   全书体检 — Book Doctor
   把三个镜头（弧线 / 线索 / 节奏）暴露的问题汇总成一张可操作的
   待办清单：悬空线索、字数超额、张力回落、视角分布。
   每项都能点进对应章节或镜头。
   ========================================================== */

function arrDeriveIssues(chapters, numOf) {
  const n = chapters.length;
  const threads = arrDeriveThreads(chapters, numOf);
  const out = [];

  /* writing frontier = last chapter that's actually been started (not just planned) */
  let frontier = 0;
  chapters.forEach((c, i) => { if (c.state !== "planned") frontier = i; });

  /* 1 · 悬空线索：未收束，且自写作前沿已 3 章以上没再提及（不含计划在后续收束的） */
  const dangling = threads.filter((t) => !t.closed && t.last.ci <= frontier && (frontier - t.last.ci) >= 3)
    .sort((a, b) => a.last.ci - b.last.ci);
  if (dangling.length) {
    out.push({
      kind: "warn", key: "dangling", label: "悬空线索", count: dangling.length,
      detail: "引入后已多章未提及、且尚未收束。点章号跳到它最后出现的一章，或在织布机里查看。",
      lens: "loom",
      chips: dangling.map((t) => ({ text: `${t.name} · 末见 ${t.last.num}`, go: t.last.chId })),
    });
  }

  /* 2 · 字数超额：实际明显超出预算 */
  const fat = chapters.filter((c) => c.words.cur > c.words.target * 1.12);
  if (fat.length) {
    out.push({
      kind: "warn", key: "fat", label: "字数超额", count: fat.length,
      detail: "实际字数明显超出预算，考虑拆分或精简。",
      lens: "pace",
      chips: fat.map((c) => ({ text: `${numOf[c.id]} ${c.title} · ${c.words.cur.toLocaleString()}/${c.words.target.toLocaleString()}`, go: c.id })),
    });
  } else {
    out.push({ kind: "ok", key: "budget", label: "字数预算在轨", detail: "没有已写章节明显超额。" });
  }

  /* 3 · 张力回落：同卷内较上一章明显下滑（卷首换场不算） */
  const dips = [];
  chapters.forEach((c, i) => {
    if (i === 0) return;
    const p = chapters[i - 1];
    if (c.act === p.act && (p.tension - c.tension) > 0.12) dips.push({ c, drop: p.tension - c.tension });
  });
  if (dips.length) {
    out.push({
      kind: "warn", key: "dip", label: "张力回落", count: dips.length,
      detail: "同卷内张力较上一章明显下滑，注意是否泄气。",
      lens: "arc",
      chips: dips.map(({ c, drop }) => ({ text: `${numOf[c.id]} ${c.title} · ↓${Math.round(drop * 100)}`, go: c.id })),
    });
  } else {
    out.push({ kind: "ok", key: "arc", label: "张力曲线健康", detail: "卷内没有意外回落。" });
  }

  /* 4 · 视角分布（信息项） */
  const povCounts = {};
  chapters.forEach((c) => { povCounts[c.pov] = (povCounts[c.pov] || 0) + 1; });
  const povList = Object.entries(povCounts).sort((a, b) => b[1] - a[1]);
  out.push({ kind: "info", key: "pov", label: "视角分布", detail: povList.map(([p, c]) => `${p} ${c} 章`).join(" · "), lens: "pace" });

  /* 5 · 在场线索（信息项）—— 未收束但仍在前沿附近或计划在后续收束 */
  const openRecent = threads.filter((t) => !t.closed).length - dangling.length;
  if (openRecent > 0) {
    out.push({ kind: "info", key: "open", label: "在场线索", detail: `${openRecent} 条线索仍在推进或计划在后续收束，暂不需处理。`, lens: "loom" });
  }

  // warnings first, then ok, then info
  const rank = { warn: 0, ok: 1, info: 2 };
  return out.sort((a, b) => rank[a.kind] - rank[b.kind]);
}

function ArrDoctor({ chapters, numOf, onOpen, onLens }) {
  const issues = React.useMemo(() => arrDeriveIssues(chapters, numOf), [chapters, numOf]);
  const todo = issues.filter((x) => x.kind === "warn").reduce((s, x) => s + (x.count || 1), 0);

  return (
    <section className="card arr-doctor">
      <div className="card-head">
        <div>
          <div className="card-title">全书体检</div>
          <div className="card-sub">从三个镜头汇总的待办与健康项。点条目直接处理。</div>
        </div>
        <span className={`arr-doc-score ${todo ? "is-todo" : "is-clear"}`}>
          {todo ? <React.Fragment><I.AlertTriangle size={13} />{todo} 项待办</React.Fragment>
                : <React.Fragment><I.Check size={13} />全部健康</React.Fragment>}
        </span>
      </div>
      <ul className="arr-doc-list">
        {issues.map((iss) => {
          const Ic = iss.kind === "warn" ? I.AlertTriangle : iss.kind === "ok" ? I.Check : I.Info || I.Circle;
          return (
            <li key={iss.key} className={`arr-doc s-${iss.kind}`}>
              <span className="arr-doc-ic"><Ic size={14} /></span>
              <div className="arr-doc-body">
                <div className="arr-doc-head">
                  <span className="arr-doc-label">{iss.label}</span>
                  {iss.count != null && <span className="arr-doc-count tab-num">{iss.count}</span>}
                  {iss.lens && onLens && (
                    <button className="arr-doc-lens" onClick={() => onLens(iss.lens)}>
                      在{iss.lens === "loom" ? "织布机" : iss.lens === "pace" ? "节奏镜头" : "弧线"}查看 →
                    </button>
                  )}
                </div>
                <div className="arr-doc-detail">{iss.detail}</div>
                {iss.chips && (
                  <div className="arr-doc-chips">
                    {iss.chips.map((c, i) => (
                      <button key={i} className="arr-doc-chip" onClick={() => onOpen(c.go)} title="跳到该章">{c.text}</button>
                    ))}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

Object.assign(window, { arrDeriveIssues, ArrDoctor });
