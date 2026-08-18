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
async function loadStore(items = [{ project_id: "p1", title: "Test Project", stats: {} }]) {
  const client = await import("./lib/client.js");
  client.apiGet.mockImplementation((url) => (
    url === "/api/v2/projects" ? Promise.resolve({ items }) : Promise.resolve({})
  ));
  client.apiPatch.mockResolvedValue({});
  client.apiPost.mockResolvedValue({});
  client.apiDelete.mockResolvedValue({});
  const mod = await import("./ws-works.jsx");
  await vi.waitFor(() => expect(mod.WsWorks.status().projects.phase).toBe("ready"));
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

describe("WsWorks 远端状态（内联失败与重试契约）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("后端确认空书架后清除加载占位，且不请求伪 dashboard", async () => {
    window.localStorage.setItem("ws_active_work_v1", "stale-project");
    const client = await import("./lib/client.js");
    client.apiGet.mockResolvedValue({ items: [] });

    const { WsWorks } = await import("./ws-works.jsx");

    await vi.waitFor(() => expect(WsWorks.status().projects.phase).toBe("ready"));
    expect(WsWorks.list()).toEqual([]);
    expect(WsWorks.activeId()).toBe("");
    expect(WsWorks.active()).toMatchObject({ id: "", title: "还没有作品" });
    expect(window.localStorage.getItem("ws_active_work_v1")).toBeNull();
    expect(client.apiGet).toHaveBeenCalledTimes(1);
    expect(client.apiGet).toHaveBeenCalledWith("/api/v2/projects");
  });

  it("清除可丢弃的作品缓存后仍恢复用户选中的作品", async () => {
    window.localStorage.setItem("ws_active_work_v1", "p2");
    const client = await import("./lib/client.js");
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v2/projects") {
        return Promise.resolve({
          items: [
            { project_id: "p1", title: "First", stats: {} },
            { project_id: "p2", title: "Selected", stats: {} },
          ],
        });
      }
      return Promise.resolve({});
    });

    const { WsWorks } = await import("./ws-works.jsx");

    await vi.waitFor(() => expect(WsWorks.status().projects.phase).toBe("ready"));
    expect(WsWorks.activeId()).toBe("p2");
    expect(WsWorks.active().title).toBe("Selected");
  });

  it("作品列表断网时保留缓存并暴露可重试 error，成功后收敛 ready", async () => {
    const client = await import("./lib/client.js");
    const offline = Object.assign(new Error("无法连接作品服务"), { code: "NETWORK_ERROR" });
    client.apiGet.mockRejectedValueOnce(offline);
    const { WsWorks } = await import("./ws-works.jsx");

    await vi.waitFor(() => expect(WsWorks.status().projects.phase).toBe("error"));
    expect(WsWorks.status().projects.error).toMatchObject({ code: "NETWORK_ERROR", message: "无法连接作品服务" });
    expect(WsWorks.list().length).toBeGreaterThan(0); // 本地缓存 / 加载影子仍可渲染

    client.apiGet.mockResolvedValue({ items: [] });
    await WsWorks.retry("projects");
    expect(WsWorks.status().projects).toMatchObject({ phase: "ready", error: null });
  });

  it("dashboard 失败单独标记，不把项目列表误报失败；retry 只重拉当前主页", async () => {
    const client = await import("./lib/client.js");
    const project = {
      project_id: "p1", title: "离线书稿", genre: "悬疑", mark: "离", accent: "sage",
      stats: { words_total: 12, words_today: 3, streak_days: 1 },
    };
    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v2/projects") return Promise.resolve({ items: [project] });
      if (url === "/api/v2/projects/p1/dashboard") return Promise.reject(new Error("dashboard timeout"));
      return Promise.resolve({});
    });
    const { WsWorks } = await import("./ws-works.jsx");
    await vi.waitFor(() => expect(WsWorks.status("p1").dashboard.phase).toBe("error"));
    expect(WsWorks.status("p1").projects.phase).toBe("ready");

    client.apiGet.mockImplementation((url) => {
      if (url === "/api/v2/projects/p1/dashboard") return Promise.resolve({ stats: { words_total: 99 }, chapters_recent: [] });
      return Promise.resolve({ items: [project] });
    });
    await WsWorks.retry("dashboard", "p1");
    expect(WsWorks.status("p1").dashboard.phase).toBe("ready");
    expect(WsWorks.active().wordsTotal).toBe(99);
  });

  it("离线缓存不会复活已退役的演示作品", async () => {
    window.localStorage.setItem("ws_active_work_v1", "tide");
    window.localStorage.setItem("ws_works_cache_v1", JSON.stringify([
      { id: "tide", title: "退役演示一" },
      { id: "salt", title: "退役演示二" },
      { id: "project-real", title: "作者作品", home: { blank: true } },
    ]));
    const client = await import("./lib/client.js");
    client.apiGet.mockRejectedValue(new Error("offline"));

    const { WsWorks } = await import("./ws-works.jsx");

    await vi.waitFor(() => expect(WsWorks.status().projects.phase).toBe("error"));
    expect(WsWorks.list().map((work) => work.id)).toEqual(["project-real"]);
    expect(WsWorks.activeId()).toBe("project-real");
  });
});
