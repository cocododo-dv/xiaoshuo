// WsCatalog / WsTrashStore store 层单测：乐观写穿 + 失败回滚/告警。
// 与 ws-works.test.jsx 同款：mock lib/client.js，按 URL 路由喂确定性后端数据。
//
// 断言取向：只断「可观测结果」+「非去重的写动词调用」。store 的 catFetch/trashFetch 带
// in-flight 去重（并发时复用同一 promise、不再发请求），所以失败兜底是否「又发了一次 apiGet」
// 不可靠地依赖时序——改为断言回滚后的最终状态（标题被服务端原值覆盖）与 alert 触发，
// 它们对去重免疫且仍可证伪（破坏 catRecover 即转红）。所有 waitFor 给足超时以耐 CI 负载。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { installApiRouter, DEFAULT_TRASH } from "./test-helpers.js";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

// 等 active 从 __loading__ 翻成真实作品 id（写穿路径都依赖它确定）。
async function settleActive() {
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("tide"), T);
}

async function loadCatalog(opts) {
  const client = await import("./lib/client.js");
  installApiRouter(client, opts);
  const mod = await import("./ws-catalog.jsx");
  await settleActive();
  await vi.waitFor(() => expect(mod.WsCatalog.get().length).toBeGreaterThan(0), T);
  return { mod, client };
}

describe("WsCatalog（目录乐观写 + 失败回滚）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("renameScene 同步改缓存并 PATCH 到后端场景端点", async () => {
    const { mod, client } = await loadCatalog();
    const { WsCatalog } = mod;
    client.apiPatch.mockClear();

    WsCatalog.renameScene("ch01", "ch01s1", "新场景标题");

    // 乐观值同步可见（视图层零等待）
    expect(WsCatalog.sceneById("ch01s1").scene.title).toBe("新场景标题");

    // diff 引擎异步派发：只发变化字段，命中后端 scene_id（PATCH 不参与 fetch 去重）
    await vi.waitFor(() =>
      expect(client.apiPatch).toHaveBeenCalledWith(
        "/api/v2/projects/tide/catalog/scenes/s1",
        { title: "新场景标题" }
      ), T);
  });

  it("PATCH 失败时告警并以服务端为准回滚乐观改动", async () => {
    const { mod, client } = await loadCatalog();
    const { WsCatalog } = mod;
    client.apiPatch.mockRejectedValueOnce(new Error("boom"));

    WsCatalog.renameScene("ch01", "ch01s1", "会被回滚的标题");
    expect(WsCatalog.sceneById("ch01s1").scene.title).toBe("会被回滚的标题");

    // 失败 → catRecover：window.alert（仅此路径调用，强可证伪）
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T);
    // 且最终以服务端原值（"交班"）覆盖乐观值——回滚到位
    await vi.waitFor(() =>
      expect(WsCatalog.sceneById("ch01s1").scene.title).toBe("交班"), T);
  });
});

describe("WsTrashStore（回收站乐观恢复 + 失败告警）", () => {
  async function loadTrash() {
    const client = await import("./lib/client.js");
    installApiRouter(client, { trash: [DEFAULT_TRASH] });
    const mod = await import("./ws-catalog.jsx");
    await settleActive();
    await vi.waitFor(() => expect(mod.WsTrashStore.list().length).toBeGreaterThan(0), T);
    return { mod, client };
  }

  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("restore 调用后端 restore 端点（id 经 encodeURIComponent）", async () => {
    const { mod, client } = await loadTrash();
    client.apiPost.mockClear();

    const ok = mod.WsTrashStore.restore("scene:s9");
    expect(ok).toBe(true); // 乐观返回

    await vi.waitFor(() =>
      expect(client.apiPost).toHaveBeenCalledWith("/api/v2/trash/scene%3As9/restore", {}), T);
  });

  it("restore 失败时告警", async () => {
    const { mod, client } = await loadTrash();
    client.apiPost.mockRejectedValueOnce(new Error("restore failed"));

    mod.WsTrashStore.restore("scene:s9");

    // 失败兜底：restore().catch 调 window.alert（强可证伪）
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T);
  });
});
