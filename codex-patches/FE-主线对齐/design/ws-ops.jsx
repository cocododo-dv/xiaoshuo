/* global React, I */
const { useState: useSt12 } = React;

/* ==========================================================
   发布索引 — Index Console（真实数据流）
   由目录（章节状态）、收件箱（审核条目）与导入导出记录实时派生：
   整本书有什么已经「发布生效」（终稿、拍板过的应用、导出的数据包），
   什么还卡在等你处理。每一行都能跳到它的来源模块，没有死按钮。
   ========================================================== */

const IDX_STATE = {
  running: { tone: "crimson", label: "进行中" },
  pending: { tone: "gold",    label: "待你处理" },
  done:    { tone: "sage",    label: "已生效" },
};

function idxDerive() {
  const rows = [];
  try {
    const chs = window.WsCatalog ? window.WsCatalog.get() : [];
    chs.forEach(c => {
      if (c.state === "approved") rows.push({ id: "ch-" + c.id, target: `chapter_final · 第 ${c.n} 章《${c.title}》`, action: "publish", state: "done", note: "终稿已锁定，汇入整书", at: null, nav: "manuscripts", cta: "查看" });
      else if (c.state === "review") rows.push({ id: "ch-" + c.id, target: `chapter_review · 第 ${c.n} 章《${c.title}》`, action: "review", state: "pending", note: "等待你在成稿中心批准", at: null, nav: "manuscripts", cta: "去批准" });
      else if (c.state === "writing" || c.current) rows.push({ id: "ch-" + c.id, target: `chapter_draft · 第 ${c.n} 章《${c.title}》`, action: "draft", state: "running", note: "正文推进中", at: null, nav: "writer", cta: "去写作" });
    });
  } catch (e) {}
  try {
    (window.rvCustomList ? window.rvCustomList() : []).forEach(it => {
      const ok = window.rvIsResolved && window.rvIsResolved(it.id);
      rows.push({ id: "rv-" + it.id, target: `review_item · ${it.title}`, action: it.source || "审核", state: ok ? "done" : "pending", note: ok ? "已拍板生效" : "等待你在收件箱拍板", at: it.at, nav: "review", cta: ok ? "查看" : "去拍板" });
    });
  } catch (e) {}
  try {
    ioLog().forEach((e, i) => rows.push({ id: "io-" + i, target: `bundle · ${e.file}`, action: e.kind === "export" ? "export" : "import", state: "done", note: e.kind === "export" ? "已导出到本机" : "已恢复为新作品", at: e.at, nav: "interop", cta: "查看" }));
  } catch (e) {}
  const w = { pending: 0, running: 1, done: 2 };
  return rows.sort((a, b) => (w[a.state] - w[b.state]) || ((b.at || 0) - (a.at || 0)));
}

