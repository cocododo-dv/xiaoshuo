// @vitest-environment jsdom

import { createApp, h } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import InjectionBundlePreview from "../src/components/styleReference/InjectionBundlePreview.vue";

let activeApp = null;

function mount(props) {
  if (activeApp) activeApp.unmount();
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(InjectionBundlePreview, props) });
  app.mount(el);
  activeApp = app;
  return el;
}

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
});

describe("InjectionBundlePreview", () => {
  it("preview 含 fragments 时渲染 3 块 + prefix", () => {
    const el = mount({
      preview: {
        fragments: {
          positive_block: "[正向]\n短句",
          forbidden_block: "[禁忌]\n禁堆砌",
          metric_anchor_block: "[量化]\n句长 18",
          strategy: "mixed",
        },
        prefix: "[STYLE_REFERENCE]\n...\n[/STYLE_REFERENCE]\n\n",
      },
    });
    expect(el.textContent).toContain("正向风格特征");
    expect(el.textContent).toContain("禁忌模式");
    expect(el.textContent).toContain("量化锚点");
    expect(el.textContent).toContain("strategy=mixed");
    expect(el.querySelector('[data-testid="bundle-preview-prefix"]')).not.toBeNull();
  });

  it("preview=null 时显示空状态", () => {
    const el = mount({ preview: null });
    expect(el.querySelector('[data-testid="bundle-preview-empty"]')).not.toBeNull();
  });

  it("loading=true 时显示加载中", () => {
    const el = mount({ preview: null, loading: true });
    expect(el.querySelector('[data-testid="bundle-preview-loading"]')).not.toBeNull();
  });

  it("error 非空时显示错误信息", () => {
    const el = mount({ preview: null, error: "请求失败" });
    expect(el.querySelector('[data-testid="bundle-preview-error"]')).not.toBeNull();
    expect(el.textContent).toContain("请求失败");
  });
});
