import React from "react";
import { I } from "./icons.jsx";
import { agoLabel } from "./lib/ago.js";
import { apiGet, apiPost } from "./lib/client.js";
import { WsCatalog, useCatalogChapters } from "./ws-catalog.jsx";
import { rvCustomList, rvIsResolved } from "./ws-review.jsx";
import { WsWorks } from "./ws-works.jsx";

/* global React, I */
const { useState: useSt12 } = React;

/* ==========================================================
   发布索引 — Index Console（真实数据流）
   由目录（章节状态）与收件箱（审核条目）实时派生：
   整本书有什么已经「发布生效」（终稿、拍板过的应用），
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
    const chs = WsCatalog ? WsCatalog.get() : [];
    chs.forEach(c => {
      if (c.state === "approved") rows.push({ id: "ch-" + c.id, target: `chapter_final · 第 ${c.n} 章《${c.title}》`, action: "publish", state: "done", note: "终稿已锁定，汇入整书", at: null, nav: "manuscripts", cta: "查看" });
      else if (c.state === "review") rows.push({ id: "ch-" + c.id, target: `chapter_review · 第 ${c.n} 章《${c.title}》`, action: "review", state: "pending", note: "等待你在成稿中心批准", at: null, nav: "manuscripts", cta: "去批准" });
      else if (c.state === "writing" || c.current) rows.push({ id: "ch-" + c.id, target: `chapter_draft · 第 ${c.n} 章《${c.title}》`, action: "draft", state: "running", note: "正文推进中", at: null, nav: "writer", cta: "去写作" });
    });
  } catch (e) {}
  try {
    (rvCustomList ? rvCustomList() : []).forEach(it => {
      const ok = rvIsResolved && rvIsResolved(it.id);
      rows.push({ id: "rv-" + it.id, target: `review_item · ${it.title}`, action: it.source || "审核", state: ok ? "done" : "pending", note: ok ? "已拍板生效" : "等待你在收件箱拍板", at: it.at, nav: "review", cta: ok ? "查看" : "去拍板" });
    });
  } catch (e) {}
  const w = { pending: 0, running: 1, done: 2 };
  return rows.sort((a, b) => (w[a.state] - w[b.state]) || ((b.at || 0) - (a.at || 0)));
}

function WsIndex({ go }) {
  /* 订阅目录 + 收件箱：上游变动时重新派生 */
  if (useCatalogChapters) useCatalogChapters();
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
            <p className="page-subtitle">由章节目录与待办收件箱实时派生——点任意一行可跳到它的来源模块处理。</p>
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
              <span>目录 · 收件箱 → 实时派生</span>
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
            这一类暂时没有条目。目录里的章节与收件箱中的审核会出现在这里。
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
                    <td className="text-muted text-sm">{j.at ? agoLabel(j.at) : "—"}</td>
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
   互操作与导出 — Interop Center（真实数据流）
   · 服务端成稿导出统一交给 WsManuscripts 的权威正文链路
   · 场景 bundle worksheet 通过后端 preview/import/export/replay 接口
   · 浏览器缓存仅可导出诊断快照，不冒充数据库备份或迁移包
   ========================================================== */