function WsIndex({ go }) {
  /* 订阅目录 + 收件箱：上游变动时重新派生 */
  if (window.useCatalogChapters) window.useCatalogChapters();
  const [, force] = useSt12(0);
  React.useEffect(() => {
    const bump = () => force(n => n + 1);
    window.addEventListener("ws:review-changed", bump);
    window.addEventListener("ws:work-changed", bump);
    return () => { window.removeEventListener("ws:review-changed", bump); window.removeEventListener("ws:work-changed", bump); };
  }, []);
  const [filter, setFilter] = useSt12("all");
  const all = idxDerive();
  const jobs = filter === "all" ? all : all.filter(j => j.state === filter);
  const counts = {
    running: all.filter(j => j.state === "running").length,
    pending: all.filter(j => j.state === "pending").length,
    done:    all.filter(j => j.state === "done").length,
  };
  return (
    <div className="page" data-screen-label="index">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <div className="page-eyebrow">发布索引</div>
            <h1 className="page-title">整本书里，什么已生效、什么在等你</h1>
            <p className="page-subtitle">由章节目录、待办收件箱与导入导出记录实时派生——点任意一行可跳到它的来源模块处理。</p>
          </div>
        </header>

        <section className="idx-stats">
          <div className="idx-stat tone-crimson">
            <div className="idx-stat-num tab-num">{counts.running}</div>
            <div className="idx-stat-label">进行中</div>
          </div>
          <div className="idx-stat tone-gold">
            <div className="idx-stat-num tab-num">{counts.pending}</div>
            <div className="idx-stat-label">待你处理</div>
          </div>
          <div className="idx-stat tone-sage">
            <div className="idx-stat-num tab-num">{counts.done}</div>
            <div className="idx-stat-label">已生效</div>
          </div>
          <div className="idx-stat-spacer">
            <div className="idx-flow">
              <I.Database size={12} />
              <span>目录 · 收件箱 · 数据包 → 实时派生</span>
            </div>
            <div className="text-muted text-sm">处理清「待你处理」，整条流水线就单向往前。</div>
          </div>
        </section>

        <div className="flex gap-2 mb-4">
          <FilterBtn id="all" cur={filter} on={setFilter}>全部 · {all.length}</FilterBtn>
          <FilterBtn id="pending" cur={filter} on={setFilter}>待你处理</FilterBtn>
          <FilterBtn id="running" cur={filter} on={setFilter}>进行中</FilterBtn>
          <FilterBtn id="done" cur={filter} on={setFilter}>已生效</FilterBtn>
        </div>

        {jobs.length === 0 ? (
          <div className="card" style={{ padding: "36px 24px", textAlign: "center", color: "var(--ink-3)", fontSize: 13 }}>
            这一类暂时没有条目。目录里的章节、收件箱的审核、导出的数据包都会出现在这里。
          </div>
        ) : (
          <div className="card" style={{padding:0}}>
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{width:100}}>状态</th>
                  <th>目标 / 动作</th>
                  <th>说明</th>
                  <th style={{width:90}}>时间</th>
                  <th style={{width:90}}></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map(j => (
                  <tr key={j.id}>
                    <td><JobState s={j.state} /></td>
                    <td>
                      <div className="text-serif fw-600">{j.target}</div>
                      <div className="text-muted text-xs" style={{fontFamily:"var(--font-mono)"}}>{j.action}</div>
                    </td>
                    <td className="text-muted text-sm">{j.note || "—"}</td>
                    <td className="text-muted text-sm">{j.at ? ioAgo(j.at) : "—"}</td>
                    <td>
                      <button className={j.state === "pending" ? "btn btn-accent btn-sm" : "btn btn-quiet btn-sm"} onClick={() => go && go(j.nav)}>{j.cta}</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

function FilterBtn({ id, cur, on, children }) {
  return (
    <button className={`pill ${cur === id ? "pill-crimson" : ""}`} onClick={() => on(id)} style={{cursor:"pointer"}}>
      {cur === id && <span className="pill-dot" />}
      {children}
    </button>
  );
}

function JobState({ s }) {
  const m = IDX_STATE[s] || IDX_STATE.done;
  return <span className={`pill pill-${m.tone} text-xs`}><span className="pill-dot" />{m.label}</span>;
}

/* ==========================================================
   导入导出 — Interop Center（真实数据流）
   · 全书稿 Markdown：目录（WsCatalog）+ 写作器正文编译下载
   · 作品数据包 JSON：当前作品全部持久化状态（目录/雪花/正文/
     旁注/待办/回收站…）打包备份
   · 导入：数据包恢复为新作品，不覆盖现有内容
   ========================================================== */

const IO_LOG_LS = "ws_io_log_v1";
function ioLog() { try { return JSON.parse(localStorage.getItem(IO_LOG_LS)) || []; } catch (e) { return []; } }
function ioLogPush(entry) {
  try { localStorage.setItem(IO_LOG_LS, JSON.stringify([{ at: Date.now(), ...entry }, ...ioLog()].slice(0, 12))); } catch (e) {}
}
function ioAgo(t) {
  const m = Math.floor((Date.now() - t) / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return m + " 分钟前";
  const h = Math.floor(m / 60);
  if (h < 24) return h + " 小时前";
  return Math.floor(h / 24) + " 天前";
}
function ioDownload(name, text, type) {
  const blob = new Blob([text], { type: type || "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  return blob.size;
}
function ioHtmlToText(html) {
  const div = document.createElement("div");
  div.innerHTML = html || "";
  const blocks = [...div.querySelectorAll("p, blockquote")];
  const txt = blocks.length
    ? blocks.map(p => (p.tagName === "BLOCKQUOTE" ? "> " : "") + p.innerText.trim()).filter(Boolean).join("\n\n")
    : (div.innerText || "").trim();
  return txt === "在这里开始写这一场……" ? "" : txt;
}
function ioBuildMarkdown() {
  const work = window.WsWorks.active();
  const chs = window.WsCatalog ? window.WsCatalog.get() : [];
  let md = `# ${work.title}\n\n> ${work.genre || ""}${work.sub ? " · " + work.sub : ""}\n`;
  chs.forEach(c => {
    md += `\n\n## 第 ${c.n} 章 · ${c.title}\n`;
    (c.scenes || []).forEach((s, i) => {
      md += `\n### ${String(i + 1).padStart(2, "0")} · ${s.title}\n\n`;
      let txt = "";
      try { txt = ioHtmlToText(localStorage.getItem(window.wsKey("wr-doc:" + s.sid)) || ""); } catch (e) {}
      md += (txt || "（本场尚无正文）") + "\n";
    });
  });
  return md;
}
function ioCollectWorkKeys() {
  const id = window.WsWorks.activeId();
  const suffix = "::" + id;
  const keys = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.slice(-suffix.length) === suffix) keys[k.slice(0, -suffix.length)] = localStorage.getItem(k);
  }
  return keys;
}
function ioExportMarkdown(setToast) {
  const work = window.WsWorks.active();
  const md = ioBuildMarkdown();
  const file = `${work.title} · 全书稿.md`;
  const size = ioDownload(file, md, "text/markdown;charset=utf-8");
  ioLogPush({ kind: "export", file, size });
  setToast(`已导出「${file}」`);
}
function ioExportBundle(setToast) {
  const work = window.WsWorks.active();
  const keys = ioCollectWorkKeys();
  /* 运行时真相强制入包：种子作品没编辑过的部分不在 localStorage 里，
     只抄键会导出一部空书。这里把目录与有种子文的正文一并物化进包。 */
  try { if (window.WsCatalog) keys["arr.chapters.v2"] = JSON.stringify(window.WsCatalog.get()); } catch (e) {}
  try { if (window.s2ExportState) { const s = window.s2ExportState(); if (s) keys["ws_snow_state_v2"] = JSON.stringify(s); } } catch (e) {}
  try {
    const chs = window.WsCatalog ? window.WsCatalog.get() : [];
    chs.forEach(c => (c.scenes || []).forEach(s => {
      if (!s.sid) return;
      if (keys["wr-doc:" + s.sid] == null) {
        const seeded = window.wrSeedHTML ? window.wrSeedHTML(s.sid) : null;
        if (seeded && !/^<p>在这里开始写/.test(seeded)) keys["wr-doc:" + s.sid] = seeded;
      }
      if (keys["wr-notes:" + s.sid] == null) {
        const ns = window.wrNotesSeed ? window.wrNotesSeed(s.sid) : "";
        if (ns) keys["wr-notes:" + s.sid] = ns;
      }
    }));
  } catch (e) {}
  const payload = {
    __ws_backup: 2,
    app: "tide-workbench",
    exportedAt: new Date().toISOString(),
    work: { title: work.title, genre: work.genre, sub: work.sub, mark: work.mark, accent: work.accent, wordsTarget: work.wordsTarget, chaptersTotal: work.chaptersTotal },
    keys,
  };
  const file = `${work.title} · 数据包.json`;
  const size = ioDownload(file, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
  ioLogPush({ kind: "export", file, size });
  setToast(`已导出「${file}」（含 ${Object.keys(payload.keys).length} 项状态）`);
}
function ioImportBundle(fileObj, setToast) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result);
      if (!data || data.__ws_backup == null || !data.keys) { setToast("这不是本工作台导出的数据包（缺少标记）。"); return; }
      const meta = data.work || {};
      if (!window.confirm(`将「${meta.title || "未命名作品"}」恢复为一部新作品？不会覆盖现有内容。`)) return;
      const w = window.WsWorks.create({ title: meta.title, genre: meta.genre, sub: meta.sub, wordsTarget: meta.wordsTarget, accent: meta.accent });
      Object.keys(data.keys).forEach(base => {
        try { localStorage.setItem(base + "::" + w.id, data.keys[base]); } catch (e) {}
      });
      if (meta.chaptersTotal) window.WsWorks.update(w.id, { chaptersTotal: meta.chaptersTotal });
      ioLogPush({ kind: "import", file: fileObj.name, size: fileObj.size });
      setToast(`已恢复为新作品「${meta.title || "未命名作品"}」，正在进入…`);
      setTimeout(() => { location.hash = "#home"; location.reload(); }, 900);
    } catch (e) {
      setToast("导入失败：文件不是有效的 JSON。");
    }
  };
  reader.readAsText(fileObj);
}
function ioFmtSize(b) {
  if (b == null) return "—";
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  return (b / 1024 / 1024).toFixed(1) + " MB";
}

function WsInterop({ go }) {
  const [toast, setToast] = useSt12(null);
  const [drag, setDrag] = useSt12(false);
  const fileRef = React.useRef(null);
  const [, force] = useSt12(0);
  React.useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 5200);
    return () => clearTimeout(id);
  }, [toast]);
  const note = (msg) => { setToast(msg); force(n => n + 1); };
  const work = window.WsWorks ? window.WsWorks.active() : { title: "—" };
  const totals = window.WsCatalog ? window.WsCatalog.totals() : { words: 0, planned: 0 };
  const recent = ioLog();

  const onFile = (f) => { if (f) ioImportBundle(f, note); };

  return (
    <div className="page" data-screen-label="interop">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <div className="page-eyebrow">导入导出</div>
            <h1 className="page-title">把作品搬进搬出</h1>
            <p className="page-subtitle">当前作品：《{work.title}》· {totals.planned} 章 · {(totals.words / 10000).toFixed(1)} 万字。导出随时可做，导入不会覆盖现有内容。</p>
          </div>
        </header>

        {/* Export cards */}
        <section style={{marginBottom: 28}}>
          <h2 className="text-serif" style={{fontSize:17, margin:"0 0 12px", color:"var(--ink-2)"}}>导出</h2>
          <div className="io-grid">
            <ExportCard
              icon="FileText" tone="crimson"
              title="全书稿"
              desc="目录 + 写作器正文编译成一份可读文档"
              formats={["Markdown"]}
              onExport={() => ioExportMarkdown(note)}
            />
            <ExportCard
              icon="Database" tone="slate"
              title="作品数据包"
              desc="章节目录、雪花构思、正文与旁注、待办、回收站……当前作品的全部状态，可备份可迁移"
              formats={["JSON"]}
              onExport={() => ioExportBundle(note)}
            />
          </div>
        </section>

        {/* Import zone */}
        <section style={{marginBottom: 28}}>
          <h2 className="text-serif" style={{fontSize:17, margin:"0 0 12px", color:"var(--ink-2)"}}>导入</h2>
          <div className="io-import">
            <div className={`io-import-zone ${drag ? "is-drag" : ""}`}
              style={drag ? { borderColor: "var(--crimson)", background: "var(--crimson-wash)" } : undefined}
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
              onDragLeave={() => setDrag(false)}
              onDrop={(e) => { e.preventDefault(); setDrag(false); onFile(e.dataTransfer.files && e.dataTransfer.files[0]); }}>
              <I.UploadCloud size={28} />
              <div className="fw-600 mt-2">把数据包拖到这里</div>
              <div className="text-muted text-sm">支持本工作台导出的 · 数据包.json</div>
              <button className="btn btn-ghost btn-sm mt-3" onClick={() => fileRef.current && fileRef.current.click()}>选择文件…</button>
              <input ref={fileRef} type="file" accept=".json,application/json" style={{ display: "none" }}
                onChange={(e) => { onFile(e.target.files && e.target.files[0]); e.target.value = ""; }} />
            </div>
            <div className="io-import-tips">
              <h3 className="text-serif fw-600 mb-2" style={{fontSize:15}}>导入会做什么</h3>
              <ul className="io-tip-list">
                <li><I.Check size={13} /> 数据包会恢复为一部新作品，出现在左上角书架里</li>
                <li><I.Check size={13} /> 章节、正文、构思、待办、回收站一并恢复</li>
                <li><I.AlertTriangle size={13} className="warn" /> 不会覆盖任何现有作品；示例作品的演示装饰（审批人、版本号等）不随包迁移</li>
              </ul>
            </div>
          </div>
        </section>

        {/* Recent activity — 真实记录 */}
        <section>
          <h2 className="text-serif" style={{fontSize:17, margin:"0 0 12px", color:"var(--ink-2)"}}>最近</h2>
          {recent.length === 0 ? (
            <div className="card" style={{ padding: "28px 24px", textAlign: "center", color: "var(--ink-3)", fontSize: 13 }}>
              还没有导入导出记录——导出一份数据包就是最好的备份习惯。
            </div>
          ) : (
            <div className="card" style={{padding:0}}>
              <table className="lib-table">
                <thead>
                  <tr>
                    <th style={{width:80}}>类型</th>
                    <th>文件</th>
                    <th style={{width:120}}>时间</th>
                    <th style={{width:90}}>大小</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((it, i) => (
                    <tr key={i}>
                      <td><IoKind k={it.kind} /></td>
                      <td className="text-serif fw-600">{it.file}</td>
                      <td className="text-muted text-sm">{ioAgo(it.at)}</td>
                      <td className="text-muted text-sm tab-num">{ioFmtSize(it.size)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {toast && (
        <div style={{ position: "fixed", left: "50%", bottom: 28, transform: "translateX(-50%)", background: "var(--ink-1)", color: "var(--paper-0)", padding: "10px 18px", borderRadius: 999, fontSize: 13, boxShadow: "var(--shadow-lg)", zIndex: 2000 }}>
          {toast}
        </div>
      )}
    </div>
  );
}

function ExportCard({ icon, tone, title, desc, formats, onExport }) {
  const Ic = I[icon] || I.Dot;
  return (
    <div className={`io-card tone-${tone}`}>
      <div className="io-card-icon"><Ic size={20} /></div>
      <h3 className="io-card-title text-serif">{title}</h3>
      <p className="io-card-desc text-muted">{desc}</p>
      <div className="io-card-formats">
        {formats.map(f => <span key={f} className="pill text-xs">{f}</span>)}
      </div>
      <button className="btn btn-quiet btn-sm io-card-btn" onClick={onExport}>导出 <I.ArrowRight size={13} /></button>
    </div>
  );
}

function IoKind({ k }) {
  const map = {
    export: { tone: "crimson", label: "导出" },
    import: { tone: "slate",   label: "导入" },
    replay: { tone: "gold",    label: "回放" },
  };
  const m = map[k] || map.import;
  return <span className={`pill pill-${m.tone} text-xs`}><span className="pill-dot" />{m.label}</span>;
}

Object.assign(window, { WsIndex, WsInterop });

