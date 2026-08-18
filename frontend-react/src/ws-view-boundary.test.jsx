import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectRequired, ViewErrorBoundary } from "./ws-view-boundary.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

describe("页面错误隔离", () => {
  let host;
  let root;
  let consoleError;

  beforeEach(() => {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    consoleError.mockRestore();
  });

  it("把渲染故障限制在当前页面并允许重试", async () => {
    let shouldThrow = true;
    const Boom = () => {
      if (shouldThrow) throw new Error("writer exploded");
      return <div>页面已恢复</div>;
    };
    const errors = [];
    const onError = (event) => errors.push(event.detail);
    window.addEventListener("ws:view-error", onError);

    await act(async () => {
      root.render(<ViewErrorBoundary resetKey="writer"><Boom /></ViewErrorBoundary>);
    });
    expect(host.querySelector('[data-testid="view-error-boundary"]')).not.toBeNull();
    expect(errors.at(-1)).toMatchObject({ message: "writer exploded", view: "writer" });

    shouldThrow = false;
    await act(async () => {
      host.querySelector(".btn-accent").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(host.textContent).toContain("页面已恢复");
    window.removeEventListener("ws:view-error", onError);
  });

  it("切换 resetKey 后自动清除上一模块的错误", async () => {
    const Boom = () => { throw new Error("broken"); };
    await act(async () => {
      root.render(<ViewErrorBoundary resetKey="scene"><Boom /></ViewErrorBoundary>);
    });
    await act(async () => {
      root.render(<ViewErrorBoundary resetKey="home"><div>主页正常</div></ViewErrorBoundary>);
    });
    expect(host.textContent).toContain("主页正常");
  });

  it("无当前作品时给出明确门控，并连通创建与返回动作", async () => {
    const onCreate = vi.fn();
    const onGoHome = vi.fn();
    await act(async () => {
      root.render(<ProjectRequired label="章节编排" onCreate={onCreate} onGoHome={onGoHome} />);
    });

    expect(host.textContent).toContain("章节编排");
    const buttons = [...host.querySelectorAll("button")];
    await act(async () => buttons[0].dispatchEvent(new MouseEvent("click", { bubbles: true })));
    await act(async () => buttons[1].dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onGoHome).toHaveBeenCalledTimes(1);
  });
});
