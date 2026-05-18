// @vitest-environment jsdom

import { createApp, h, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

import BaseBadge from "../src/components/base/BaseBadge.vue";
import BaseButton from "../src/components/base/BaseButton.vue";
import BaseEmptyState from "../src/components/base/BaseEmptyState.vue";
import BaseTooltip from "../src/components/base/BaseTooltip.vue";

let activeApp = null;
const SOURCE_ROOT = process.cwd();

function mount(component, props = {}, slots = {}) {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(component, props, slots) });
  app.mount(el);
  activeApp = app;
  return el;
}

afterEach(() => {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
});

describe("BaseEmptyState", () => {
  it("renders title and description", () => {
    const el = mount(BaseEmptyState, { title: "还没有内容", description: "稍后再来看看。" });
    expect(el.querySelector(".base-empty")).not.toBeNull();
    expect(el.querySelector(".base-empty-title").textContent).toBe("还没有内容");
    expect(el.querySelector(".base-empty-desc").textContent).toBe("稍后再来看看。");
  });

  it("renders the default slot as the description body", () => {
    const el = mount(BaseEmptyState, {}, { default: () => "插槽说明" });
    expect(el.querySelector(".base-empty-desc").textContent).toBe("插槽说明");
  });

  it("renders icon and action slots when provided", () => {
    const el = mount(
      BaseEmptyState,
      { title: "空" },
      { icon: () => h("svg", { "data-testid": "ico" }), action: () => h("button", "去创建") },
    );
    expect(el.querySelector(".base-empty-icon")).not.toBeNull();
    expect(el.querySelector('.base-empty-icon [data-testid="ico"]')).not.toBeNull();
    expect(el.querySelector(".base-empty-action button").textContent).toBe("去创建");
  });

  it("omits title/description nodes when empty", () => {
    const el = mount(BaseEmptyState);
    expect(el.querySelector(".base-empty")).not.toBeNull();
    expect(el.querySelector(".base-empty-title")).toBeNull();
    expect(el.querySelector(".base-empty-desc")).toBeNull();
  });

  it("forwards data-testid onto the root element", () => {
    const el = mount(BaseEmptyState, { description: "x", "data-testid": "scene-empty" });
    const root = el.querySelector('[data-testid="scene-empty"]');
    expect(root).not.toBeNull();
    expect(root.classList.contains("base-empty")).toBe(true);
  });
});

describe("BaseTooltip", () => {
  it("wires the trigger to the tooltip bubble for screen readers", () => {
    const el = mount(BaseTooltip, { text: "这一步会做什么" }, { default: () => "说明" });
    const trigger = el.querySelector(".base-tooltip-trigger");
    const bubble = el.querySelector(".base-tooltip-bubble");

    expect(trigger.getAttribute("tabindex")).toBe("0");
    expect(bubble.getAttribute("role")).toBe("tooltip");
    expect(bubble.textContent.trim()).toBe("这一步会做什么");
    expect(trigger.getAttribute("aria-describedby")).toBe(bubble.getAttribute("id"));
    expect(bubble.getAttribute("id")).toBeTruthy();
  });

  it("opens on focus and closes on blur", async () => {
    const el = mount(BaseTooltip, { text: "提示" }, { default: () => "字段" });
    const trigger = el.querySelector(".base-tooltip-trigger");
    const bubble = el.querySelector(".base-tooltip-bubble");

    expect(bubble.classList.contains("is-open")).toBe(false);

    trigger.dispatchEvent(new Event("focus"));
    await nextTick();
    expect(bubble.classList.contains("is-open")).toBe(true);

    trigger.dispatchEvent(new Event("blur"));
    await nextTick();
    expect(bubble.classList.contains("is-open")).toBe(false);
  });

  it("opens on hover via the wrapper", async () => {
    const el = mount(BaseTooltip, { text: "悬停提示" }, { default: () => "词条" });
    const wrapper = el.querySelector(".base-tooltip");
    const bubble = el.querySelector(".base-tooltip-bubble");

    wrapper.dispatchEvent(new Event("mouseenter"));
    await nextTick();
    expect(bubble.classList.contains("is-open")).toBe(true);

    wrapper.dispatchEvent(new Event("mouseleave"));
    await nextTick();
    expect(bubble.classList.contains("is-open")).toBe(false);
  });
});

describe("warm paper design system primitives", () => {
  it("documents layered app.css sections and exposes semantic tokens", () => {
    const styleSource = readFileSync(path.join(SOURCE_ROOT, "src/styles/app.css"), "utf8");

    expect(styleSource).toContain("/* Design tokens: warm paper workbench */");
    expect(styleSource).toContain("/* Base elements */");
    expect(styleSource).toContain("/* Layout shell */");
    expect(styleSource).toContain("/* Shared components */");
    expect(styleSource).toContain("/* View surfaces */");
    expect(styleSource).toContain("/* Cross-view workbench refinements */");

    [
      "--color-canvas",
      "--color-paper",
      "--color-panel",
      "--color-rail",
      "--color-primary",
      "--color-accent",
      "--color-warning",
      "--color-danger",
      "--radius-panel",
      "--shadow-panel",
      "--font-display",
      "--font-body",
      "--focus-ring",
    ].forEach((token) => {
      expect(styleSource, token).toContain(token);
    });

    expect(styleSource).not.toMatch(/font-size:\s*clamp\(/);
    const nonZeroLetterSpacing = Array.from(styleSource.matchAll(/letter-spacing:\s*([^;]+);/g))
      .map((match) => match[1].trim())
      .filter((value) => value !== "0");
    expect(nonZeroLetterSpacing).toEqual([]);
    expect(styleSource).not.toMatch(/border-radius:\s*(?:0\.9rem|1rem|1\.2rem|1\.25rem|14px|16px|18px)\s*;/);
  });

  it("renders base buttons with icon, loading and block affordances", () => {
    const el = mount(
      BaseButton,
      { variant: "primary", loading: true, block: true, "data-testid": "primary-save" },
      {
        icon: () => h("svg", { "data-testid": "save-icon" }),
        default: () => "保存步骤",
      },
    );

    const button = el.querySelector('[data-testid="primary-save"]');
    expect(button).not.toBeNull();
    expect(button.classList.contains("base-btn-primary")).toBe(true);
    expect(button.classList.contains("base-btn-block")).toBe(true);
    expect(button.getAttribute("aria-busy")).toBe("true");
    expect(button.disabled).toBe(true);
    expect(button.querySelector('[data-testid="save-icon"]')).not.toBeNull();
    expect(button.querySelector(".base-btn-spinner")).not.toBeNull();
    expect(button.textContent).toContain("保存步骤");
  });

  it("keeps badges compact while exposing semantic tones", () => {
    const el = mount(BaseBadge, { tone: "warning", "data-testid": "risk-badge" }, { default: () => "需要确认" });
    const badge = el.querySelector('[data-testid="risk-badge"]');

    expect(badge).not.toBeNull();
    expect(badge.classList.contains("base-badge-warning")).toBe(true);
    expect(badge.textContent).toBe("需要确认");
  });
});