const IO_LOG_LS = "ws_io_log_v1";
function ioLog() { try { return JSON.parse(localStorage.getItem(IO_LOG_LS)) || []; } catch (e) { return []; } }
function ioLogPush(entry) {
  try { localStorage.setItem(IO_LOG_LS, JSON.stringify([{ at: Date.now(), ...entry }, ...ioLog()].slice(0, 12))); } catch (e) {}
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
function ioCollectWorkKeys(workId = WsWorks.activeId()) {
  const id = String(workId || "");
  if (!id || id === "__loading__") return {};
  const suffix = "::" + id;
  const keys = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.slice(-suffix.length) === suffix) keys[k.slice(0, -suffix.length)] = localStorage.getItem(k);
  }
  return keys;
}
function ioBuildCacheSnapshot() {
  const work = (WsWorks && WsWorks.active && WsWorks.active()) || {};
  return {
    __ws_cache_snapshot: 1,
    app: "novel-system-workbench",
    exportedAt: new Date().toISOString(),
    boundary: {
      authoritative: false,
      import_supported: false,
      includes_server_database: false,
      note: "仅包含当前浏览器中带作品后缀的缓存键，不是完整项目备份。",
    },
    work: {
      projectId: work.id || "",
      title: work.title || "未命名作品",
      genre: work.genre || "",
      sub: work.sub || "",
    },
    keys: ioCollectWorkKeys(work.id),
  };
}
function ioExportCacheSnapshot(setToast) {
  const payload = ioBuildCacheSnapshot();
  const file = `${payload.work.title} · 浏览器缓存快照.json`;
  const size = ioDownload(file, JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
  ioLogPush({ kind: "cache-export", file, size });
  setToast(`已导出「${file}」（${Object.keys(payload.keys).length} 个本机缓存键；不含服务端数据库）`);
}

function ioExtractEnvelope(payload) {
  if (payload && payload.envelope) return payload.envelope;
  if (!payload || !payload.bundle_id) return null;
  return {
    bundle_id: payload.bundle_id,
    scene_id: payload.scene_id,
    chapter_id: payload.chapter_id,
    bundle_snapshot_hash: payload.bundle_snapshot_hash,
    hash_contract_version: payload.hash_contract_version,
    hash_alg: payload.hash_alg,
    execution_mode: payload.execution_mode,
    created_by_action: payload.created_by_action,
    snapshot: payload.snapshot,
  };
}

function ioResultFromPayload(payload, mode) {
  return {
    mode,
    envelope: ioExtractEnvelope(payload),
    receipt: (payload && payload.artifact_receipt) || null,
    comparisons: Array.isArray(payload && payload.source_ref_comparisons)
      ? payload.source_ref_comparisons
      : [],
  };
}
function ioFmtSize(b) {
  if (b == null) return "—";
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  return (b / 1024 / 1024).toFixed(1) + " MB";
}

function WsInterop({ go }) {
  const [toast, setToast] = useSt12(null);
  const [worksheetYaml, setWorksheetYaml] = useSt12("");
  const [preview, setPreview] = useSt12(null);
  const [previewedYaml, setPreviewedYaml] = useSt12("");
  const [bundleId, setBundleId] = useSt12("");
  const [finalRowId, setFinalRowId] = useSt12("");
  const [draftRowId, setDraftRowId] = useSt12("");
  const [activeResult, setActiveResult] = useSt12(null);
  const [busy, setBusy] = useSt12("");
  const [error, setError] = useSt12("");
  const [, force] = useSt12(0);
  React.useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 5200);
    return () => clearTimeout(id);
  }, [toast]);
  const note = (msg) => { setToast(msg); force(n => n + 1); };
  const work = WsWorks ? WsWorks.active() : { title: "—" };
  const totals = WsCatalog ? WsCatalog.totals() : { words: 0, planned: 0 };
  const recent = ioLog();
  const canImport = !!(
    preview
    && worksheetYaml.trim()
    && worksheetYaml.trim() === previewedYaml
  );

  const runAction = async (actionId, action) => {
    if (busy) return null;
    setBusy(actionId);
    setError("");
    try {
      return await action();
    } catch (e) {
      setError((e && e.message) || "互操作请求失败。");
      return null;
    } finally {
      setBusy("");
    }
  };

  const previewWorksheet = () => runAction("preview", async () => {
    const yaml = worksheetYaml.trim();
    if (!yaml) throw new Error("请先粘贴场景工作表 YAML。");
    const payload = await apiPost("/api/v1/interop/preview/bundle-worksheet", { worksheet_yaml: yaml });
    setPreview(payload);
    setPreviewedYaml(yaml);
    setActiveResult(ioResultFromPayload(payload, "preview"));
    if (payload && payload.envelope && payload.envelope.bundle_id) setBundleId(payload.envelope.bundle_id);
    note(`工作表 ${payload && payload.envelope ? payload.envelope.bundle_id : ""} 已通过预览校验。`);
    return payload;
  });

  const importWorksheet = () => runAction("import", async () => {
    const yaml = worksheetYaml.trim();
    if (!canImport || yaml !== previewedYaml) throw new Error("工作表内容已变化，请重新预览后再导入。");
    const payload = await apiPost("/api/v1/interop/import/bundle-worksheet", { worksheet_yaml: yaml });
    const envelope = ioExtractEnvelope(payload);
    setActiveResult(ioResultFromPayload(payload, "import"));
    if (envelope && envelope.bundle_id) setBundleId(envelope.bundle_id);
    ioLogPush({ kind: "worksheet-import", file: (envelope && envelope.bundle_id) || "bundle worksheet" });
    note(`已导入场景工作表 ${envelope && envelope.bundle_id ? envelope.bundle_id : ""}。`);
    return payload;
  });

  const loadInteropResult = (actionId, value, path, mode, logKind, label) => runAction(actionId, async () => {
    const id = String(value || "").trim();
    if (!id) throw new Error(`请先填写${label}。`);
    const payload = await apiGet(`${path}/${encodeURIComponent(id)}`);
    const result = ioResultFromPayload(payload, mode);
    setActiveResult(result);
    if (result.envelope && result.envelope.bundle_id) setBundleId(result.envelope.bundle_id);
    ioLogPush({ kind: logKind, file: id });
    note(`${label} ${id} 已加载。`);
    return payload;
  });

  const downloadEnvelope = () => {
    const envelope = activeResult && activeResult.envelope;
    if (!envelope) return;
    const file = `${envelope.bundle_id || "bundle"} · bundle-worksheet.json`;
    const size = ioDownload(file, JSON.stringify(envelope, null, 2), "application/json;charset=utf-8");
    ioLogPush({ kind: "worksheet-export", file, size });
    note(`已下载「${file}」。JSON 同时也是合法 YAML，可重新粘贴预览。`);
  };

  return (
    <div className="page" data-screen-label="interop" data-testid="interop-center-view">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <div className="page-eyebrow">互操作与导出</div>
            <h1 className="page-title">导出成稿、检查工作表与保存本机快照</h1>
            <p className="page-subtitle">当前作品：《{work.title}》· {totals.planned} 章 · {(totals.words / 10000).toFixed(1)} 万字。正文、场景工作表与浏览器缓存各走独立且明确的边界。</p>
          </div>
        </header>

        <section style={{marginBottom: 28}}>
          <h2 className="text-serif" style={{fontSize:17, margin:"0 0 12px", color:"var(--ink-2)"}}>导出</h2>
          <div className="io-grid">
            <ExportCard
              icon="FileText" tone="crimson"
              title="服务端成稿"
              desc="前往成稿中心逐章核验服务端权威正文，再导出全书或指定章节"
              formats={["Markdown", "TXT", "Word"]}
              actionLabel="前往成稿中心"
              onExport={() => go && go("manuscripts")}
            />
            <ExportCard
              icon="Database" tone="slate"
              title="浏览器缓存快照"
              desc="只保存当前浏览器中属于本作品的缓存键，供诊断或人工取证；不含服务端数据库"
              formats={["JSON"]}
              actionLabel="导出本机快照"
              onExport={() => ioExportCacheSnapshot(note)}
            />
          </div>
        </section>

        <section style={{marginBottom: 28}}>
          <h2 className="text-serif" style={{fontSize:17, margin:"0 0 12px", color:"var(--ink-2)"}}>场景工作表互操作</h2>
          <div className="io-workspace">
            <article className="io-panel">
              <div className="io-panel-head">
                <div>
                  <h3 className="text-serif">预览并导入 bundle worksheet</h3>
                  <p className="text-muted text-sm">粘贴严格的 YAML/JSON 信封。后端先验证结构、哈希与来源引用；只有内容未变化时才允许导入 P0/P1 包。</p>
                </div>
                <span className="pill text-xs">worksheet_yaml</span>
              </div>
              <textarea
                className="io-editor"
                data-testid="interop-worksheet-input"
                aria-label="场景工作表 YAML"
                value={worksheetYaml}
                onChange={(e) => setWorksheetYaml(e.target.value)}
                placeholder="bundle_id: bundle_CH001_SC01"
              />
              <div className="io-actions">
                <button className="btn btn-ghost btn-sm" data-testid="interop-preview-button" disabled={!!busy} onClick={previewWorksheet}>
                  {busy === "preview" ? "预览中…" : "预览工作表"}
                </button>
                <button className="btn btn-accent btn-sm" data-testid="interop-import-button" disabled={!canImport || !!busy} onClick={importWorksheet}>
                  {busy === "import" ? "导入中…" : "导入工作表"}
                </button>
              </div>
              {preview && preview.summary && (
                <div className="io-summary" data-testid="interop-preview-summary">
                  <span><b>包</b> {preview.summary.bundle_id}</span>
                  <span><b>场景</b> {preview.summary.scene_id}</span>
                  <span><b>章节</b> {preview.summary.chapter_id}</span>
                  <span><b>对比项</b> {preview.summary.comparison_count}</span>
                </div>
              )}
            </article>

            <article className="io-panel">
              <div className="io-panel-head">
                <div>
                  <h3 className="text-serif">导出与回放</h3>
                  <p className="text-muted text-sm">按服务端持久化 ID 加载 bundle 信封，或回放终稿/草稿关联的冻结输入。</p>
                </div>
                <span className="pill text-xs">服务端接口</span>
              </div>
              <InteropQuery label="Bundle ID" value={bundleId} onChange={setBundleId} placeholder="bundle_CH001_SC01"
                testId="interop-export-bundle-id" buttonTestId="interop-export-button" buttonLabel={busy === "export" ? "加载中…" : "加载导出结果"}
                disabled={!!busy} onRun={() => loadInteropResult("export", bundleId, "/api/v1/interop/export/bundle-worksheet", "export", "worksheet-load", "Bundle ID")} />
              <InteropQuery label="终稿场景行 ID" value={finalRowId} onChange={setFinalRowId} placeholder="final_scene_CH001_SC01"
                testId="interop-replay-final-row-id" buttonTestId="interop-replay-final-button" buttonLabel={busy === "replay-final" ? "加载中…" : "回放终稿"}
                disabled={!!busy} onRun={() => loadInteropResult("replay-final", finalRowId, "/api/v1/replay/final-scene", "replay-final", "replay-final", "终稿场景行 ID")} />
              <InteropQuery label="草稿行 ID" value={draftRowId} onChange={setDraftRowId} placeholder="draft_scene_CH001_SC01"
                testId="interop-replay-draft-row-id" buttonLabel={busy === "replay-draft" ? "加载中…" : "回放草稿"}
                disabled={!!busy} onRun={() => loadInteropResult("replay-draft", draftRowId, "/api/v1/replay/draft", "replay-draft", "replay-draft", "草稿行 ID")} />
            </article>
          </div>
          {error && <div className="io-error" role="alert">{error}</div>}
        </section>

        {activeResult && activeResult.envelope && (
          <section className="io-result" data-testid="interop-envelope-panel" style={{marginBottom: 28}}>
            <div className="io-panel-head">
              <div>
                <h2 className="text-serif">结果信封</h2>
                <p className="text-muted text-sm">{activeResult.mode} · {activeResult.envelope.bundle_id}</p>
              </div>
              <button className="btn btn-quiet btn-sm" onClick={downloadEnvelope}><I.Download size={13} /> 下载信封 JSON</button>
            </div>
            <div className="io-summary">
              <span><b>场景</b> {activeResult.envelope.scene_id || "—"}</span>
              <span><b>章节</b> {activeResult.envelope.chapter_id || "—"}</span>
              <span><b>模式</b> {activeResult.envelope.execution_mode || "—"}</span>
              <span><b>哈希</b> {activeResult.envelope.bundle_snapshot_hash || "—"}</span>
            </div>
            {activeResult.receipt && <p className="text-muted text-xs">服务端回执：{activeResult.receipt.artifact_id} · {activeResult.receipt.artifact_kind}</p>}
            {!!activeResult.comparisons.length && (
              <div className="io-comparisons">
                {activeResult.comparisons.map((item, i) => (
                  <article className="io-comparison" key={`${item.object_type || "ref"}:${item.lineage_key || i}:${item.source_ref_key || i}`}>
                    <div className="fw-600">{item.object_type || "source"} · {item.lineage_key || item.source_ref_key || "—"}</div>
                    <div className="text-muted text-xs">版本：{item.version_status || "—"} · 文本：{item.text_status || "—"}</div>
                  </article>
                ))}
              </div>
            )}
            <details className="io-details">
              <summary>查看完整信封</summary>
              <pre className="io-json">{JSON.stringify(activeResult.envelope, null, 2)}</pre>
            </details>
          </section>
        )}

        <section style={{marginBottom: 28}}>
          <h2 className="text-serif" style={{fontSize:17, margin:"0 0 12px", color:"var(--ink-2)"}}>备份与恢复边界</h2>
          <div className="io-import">
            <div className="io-import-tips">
              <h3 className="text-serif fw-600 mb-2" style={{fontSize:15}}>完整项目备份</h3>
              <ul className="io-tip-list">
                <li><I.Check size={13} /> 权威作品、章节、正文、审核与运行记录都在服务端数据库</li>
                <li><I.Check size={13} /> 完整备份与恢复必须使用带完整性、外键及 SHA-256 校验的数据库工具</li>
                <li><I.AlertTriangle size={13} className="warn" /> 恢复是停机运维操作，不能在浏览器里用 JSON 覆盖运行库</li>
              </ul>
            </div>
            <div className="io-import-tips">
              <h3 className="text-serif fw-600 mb-2" style={{fontSize:15}}>浏览器缓存快照</h3>
              <ul className="io-tip-list">
                <li><I.Check size={13} /> 可帮助诊断当前设备的界面缓存与未同步恢复记录</li>
                <li><I.AlertTriangle size={13} className="warn" /> 不包含完整服务端数据，也不支持导入成新作品</li>
                <li><I.AlertTriangle size={13} className="warn" /> 不能替代数据库备份、恢复演练或成稿导出</li>
              </ul>
            </div>
          </div>
        </section>

        <section>
          <h2 className="text-serif" style={{fontSize:17, margin:"0 0 12px", color:"var(--ink-2)"}}>最近</h2>
          {recent.length === 0 ? (
            <div className="card" style={{ padding: "28px 24px", textAlign: "center", color: "var(--ink-3)", fontSize: 13 }}>
              还没有互操作或本机快照记录。
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
                      <td className="text-muted text-sm">{it.at ? agoLabel(it.at) : "—"}</td>
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

function InteropQuery({ label, value, onChange, placeholder, testId, buttonTestId, buttonLabel, disabled, onRun }) {
  return (
    <div className="io-query-row">
      <label>
        <span>{label}</span>
        <input className="control-input" data-testid={testId} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      </label>
      <button className="btn btn-ghost btn-sm" data-testid={buttonTestId} disabled={disabled || !String(value || "").trim()} onClick={onRun}>{buttonLabel}</button>
    </div>
  );
}

function ExportCard({ icon, tone, title, desc, formats, actionLabel = "导出", onExport }) {
  const Ic = I[icon] || I.Dot;
  return (
    <div className={`io-card tone-${tone}`}>
      <div className="io-card-icon"><Ic size={20} /></div>
      <h3 className="io-card-title text-serif">{title}</h3>
      <p className="io-card-desc text-muted">{desc}</p>
      <div className="io-card-formats">
        {formats.map(f => <span key={f} className="pill text-xs">{f}</span>)}
      </div>
      <button className="btn btn-quiet btn-sm io-card-btn" onClick={onExport}>{actionLabel} <I.ArrowRight size={13} /></button>
    </div>
  );
}

function IoKind({ k }) {
  const map = {
    "cache-export": { tone: "slate", label: "缓存快照" },
    "worksheet-import": { tone: "sage", label: "工作表导入" },
    "worksheet-export": { tone: "crimson", label: "信封下载" },
    "worksheet-load": { tone: "crimson", label: "信封加载" },
    "replay-final": { tone: "gold", label: "终稿回放" },
    "replay-draft": { tone: "gold", label: "草稿回放" },
    export: { tone: "crimson", label: "旧版导出" },
    import: { tone: "slate", label: "旧版导入" },
  };
  const m = map[k] || { tone: "slate", label: "记录" };
  return <span className={`pill pill-${m.tone} text-xs`}><span className="pill-dot" />{m.label}</span>;
}

export { WsIndex, WsInterop, ioBuildCacheSnapshot, ioExtractEnvelope, ioResultFromPayload };
