// @vitest-environment jsdom

import { createApp, h } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import MetricsTrendChart from "../src/components/styleReference/MetricsTrendChart.vue";

let activeApp = null;

function mount(daily) {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(MetricsTrendChart, { daily }) });
  app.mount(el);
  activeApp = app;
  return { el };
}

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
});

const SAMPLE = [
  { date: "2026-05-28", count: 2 },
  { date: "2026-05-29", count: 0 },
  { date: "2026-05-30", count: 8 },
  { date: "2026-05-31", count: 4 },
];

describe("MetricsTrendChart", () => {
  it("空数组显示空提示且不渲染 svg", () => {
    const { el } = mount([]);
    expect(el.querySelector('[data-testid="trend-empty"]')).not.toBeNull();
    expect(el.querySelector("svg")).toBeNull();
  });

  it("柱数等于数据长度", () => {
    const { el } = mount(SAMPLE);
    expect(el.querySelectorAll('[data-testid="trend-bar"]').length).toBe(4);
  });

  it("柱高按峰值归一:峰值满高、零值零高", () => {
    const { el } = mount(SAMPLE);
    const bars = Array.from(el.querySelectorAll('[data-testid="trend-bar"]'));
    const peak = bars.find((b) => b.getAttribute("data-count") === "8");
    const zero = bars.find((b) => b.getAttribute("data-count") === "0");
    // 峰值柱高 = viewBox 高度 64
    expect(Number(peak.getAttribute("height"))).toBe(64);
    // 零值柱高 = 0(空档)
    expect(Number(zero.getAttribute("height"))).toBe(0);
  });

  it("SVG 有 role=img + aria-label 含峰值摘要", () => {
    const { el } = mount(SAMPLE);
    const svg = el.querySelector("svg");
    expect(svg.getAttribute("role")).toBe("img");
    expect(svg.getAttribute("aria-label")).toContain("峰值 8 次");
    expect(svg.getAttribute("aria-label")).toContain("近 4 日");
  });

  it("每柱带 date/count data 属性与 title", () => {
    const { el } = mount(SAMPLE);
    const first = el.querySelector('[data-testid="trend-bar"]');
    expect(first.getAttribute("data-date")).toBe("2026-05-28");
    expect(first.getAttribute("data-count")).toBe("2");
    expect(first.querySelector("title").textContent).toContain("2026-05-28");
  });
});
