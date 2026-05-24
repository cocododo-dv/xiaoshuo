// @vitest-environment jsdom

import { createApp, h } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import PreviewPanel from "../src/components/styleReference/PreviewPanel.vue";

let activeApp = null;

function mount(component, props = {}) {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  const el = document.createElement("div");
  document.body.appendChild(el);
  const emitted = { regenerate: 0 };
  const app = createApp({
    render: () => h(component, {
      ...props,
      onRegenerate: () => emitted.regenerate += 1,
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

describe("PreviewPanel", () => {
  it("samples 为空时显示 BaseEmptyState", () => {
    const { el } = mount(PreviewPanel, { samples: [] });
    expect(el.querySelector(".base-empty")).not.toBeNull();
  });

  it("3 个 sample 渲染 3 个 sample-item", () => {
    const samples = [
      { paragraph_type: "dialogue", sample_text: "对话示例", report_id: "r1", verdict: "pass" },
      { paragraph_type: "description_env", sample_text: "环境示例", report_id: "r2", verdict: "partial" },
      { paragraph_type: "psychology", sample_text: "心理示例", report_id: "r3", verdict: "fail" },
    ];
    const { el } = mount(PreviewPanel, { samples });
    expect(el.querySelectorAll(".sample-item")).toHaveLength(3);
  });

  it("verdict=plagiarism 渲染对应 badge", () => {
    const samples = [
      { paragraph_type: "dialogue", sample_text: "重叠示例", report_id: "r1", verdict: "plagiarism" },
    ];
    const { el } = mount(PreviewPanel, { samples });
    // verdict label "抄袭命中" 与 danger badge tone
    const badges = el.querySelectorAll(".base-badge-danger");
    expect(badges.length).toBeGreaterThan(0);
  });

  it("error 字段降级时显示错误提示文案", () => {
    const samples = [
      { paragraph_type: "dialogue", sample_text: "", report_id: null, verdict: null, error: "llm_call_failed" },
    ];
    const { el } = mount(PreviewPanel, { samples });
    const reportError = el.querySelector(".report-error");
    expect(reportError).not.toBeNull();
    expect(reportError.textContent).toContain("llm_call_failed");
  });

  it("点击重新生成按钮触发 emit", async () => {
    const { el, emitted } = mount(PreviewPanel, { samples: [] });
    const btn = el.querySelector(".panel-head button");
    btn.click();
    expect(emitted.regenerate).toBe(1);
  });
});
