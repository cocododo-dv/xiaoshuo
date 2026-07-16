import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fixture = vi.hoisted(() => ({ catalog: [], projectId: "p1" }));
const flow = vi.hoisted(() => ({
  refresh: vi.fn().mockResolvedValue({}),
  body: vi.fn(() => null),
  snapshot: vi.fn(),
  aggregate: vi.fn().mockResolvedValue({ status: "created" }),
  setReviewState: vi.fn().mockResolvedValue({}),
  confirmRead: vi.fn().mockResolvedValue({ body_hash: "hash-1" }),
  approveFinal: vi.fn().mockResolvedValue({ approved_chapter_id: "c1" }),
  reopenFinal: vi.fn().mockResolvedValue({ reopened_chapter_id: "c1" }),
}));
const catalogRefresh = vi.hoisted(() => vi.fn().mockResolvedValue({}));
const worksRefresh = vi.hoisted(() => vi.fn().mockResolvedValue({}));

vi.mock("./ws-catalog.jsx", () => ({
  WsCatalog: {
    get: () => fixture.catalog,
    __refresh: catalogRefresh,
  },
  useCatalogChapters: () => fixture.catalog,
}));
vi.mock("./ws-works.jsx", () => ({
  WsWorks: {
    activeId: () => fixture.projectId,
    active: () => ({ id: fixture.projectId, title: "测试长篇", genre: "悬疑", wordsTarget: 100000, chaptersTotal: 2 }),
    __refresh: worksRefresh,
  },
}));
vi.mock("./ws-review.jsx", () => ({ rvPush: vi.fn() }));
vi.mock("./ws-manuscripts-store.jsx", () => ({
  WsManuStore: flow,
  manuscriptChapterEligible: () => true,
  manuscriptDisplayState: (state) => state,
}));

import { WsManuscripts } from "./ws-manuscripts.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const mounted = [];

function chapter(state) {
  return {
    id: "ch01", backendId: "c1", n: "01", title: "盐场的早班", state,
    current: true, words: { cur: 3600, target: 4000 }, approvedAt: state === "approved" ? Date.now() : null,
    scenes: [{ sid: "ch01s1", backendId: "s1", title: "交班", state: "done" }],
  };
}

const COMPLETE_BODY = {
  completion: "complete",
  missingSceneIds: [],
  scenes: [{ sceneId: "s1", live: true, paras: ["潮水退去，她看清了闸门上的名字。"] }],
};

function readySnapshot(body = COMPLETE_BODY) {
  return { status: "ready", body, error: null };
}

async function renderPage(state) {
  fixture.catalog = [chapter(state)];
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  mounted.push({ root, host });
  await act(async () => root.render(<WsManuscripts go={vi.fn()} />));
  await act(async () => Promise.resolve());
  return host;
}

async function click(node) {
  await act(async () => node.click());
  await act(async () => Promise.resolve());
}

async function typeTextarea(node, value) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
  await act(async () => {
    setter.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  fixture.projectId = "p1";
  flow.refresh.mockResolvedValue({});
  flow.body.mockReturnValue(COMPLETE_BODY);
  flow.snapshot.mockReturnValue(readySnapshot());
  flow.setReviewState.mockResolvedValue({});
  flow.confirmRead.mockResolvedValue({ body_hash: "hash-1" });
  flow.approveFinal.mockResolvedValue({ approved_chapter_id: "c1" });
  flow.reopenFinal.mockResolvedValue({ reopened_chapter_id: "c1" });
  catalogRefresh.mockResolvedValue({});
  worksRefresh.mockResolvedValue({});
  delete window.WrDocVersions;
});

afterEach(async () => {
  while (mounted.length) {
    const { root, host } = mounted.pop();
    await act(async () => root.unmount());
    host.remove();
  }
});

