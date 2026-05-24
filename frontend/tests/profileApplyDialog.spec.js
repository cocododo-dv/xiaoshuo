// @vitest-environment jsdom

import { createApp, h, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";

import ProfileApplyDialog from "../src/components/styleReference/ProfileApplyDialog.vue";

let activeApp = null;

function mount(component, props = {}) {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  const el = document.createElement("div");
  document.body.appendChild(el);
  const emitted = { submit: [], close: 0 };
  const app = createApp({
    render: () => h(component, {
      ...props,
      onSubmit: (value) => emitted.submit.push(value),
      onClose: () => emitted.close += 1,
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

const defaultDraft = {
  scope: "project",
  scope_ref_id: "",
  task_type: "scene_generation",
  strategy: "A",
};

describe("ProfileApplyDialog", () => {
  it("open=false 不渲染 dialog", () => {
    const { el } = mount(ProfileApplyDialog, { open: false, draft: defaultDraft });
    expect(el.querySelector(".apply-dialog")).toBeNull();
  });

  it("open=true 渲染 4 字段(scope/scope_ref_id/task_type/strategy)", () => {
    const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft });
    expect(el.querySelector(".apply-dialog")).not.toBeNull();
    const selects = el.querySelectorAll("select");
    expect(selects.length).toBe(3);  // scope / task_type / strategy
    const inputs = el.querySelectorAll('input[type="text"]');
    expect(inputs.length).toBe(1);  // scope_ref_id
  });

  it("scope 下拉含 3 个选项 project/scene/character", () => {
    const { el } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft });
    const options = Array.from(el.querySelectorAll("select")[0].querySelectorAll("option"))
      .map((o) => o.value);
    expect(options).toEqual(["project", "scene", "character"]);
  });

  it("点击「应用」触发 submit emit 含完整 draft", async () => {
    const { el, emitted } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft });
    const buttons = el.querySelectorAll(".dialog-actions button");
    const submitBtn = buttons[buttons.length - 1];  // "应用" 在右侧
    submitBtn.click();
    await nextTick();
    expect(emitted.submit).toHaveLength(1);
    expect(emitted.submit[0]).toEqual(defaultDraft);
  });

  it("点击关闭(× / 取消)触发 close emit", async () => {
    const { el, emitted } = mount(ProfileApplyDialog, { open: true, draft: defaultDraft });
    el.querySelector(".dialog-close").click();
    await nextTick();
    expect(emitted.close).toBe(1);
  });
});
