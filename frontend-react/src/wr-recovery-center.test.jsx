import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { installApiRouter } from "./test-helpers.js";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const T = { timeout: 5000, interval: 25 };
const mounted = [];

async function loadRecovery() {
  const client = await import("./lib/client.js");
  installApiRouter(client);
  client.apiPost.mockImplementation((url) => {
    if (/\/author-drafts\/scene\/.+\/ensure$/.test(url)) {
      return Promise.resolve({ draft: { draft_id: "d1", revision_no: 1, content: "" } });
    }
    return Promise.resolve({});
  });
  client.apiPatch.mockImplementation((url, body) => Promise.resolve({
    draft: { draft_id: "d1", revision_no: 2, content: body.content },
  }));
  await import("./ws-catalog.jsx");
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("prj-main"), T);
  await vi.waitFor(() => expect(window.WsCatalog.get().length).toBeGreaterThan(0), T);
  const store = await import("./wr-doc-store.jsx");
  const ui = await import("./wr-recovery-center.jsx");
  return { ...store, ...ui, client };
}

async function renderCenter(Component) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  await act(async () => root.render(<Component />));
  return host;
}

async function click(node) {
  await act(async () => node.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

beforeEach(() => {
  vi.resetModules();
  window.localStorage.clear();
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(async () => {
  while (mounted.length) {
    const { root, host } = mounted.pop();
    await act(async () => root.unmount());
    host.remove();
  }
  vi.restoreAllMocks();
});

describe("同步与恢复中心", () => {
  it("冲突/候选可发现、可看差异、可复制，Esc 关闭后焦点回到入口", async () => {
    const { WrRecovery, WrRecoveryCenter } = await loadRecovery();
    window.localStorage.setItem(window.wsKey("wr-doc:ch01s1"), "<p>作者当前正文。</p>");
    WrRecovery.createCandidate("ch01s1", "<p>AI 候选正文。</p>");
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", { configurable: true, value: { writeText } });

    const host = await renderCenter(WrRecoveryCenter);
    const trigger = host.querySelector(".wrr-trigger");
    expect(trigger.getAttribute("aria-label")).toContain("有 1 份恢复记录");
    await click(trigger);

    const dialog = host.querySelector('[role="dialog"]');
    expect(dialog).toBeTruthy();
    expect(dialog.textContent).toContain("AI 候选正文");
    expect(dialog.textContent).toContain("作者当前正文");
    await vi.waitFor(() => expect(document.activeElement?.getAttribute("aria-label")).toBe("关闭同步与恢复中心"), T);

    await click([...dialog.querySelectorAll("button")].find(button => button.textContent.includes("复制正文")));
    expect(writeText).toHaveBeenCalledWith("AI 候选正文。");

    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    await vi.waitFor(() => expect(document.activeElement).toBe(trigger), T);
  });

  it("重试同步走 author-drafts 乐观并发保存，成功后从恢复列表移除", async () => {
    const { WrRecovery, WrRecoveryCenter, client } = await loadRecovery();
    WrRecovery.create({ sid: "ch01s1", html: "<p>断网留下的正文。</p>", type: "unsynced", reason: "网络中断" });
    const host = await renderCenter(WrRecoveryCenter);
    await click(host.querySelector(".wrr-trigger"));
    const retry = [...host.querySelectorAll("button")].find(button => button.textContent.includes("重试同步"));
    await click(retry);

    await vi.waitFor(() => expect(client.apiPatch).toHaveBeenCalledWith(
      "/api/v1/author-drafts/d1",
      { content: "<p>断网留下的正文。</p>", base_revision_no: 1 },
    ), T);
    await vi.waitFor(() => expect(WrRecovery.list()).toEqual([]), T);
    expect(host.textContent).toContain("没有待恢复稿件");
  });
});
