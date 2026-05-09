import { onBeforeUnmount, ref } from "vue";

const NOTICE_TTL_MS = 10000;
const NOTICE_LIMIT = 3;

function formatNotice(message) {
  if (!message) {
    return "";
  }
  const text = String(message).trim();
  if (text.startsWith("profile ready")) {
    return "参考书画像已生成。下一步：选择应用范围，并创建审核项。";
  }
  if (text.startsWith("started ")) {
    return "学习任务已启动。下一步：点击「继续分析」生成候选卡。";
  }
  if (text.startsWith("round ") && text.includes("waiting for review")) {
    return "新一轮候选卡已生成，请审核下方卡片。";
  }
  return text.length > 180 ? `${text.slice(0, 177)}...` : text;
}

function noticeKind(message) {
  const text = String(message || "");
  if (
    text.includes("已移入作者回收站")
    || text.includes("已恢复")
    || text.includes("已彻底清理")
    || text.toLowerCase().includes("trash")
    || text.toLowerCase().includes("restore")
    || text.toLowerCase().includes("purge")
  ) {
    return "trash";
  }
  return text;
}

export function useNotices() {
  const notices = ref([]);
  const timers = new Map();

  function removeNotice(id) {
    const timer = timers.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.delete(id);
    }
    notices.value = notices.value.filter((n) => n.id !== id);
  }

  function pushNotice(message) {
    const text = formatNotice(message);
    if (!text) {
      return;
    }
    const kind = noticeKind(text);
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    notices.value
      .filter((n) => n.message === text || n.kind === kind)
      .forEach((n) => removeNotice(n.id));
    const nextNotices = [{ id, kind, message: text, createdAt: Date.now() }, ...notices.value];
    nextNotices.slice(NOTICE_LIMIT).forEach((n) => removeNotice(n.id));
    notices.value = nextNotices.slice(0, NOTICE_LIMIT);
    timers.set(
      id,
      setTimeout(() => {
        removeNotice(id);
      }, NOTICE_TTL_MS),
    );
  }

  onBeforeUnmount(() => {
    timers.forEach((timer) => clearTimeout(timer));
    timers.clear();
  });

  return { notices, pushNotice, removeNotice };
}
