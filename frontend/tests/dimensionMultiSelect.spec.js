// @vitest-environment jsdom

import { createApp, h, ref } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import DimensionMultiSelect from "../src/components/styleReference/DimensionMultiSelect.vue";

let activeApp = null;

function mount(props) {
  if (activeApp) activeApp.unmount();
  const el = document.createElement("div");
  document.body.appendChild(el);
  const value = ref([...(props.modelValue || [])]);
  const app = createApp({
    render: () => h(DimensionMultiSelect, {
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

describe("DimensionMultiSelect", () => {
  it("渲染 16 个 sub_dim 复选框", () => {
    const { el } = mount({ modelValue: [] });
    const boxes = el.querySelectorAll('input[type="checkbox"]');
    expect(boxes.length).toBe(16);
  });

  it("点击单项 toggle 选中状态", async () => {
    const { el, value } = mount({ modelValue: [] });
    const target = el.querySelector('[data-testid="sub-dim-language.vocabulary"]');
    target.click();
    await Promise.resolve();
    expect(value.value).toContain("language.vocabulary");
    target.click();
    await Promise.resolve();
    expect(value.value).not.toContain("language.vocabulary");
  });

  it("全选本层 button 把同层 4 项加入选中", async () => {
    const { el, value } = mount({ modelValue: [] });
    el.querySelector('[data-testid="select-layer-narrative"]').click();
    await Promise.resolve();
    expect(value.value).toEqual(expect.arrayContaining([
      "narrative.perspective",
      "narrative.pacing",
      "narrative.time_handling",
      "narrative.information_density",
    ]));
  });

  it("全反选清空选中", async () => {
    const initial = [
      "language.sentence_structure",
      "narrative.pacing",
    ];
    const { el, value } = mount({ modelValue: initial });
    el.querySelector('[data-testid="clear-all"]').click();
    await Promise.resolve();
    expect(value.value).toEqual([]);
  });
});
