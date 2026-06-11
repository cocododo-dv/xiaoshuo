/* global React, ReactDOM, I, LF2_BOOK, LF2_NEXT, LF2_LOOPS, LF2_CANON, LF2_TARGET, LF3_RETRIEVE, LF3_AUDIT, LF3_BUDGET_CAP,
   lf2Derive, lf3Issues, lf3Brief, Lf3Atlas, Lf3Guard, Lf3ConsolePane */
const { useState: useApp3, useMemo: useMemo3, useEffect: useEffect3 } = React;

const LF3_HEART = ["规划", "交接", "生成", "审计", "归档"];

function Lf3Tower({ go, standalone }) {
  const [loops, setLoops] = useApp3(() => JSON.parse(JSON.stringify(LF2_LOOPS)));
  const [canon, setCanon] = useApp3(() => JSON.parse(JSON.stringify(LF2_CANON)));
  const [sel, setSel] = useApp3(null);
  const [tab, setTab] = useApp3("board");
  const [doneIds, setDoneIds] = useApp3(() => new Set());
  const [modes, setModes] = useApp3(() => ({}));        // brief item id -> 'enforce' | 'retrieve'
  const [pinnedFacts, setPinnedFacts] = useApp3(() => new Set());
  const [consoleTab, setConsoleTab] = useApp3("brief");
  const [hasDraft, setHasDraft] = useApp3(false);
  const [gen, setGen] = useApp3("idle");
  const [fixDone, setFixDone] = useApp3(() => new Set());
  const [newDone, setNewDone] = useApp3(() => new Set());
  const [scan, setScan] = useApp3("idle");
  const [preview, setPreview] = useApp3(false);
  const [toast, setToast] = useApp3(null);
  const [theme, setTheme] = useApp3("day");

  useEffect3(() => { if (standalone) document.documentElement.setAttribute("data-theme", theme === "night" ? "dark" : "light"); }, [theme, standalone]);

  const d = useMemo3(() => lf2Derive(loops, canon), [loops, canon]);
  const issues = useMemo3(() => lf3Issues(d, loops, canon), [d, loops, canon]);
  const brief = useMemo3(() => lf3Brief(loops, canon, modes), [loops, canon, modes]);

  const flash = (msg) => { setToast(msg); clearTimeout(flash._t); flash._t = setTimeout(() => setToast(null), 3400); };

  const TAB_OF = { loop: "ledger", thread: "threads", arc: "arcs", canon: "canon", clue: "clues", orphan: "board", causal: "board", risk: "board" };
  const select = (ref) => {
    setSel(ref);
    if (ref && TAB_OF[ref.type]) setTab(TAB_OF[ref.type]);
  };

  const pinLoop = (id) => setLoops(ls => ls.map(l => l.id === id ? { ...l, pinned: !l.pinned } : l));
  const ensurePinLoop = (id) => setLoops(ls => ls.map(l => l.id === id ? { ...l, pinned: true } : l));
  const schedule = (id, ch) => setLoops(ls => ls.map(l => l.id === id ? { ...l, payoff: ch } : l));
  const resolveLoop = (id) => { setLoops(ls => ls.map(l => l.id === id ? { ...l, state: "closed", pinned: false } : l)); setSel(null); flash("已标记回收，悬念债结清"); };
  const resolveCanon = (id) => setCanon(cs => cs.map(c => c.id === id ? { ...c, status: "locked", pinned: true } : c));
  const pinCanon = (id) => setCanon(cs => cs.map(c => c.id === id ? { ...c, pinned: !c.pinned } : c));

  const act = (it) => {
    if (it.kind === "conflict") {
      setDoneIds(s => new Set(s).add(it.id)); resolveCanon(it.ref.id); select(it.ref);
      flash(`已统一并锁定「${(canon.find(c => c.id === it.ref.id) || {}).subject}」→ 装入第 ${LF2_NEXT} 章强约束`);
    } else if (it.kind === "overdue") {
      setDoneIds(s => new Set(s).add(it.id)); ensurePinLoop(it.ref.id);
      flash(`逾期悬念已钉入第 ${LF2_NEXT} 章强约束，将提醒 AI 回收`);
    } else if (it.kind === "stall") {
      setDoneIds(s => new Set(s).add(it.id)); flash(`停滞线索已装入交接，AI 将在第 ${LF2_NEXT} 章推进它`);
    } else if (it.kind === "orphan") {
      setDoneIds(s => new Set(s).add(it.id)); flash("已记下：需在揭示章之前补铺垫，已列入下一轮交接");
    } else if (it.kind === "causal") {
      setDoneIds(s => new Set(s).add(it.id)); flash("断链已记入交接：AI 将在前序章节补上承重因");
    } else if (it.kind === "fair") {
      select(it.ref); setTab("clues"); flash("公平性问题已定位——在揭晓前补可推理线索");
    } else if (it.kind === "continuity") {
      select(it.ref);
    } else if (it.kind === "dip") {
      setDoneIds(s => new Set(s).add(it.id)); flash(`已设为第 ${LF2_NEXT} 章张力基准`);
    } else if (it.kind === "arc") {
      select(it.ref); setTab("arcs");
    }
  };

  const toggleMode = (id) => setModes(m => ({ ...m, [id]: (m[id] === "retrieve" ? "enforce" : (m[id] === "enforce" ? "retrieve" : "retrieve")) }));
  const promoteFact = (id) => { setPinnedFacts(s => new Set(s).add(id)); flash("已提升为强约束 · 将占用记忆预算、随每次生成在场"); };

  const repin = () => {
    setLoops(ls => ls.map(l => d.fading.some(f => f.kind === "loop" && f.id === l.id) ? { ...l, pinned: true } : l));
    setCanon(cs => cs.map(c => d.fading.some(f => f.kind === "canon" && f.id === c.id) ? { ...c, pinned: true } : c));
    flash(`已把 ${d.fading.length} 项淡出的关键内容重新钉为强约束`);
  };

  const generate = () => {
    if (gen !== "idle") return;
    setGen("generating");
    setTimeout(() => { setGen("idle"); setHasDraft(true); setConsoleTab("audit"); flash(`第 ${LF2_NEXT} 章草稿已生成 · 控制塔正在比对交接契约…`); }, 2000);
  };

  const fixDrift = (id, idx) => { setFixDone(s => new Set(s).add(id)); flash("已裁决并送入下一轮交接复核"); };
  const archiveNew = (id, idx) => {
    setNewDone(s => new Set(s).add(id));
    if (id === "n1") setCanon(cs => cs.some(c => c.id === "c7") ? cs : [...cs, { id: "c7", subject: "周岚 · 办公室", value: "（待统一）", source: 9, status: "conflict", drift: true, conflictCh: 6, conflictText: "第 9 章「三楼档案室」与第 6 章「地下档案室」不一致", critical: false, pinned: false, fresh: true }]);
    if (id === "n3") setCanon(cs => cs.some(c => c.id === "c8") ? cs : [...cs, { id: "c8", subject: "父亲 · 工牌编号", value: "A-7", source: 9, status: "locked", critical: false, pinned: true }]);
    flash("已归档进设定锚点 · 进入下一轮的全书记忆");
  };

  const archive = () => {
    // 第 9 章归档：回收的逾期悬念结清，新发现的漂移已并入设定，复位到下一轮交接
    setLoops(ls => ls.map(l => l.id === "l6" ? { ...l, state: "closed", pinned: false } : l));
    setCanon(cs => cs.some(c => c.id === "c7") ? cs : [...cs, { id: "c7", subject: "周岚 · 办公室", value: "（待统一）", source: 9, status: "conflict", drift: true, conflictCh: 6, conflictText: "第 9 章「三楼档案室」与第 6 章「地下档案室」不一致", critical: false, pinned: false, fresh: true }]);
    setHasDraft(false); setConsoleTab("brief"); setFixDone(new Set()); setNewDone(new Set());
    setSel({ type: "canon", id: "c7" }); setTab("canon");
    flash("第 9 章已归档 · 逾期脚印已回收 · 新发现的「三楼/地下」漂移已送入下一轮交接");
  };

  const copy = () => flash("强约束提示词已复制到剪贴板");
  const write = (ch) => { flash(`正在第 ${ch} 章打开写作台…`); if (go) setTimeout(() => go("writer"), 500); };

  const runScan = () => {
    if (scan === "scanning") return;
    setScan("scanning");
    setTimeout(() => { setScan("idle"); flash(`已重扫全书 ${LF2_BOOK.written} 章 · ${d.driftConflicts.length} 处漂移 · ${d.overdue.length} 处逾期 · ${window.LF3_ORPHANS.length} 处空降 · ${d.fading.length} 项记忆淡出`); }, 1700);
  };

  const heartIdx = gen === "generating" ? 2 : hasDraft ? 3 : 1;

  const vitals = [
    { label: "总进度", val: d.progress.written, suffix: `/${d.progress.total}`, tone: "ink" },
    { label: "字数", val: (d.progress.words / 10000).toFixed(1), suffix: "万", tone: "ink" },
    { label: "张力健康", val: d.tensionHealth, tone: d.tensionHealth >= 80 ? "sage" : d.tensionHealth >= 65 ? "gold" : "rose" },
    { label: "AI 漂移", val: d.driftConflicts.length, tone: d.driftConflicts.length ? "rose" : "sage", alarm: !!d.driftConflicts.length },
    { label: "悬念逾期", val: d.overdue.length, tone: d.overdue.length ? "rose" : "sage", alarm: !!d.overdue.length },
    { label: "线索停滞", val: d.stalledThreads.length, tone: d.stalledThreads.length ? "gold" : "sage" },
    { label: "记忆淡出", val: d.fading.length, tone: d.fading.length ? "rose" : "sage", alarm: !!d.fading.length },
  ];

  return (
    <div className="lf3-root" onClick={() => setSel(null)}>
      <header className="lf3-cmd" onClick={(e) => e.stopPropagation()}>
        <div className="lf3-brand">
          <span className="lf3-brand-mark"><I.Radar size={20} /></span>
          <div>
            <div className="lf3-brand-eyebrow">长篇 · 控制塔</div>
            <div className="lf3-brand-title">潮汐档案<span className="lf3-brand-genre">悬疑 · 长篇</span></div>
          </div>
        </div>

        <div className="lf3-heart">
          {LF3_HEART.map((s, i) => (
            <React.Fragment key={s}>
              {i > 0 && <span className={`lf3-heart-link ${i <= heartIdx ? "is-done" : ""}`} />}
              <div className={`lf3-heart-node ${i < heartIdx ? "is-done" : ""} ${i === heartIdx ? "is-on" : ""}`}>
                <span className="lf3-heart-dot">{i < heartIdx ? <I.Check size={14} /> : i + 1}</span>
                <span className="lf3-heart-label">{s}</span>
              </div>
            </React.Fragment>
          ))}
          <span className="lf3-heart-ch">第 {LF2_NEXT} 章 · {LF3_HEART[heartIdx]}中</span>
        </div>

        <div className="lf3-cmd-right">
          <div className="lf3-vitals">
            {vitals.map(m => (
              <div key={m.label} className={`lf3-vital ${m.alarm ? "is-alarm" : ""}`}>
                <span className={`lf3-vital-val tone-${m.tone}`}>{m.val}{m.suffix && <small>{m.suffix}</small>}</span>
                <span className="lf3-vital-label">{m.label}</span>
              </div>
            ))}
          </div>
          {standalone && <button className="lf3-iconbtn" onClick={() => setTheme(t => t === "night" ? "day" : "night")} title="切换昼夜">{theme === "night" ? <I.Sun size={16} /> : <I.Moon size={16} />}</button>}
          <button className="lf3-iconbtn" disabled={scan === "scanning"} onClick={runScan} title="重新分析全书">{scan === "scanning" ? <I.Refresh size={16} className="lf3-spin" /> : <I.Refresh size={16} />}</button>
        </div>
      </header>

      <div className="lf3-tagline" onClick={(e) => e.stopPropagation()}>
        <span className="lf3-tagline-text"><I.Info size={12} /> AI 一次只读得进几章，记不住整本书。控制塔替它记住——把<b>该守住的长程约束</b>，钉回它写下一章的工作记忆。</span>
        <span className="lf3-tagline-seam">左 · 你写下的书 │ 右 · AI 的下一口呼吸</span>
      </div>

      <div className="lf3-body" onClick={(e) => e.stopPropagation()}>
        <div className="lf3-paper">
          <Lf3Atlas chapters={window.LF2_CHAPTERS} threads={window.LF2_THREADS} loops={loops.filter(l => l.state !== "closed")} canon={canon} now={d.now} horizon={d.horizon} acts={window.LF2_ACTS} selected={sel} onSelect={select} scanning={scan === "scanning"} />
          <Lf3Guard tab={tab} setTab={setTab} issues={issues} doneIds={doneIds} d={d} loops={loops} canon={canon} now={d.now}
            sel={sel} onSelect={select} onAct={act} onPinLoop={pinLoop} onSchedule={schedule} onResolveLoop={resolveLoop}
            onResolveCanon={resolveCanon} onPinCanon={pinCanon} onWrite={write} />
        </div>

        <Lf3ConsolePane
          consoleTab={consoleTab} setConsoleTab={setConsoleTab} hasDraft={hasDraft}
          d={d} now={d.now} onRepin={repin}
          brief={brief} pinnedFacts={pinnedFacts} onToggleMode={toggleMode} onPromoteFact={promoteFact}
          onCopy={copy} onPreview={() => setPreview(true)} onGenerate={generate} gen={gen}
          audit={LF3_AUDIT} fixDone={fixDone} onFix={fixDrift} newDone={newDone} onArchiveNew={archiveNew} onArchive={archive} />
      </div>

      {toast && ReactDOM.createPortal(<div className="lf3-toast"><span className="lf3-toast-dot"><I.Check size={13} /></span>{toast}</div>, document.body)}
      {gen === "generating" && ReactDOM.createPortal(<Lf3Generating brief={brief} />, document.body)}
      {preview && ReactDOM.createPortal(<Lf3Preview brief={brief} pinnedFacts={pinnedFacts} onClose={() => setPreview(false)} />, document.body)}
    </div>
  );
}

