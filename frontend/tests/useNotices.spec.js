// @vitest-environment jsdom

import { readFileSync } from "node:fs";
import path from "node:path";

import { createApp } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNotices } from "../src/composables/useNotices.js";

const SOURCE_ROOT = process.cwd();

let activeApp = null;

// useNotices registers onBeforeUnmount, so it must run inside a component
// setup() for the timer-cleanup path to be exercised (and to avoid Vue's
// "no active instance" warning). This harness mounts a throwaway component
// and hands back the composable API plus an explicit unmount.
function mountNotices() {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  let api;
  const app = createApp({
    setup() {
      api = useNotices();
      return () => null;
    },
  });
  app.mount(document.createElement("div"));
  activeApp = app;
  return {
    api,
    unmount() {
      app.unmount();
      if (activeApp === app) {
        activeApp = null;
      }
    },
  };
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("useNotices", () => {
  it("passes plain strings through verbatim and infers the info level", () => {
    const { api } = mountNotices();
    api.pushNotice("草稿已保存");

    expect(api.notices.value).toHaveLength(1);
    const notice = api.notices.value[0];
    expect(notice.message).toBe("草稿已保存");
    expect(notice.level).toBe("info");
    expect(notice.kicker).toBe("");
    expect(notice.kind).toBe("草稿已保存");
    expect(notice).toHaveProperty("id");
    expect(notice).toHaveProperty("createdAt");
  });

  it("infers the error level from failure keywords (zh + en, case-insensitive)", () => {
    const { api } = mountNotices();
    const errorCases = ["保存失败", "无法连接服务", "出现错误", "解析异常", "出错了", "Request failed", "ERROR occurred"];
    for (const message of errorCases) {
      api.pushNotice(message);
      expect(api.notices.value[0].level, message).toBe("error");
    }
    for (const message of ["一切正常", "操作成功"]) {
      api.pushNotice(message);
      expect(api.notices.value[0].level, message).toBe("info");
    }
  });

  it("honors structured level/type, validates unknown levels, and coerces kicker", () => {
    const { api } = mountNotices();

    api.pushNotice({ message: "结构已确认", level: "success" });
    expect(api.notices.value[0].level).toBe("success");

    api.pushNotice({ message: "已应用风格", type: "success" });
    expect(api.notices.value[0].level).toBe("success");

    api.pushNotice({ message: "请注意配额", level: "warning" });
    expect(api.notices.value[0].level).toBe("warning");

    api.pushNotice({ message: "普通提示", level: "bogus" });
    expect(api.notices.value[0].level).toBe("info");

    api.pushNotice({ message: "读取失败", level: "nope" });
    expect(api.notices.value[0].level).toBe("error");

    api.pushNotice({ message: "带提要", level: "info", kicker: 7 });
    expect(api.notices.value[0].kicker).toBe("7");

    api.pushNotice({ message: "无提要", level: "info" });
    expect(api.notices.value[0].kicker).toBe("");
  });

  it("ignores empty, blank, or falsy messages", () => {
    const { api } = mountNotices();
    api.pushNotice("");
    api.pushNotice(null);
    api.pushNotice(undefined);
    api.pushNotice({ message: "" });
    api.pushNotice({ message: "   " });
    expect(api.notices.value).toHaveLength(0);
  });

  it("trims and truncates pathologically long messages", () => {
    const { api } = mountNotices();

    api.pushNotice("   带空白   ");
    expect(api.notices.value[0].message).toBe("带空白");

    api.pushNotice("y".repeat(180));
    expect(api.notices.value[0].message).toBe("y".repeat(180));

    api.pushNotice("z".repeat(181));
    expect(api.notices.value[0].message).toBe(`${"z".repeat(177)}...`);

    api.pushNotice("x".repeat(200));
    const truncated = api.notices.value[0].message;
    expect(truncated).toHaveLength(180);
    expect(truncated.endsWith("...")).toBe(true);
    expect(truncated).toBe(`${"x".repeat(177)}...`);
  });

  it("deduplicates by identical message", () => {
    const { api } = mountNotices();
    api.pushNotice("重复消息");
    api.pushNotice("重复消息");
    expect(api.notices.value).toHaveLength(1);
  });

  it("deduplicates trash-family notices by shared kind but keeps distinct messages", () => {
    const { api } = mountNotices();

    api.pushNotice("已移入作者回收站");
    expect(api.notices.value).toHaveLength(1);
    expect(api.notices.value[0].kind).toBe("trash");

    api.pushNotice("已恢复");
    expect(api.notices.value).toHaveLength(1);
    expect(api.notices.value[0].message).toBe("已恢复");

    api.pushNotice("scene purge done");
    expect(api.notices.value).toHaveLength(1);
    expect(api.notices.value[0].message).toBe("scene purge done");

    const fresh = mountNotices();
    fresh.api.pushNotice("甲消息");
    fresh.api.pushNotice("乙消息");
    expect(fresh.api.notices.value).toHaveLength(2);
    expect(fresh.api.notices.value.map((n) => n.message)).toEqual(["乙消息", "甲消息"]);
  });

  it("caps the stack at NOTICE_LIMIT (3), newest first, dropping the oldest", () => {
    const { api } = mountNotices();
    api.pushNotice("m1");
    api.pushNotice("m2");
    api.pushNotice("m3");
    api.pushNotice("m4");

    const messages = api.notices.value.map((n) => n.message);
    expect(api.notices.value).toHaveLength(3);
    expect(messages).toEqual(["m4", "m3", "m2"]);
    expect(messages).not.toContain("m1");
  });

  it("auto-removes a notice once the TTL elapses", () => {
    const { api } = mountNotices();
    api.pushNotice("会过期的提示");
    expect(api.notices.value).toHaveLength(1);

    vi.advanceTimersByTime(9999);
    expect(api.notices.value).toHaveLength(1);

    vi.advanceTimersByTime(1);
    expect(api.notices.value).toHaveLength(0);
  });

  it("removeNotice removes the notice and clears its pending timer", () => {
    const { api } = mountNotices();
    api.pushNotice("手动移除");
    const { id } = api.notices.value[0];

    api.removeNotice(id);
    expect(api.notices.value).toHaveLength(0);

    expect(() => vi.advanceTimersByTime(10000)).not.toThrow();
    expect(api.notices.value).toHaveLength(0);
  });

  it("clears pending timers on unmount so notices never auto-remove afterwards", () => {
    const { api, unmount } = mountNotices();
    api.pushNotice("挂载期内的提示");
    expect(api.notices.value).toHaveLength(1);

    unmount();
    vi.advanceTimersByTime(10000);

    // Timer was cleared in onBeforeUnmount, so the captured ref is untouched.
    expect(api.notices.value).toHaveLength(1);
  });

  it("App.vue wires notice level into class, role, aria-live, and renders the kicker", () => {
    const src = readFileSync(path.join(SOURCE_ROOT, "src/App.vue"), "utf8");
    expect(src).toContain("notice-${notice.level || 'info'}");
    expect(src).toContain("notice.level === 'error' ? 'alert' : 'status'");
    expect(src).toContain("notice.level === 'error' ? 'assertive' : 'polite'");
    expect(src).toContain('class="notice-kicker"');
    expect(src).toContain("{{ notice.kicker }}");
  });
});
