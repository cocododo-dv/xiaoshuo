import { describe, expect, it, vi } from "vitest";
import { onRovingTabKeyDown } from "./a11y-tabs.js";

describe("onRovingTabKeyDown", () => {
  it("方向键循环移动焦点并激活目标 tab，Home/End 可直达", () => {
    const list = document.createElement("div");
    list.setAttribute("role", "tablist");
    const clicks = [vi.fn(), vi.fn(), vi.fn()];
    clicks.forEach((click, index) => {
      const button = document.createElement("button");
      button.setAttribute("role", "tab");
      button.textContent = String(index);
      button.addEventListener("click", click);
      button.addEventListener("keydown", onRovingTabKeyDown);
      list.appendChild(button);
    });
    document.body.appendChild(list);
    const tabs = list.querySelectorAll("button");

    tabs[0].focus();
    tabs[0].dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    expect(document.activeElement).toBe(tabs[2]);
    expect(clicks[2]).toHaveBeenCalledTimes(1);

    tabs[2].dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
    expect(document.activeElement).toBe(tabs[0]);
    expect(clicks[0]).toHaveBeenCalledTimes(1);

    list.remove();
  });
});
