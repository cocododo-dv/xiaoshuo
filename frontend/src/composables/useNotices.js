import { onBeforeUnmount, ref } from "vue";

const NOTICE_TTL_MS = 10000;
const NOTICE_LIMIT = 3;
const VALID_LEVELS = new Set(["success", "info", "warning", "error"]);

// Pass messages through verbatim. Backends/stores already emit human-readable
// (Chinese) copy; the previous hardcoded English→Chinese rewrites guessed at
// meaning and drifted from the source, so they were removed. We only trim and
// cap pathologically long strings.
function formatNotice(message) {
  if (!message) {
    return "";
  }
  const text = String(message).trim();
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

function inferLevel(text) {
  if (/失败|无法|错误|出错|异常|error|failed/i.test(text)) {
    return "error";
  }
  return "info";
}

// Accepts either a plain string (legacy callers: emit("notice", "...")) or a
// structured payload { message, level|type, kicker }. Many view callers (e.g.
// SnowflakeWorkbenchView) emit { type: "success", ... }, so `type` is honored
// as an alias for `level`. Strings / unknown levels fall back to inferLevel.
function normalizeInput(input) {
  if (input && typeof input === "object" && !Array.isArray(input)) {
    const message = formatNotice(input.message);
    const requestedLevel = input.level ?? input.type;
    const level = VALID_LEVELS.has(requestedLevel) ? requestedLevel : inferLevel(message);
    return { message, level, kicker: input.kicker ? String(input.kicker) : "" };
  }
  const message = formatNotice(input);
  return { message, level: inferLevel(message), kicker: "" };
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

  function pushNotice(input) {
    const { message, level, kicker } = normalizeInput(input);
    if (!message) {
      return;
    }
    const kind = noticeKind(message);
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    notices.value
      .filter((n) => n.message === message || n.kind === kind)
      .forEach((n) => removeNotice(n.id));
    const nextNotices = [{ id, kind, level, kicker, message, createdAt: Date.now() }, ...notices.value];
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
