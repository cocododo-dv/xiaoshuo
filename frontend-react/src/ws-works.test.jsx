// React 主线首个 store 层单测：WsWorks 乐观写 + 失败回滚。
// mock client 模块（比 mock fetch 干净——store 只消费 verb 返回的 promise）。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// vi.mock 被提升到 import 之上；factory 不得引用外部变量。
vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

// 在 mock 就位后再动态载入 store，拿到「全新」模块实例（module 级 WS_WORKS 复位）。
async function loadStore() {
  const client = await import("./lib/client.js");
  // 导入即触发的 wsRefresh() 会 apiGet("/api/v2/projects")；返回空 items 使其 no-op。
  client.apiGet.mockResolvedValue({ items: [] });
  client.apiPatch.mockResolvedValue({});
  client.apiPost.mockResolvedValue({});
  client.apiDelete.mockResolvedValue({});
  const mod = await import("./ws-works.jsx");
  return { mod, client };
}

describe("WsWorks.update (optimistic write + rollback)", () => {
  beforeEach(() => {
    vi.resetModules(); // 每个用例拿到全新 module 级 WS_WORKS
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {}); // wsToastError -> alert
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("applies the optimistic profile change immediately", async () => {
    const { mod } = await loadStore();
    const { WsWorks } = mod;

    const before = WsWorks.list()[0];
    expect(before).toBeTruthy();

    WsWorks.update(before.id, { title: "新书名" });

    expect(WsWorks.list().find((w) => w.id === before.id).title).toBe("新书名");
  });

  it("rolls back to the prior value when the PATCH rejects", async () => {
    const { mod, client } = await loadStore();
    const { WsWorks } = mod;

    const before = WsWorks.list()[0];
    const originalTitle = before.title;

    client.apiPatch.mockRejectedValueOnce(new Error("boom"));

    WsWorks.update(before.id, { title: "会被回滚的标题" });

    // 乐观值同步可见
    expect(WsWorks.list().find((w) => w.id === before.id).title).toBe("会被回滚的标题");

    // 等待被拒的 apiPatch microtask + .catch 回滚
    await vi.waitFor(() => {
      expect(WsWorks.list().find((w) => w.id === before.id).title).toBe(originalTitle);
    });

    expect(client.apiPatch).toHaveBeenCalledWith(
      `/api/v2/projects/${before.id}/profile`,
      { title: "会被回滚的标题" }
    );
    expect(window.alert).toHaveBeenCalled(); // 失败时 wsToastError 触发
  });
});
