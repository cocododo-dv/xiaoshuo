import React from "react";

const CANONICAL_LABELS = {
  unknown: "权威正文状态待确认",
  dirty: "权威正文待更新",
  promoting: "正在提升权威正文…",
  current: "权威正文已更新",
  reconcile: "需先核对事实变更",
  error: "权威正文提升失败",
};

function WrCanonicalControl({ saveStatus, canonicalStatus, disabled = false, onPromote }) {
  const status = CANONICAL_LABELS[canonicalStatus] ? canonicalStatus : "unknown";
  const busy = status === "promoting";
  const saveFailed = saveStatus === "草稿保存失败";
  const promotionDisabled = disabled || busy || status === "unknown" || status === "current";
  return (
    <div className="wr-publish-state" aria-label="草稿与权威正文状态">
      <span className={`wr-save ${saveStatus === "草稿已保存" ? "" : "saving"} ${saveFailed ? "is-error" : ""}`} data-testid="draft-save-status">
        <span className="wr-save-dot" />{saveStatus}
      </span>
      <span className={`wr-canonical-state is-${status}`} data-testid="canonical-status">
        {CANONICAL_LABELS[status]}
      </span>
      <button
        type="button"
        className="wr-canonical-promote"
        disabled={promotionDisabled}
        onClick={onPromote}
        title="仅在本次修改不改变故事事实时，将已保存草稿提升为运行时权威正文"
      >
        {busy ? "提升中…" : "提升为权威正文"}
      </button>
    </div>
  );
}

export { CANONICAL_LABELS, WrCanonicalControl };
