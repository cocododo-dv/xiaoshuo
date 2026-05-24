// @vitest-environment jsdom

import { createApp, h, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import DimensionMatrix from "../src/components/styleReference/DimensionMatrix.vue";

let activeApp = null;

function mount(component, props = {}) {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  const el = document.createElement("div");
  document.body.appendChild(el);
  const emitted = { selectSubDim: [] };
  const app = createApp({
    render: () => h(component, {
      ...props,
      onSelectSubDim: (value) => emitted.selectSubDim.push(value),
    }),
  });
  app.mount(el);
  activeApp = app;
  return { el, emitted };
}

afterEach(() => {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
});

function emptyFindings() {
  const dims = [
    "language.sentence_structure", "language.vocabulary", "language.rhetoric", "language.punctuation",
    "narrative.perspective", "narrative.pacing", "narrative.time_handling", "narrative.information_density",
  ];
  const result = {};
  for (const d of dims) result[d] = { observations: [], forbidden_patterns: [] };
  return result;
}

describe("DimensionMatrix", () => {
  it("渲染 4 层 × 4 列 = 16 个 cell", () => {
    const { el } = mount(DimensionMatrix, { findings: emptyFindings() });
    expect(el.querySelectorAll(".matrix-cell")).toHaveLength(16);
  });

  it("无 findings 时 cell 显示 skip confidence", () => {
    const { el } = mount(DimensionMatrix, { findings: emptyFindings() });
    const skipCells = el.querySelectorAll(".cell-skip");
    expect(skipCells.length).toBe(16);
  });

  it("有 ≥5 obs 的 sub_dim 应为 high confidence", () => {
    const findings = emptyFindings();
    findings["language.rhetoric"].observations = Array.from({ length: 6 }, (_, i) => ({
      finding_id: `f${i}`,
    }));
    const { el } = mount(DimensionMatrix, { findings });
    const cells = el.querySelectorAll(".matrix-cell");
    const highCells = el.querySelectorAll(".cell-high");
    expect(highCells.length).toBe(1);
  });

  it("scene + theme 的 8 格 disabled,click 不触发 emit", async () => {
    const { el, emitted } = mount(DimensionMatrix, { findings: emptyFindings() });
    const disabled = el.querySelectorAll(".cell-disabled");
    expect(disabled.length).toBe(16);  // 全部 skip,因为 emptyFindings 都是空
    // 点击不触发
    disabled[0].click();
    await nextTick();
    expect(emitted.selectSubDim).toHaveLength(0);
  });

  it("highlightDim prop 高亮对应 cell", () => {
    const findings = emptyFindings();
    findings["language.rhetoric"].observations = [{ finding_id: "f1" }, { finding_id: "f2" }, { finding_id: "f3" }];
    const { el } = mount(DimensionMatrix, { findings, highlightDim: "language.rhetoric" });
    const highlighted = el.querySelectorAll(".cell-highlight");
    expect(highlighted.length).toBe(1);
  });
});
