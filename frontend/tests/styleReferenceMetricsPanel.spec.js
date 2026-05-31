// @vitest-environment jsdom

import { createApp, h } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import StyleReferenceMetricsPanel from "../src/components/styleReference/StyleReferenceMetricsPanel.vue";

let activeApp = null;

function mount(props, listeners = {}) {
  if (activeApp) activeApp.unmount();
  const el = document.createElement("div");
  document.body.appendChild(el);
  const emitted = { reload: [] };
  const app = createApp({
    render: () => h(StyleReferenceMetricsPanel, {
      ...props,
      onReload: (hours) => { emitted.reload.push(hours); listeners.reload?.(hours); },
    }),
  });
  app.mount(el);
  activeApp = app;
  return { el, emitted };
}

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
});

const SAMPLE_METRICS = {
  injection_hit_rate: 0.823,
  qc_gate_reject_rate: 0.06,
  auto_rewrite_pass_rate: 0.74,
  validation_p95_latency_ms: 320,
  sample_counts: {
    injection_invoked: 124,
    qc_gate_decided: 81,
    validation_executed: 81,
    auto_rewrite_triggered: 19,
    auto_rewrite_completed: 14,
  },
  window_hours: 168,
  computed_at: "2026-05-25T08:00:00Z",
};

describe("StyleReferenceMetricsPanel", () => {
  it("loading=true 时显示加载中并隐藏指标卡", () => {
    const { el } = mount({ loading: true, metrics: null });
    expect(el.querySelector('[data-testid="metrics-loading"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="metric-injection"]')).toBeNull();
  });

  it("error 非空时显示错误且不渲染指标卡", () => {
    const { el } = mount({ error: "请求失败", metrics: null });
    expect(el.querySelector('[data-testid="metrics-error"]')).not.toBeNull();
    expect(el.textContent).toContain("请求失败");
  });

  it("metrics=null 且 loading=false 时显示空状态", () => {
    const { el } = mount({ metrics: null });
    expect(el.querySelector('[data-testid="metrics-empty"]')).not.toBeNull();
  });

  it("不传 daily 时不渲染趋势图(向后兼容)", () => {
    const { el } = mount({ metrics: SAMPLE_METRICS });
    expect(el.querySelector('[data-testid="metrics-trend-chart"]')).toBeNull();
  });

  it("传 daily 时渲染 MetricsTrendChart 趋势图", () => {
    const daily = {
      daily: [
        { date: "2026-05-30", count: 3 },
        { date: "2026-05-31", count: 7 },
      ],
      window_days: 2,
      computed_at: "2026-05-31T08:00:00Z",
    };
    const { el } = mount({ metrics: SAMPLE_METRICS, daily });
    expect(el.querySelector('[data-testid="metrics-trend-chart"]')).not.toBeNull();
    expect(el.querySelectorAll('[data-testid="trend-bar"]').length).toBe(2);
  });

  it("metrics 注入时渲染 4 个指标卡 + 百分比格式", () => {
    const { el } = mount({ metrics: SAMPLE_METRICS });
    expect(el.querySelector('[data-testid="metric-injection"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="metric-qc-reject"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="metric-auto-rewrite"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="metric-p95"]')).not.toBeNull();
    expect(el.textContent).toContain("82.3%");      // injection_hit_rate
    expect(el.textContent).toContain("6.0%");       // qc_gate_reject_rate
    expect(el.textContent).toContain("74.0%");      // auto_rewrite_pass_rate
    expect(el.textContent).toContain("320 ms");     // validation_p95
    expect(el.textContent).toContain("124 次注入调用");
  });

  it("切换时间窗口按钮触发 reload emit 含 hours 数值", async () => {
    const { el, emitted } = mount({ metrics: SAMPLE_METRICS });
    el.querySelector('[data-testid="window-720"]').click();
    await Promise.resolve();
    expect(emitted.reload).toEqual([720]);
    el.querySelector('[data-testid="window-0"]').click();
    await Promise.resolve();
    expect(emitted.reload).toEqual([720, 0]);
  });

  describe("a11y", () => {
    it("当前 window button aria-pressed=true,其余=false", () => {
      // SAMPLE_METRICS.window_hours = 168
      const { el } = mount({ metrics: SAMPLE_METRICS });
      expect(el.querySelector('[data-testid="window-168"]').getAttribute("aria-pressed")).toBe("true");
      expect(el.querySelector('[data-testid="window-720"]').getAttribute("aria-pressed")).toBe("false");
      expect(el.querySelector('[data-testid="window-0"]').getAttribute("aria-pressed")).toBe("false");
    });
  });
});
