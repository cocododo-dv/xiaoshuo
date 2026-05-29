// @vitest-environment jsdom

import { createApp, h, ref } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import IntensitySlider from "../src/components/styleReference/IntensitySlider.vue";

let activeApp = null;

function mount(props, onUpdate) {
  if (activeApp) activeApp.unmount();
  const el = document.createElement("div");
  document.body.appendChild(el);
  const value = ref(props.modelValue ?? 50);
  const app = createApp({
    render: () => h(IntensitySlider, {
      modelValue: value.value,
      disabled: props.disabled,
      "onUpdate:modelValue": (next) => {
        value.value = next;
        onUpdate?.(next);
      },
    }),
  });
  app.mount(el);
  activeApp = app;
  return { el, value };
}

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
});

describe("IntensitySlider", () => {
  it("接受 0-100 范围输入并 emit", async () => {
    const updates = [];
    const { el } = mount({ modelValue: 30 }, (n) => updates.push(n));
    const input = el.querySelector('[data-testid="intensity-input"]');
    input.value = "75";
    input.dispatchEvent(new Event("input"));
    await Promise.resolve();
    expect(updates[updates.length - 1]).toBe(75);
  });

  it("disabled 时不响应输入", async () => {
    const updates = [];
    const { el } = mount({ modelValue: 40, disabled: true }, (n) => updates.push(n));
    const input = el.querySelector('[data-testid="intensity-input"]');
    expect(input.disabled).toBe(true);
    input.value = "90";
    input.dispatchEvent(new Event("input"));
    await Promise.resolve();
    expect(updates).toHaveLength(0);
  });

  it("渲染 3 档刻度文案 0.3x / 0.9x 基线 / 1.5x", () => {
    const { el } = mount({ modelValue: 50 });
    expect(el.textContent).toContain("0.3x");
    expect(el.textContent).toContain("0.9x 基线");
    expect(el.textContent).toContain("1.5x");
  });

  describe("a11y", () => {
    it("range input 有 aria-label + aria-valuetext 含当前值", () => {
      const { el } = mount({ modelValue: 70 });
      const input = el.querySelector('[data-testid="intensity-input"]');
      expect(input.getAttribute("aria-label")).toBe("注入强度");
      expect(input.getAttribute("aria-valuetext")).toContain("70");
    });
  });
});
