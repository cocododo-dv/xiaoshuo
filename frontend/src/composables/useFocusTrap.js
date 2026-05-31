// PR-21 a11y — 抽自 ProfileApplyDialog(PR-17):dialog 内 Tab/Shift+Tab 循环捕获,焦点不逃逸。
//
// 用法:传入 dialog 容器的 template ref,模板上挂 `@keydown.tab="onTab"`。
// 仅封装 Tab 循环;esc 关闭与 open 初始聚焦由各 dialog 自留(对既有行为零回归)。
//
//   const dialogEl = ref(null);
//   const { onTab } = useFocusTrap(dialogEl);
//   <div ref="dialogEl" tabindex="-1" @keydown.tab="onTab"> ... </div>

// 排除 tabindex=-1(含 roving 未选中的 radio),保证 Tab 序列与浏览器一致。
const FOCUSABLE_SELECTOR = [
  'button:not([disabled]):not([tabindex="-1"])',
  'select:not([disabled]):not([tabindex="-1"])',
  'input:not([disabled]):not([tabindex="-1"])',
  'textarea:not([disabled]):not([tabindex="-1"])',
  'a[href]:not([tabindex="-1"])',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export function useFocusTrap(dialogElRef) {
  function getFocusable() {
    const root = dialogElRef.value;
    if (!root) return [];
    return Array.from(root.querySelectorAll(FOCUSABLE_SELECTOR));
  }

  function onTab(e) {
    const items = getFocusable();
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return { getFocusable, onTab };
}
