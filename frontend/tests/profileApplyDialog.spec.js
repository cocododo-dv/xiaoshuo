// @vitest-environment jsdom

import { createApp, h, nextTick, ref } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProfileApplyDialog from "../src/components/styleReference/ProfileApplyDialog.vue";

let activeApp = null;

function mount(component, props = {}, listeners = {}) {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  const el = document.createElement("div");
  document.body.appendChild(el);
  const emitted = { submit: [], close: 0, "update:draft": [], "request-preview": [] };
  const app = createApp({
    render: () => h(component, {
      ...props,
      onSubmit: (value) => emitted.submit.push(value),
      onClose: () => { emitted.close += 1; },
      "onUpdate:draft": (value) => { emitted["update:draft"].push(value); listeners["update:draft"]?.(value); },
      "onRequest-preview": (value) => { emitted["request-preview"].push(value); listeners["request-preview"]?.(value); },
    }),
  });
  app.mount(el);
  activeApp = app;
  return { el, emitted };
}

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
  vi.useRealTimers();
});

const defaultDraft = () => ({
  scope: "project",
  scope_ref_id: "",
  task_type: "scene_generation",
  strategy: "mixed",
  intensity: 50,
  sub_dimensions: [
    "language.sentence_structure", "language.vocabulary", "language.rhetoric", "language.punctuation",
    "narrative.perspective", "narrative.pacing", "narrative.time_handling", "narrative.information_density",
    "scene.environment", "scene.character_portrayal", "scene.dialogue", "scene.sensory_priority",
    "theme.emotional_tone", "theme.values", "theme.motifs", "theme.narrative_philosophy",
  ],
  include_positive: true,
  include_forbidden: true,
  include_metric: true,
});

describe("ProfileApplyDialog", () => {
  it("open=false 不渲染 dialog", () => {
    const { el } = mount(ProfileApplyDialog, { open: false, draft: defaultDraft() });
    expect(el.querySelector(".apply-dialog")).toBeNull();
  });

  it("open=true 渲染 dialog 含 scope / scope_ref_id / task_type / strategy picker", () => {
    const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
    expect(el.querySelector(".apply-dialog")).not.toBeNull();
    // 2 个 select(scope / task_type)+ 1 个 text input(scope_ref_id)+ 4 个 strategy 按钮
    expect(el.querySelectorAll("select").length).toBe(2);
    expect(el.querySelectorAll('input[type="text"]').length).toBe(1);
    ["A", "B", "C", "mixed"].forEach((s) => {
      expect(el.querySelector(`[data-testid="strategy-${s}"]`)).not.toBeNull();
    });
  });

  it("scope 下拉含 3 个选项 project/scene/character", () => {
    const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
    const options = Array.from(el.querySelectorAll("select")[0].querySelectorAll("option"))
      .map((o) => o.value);
    expect(options).toEqual(["project", "scene", "character"]);
  });

  it("点击「应用」触发 submit emit,payload 含 intensity 与 sub_dimensions", async () => {
    const { el, emitted } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
    el.querySelector('[data-testid="confirm-apply"]').click();
    await nextTick();
    expect(emitted.submit).toHaveLength(1);
    const payload = emitted.submit[0];
    expect(payload.strategy).toBe("mixed");
    expect(payload.intensity).toBe(50);
    expect(payload.sub_dimensions.length).toBe(16);
    expect(payload.include_metric).toBe(true);
  });

  it("点击关闭 × 触发 close emit", async () => {
    const { el, emitted } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
    el.querySelector(".dialog-close").click();
    await nextTick();
    expect(emitted.close).toBe(1);
  });

  it("选 MIXED 时展开 IntensitySlider + DimensionMultiSelect", async () => {
    const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
    el.querySelector('[data-testid="strategy-mixed"]').click();
    await nextTick();
    expect(el.querySelector('[data-testid="mixed-controls"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="intensity-input"]')).not.toBeNull();
  });

  it("strategy 变更 debounce 300ms 后触发 request-preview", async () => {
    vi.useFakeTimers();
    const { el, emitted } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
    el.querySelector('[data-testid="strategy-B"]').click();
    await nextTick();
    expect(emitted["request-preview"]).toHaveLength(0);
    vi.advanceTimersByTime(310);
    expect(emitted["request-preview"]).toHaveLength(1);
    expect(emitted["request-preview"][0].strategy).toBe("B");
  });

  it("preview prop 注入时渲染 InjectionBundlePreview", () => {
    const preview = {
      fragments: {
        positive_block: "[正向]\n短句",
        forbidden_block: "",
        metric_anchor_block: "",
        strategy: "A",
      },
      prefix: "[STYLE_REFERENCE]\n[正向]\n短句\n[/STYLE_REFERENCE]\n\n",
    };
    const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft(), preview });
    expect(el.querySelector('[data-testid="bundle-preview"]')).not.toBeNull();
    expect(el.textContent).toContain("正向风格特征");
  });

  describe("a11y", () => {
    it("dialog 容器有 role=dialog + aria-modal + aria-labelledby", () => {
      const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
      const dialog = el.querySelector(".apply-dialog");
      expect(dialog.getAttribute("role")).toBe("dialog");
      expect(dialog.getAttribute("aria-modal")).toBe("true");
      expect(dialog.getAttribute("aria-labelledby")).toBe("apply-dialog-title");
      expect(el.querySelector("#apply-dialog-title")).not.toBeNull();
    });

    it("Escape 键触发 close emit", async () => {
      const { el, emitted } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
      const dialog = el.querySelector(".apply-dialog");
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
      await nextTick();
      expect(emitted.close).toBe(1);
    });

    it("点击遮罩本体关闭,点击内容区不关闭", async () => {
      const { el, emitted } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
      // 内容区点击冒泡到 mask,但 @click.self 不触发
      el.querySelector(".apply-dialog").click();
      await nextTick();
      expect(emitted.close).toBe(0);
      // 点击遮罩本体(mask 根)关闭
      el.querySelector(".apply-dialog-mask").click();
      await nextTick();
      expect(emitted.close).toBe(1);
    });

    it("打开后焦点落到关闭按钮", async () => {
      const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
      await nextTick();
      await nextTick();
      expect(document.activeElement).toBe(el.querySelector(".dialog-close"));
    });

    it("focus trap:末项 Tab 循环回首项(关闭按钮)", async () => {
      const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
      await nextTick();
      const dialog = el.querySelector(".apply-dialog");
      const sel = 'button:not([disabled]):not([tabindex="-1"]), select:not([disabled]),'
        + ' input:not([disabled]), [tabindex]:not([tabindex="-1"])';
      const items = Array.from(dialog.querySelectorAll(sel));
      const last = items[items.length - 1];
      last.focus();
      expect(document.activeElement).toBe(last);
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
      await nextTick();
      expect(document.activeElement).toBe(el.querySelector(".dialog-close"));
    });

    it("focus trap:首项 Shift+Tab 循环到末项", async () => {
      const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft() });
      await nextTick();
      const dialog = el.querySelector(".apply-dialog");
      const first = el.querySelector(".dialog-close");
      first.focus();
      const sel = 'button:not([disabled]):not([tabindex="-1"]), select:not([disabled]),'
        + ' input:not([disabled]), [tabindex]:not([tabindex="-1"])';
      const items = Array.from(dialog.querySelectorAll(sel));
      const last = items[items.length - 1];
      dialog.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }));
      await nextTick();
      expect(document.activeElement).toBe(last);
    });
  });
});
