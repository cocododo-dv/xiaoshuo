// @vitest-environment jsdom

import { createApp, h, nextTick, reactive } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import SnowflakeSkipStepDialog from "../src/components/SnowflakeSkipStepDialog.vue";

let activeApp = null;

// 焦点 trap 选择器(与 useFocusTrap FOCUSABLE_SELECTOR 一致)
const FOCUSABLE = [
  'button:not([disabled]):not([tabindex="-1"])',
  'textarea:not([disabled]):not([tabindex="-1"])',
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

function mount(open = true) {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
  const el = document.createElement("div");
  document.body.appendChild(el);
  const emitted = { close: 0, confirm: [], "draft-assistant": 0 };
  const state = reactive({ open, step: { label: "一句话概述" } });
  const app = createApp({
    render: () =>
      h(SnowflakeSkipStepDialog, {
        open: state.open,
        step: state.step,
        onClose: () => { emitted.close += 1; },
        onConfirm: (value) => emitted.confirm.push(value),
        "onDraft-assistant": () => { emitted["draft-assistant"] += 1; },
      }),
  });
  app.mount(el);
  activeApp = app;
  return { el, emitted, state };
}

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
});

describe("SnowflakeSkipStepDialog", () => {
  it("open=false 不渲染 dialog", () => {
    const { el } = mount(false);
    expect(el.querySelector(".snowflake-skip-dialog")).toBeNull();
  });

  it("open=true 渲染 dialog 含标题与原因输入", () => {
    const { el } = mount(true);
    expect(el.querySelector(".snowflake-skip-dialog")).not.toBeNull();
    expect(el.querySelector(".control-input")).not.toBeNull();
  });

  it("reason 为空时确认禁用,填入后可确认并 emit", async () => {
    const { el, emitted } = mount(true);
    const confirmBtn = el.querySelector(".primary.action-btn");
    expect(confirmBtn.disabled).toBe(true);
    const textarea = el.querySelector(".control-input");
    textarea.value = "已在上一层大纲明确";
    textarea.dispatchEvent(new Event("input"));
    await nextTick();
    expect(confirmBtn.disabled).toBe(false);
    confirmBtn.click();
    await nextTick();
    expect(emitted.confirm).toEqual(["已在上一层大纲明确"]);
  });

  describe("a11y", () => {
    it("dialog 容器有 role=dialog + aria-modal + aria-labelledby", () => {
      const { el } = mount(true);
      const dialog = el.querySelector(".snowflake-skip-dialog");
      expect(dialog.getAttribute("role")).toBe("dialog");
      expect(dialog.getAttribute("aria-modal")).toBe("true");
      expect(dialog.getAttribute("aria-labelledby")).toBe("snowflake-skip-dialog-title");
      expect(el.querySelector("#snowflake-skip-dialog-title")).not.toBeNull();
    });

    it("Escape 键触发 close emit", async () => {
      const { el, emitted } = mount(true);
      el.querySelector(".snowflake-skip-dialog-backdrop")
        .dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await nextTick();
      expect(emitted.close).toBe(1);
    });

    it("打开后焦点落到原因输入框", async () => {
      const { el, state } = mount(false);
      state.open = true;
      await nextTick();
      await nextTick();
      expect(document.activeElement).toBe(el.querySelector(".control-input"));
    });

    it("focus trap:末项 Tab 循环回首项", async () => {
      const { el } = mount(true);
      await nextTick();
      const dialog = el.querySelector(".snowflake-skip-dialog");
      const items = Array.from(dialog.querySelectorAll(FOCUSABLE));
      const first = items[0];
      const last = items[items.length - 1];
      last.focus();
      expect(document.activeElement).toBe(last);
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
      await nextTick();
      expect(document.activeElement).toBe(first);
    });

    it("focus trap:首项 Shift+Tab 循环到末项", async () => {
      const { el } = mount(true);
      await nextTick();
      const dialog = el.querySelector(".snowflake-skip-dialog");
      const items = Array.from(dialog.querySelectorAll(FOCUSABLE));
      const first = items[0];
      const last = items[items.length - 1];
      first.focus();
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }));
      await nextTick();
      expect(document.activeElement).toBe(last);
    });
  });
});
