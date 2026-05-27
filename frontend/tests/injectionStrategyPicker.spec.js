// @vitest-environment jsdom

import { createApp, h, ref } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import InjectionStrategyPicker from "../src/components/styleReference/InjectionStrategyPicker.vue";

let activeApp = null;

function mount(initial) {
  if (activeApp) activeApp.unmount();
  const el = document.createElement("div");
  document.body.appendChild(el);
  const value = ref({ ...initial });
  const app = createApp({
    render: () => h(InjectionStrategyPicker, {
      modelValue: value.value,
      "onUpdate:modelValue": (next) => { value.value = next; },
    }),
  });
  app.mount(el);
  activeApp = app;
  return { el, value };
}

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
});

describe("InjectionStrategyPicker", () => {
  const baseState = () => ({
    strategy: "A",
    intensity: 50,
    sub_dimensions: ["language.vocabulary"],
  });

  it("渲染 4 个 strategy 按钮", () => {
    const { el } = mount(baseState());
    ["A", "B", "C", "mixed"].forEach((s) => {
      expect(el.querySelector(`[data-testid="strategy-${s}"]`)).not.toBeNull();
    });
  });

  it("点击切换 strategy 触发 update:modelValue", async () => {
    const { el, value } = mount(baseState());
    el.querySelector('[data-testid="strategy-B"]').click();
    await Promise.resolve();
    expect(value.value.strategy).toBe("B");
  });

  it("非 MIXED 时不显示 IntensitySlider / DimensionMultiSelect", () => {
    const { el } = mount(baseState());
    expect(el.querySelector('[data-testid="mixed-controls"]')).toBeNull();
  });

  it("MIXED 时展开 IntensitySlider + DimensionMultiSelect", async () => {
    const { el, value } = mount(baseState());
    el.querySelector('[data-testid="strategy-mixed"]').click();
    await Promise.resolve();
    expect(value.value.strategy).toBe("mixed");
    expect(el.querySelector('[data-testid="mixed-controls"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="intensity-input"]')).not.toBeNull();
  });

  it("MIXED 下 intensity 滑动同步 modelValue.intensity", async () => {
    const { el, value } = mount({ ...baseState(), strategy: "mixed" });
    const input = el.querySelector('[data-testid="intensity-input"]');
    input.value = "80";
    input.dispatchEvent(new Event("input"));
    await Promise.resolve();
    expect(value.value.intensity).toBe(80);
  });

  it("MIXED 下子维度勾选同步 modelValue.sub_dimensions", async () => {
    const { el, value } = mount({
      ...baseState(),
      strategy: "mixed",
      sub_dimensions: [],
    });
    el.querySelector('[data-testid="sub-dim-narrative.pacing"]').click();
    await Promise.resolve();
    expect(value.value.sub_dimensions).toContain("narrative.pacing");
  });
});
