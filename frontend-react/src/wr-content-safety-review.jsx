import React from "react";
import ReactDOM from "react-dom";
import { I } from "./icons.jsx";

const { useEffect, useMemo, useRef, useState } = React;

function exactFindingCode(value) {
  return typeof value === "string"
    && value.length > 0
    && value.length <= 128
    && value === value.trim()
    ? value
    : null;
}

// 只读取后端 CONTENT_SAFETY_REVIEW_REQUIRED 信封中的原始 finding code。
// 不接受 blocker 前缀、warning issue_key 或客户端自造值，避免把普通警告扩成绕过令牌。
function contentSafetyReviewFromError(error) {
  if (!error || error.code !== "CONTENT_SAFETY_REVIEW_REQUIRED") return null;
  const gate = error.details && error.details.final_text_gate;
  const safety = gate && gate.content_safety;
  const raw = safety && Array.isArray(safety.findings) ? safety.findings : [];
  const seen = new Set();
  const findings = raw.flatMap((finding) => {
    if (!finding || finding.review_required !== true || finding.acknowledged === true) return [];
    const code = exactFindingCode(finding.code);
    if (!code || seen.has(code)) return [];
    seen.add(code);
    return [{
      code,
      severity: typeof finding.severity === "string" ? finding.severity : "unknown",
      confidence: typeof finding.confidence === "string" ? finding.confidence : "heuristic",
      message: typeof finding.message === "string" && finding.message.trim()
        ? finding.message.trim()
        : "该内容风险需要作者人工核对。",
      evidenceTerms: Array.isArray(finding.evidence_terms)
        ? finding.evidence_terms.filter(term => typeof term === "string" && term.trim()).map(term => term.trim()).slice(0, 8)
        : [],
    }];
  });
  if (!findings.length) return null;
  return {
    findings,
    limitations: Array.isArray(safety.limitations)
      ? safety.limitations.filter(item => typeof item === "string" && item.trim()).map(item => item.trim()).slice(0, 4)
      : [],
  };
}

function focusable(root) {
  if (!root) return [];
  return [...root.querySelectorAll('button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')];
}

function ContentSafetyReviewDialog({ review, busy = false, error = "", onCancel, onConfirm }) {
  const [checked, setChecked] = useState(() => new Set());
  const dialogRef = useRef(null);
  const cancelRef = useRef(null);
  const previousFocus = useRef(null);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const findings = (review && review.findings) || [];
  useEffect(() => { setChecked(new Set()); }, [review]);

  useEffect(() => {
    previousFocus.current = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    requestAnimationFrame(() => cancelRef.current?.focus());
    const onKey = (event) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        onCancel();
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
      previousFocus.current?.focus?.();
    };
  }, []);

  const acceptedCodes = useMemo(
    () => findings.filter(item => checked.has(item.code)).map(item => item.code),
    [checked, findings],
  );
  const allConfirmed = findings.length > 0 && acceptedCodes.length === findings.length;
  const toggle = (code) => {
    if (busy) return;
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code); else next.add(code);
      return next;
    });
  };

  const node = (
    <div className="wr-safety-scrim" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onCancel();
    }}>
      <section
        ref={dialogRef}
        className="wr-safety-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="wr-safety-title"
        aria-describedby="wr-safety-desc"
      >
        <header className="wr-safety-head">
          <span className="wr-safety-shield" aria-hidden="true"><I.ShieldCheck size={19} /></span>
          <div>
            <div className="wr-safety-eyebrow">AUTHOR REVIEW · 内容风险复核</div>
            <h2 id="wr-safety-title">提升前需要你逐项核对</h2>
            <p id="wr-safety-desc">这是启发式提醒，不是自动判决。系统不会替你勾选，也不会在未确认时提升正文。</p>
          </div>
          <button ref={cancelRef} type="button" className="wr-safety-close" onClick={onCancel} disabled={busy} aria-label="取消内容风险确认"><I.X size={18} /></button>
        </header>

        <div className="wr-safety-findings" aria-label="需要作者确认的内容风险">
          {findings.map((finding, index) => (
            <label className={`wr-safety-finding ${checked.has(finding.code) ? "is-checked" : ""}`} key={finding.code}>
              <input
                type="checkbox"
                checked={checked.has(finding.code)}
                onChange={() => toggle(finding.code)}
                disabled={busy}
                aria-describedby={`wr-safety-finding-${index}`}
              />
              <span className="wr-safety-check" aria-hidden="true"><I.Check size={13} /></span>
              <span className="wr-safety-copy" id={`wr-safety-finding-${index}`}>
                <span className="wr-safety-finding-top"><strong>需人工复核</strong><code>{finding.code}</code></span>
                <span className="wr-safety-message">{finding.message}</span>
                {finding.evidenceTerms.length > 0 && (
                  <span className="wr-safety-evidence"><b>命中词</b>{finding.evidenceTerms.map(term => <em key={term}>{term}</em>)}</span>
                )}
                <small>严重度 {finding.severity} · 置信方式 {finding.confidence}</small>
              </span>
            </label>
          ))}
        </div>

        {(review.limitations || []).length > 0 && (
          <details className="wr-safety-limits">
            <summary>这类启发式有哪些盲区</summary>
            <ul>{review.limitations.map(item => <li key={item}>{item}</li>)}</ul>
          </details>
        )}

        <footer className="wr-safety-foot">
          <div className="wr-safety-progress" role="status" aria-live="polite">
            已核对 {acceptedCodes.length} / {findings.length} 项
            {error && <span role="alert">{error}</span>}
          </div>
          <button type="button" className="btn btn-quiet" onClick={onCancel} disabled={busy}>返回修改</button>
          <button
            type="button"
            className="btn btn-accent"
            disabled={!allConfirmed || busy}
            onClick={() => onConfirm(findings.map(item => item.code))}
            data-testid="content-safety-confirm"
          >
            <I.CheckCircle size={14} /> {busy ? "正在重新校验…" : "逐项确认并重试提升"}
          </button>
        </footer>
      </section>
    </div>
  );
  return ReactDOM.createPortal(node, document.body);
}

export { ContentSafetyReviewDialog, contentSafetyReviewFromError };
