import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TweakRadio } from "./tweaks-panel.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root;
let host;

afterEach(async () => {
  if (root) await act(async () => root.unmount());
  if (host) host.remove();
  root = null;
  host = null;
});

describe("Tweaks 分段单选", () => {
  it("按钮指针事件与 click 不会重复提交同一次选择", async () => {
    const onChange = vi.fn();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => root.render(
      <TweakRadio
        label="稿纸宽度"
        value="narrow"
        options={[{ label: "窄", value: "narrow" }, { label: "宽", value: "wide" }]}
        onChange={onChange}
      />,
    ));

    const wide = host.querySelector('button[aria-label="宽"]');
    await act(async () => {
      wide.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, clientX: 20 }));
      wide.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("wide");
  });
});
