import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(), apiPost: vi.fn(), apiPatch: vi.fn(), apiDelete: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function flushPromises() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function changeTextarea(node, value) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
  await act(async () => {
    setter.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function loadNotes() {
  const client = await import("./lib/client.js");
  const { WsCatalog } = await import("./ws-catalog.jsx");
  vi.spyOn(WsCatalog, "__backendSceneId").mockImplementation(async (scene) => `backend-${scene}`);
  const { WrCtxNotes } = await import("./ws-writer.jsx");
  return { client, WrCtxNotes };
}

describe("写作台场景笔记的异步隔离", () => {
  let host;
  let root;

  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    window.localStorage.clear();
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    host.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("切换场景后不会把旧场景排队中的保存写到新场景", async () => {
    const firstPatch = deferred();
    const { client, WrCtxNotes } = await loadNotes();
    client.apiGet.mockResolvedValue({ notes: "", revision_no: 1 });
    client.apiPatch.mockImplementationOnce(() => firstPatch.promise);

    await act(async () => root.render(<WrCtxNotes scene="scene-a" />));
    await flushPromises();
    const textarea = host.querySelector("textarea");

    await changeTextarea(textarea, "first edit");
    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });
    expect(client.apiPatch).toHaveBeenCalledTimes(1);

    await changeTextarea(textarea, "queued edit");
    await act(async () => {
      vi.advanceTimersByTime(500);
      await Promise.resolve();
    });
    await act(async () => root.render(<WrCtxNotes scene="scene-b" />));
    await flushPromises();

    firstPatch.resolve({ revision_no: 2 });
    await flushPromises();

    expect(client.apiPatch).toHaveBeenCalledTimes(1);
    expect(client.apiPatch.mock.calls[0][0]).toBe("/api/v1/scenes/backend-scene-a/author-notes");
    expect(client.apiPatch.mock.calls.some(([url]) => url.includes("backend-scene-b"))).toBe(false);
    expect([...Array(window.localStorage.length).keys()]
      .map((index) => window.localStorage.key(index))
      .some((key) => key.startsWith("wr-notes-pending:scene-a"))).toBe(true);
  });

  it("服务器初始读取晚到时不会覆盖用户刚输入的本地笔记", async () => {
    const initialLoad = deferred();
    const { client, WrCtxNotes } = await loadNotes();
    client.apiGet.mockImplementation(() => initialLoad.promise);

    await act(async () => root.render(<WrCtxNotes scene="scene-a" />));
    await flushPromises();
    const textarea = host.querySelector("textarea");
    await changeTextarea(textarea, "local draft");

    initialLoad.resolve({ notes: "server note", revision_no: 4 });
    await flushPromises();

    expect(textarea.value).toBe("local draft");
    expect([...Array(window.localStorage.length).keys()]
      .map((index) => window.localStorage.key(index))
      .some((key) => key.startsWith("wr-notes-pending:scene-a"))).toBe(true);
  });
});
