// @vitest-environment jsdom

import { createApp, h } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import ValidationReportCard from "../src/components/styleReference/ValidationReportCard.vue";

let activeApp = null;

function mount(props) {
  if (activeApp) activeApp.unmount();
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(ValidationReportCard, props) });
  app.mount(el);
  activeApp = app;
  return el;
}

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
});

describe("ValidationReportCard — PR-5 简化态向后兼容", () => {
  it("无 report 仅 sample 时显示 verdict + 简化态注释", () => {
    const el = mount({
      sample: { paragraph_type: "dialogue", verdict: "pass", sample_text: "示例" },
    });
    expect(el.querySelector(".validation-report")).not.toBeNull();
    expect(el.textContent).toContain("通过");
    expect(el.textContent).toContain("PR-5 简化态");
  });

  it("verdict=plagiarism 渲染 danger badge", () => {
    const el = mount({
      sample: { paragraph_type: "dialogue", verdict: "plagiarism" },
    });
    expect(el.querySelector(".base-badge-danger")).not.toBeNull();
    expect(el.textContent).toContain("抄袭命中");
  });
});

describe("ValidationReportCard — PR-7 完整 4 路", () => {
  const fullReport = {
    verdict: "partial",
    mode_executed: "async_full",
    quantitative_json: [
      { metric: "avg_sentence_length", target_mean: 18, target_std: 4, actual: 30, tolerance: 5, passed: false, deviation_ratio: 2.4 },
      { metric: "dialogue_ratio", target_mean: 0.3, target_std: 0.1, actual: 0.32, tolerance: 0.13, passed: true, deviation_ratio: 0.15 },
    ],
    semantic_json: [
      { dimension: "rhythm", score: 7.5, explanation: "节奏「短句」明显", quotes_found: true },
      { dimension: "tone", score: 4.0, explanation: "情绪流畅(无引文)", quotes_found: false },
    ],
    plagiarism_json: { passed: true, hits: [] },
    forbidden_hits_json: [
      { pattern_statement: "禁堆华丽形容词", matched_excerpt: "美轮美奂", severity: "error" },
    ],
  };

  it("verdict=partial 渲染 warning badge + 各路 hits/scores", () => {
    const el = mount({
      sample: { paragraph_type: "psychology" },
      report: fullReport,
    });
    expect(el.querySelector(".base-badge-warning")).not.toBeNull();
    expect(el.textContent).toContain("部分通过");
    // mode badge
    expect(el.textContent).toContain("async_full");
  });

  it("quantitative 仅渲染未通过的 metric 行", () => {
    const el = mount({ sample: {}, report: fullReport });
    const quantRows = el.querySelectorAll(".quant-row");
    // 仅 1 个 failed metric(avg_sentence_length)
    expect(quantRows.length).toBe(1);
    expect(el.textContent).toContain("avg_sentence_length");
  });

  it("semantic 渲染所有 dimension + 无引文时 warn", () => {
    const el = mount({ sample: {}, report: fullReport });
    const semanticRows = el.querySelectorAll(".semantic-row");
    expect(semanticRows.length).toBe(2);
    expect(el.textContent).toContain("rhythm");
    expect(el.textContent).toContain("tone");
    expect(el.textContent).toContain("无引文,已截至 4");
  });

  it("forbidden_hits_json 渲染 hits 列表", () => {
    const el = mount({ sample: {}, report: fullReport });
    expect(el.textContent).toContain("禁堆华丽形容词");
    expect(el.textContent).toContain("美轮美奂");
  });

  it("plagiarism hits 数组渲染", () => {
    const el = mount({
      sample: {},
      report: {
        ...fullReport,
        verdict: "plagiarism",
        plagiarism_json: {
          passed: false,
          hits: [
            { matched_text: "暮色四合街口的雾气", position: 5, matched_length: 14 },
          ],
        },
      },
    });
    expect(el.textContent).toContain("抄袭命中");
    expect(el.textContent).toContain("暮色四合街口的雾气");
    expect(el.textContent).toContain("14 字");
  });
});