function Lf3Generating({ brief }) {
  return (
    <div className="lf3-gen-scrim">
      <div className="lf3-gen-card">
        <div className="lf3-gen-orb"><I.Cpu size={26} /></div>
        <div className="lf3-gen-title">AI 正在按 {brief.enforce.length} 条强约束<br />生成第 {brief.next} 章草稿…</div>
        <div className="lf3-gen-bar"><span /></div>
        <div className="lf3-gen-sub">设定锚点 · 到期承诺 · 待推进线索 已随本次生成下发 · 其余靠向量库按需召回</div>
      </div>
    </div>
  );
}

function Lf3Preview({ brief, pinnedFacts, onClose }) {
  const facts = window.LF3_RETRIEVE.filter(f => pinnedFacts.has(f.id));
  const total = brief.enforce.length + facts.length;
  return (
    <div className="lf3-modal-scrim" onClick={onClose}>
      <div className="lf3-modal" onClick={(e) => e.stopPropagation()}>
        <div className="lf3-modal-h">
          <div><div className="lf3-modal-eyebrow"><I.Cpu size={13} /> AI 将收到的完整上下文 · 第 {brief.next} 章</div><div className="lf3-modal-title">长程约束 · 系统记忆段</div></div>
          <button className="lf3-modal-x" onClick={onClose}><I.X size={16} /></button>
        </div>
        <div className="lf3-prompt">
          <div className="lf3-prompt-cmt"># 控制塔注入 · 写作第 {brief.next} 章前必须守住的长程约束（强制 · 永在场）</div>
          <div className="lf3-prompt-cmt"># 全书已写 {brief.next - 1} 章；以下为你（AI）上下文外、但绝不能违反的设定与承诺。</div>
          {brief.strata.map(s => {
            const items = s.items.filter(it => it.mode === "enforce");
            if (!items.length) return null;
            return (<div key={s.key} style={{ marginTop: 8 }}><div className="lf3-prompt-sec">【{s.title}】</div>{items.map((it, i) => <div key={it.id}>　{i + 1}. <b>{it.text}</b><span className="lf3-prompt-src"> — {it.label} · {it.source}</span></div>)}</div>);
          })}
          {facts.length > 0 && <div style={{ marginTop: 8 }}><div className="lf3-prompt-sec">【已提升 · 世界设定】</div>{facts.map((f, i) => <div key={f.id}>　{i + 1}. <b>{f.text}</b></div>)}</div>}
          <div className="lf3-prompt-cmt" style={{ marginTop: 10 }}># 共 {total} 条强约束随本次生成全程生效；如与正文冲突，以本段为准。</div>
          <div className="lf3-prompt-cmt"># 另有可检索池存于全书向量库，写到相关情节时自动召回，不占本段预算。</div>
        </div>
        <div className="lf3-modal-foot">
          <span className="lf3-con-note">这是控制塔在你点「交接生成」时，自动拼接进 AI 提示词的强约束记忆段。</span>
          <button className="lf3-cbtn is-go" style={{ flex: "0 0 auto" }} onClick={onClose}><I.Check size={13} /> 明白了</button>
        </div>
      </div>
    </div>
  );
}

function WsLongform3(props) { return <Lf3Tower {...props} />; }
Object.assign(window, { Lf3Tower, Lf3Generating, Lf3Preview, WsLongform3 });
