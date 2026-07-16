/**
 * WAI-ARIA tabs 的通用键盘行为：方向键移动并激活，Home/End 跳首尾。
 * 组件只需维护 aria-selected/tabIndex；这里按当前 tablist 的真实 DOM 顺序工作。
 */
function onRovingTabKeyDown(event) {
  const keys = ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"];
  if (!keys.includes(event.key)) return;
  const list = event.currentTarget && event.currentTarget.closest('[role="tablist"]');
  if (!list) return;
  const tabs = Array.from(list.querySelectorAll('[role="tab"]')).filter((tab) => !tab.disabled);
  if (!tabs.length) return;
  const current = Math.max(0, tabs.indexOf(event.currentTarget));
  let next = current;
  if (event.key === "Home") next = 0;
  else if (event.key === "End") next = tabs.length - 1;
  else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (current - 1 + tabs.length) % tabs.length;
  else next = (current + 1) % tabs.length;
  event.preventDefault();
  tabs[next].focus();
  tabs[next].click();
}

export { onRovingTabKeyDown };
