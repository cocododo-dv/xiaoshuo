import React from "react";

/* ==========================================================
   UndoToast — 删除类动作的统一回执
   ----------------------------------------------------------
   删除的交互难点从来不是「怎么删」，而是「删完之后东西去哪了」。
   原来三个视图删完一片安静，作者只能靠猜；确认弹窗又只在动手前出现，
   帮不上事后的忙。这里给一条统一回执：说清删了几条、去了哪儿，
   并把「撤销 / 打开回收站」放在手边。

   两种回执：
   · 可撤销（起草台移出队列这类纯本地动作）→ 给「撤销」，点了立刻还原；
   · 不可即时撤销（章/场软删，需要服务端 restore）→ 给「打开回收站」，
     诚实地把恢复入口指出来，不假装一键还原。
   ========================================================== */

const TOAST_MS = 6000;

export function useUndoToast() {
  const [toast, setToast] = React.useState(null);
  const timerRef = React.useRef(null);
  const clear = React.useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
    setToast(null);
  }, []);
  /* show({ text, actionLabel, onAction, tone }) —— onAction 执行后回执自动收起 */
  const show = React.useCallback((next) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setToast(next ? { ...next, key: Date.now() } : null);
    if (next) timerRef.current = setTimeout(() => setToast(null), next.timeout || TOAST_MS);
  }, []);
  React.useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);
  return { toast, show, clear };
}

export function UndoToast({ toast, onClose }) {
  if (!toast) return null;
  return (
    <div className={`ws-toast tone-${toast.tone || "neutral"}`} role="status" aria-live="polite" data-testid="undo-toast">
      <span className="ws-toast-text">{toast.text}</span>
      {toast.actionLabel && (
        <button className="ws-toast-action" data-testid="undo-toast-action"
          onClick={() => { if (toast.onAction) toast.onAction(); if (onClose) onClose(); }}>
          {toast.actionLabel}
        </button>
      )}
      <button className="ws-toast-x" aria-label="关闭提示" onClick={onClose}>×</button>
    </div>
  );
}

export default UndoToast;
