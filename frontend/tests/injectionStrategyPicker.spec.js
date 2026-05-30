// @vitest-environment jsdom

import { createApp, h, nextTick, ref } from "vue";
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

  describe("a11y", () => {
    it("radiogroup + radio role,选中项 aria-checked=true 其余 false", () => {
      const { el } = mount({ ...baseState(), strategy: "A" });
      expect(el.querySelector('[role="radiogroup"]')).not.toBeNull();
      const a = el.querySelector('[data-testid="strategy-A"]');
      expect(a.getAttribute("role")).toBe("radio");
      expect(a.getAttribute("aria-checked")).toBe("true");
      expect(el.querySelector('[data-testid="strategy-B"]').getAttribute("aria-checked")).toBe("false");
      expect(el.querySelector('[data-testid="strategy-mixed"]').getAttribute("aria-checked")).toBe("false");
    });

    it("roving tabindex:选中项 0,其余 -1", () => {
      const { el } = mount({ ...baseState(), strategy: "A" });
      expect(el.querySelector('[data-testid="strategy-A"]').getAttribute("tabindex")).toBe("0");
      expect(el.querySelector('[data-testid="strategy-B"]').getAttribute("tabindex")).toBe("-1");
    });

    it("切换 strategy 后 aria-checked + tabindex 更新", async () => {
      const { el } = mount({ ...baseState(), strategy: "A" });
      el.querySelector('[data-testid="strategy-mixed"]').click();
      await nextTick();
      const mixed = el.querySelector('[data-testid="strategy-mixed"]');
      expect(mixed.getAttribute("aria-checked")).toBe("true");
      expect(mixed.getAttribute("tabindex")).toBe("0");
      expect(el.querySelector('[data-testid="strategy-A"]').getAttribute("aria-checked")).toBe("false");
    });

    it("ArrowRight 移动即选中下一个(A→B)", async () => {
      const { el, value } = mount({ ...baseState(), strategy: "A" });
      el.querySelector('[role="radiogroup"]').dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
      );
      await nextTick();
      expect(value.value.strategy).toBe("B");
      expect(el.querySelector('[data-testid="strategy-B"]').getAttribute("aria-checked")).toBe("true");
    });

    it("ArrowLeft 从首项循环到末项(A→mixed)", async () => {
      const { el, value } = mount({ ...baseState(), strategy: "A" });
      el.querySelector('[role="radiogroup"]').dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }),
      );
      await nextTick();
      expect(value.value.strategy).toBe("mixed");
    });

    it("Home/End 跳到首/末", async () => {
      const { el, value } = mount({ ...baseState(), strategy: "B" });
      const group = el.querySelector('[role="radiogroup"]');
      group.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true }));
      await nextTick();
      expect(value.value.strategy).toBe("mixed");
      group.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
      await nextTick();
      expect(value.value.strategy).toBe("A");
    });
  });
});