describe("成稿中心权威章节流", () => {
  it("批准按钮先要求逐项通读确认，再按 read-confirm → approve-final 顺序提交", async () => {
    const host = await renderPage("review");
    await click(host.querySelector('[data-testid="approve-final-open"]'));

    const check = host.querySelector('[data-testid="approve-read-confirm"]');
    const confirm = host.querySelector('[data-testid="approve-final-confirm"]');
    expect(host.querySelector('[role="dialog"]').textContent).toContain("绑定当前服务端正文哈希");
    expect(confirm.disabled).toBe(true);

    await click(check);
    expect(confirm.disabled).toBe(false);
    await click(confirm);

    expect(flow.confirmRead).toHaveBeenCalledWith("p1", "c1", "");
    expect(flow.approveFinal).toHaveBeenCalledWith("p1", "c1", "");
    expect(flow.confirmRead.mock.invocationCallOrder[0]).toBeLessThan(flow.approveFinal.mock.invocationCallOrder[0]);
    expect(catalogRefresh).toHaveBeenCalledWith("p1");
  });

  it("重新打开终稿必须填写审计理由，不能直接做本地状态回滚", async () => {
    const host = await renderPage("approved");
    await click(host.querySelector('[data-testid="reopen-final-open"]'));

    const confirm = host.querySelector('[data-testid="reopen-final-confirm"]');
    const area = host.querySelector('textarea[placeholder*="打破终稿锁"]');
    expect(confirm.disabled).toBe(true);
    expect(host.querySelector('[role="dialog"]').textContent).toContain("后已批准章节会失效");

    await typeTextarea(area, "第三场时间线需要纠正");
    expect(confirm.disabled).toBe(false);
    await click(confirm);

    expect(flow.reopenFinal).toHaveBeenCalledWith("p1", "c1", "第三场时间线需要纠正");
    expect(catalogRefresh).toHaveBeenCalledWith("p1");
  });

  it("送入审阅等待服务端目录 PATCH 成功后再刷新权威目录", async () => {
    const host = await renderPage("draft");
    const button = [...host.querySelectorAll("button")].find((node) => node.textContent.includes("送入审阅"));
    await click(button);

    expect(flow.setReviewState).toHaveBeenCalledWith("p1", "c1", "review");
    expect(catalogRefresh).toHaveBeenCalledWith("p1");
    expect(host.textContent).toContain("状态已由服务端确认");
  });

  it("服务端正文失败时显示错误与重试，潮汐演示章也不回退示例正文", async () => {
    fixture.projectId = "tide";
    flow.snapshot.mockReturnValue({
      status: "error",
      body: null,
      error: { code: "UPSTREAM_DOWN", message: "成稿服务暂时不可用" },
    });
    flow.body.mockReturnValue(null);

    const host = await renderPage("review");

    expect(host.textContent).toContain("服务端正文加载失败");
    expect(host.textContent).toContain("成稿服务暂时不可用");
    expect(host.textContent).not.toContain("纸箱在阁楼上放了十二年");
    expect(host.querySelector('[data-testid="approve-final-open"]').disabled).toBe(true);

    const callsBeforeRetry = flow.refresh.mock.calls.length;
    await click(host.querySelector('[data-testid="manuscript-retry"]'));
    expect(flow.refresh).toHaveBeenCalledTimes(callsBeforeRetry + 1);
  });

  it("部分稿保留缺失场景占位，不显示章节结束且关闭送审/批准", async () => {
    const partial = {
      completion: "partial",
      missingSceneIds: ["s1"],
      scenes: [{ sceneId: "s1", live: false, paras: [] }],
    };
    flow.snapshot.mockReturnValue(readySnapshot(partial));
    flow.body.mockReturnValue(partial);

    const host = await renderPage("review");

    expect(host.textContent).toContain("这一场尚无服务端归档正文");
    expect(host.textContent).not.toContain("章节结束");
    expect(host.querySelector('[data-testid="approve-final-open"]').disabled).toBe(true);
  });

  it("本章导出会二次核验，服务端失败后显示失败且不下载", async () => {
    const host = await renderPage("approved");
    const button = host.querySelector('[data-testid="chapter-export"]');
    expect(button.disabled).toBe(false);

    flow.snapshot.mockReturnValue({ status: "error", body: null, error: { message: "导出前正文核验失败" } });
    await click(button);

    expect(host.textContent).toContain("导出前正文核验失败");
    expect(button.textContent).toContain("导出本章");
  });

  it("本章导出忙碌期间防双击，只发起一次服务端核验", async () => {
    const host = await renderPage("approved");
    flow.refresh.mockClear();
    let resolveRefresh;
    flow.refresh.mockReturnValueOnce(new Promise(resolve => { resolveRefresh = resolve; }));
    const button = host.querySelector('[data-testid="chapter-export"]');

    await act(async () => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(flow.refresh).toHaveBeenCalledTimes(1);
    expect(button.disabled).toBe(true);
    expect(button.textContent).toContain("导出中");

    await act(async () => {
      resolveRefresh({});
      await Promise.resolve();
      await Promise.resolve();
    });
  });

  it("版本历史请求失败会显示错误并可重试", async () => {
    window.WrDocVersions = {
      list: vi.fn()
        .mockRejectedValueOnce(new Error("版本服务暂时不可用"))
        .mockResolvedValueOnce([]),
      paras: vi.fn(),
      diff: vi.fn(),
    };
    const host = await renderPage("review");
    const diffTab = [...host.querySelectorAll("button")].find(node => node.textContent === "对比");
    await click(diffTab);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(host.textContent).toContain("版本服务暂时不可用");
    await click(host.querySelector('[data-testid="manuscript-diff-history-retry"]'));
    expect(window.WrDocVersions.list).toHaveBeenCalledTimes(2);
  });
});
