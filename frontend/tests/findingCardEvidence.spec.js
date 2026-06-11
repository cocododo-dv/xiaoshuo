// @vitest-environment jsdom
//
// PR-23 — FindingCard 证据区渲染(P0-2):引文文本 / anchor_kind 徽章 /
// 合成角标 / evidence 缺失时整体不渲染(兼容旧数据)。

import { createApp, h, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import FindingCard from "../src/components/styleReference/FindingCard.vue";

let activeApp = null;

function mountCard(finding) {
  if (activeApp) activeApp.unmount();
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(FindingCard, { finding }) });
  app.mount(el);
  activeApp = app;
  return el;
}

afterEach(() => {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  document.body.innerHTML = "";
});

function baseFinding(overrides = {}) {
  return {
    finding_id: "sr_find_ev_1",
    finding_kind: "observation",
    statement: "短句节奏明显",
    confidence: "high",
    status: "pending",
    sub_dimension: "language.rhetoric",
    ...overrides,
  };
}

describe("FindingCard 证据区(PR-23)", () => {
  it("渲染引文文本 + 区头计数 + 「已满足 ≥2」", async () => {
    const el = mountCard(
      baseFinding({
        evidence: [
          {
            evidence_id: "ev1",
            anchor_kind: "paragraph_quote",
            quote_text: "他低头看着脚下的路",
            paragraph_id: "sr_para_abcd1234_0003",
            is_synthetic: 0,
          },
          {
            evidence_id: "ev2",
            anchor_kind: "author_avoidance",
            quote_text: "全书未出现景物铺陈",
            paragraph_id: null,
            is_synthetic: 0,
          },
        ],
      }),
    );
    await nextTick();
    const section = el.querySelector('[data-testid="reference-evidence-sr_find_ev_1"]');
    expect(section).not.toBeNull();
    expect(section.textContent).toContain("证据 · 2");
    expect(section.textContent).toContain("已满足 ≥2");
    // 引文文本(衬线引文)
    const quotes = [...section.querySelectorAll(".evidence-quote")];
    expect(quotes.map((q) => q.textContent)).toEqual([
      "他低头看着脚下的路",
      "全书未出现景物铺陈",
    ]);
    // paragraph_quote 显示段号;author_avoidance 显示「负空间」徽章
    expect(section.textContent).toContain("段落 #3");
    expect(section.textContent).toContain("负空间");
  });

  it("counter_example + is_synthetic 显示「合成反例」与「合成」角标;单条证据标「不足」", async () => {
    const el = mountCard(
      baseFinding({
        evidence: [
          {
            evidence_id: "ev1",
            anchor_kind: "counter_example",
            quote_text: "合成的反例文本",
            paragraph_id: null,
            is_synthetic: 1,
          },
        ],
      }),
    );
    await nextTick();
    const section = el.querySelector('[data-testid="reference-evidence-sr_find_ev_1"]');
    expect(section.textContent).toContain("证据 · 1");
    expect(section.textContent).toContain("不足");
    expect(section.textContent).toContain("合成反例");
    expect(section.textContent).toContain("合成");
  });

  it("evidence 为空数组 / 缺失时,证据区整体不渲染(兼容旧数据)", async () => {
    const elEmpty = mountCard(baseFinding({ evidence: [] }));
    await nextTick();
    expect(elEmpty.querySelector(".card-evidence")).toBeNull();

    const elMissing = mountCard(baseFinding());
    await nextTick();
    expect(elMissing.querySelector(".card-evidence")).toBeNull();
    // statement 与操作按钮不受影响
    expect(elMissing.textContent).toContain("短句节奏明显");
    expect(elMissing.querySelector('[data-testid="reference-approve-sr_find_ev_1"]')).not.toBeNull();
  });
});
