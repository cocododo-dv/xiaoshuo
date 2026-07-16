import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const catalogState = vi.hoisted(() => ({ ready: false, chapters: [], error: null }));

vi.mock("./ws-catalog.jsx", () => ({
  WsCatalog: {
    ready: vi.fn(() => catalogState.ready),
    loadError: vi.fn(() => catalogState.error),
    get: vi.fn(() => catalogState.chapters),
    set: vi.fn(),
    __refresh: vi.fn(async () => {}),
    addChapter: vi.fn(),
  },
  useCatalogChapters: () => catalogState.chapters,
}));

vi.mock("./ws-works.jsx", () => ({
  wsKey: (key) => key,
  WsWorks: {
    activeId: () => "project-1",
    active: () => ({ id: "project-1", title: "测试作品" }),
  },
}));

vi.mock("./ws-chapter-run.jsx", () => ({
  ArrChapterRunAction: () => <button type="button">运行本章</button>,
}));

import { WsCatalog } from "./ws-catalog.jsx";
import { WsAuthor } from "./ws-author.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let host;
let root;

beforeEach(() => {
  localStorage.clear();
  catalogState.ready = false;
  catalogState.chapters = [];
  catalogState.error = null;
  vi.clearAllMocks();
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("章节编排 · 服务端目录真相", () => {
  it("冷启动目录未就绪时只显示加载态，绝不把空数组写回覆盖服务端", async () => {
    await act(async () => root.render(<WsAuthor />));

    expect(host.textContent).toContain("正在从服务端加载章节目录");
    expect(WsCatalog.set).not.toHaveBeenCalled();

    catalogState.ready = true;
    catalogState.chapters = [{
      id: "ch01",
      backendId: "chapter-1",
      act: "act1",
      title: "服务端真实章节",
      state: "writing",
      current: true,
      tension: 0.3,
      words: { cur: 0, target: 4000 },
      drama: {},
      threads: [],
      scenes: [],
    }];
    await act(async () => root.render(<WsAuthor />));

    expect(host.textContent).toContain("服务端真实章节");
    expect(WsCatalog.set).not.toHaveBeenCalled();
  });

  it("已批准终稿在编排台全字段只读，并引导先重新打开", async () => {
    localStorage.setItem("arr.mode", JSON.stringify("detail"));
    localStorage.setItem("arr.picked", JSON.stringify("ch01"));
    catalogState.ready = true;
    catalogState.chapters = [{
      id: "ch01",
      backendId: "chapter-1",
      act: "act1",
      title: "锁定章节",
      state: "approved",
      current: false,
      tension: 0.5,
      pov: "林岑",
      words: { cur: 1200, target: 4000 },
      drama: { promise: "承诺", spine: "推进", arc: "转变", problem: "问题", aftertaste: "余味", ending: "章末", forbidden: "无", notes: "备注" },
      threads: [],
      scenes: [{ sid: "s1", backendId: "scene-1", title: "锁定场景", kind: "主动", state: "done", goal: "目标", obstacle: "阻碍", turn: "出口" }],
    }];

    await act(async () => root.render(<WsAuthor />));

    expect(host.textContent).toContain("章节结构与场景卡均为只读");
    expect(host.querySelector('input[aria-label="章节标题"]')).toHaveProperty("disabled", true);
    expect(host.querySelector('input[aria-label="场景标题"]')).toHaveProperty("disabled", true);
    expect([...host.querySelectorAll("button")].find((node) => node.textContent.includes("新场景"))).toHaveProperty("disabled", true);
    expect(WsCatalog.set).not.toHaveBeenCalled();
  });

  it("目录请求失败与真空作品分开呈现，并提供真实重试", async () => {
    catalogState.error = new Error("network down");
    await act(async () => root.render(<WsAuthor />));

    expect(host.textContent).toContain("章节目录加载失败");
    expect(host.textContent).not.toContain("还没有章节结构");
    const retry = [...host.querySelectorAll("button")].find((node) => node.textContent.includes("重试加载"));
    await act(async () => retry.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(WsCatalog.__refresh).toHaveBeenCalledTimes(1);
    expect(WsCatalog.set).not.toHaveBeenCalled();
  });
});
