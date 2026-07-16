import React from "react";
import ReactDOMClient from "react-dom/client";
import { I } from "./icons.jsx";
import { WrRecovery } from "./wr-doc-store.jsx";

const { useEffect, useMemo, useRef, useState } = React;

const TYPE_LABEL = {
  conflict: "冲突副本",
  unsynced: "未同步稿",
  backup: "覆盖前备份",
  candidate: "AI 候选",
};

function plainText(html) {
  const node = document.createElement("div");
  node.innerHTML = html || "";
  return (node.textContent || "").trim();
}

function formatTime(value) {
  if (!value) return "时间未知";
  try {
    return new Date(value).toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return "时间未知"; }
}

function focusable(root) {
  if (!root) return [];
  return [...root.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )].filter((node) => !node.hidden && node.getAttribute("aria-hidden") !== "true");
}

async function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch (e) {
      // 权限策略可能拒绝异步剪贴板；保留传统选择复制作为降级路径。
    }
  }
  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  field.style.position = "fixed";
  field.style.opacity = "0";
  document.body.appendChild(field);
  field.select();
  const copied = document.execCommand && document.execCommand("copy");
  field.remove();
  if (!copied) throw new Error("浏览器拒绝了剪贴板权限，请改用导出");
}

function exportEntry(entry) {
  const text = plainText(entry.html || "");
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(entry.sid || "恢复稿").replace(/[^\w\u4e00-\u9fa5-]/g, "-")}-${entry.createdAt || Date.now()}.txt`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function RecoveryDiff({ diff }) {
  if (!diff) return <div className="wrr-empty-detail">选择左侧记录查看正文与差异。</div>;
  if (!diff.adds && !diff.dels) {
    return <div className="wrr-same"><I.CheckCircle size={16} /> 这份记录与当前本地草稿内容一致。</div>;
  }
  return (
    <div className="wrr-diff" aria-label="恢复稿与当前草稿差异">
      <div className="wrr-diff-key">
        <span><i className="is-del" /> 当前草稿中将被替换的内容</span>
        <span><i className="is-add" /> 恢复稿中将写入的内容</span>
      </div>
      {diff.paras.map((para, index) => (
        <p key={`${para.p}-${index}`}>
          {para.segs.map((seg, segIndex) => (
            <span key={`${seg.t}-${segIndex}`} className={`is-${seg.t}`}>{seg.text}</span>
          ))}
        </p>
      ))}
    </div>
  );
}

function WrRecoveryCenter() {
  const [open, setOpen] = useState(false);
  const [entries, setEntries] = useState(() => WrRecovery.list());
  const [selectedId, setSelectedId] = useState(() => (entries[0] && entries[0].id) || null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const triggerRef = useRef(null);
  const dialogRef = useRef(null);
  const closeRef = useRef(null);
  const shouldReturnFocus = useRef(false);

  const refresh = () => {
    const next = WrRecovery.list();
    setEntries(next);
    setSelectedId((current) => next.some(item => item.id === current) ? current : ((next[0] && next[0].id) || null));
  };

  useEffect(() => {
    const onChange = () => refresh();
    window.addEventListener("ws:recovery-changed", onChange);
    return () => window.removeEventListener("ws:recovery-changed", onChange);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(() => (closeRef.current || dialogRef.current)?.focus());
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = focusable(dialogRef.current);
      if (!nodes.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  useEffect(() => {
    if (open) {
      shouldReturnFocus.current = true;
      return;
    }
    if (shouldReturnFocus.current) {
      shouldReturnFocus.current = false;
      triggerRef.current?.focus();
    }
  }, [open]);

  const selected = entries.find(item => item.id === selectedId) || null;
  const diff = useMemo(() => selected ? WrRecovery.diff(selected.id) : null, [selected, entries]);
  const volatileCount = entries.filter(item => item.durable === false).length;

  const run = async (kind, action) => {
    if (!selected || busy) return;
    setBusy(kind);
    setMessage("");
    try {
      await action();
      refresh();
      setMessage(kind === "retry" ? "已同步到服务端，并移出恢复列表。" : "已恢复为当前草稿并同步到服务端。恢复记录仍保留，确认无误后可删除。");
    } catch (error) {
      setMessage(`操作未完成：${(error && error.message) || "请检查网络后重试"}`);
    } finally { setBusy(""); }
  };

  const restore = () => {
    if (!selected) return;
    if (!window.confirm(`把“${selected.label}”恢复为当前草稿并同步到服务端？\n当前草稿若不同，系统会先自动留下可撤销备份。`)) return;
    void run("restore", () => WrRecovery.restore(selected.id));
  };
  const retry = () => {
    if (!selected) return;
    if (!window.confirm("用这份记录重试同步？同步成功后，它会从恢复列表移除。")) return;
    void run("retry", () => WrRecovery.retry(selected.id));
  };
  const remove = () => {
    if (!selected || !window.confirm("永久删除这份本地恢复记录？删除后无法撤销。")) return;
    WrRecovery.remove(selected.id);
    setMessage("恢复记录已删除。");
    refresh();
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className={`wrr-trigger ${entries.length ? "has-items" : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`打开同步与恢复中心${entries.length ? `，有 ${entries.length} 份恢复记录` : ""}`}
        onClick={() => setOpen(true)}
      >
        <span className="wrr-trigger-stitch" aria-hidden="true" />
        <I.Save size={15} />
        <span>同步与恢复</span>
        {entries.length > 0 && <b>{entries.length}</b>}
      </button>

      {open && (
        <div className="wrr-scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
          <section
            ref={dialogRef}
            className="wrr-panel"
            role="dialog"
            aria-modal="true"
            aria-labelledby="wrr-title"
            tabIndex={-1}
          >
            <header className="wrr-head">
              <div className="wrr-seal" aria-hidden="true"><I.Save size={19} /></div>
              <div>
                <div className="wrr-eyebrow">LOCAL PROOF DESK · 本地校样台</div>
                <h2 id="wrr-title">同步与恢复中心</h2>
                <p>冲突、断网和覆盖前的稿件都留在这里；先比较，再决定。</p>
              </div>
              <button ref={closeRef} type="button" className="wrr-close" onClick={() => setOpen(false)} aria-label="关闭同步与恢复中心"><I.X size={18} /></button>
            </header>

            {volatileCount > 0 && (
              <div className="wrr-warning" role="alert">
                <I.AlertTriangle size={15} /> {volatileCount} 份记录因浏览器空间不足仅保留在本次会话。请立即复制或导出，刷新页面后它们会消失。
              </div>
            )}

            <div className="wrr-body">
              <aside className="wrr-list" aria-label="恢复记录">
                <div className="wrr-list-head"><span>待处理校样</span><b>{entries.length}</b></div>
                {entries.length === 0 ? (
                  <div className="wrr-empty"><I.CheckCircle size={20} /><strong>没有待恢复稿件</strong><span>本地草稿与服务端目前没有已知冲突。</span></div>
                ) : entries.map((entry) => {
                  const preview = plainText(entry.html || "").slice(0, 54);
                  return (
                    <button
                      type="button"
                      key={entry.id}
                      className={`wrr-row ${selectedId === entry.id ? "is-active" : ""}`}
                      onClick={() => { setSelectedId(entry.id); setMessage(""); }}
                      aria-pressed={selectedId === entry.id}
                    >
                      <span className={`wrr-type is-${entry.type || "conflict"}`}>{TYPE_LABEL[entry.type] || "恢复稿"}</span>
                      <strong>{entry.label || entry.sid || "未命名稿件"}</strong>
                      <span className="wrr-row-meta">{formatTime(entry.createdAt)} · {entry.workId || "当前作品"}</span>
                      <span className="wrr-row-preview">{preview || "（空白稿件）"}</span>
                      {!entry.durable && <span className="wrr-volatile">仅本次会话</span>}
                    </button>
                  );
                })}
              </aside>

              <main className="wrr-detail">
                {selected ? (
                  <>
                    <div className="wrr-detail-head">
                      <div>
                        <span className="wrr-detail-kicker">{TYPE_LABEL[selected.type] || "恢复稿"} · {selected.sid || "未知对象"}</span>
                        <h3>{selected.label}</h3>
                        <p>{selected.reason || "系统在可能丢稿前留下的本地副本。"}</p>
                      </div>
                      <div className="wrr-delta" aria-label={`新增 ${diff ? diff.adds : 0} 句，替换 ${diff ? diff.dels : 0} 句`}>
                        <span className="is-add">+{diff ? diff.adds : 0}</span>
                        <span className="is-del">−{diff ? diff.dels : 0}</span>
                      </div>
                    </div>
                    <RecoveryDiff diff={diff} />
                    <div className="wrr-actions" role="group" aria-label="恢复操作">
                      <button type="button" className="btn btn-accent" onClick={restore} disabled={!!busy}>
                        <I.Refresh size={14} /> {busy === "restore" ? "恢复中…" : "恢复为当前草稿"}
                      </button>
                      <button type="button" className="btn btn-primary" onClick={retry} disabled={!!busy}>
                        <I.UploadCloud size={14} /> {busy === "retry" ? "同步中…" : "重试同步"}
                      </button>
                      <button type="button" className="btn btn-ghost" onClick={async () => {
                        try {
                          await copyText(plainText(selected.html || ""));
                          setMessage("正文已复制到剪贴板。");
                        } catch (error) { setMessage((error && error.message) || "复制失败，请改用导出"); }
                      }}>
                        <I.FileText size={14} /> 复制正文
                      </button>
                      <button type="button" className="btn btn-ghost" onClick={() => { exportEntry(selected); setMessage("已导出为纯文本文件。"); }}>
                        <I.Download size={14} /> 导出
                      </button>
                      <button type="button" className="btn btn-quiet wrr-delete" onClick={remove}><I.Trash size={14} /> 删除</button>
                    </div>
                  </>
                ) : <div className="wrr-empty-detail"><I.FileText size={23} />没有恢复记录时，这里会保持安静。</div>}
                <div className="wrr-live" role="status" aria-live="polite">{message}</div>
              </main>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

function mountWrRecoveryCenter() {
  let host = document.getElementById("wr-recovery-root");
  if (!host) {
    host = document.createElement("div");
    host.id = "wr-recovery-root";
    document.body.appendChild(host);
  }
  if (!host.__root) host.__root = ReactDOMClient.createRoot(host);
  host.__root.render(<WrRecoveryCenter />);
  return host.__root;
}

export { WrRecoveryCenter, mountWrRecoveryCenter };
