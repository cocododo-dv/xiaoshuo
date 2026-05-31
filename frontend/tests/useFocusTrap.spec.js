// @vitest-environment jsdom

import { afterEach, describe, expect, it } from "vitest";

import { useFocusTrap } from "../src/composables/useFocusTrap";

let containers = [];

function makeContainer(html) {
  const el = document.createElement("div");
  el.innerHTML = html;
  document.body.appendChild(el);
  containers.push(el);
  return el;
}

afterEach(() => {
  containers.forEach((c) => c.remove());
  containers = [];
});

describe("useFocusTrap", () => {
  it("getFocusable 过滤 disabled 与 tabindex=-1", () => {
    const el = makeContainer(`
      <button id="b1">b1</button>
      <button id="b2" disabled>b2</button>
      <button id="b3" tabindex="-1">b3</button>
      <input id="i1" />
      <a id="a1" href="#">a1</a>
    `);
    const { getFocusable } = useFocusTrap({ value: el });
    expect(getFocusable().map((n) => n.id)).toEqual(["b1", "i1", "a1"]);
  });

  it("getFocusable 无 root 返空数组", () => {
    const { getFocusable } = useFocusTrap({ value: null });
    expect(getFocusable()).toEqual([]);
  });

  it("onTab 末项 Tab → 循环回首项", () => {
    const el = makeContainer(`<button id="b1">1</button><button id="b2">2</button>`);
    const { onTab } = useFocusTrap({ value: el });
    el.querySelector("#b2").focus();
    let prevented = false;
    onTab({ shiftKey: false, preventDefault: () => { prevented = true; } });
    expect(prevented).toBe(true);
    expect(document.activeElement).toBe(el.querySelector("#b1"));
  });

  it("onTab 首项 Shift+Tab → 循环到末项", () => {
    const el = makeContainer(`<button id="b1">1</button><button id="b2">2</button>`);
    const { onTab } = useFocusTrap({ value: el });
    el.querySelector("#b1").focus();
    let prevented = false;
    onTab({ shiftKey: true, preventDefault: () => { prevented = true; } });
    expect(prevented).toBe(true);
    expect(document.activeElement).toBe(el.querySelector("#b2"));
  });

  it("onTab 中间项不拦截(交回浏览器默认 Tab)", () => {
    const el = makeContainer(
      `<button id="b1">1</button><button id="b2">2</button><button id="b3">3</button>`,
    );
    const { onTab } = useFocusTrap({ value: el });
    el.querySelector("#b2").focus();
    let prevented = false;
    onTab({ shiftKey: false, preventDefault: () => { prevented = true; } });
    expect(prevented).toBe(false);
    expect(document.activeElement).toBe(el.querySelector("#b2"));
  });

  it("onTab 无可聚焦元素时不抛错", () => {
    const el = makeContainer(`<p>no focusable</p>`);
    const { onTab } = useFocusTrap({ value: el });
    expect(() => onTab({ shiftKey: false, preventDefault: () => {} })).not.toThrow();
  });
});
