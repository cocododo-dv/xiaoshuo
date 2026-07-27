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
    removeChapters: vi.fn(),
    removeScenes: vi.fn(),
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

/* 一章的最小合法形状（视图直接读 words/drama/threads/scenes，缺一即崩） */
function chapter(id, title, extra = {}) {
  return {
    id,
    backendId: "backend-" + id,
    act: "act1",
    title,
    state: "writing",
    current: false,
    tension: 0.3,
    words: { cur: 0, target: 4000 },
    drama: {},
    threads: [],
    scenes: [],
    ...extra,
  };
}

const click = (node) => node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
const byText = (selector, text) => [...host.querySelectorAll(selector)].find((node) => node.textContent.includes(text));

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

  it("全书编排多选批量删章：一次 set() 摘掉所选，已批准终稿不可勾选", async () => {
    catalogState.ready = true;
    catalogState.chapters = [chapter("ch01", "第一章"), chapter("ch02", "第二章"), chapter("ch03", "锁定章", { state: "approved" })];
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    await act(async () => root.render(<WsAuthor />));

    await act(async () => click(byText("button", "多选")));
    const boxes = [...host.querySelectorAll('.arr-card-check input')];
    expect(boxes).toHaveLength(3);
    expect(boxes[2]).toHaveProperty("disabled", true);       // 已批准终稿：勾不动

    await act(async () => { boxes[0].click(); });
    await act(async () => { boxes[1].click(); });
    expect(host.textContent).toContain("已选 2 / 2 章");

    await act(async () => click(host.querySelector('[data-testid="author-batch-delete-chapters"]')));

    expect(confirmSpy).toHaveBeenCalled();
    expect(WsCatalog.set).toHaveBeenCalledTimes(1);
    expect(WsCatalog.set.mock.calls[0][0].map((c) => c.id)).toEqual(["ch03"]);
  });

  it("多选是独占模式：进入后头部不再摆新建/切视图，删完给出回收站回执", async () => {
    catalogState.ready = true;
    catalogState.chapters = [chapter("ch01", "第一章"), chapter("ch02", "第二章")];
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const go = vi.fn();
    await act(async () => root.render(<WsAuthor go={go} />));

    expect(byText("button", "新建章节")).toBeTruthy();
    await act(async () => click(byText("button", "多选")));

    // 选择态里只剩「选择」这一件事：与选择无关的动作全部收起
    expect(byText("button", "新建章节")).toBeUndefined();
    expect(byText("button", "章节详情")).toBeUndefined();
    expect(host.querySelector('[data-testid="author-chapter-select-exit"]')).toBeTruthy();

    await act(async () => { host.querySelector(".arr-card-check input").click(); });
    await act(async () => click(host.querySelector('[data-testid="author-batch-delete-chapters"]')));

    // 删完给回执，并把「东西去哪了」指出来
    const toast = host.querySelector('[data-testid="undo-toast"]');
    expect(toast.textContent).toContain("移入回收站");
    await act(async () => click(toast.querySelector('[data-testid="undo-toast-action"]')));
    expect(go).toHaveBeenCalledWith("trash");
    // 删除完成即退出多选，头部动作回来
    expect(byText("button", "新建章节")).toBeTruthy();
  });

  it("场景多选态下行内编辑与分流按钮全部收起，避免一次点击有四种含义", async () => {
    localStorage.setItem("arr.mode", JSON.stringify("detail"));
    localStorage.setItem("arr.picked", JSON.stringify("ch01"));
    catalogState.ready = true;
    catalogState.chapters = [chapter("ch01", "第一章", {
      scenes: [{ sid: "s1", backendId: "b1", title: "开场", kind: "主动", state: "todo", goal: "", obstacle: "", turn: "" }],
    })];
    await act(async () => root.render(<WsAuthor />));

    expect(byText("button", "交给 AI")).toBeTruthy();
    expect(host.querySelector('input[aria-label="场景标题"]')).toHaveProperty("disabled", false);

    await act(async () => click(host.querySelector('[data-testid="author-scene-select-mode"]')));

    expect(byText("button", "交给 AI")).toBeUndefined();
    expect(byText("button", "自己写")).toBeUndefined();
    expect(host.querySelector(".arr-scene-more")).toBeNull();
    expect(host.querySelector('input[aria-label="场景标题"]')).toHaveProperty("disabled", true);
  });

  it("批量删除被作者取消时不写目录（confirm 是真闸门，不是装饰）", async () => {
    catalogState.ready = true;
    catalogState.chapters = [chapter("ch01", "第一章"), chapter("ch02", "第二章")];
    vi.spyOn(window, "confirm").mockReturnValue(false);
    await act(async () => root.render(<WsAuthor />));

    await act(async () => click(byText("button", "多选")));
    await act(async () => { host.querySelector(".arr-card-check input").click(); });
    await act(async () => click(host.querySelector('[data-testid="author-batch-delete-chapters"]')));

    expect(WsCatalog.set).not.toHaveBeenCalled();
  });

  it("章节详情场景看板多选批量删场：只摘本章所选场景", async () => {
    localStorage.setItem("arr.mode", JSON.stringify("detail"));
    localStorage.setItem("arr.picked", JSON.stringify("ch01"));
    catalogState.ready = true;
    catalogState.chapters = [chapter("ch01", "第一章", {
      scenes: [
        { sid: "s1", backendId: "b1", title: "开场", kind: "主动", state: "todo", goal: "", obstacle: "", turn: "" },
        { sid: "s2", backendId: "b2", title: "追击", kind: "主动", state: "todo", goal: "", obstacle: "", turn: "" },
        { sid: "s3", backendId: "b3", title: "收束", kind: "主动", state: "todo", goal: "", obstacle: "", turn: "" },
      ],
    })];
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await act(async () => root.render(<WsAuthor />));

    await act(async () => click(host.querySelector('[data-testid="author-scene-select-mode"]')));
    const boxes = [...host.querySelectorAll(".arr-scene-check input")];
    expect(boxes).toHaveLength(3);
    await act(async () => { boxes[0].click(); });
    await act(async () => { boxes[2].click(); });
    expect(host.textContent).toContain("已选 2 / 3 场");

    await act(async () => click(host.querySelector('[data-testid="author-batch-delete-scenes"]')));

    expect(WsCatalog.set).toHaveBeenCalledTimes(1);
    expect(WsCatalog.set.mock.calls[0][0][0].scenes.map((s) => s.sid)).toEqual(["s2"]);
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
