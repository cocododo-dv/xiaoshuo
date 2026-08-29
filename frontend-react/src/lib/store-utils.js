import React from "react";

/* ==========================================================
   store-utils — store 层三类样板的机械收敛（行为等价，无新语义）
   · createSubscribers()：Set 订阅者 + 吞异常广播
   · useStoreTick(subscribe)：force-render hook 内核
   · storeAlert(error, fallback)：try/alert/catch 失败提示
   注意：各 store 的 CustomEvent 双通道广播（ws:work-changed 等）
   不在此收敛，仍留在各自 notify 内。
   ========================================================== */

/* 订阅者集合：subscribe(fn) 加入并返回退订函数；notify() 逐个调用，
   单个订阅者抛错被吞掉，不阻断其余订阅者与后续流程。 */
export function createSubscribers() {
  const subs = new Set();
  return {
    subscribe(fn) { subs.add(fn); return () => subs.delete(fn); },
    notify() { subs.forEach((fn) => { try { fn(); } catch (e) {} }); },
  };
}

/* force-render hook 内核：挂载时 subscribe(tick)，每次通知触发重渲；
   subscribe 返回退订函数（或 undefined）作为 effect 清理。 */
export function useStoreTick(subscribe) {
  const [, force] = React.useState(0);
  React.useEffect(() => subscribe(() => force((n) => n + 1)), []);
}

/* 失败提示样板：alert((error && error.message) || fallback)；
   error 传 null 即固定文案。alert 不可用（无头环境等）时静默。 */
export function storeAlert(error, fallback) {
  try { window.alert((error && error.message) || fallback); } catch (e) {}
}
