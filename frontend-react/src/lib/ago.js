/* 相对时间文案：毫秒时间戳 → 「刚刚 / N 分钟前 / N 小时前 / N 天前」。
   不做入参守卫（undefined 会得到 NaN 文案）——需要兜底的调用方
   自行在调用点补 `|| 0` 之类的前置守卫。 */
export function agoLabel(t) {
  const m = Math.floor((Date.now() - t) / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return m + " 分钟前";
  const h = Math.floor(m / 60);
  if (h < 24) return h + " 小时前";
  return Math.floor(h / 24) + " 天前";
}

/* 天级绝对时间文案：ISO 串或时间戳 → 今天「今天 HH:MM」、跨天「M 月 D 日 HH:MM」。
   非法入参返回空串——需要占位符的调用方自行在调用点补 `|| "—"`。 */
export function dayTimeLabel(t) {
  try {
    const d = new Date(t);
    if (isNaN(d.getTime())) return "";
    const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    return d.toDateString() === new Date().toDateString() ? `今天 ${hm}` : `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${hm}`;
  } catch (e) { return ""; }
}
