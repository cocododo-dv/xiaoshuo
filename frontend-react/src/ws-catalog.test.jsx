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

// adoptOutline 的物化主路径依赖真实 SnowSync（ws-snow-sync.jsx），后者仅从 ws-snow.jsx
// 取 S2_BE_STEPS（FE↔BE 步骤映射，与 materialize / readyToMaterialize 无关）。把它 mock 成空，
// 避免为测 store 契约而拉入整张雪花视图模块。
vi.mock("./ws-snow.jsx", () => ({ S2_BE_STEPS: [] }));

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

  it("设 povName 经 set() diff 只 PATCH pov_character_name（POV 设置入口契约）", async () => {
    const { mod, client } = await loadCatalog();
    const { WsCatalog } = mod;
    client.apiPatch.mockClear();

    const next = WsCatalog.get().map((c) =>
      c.id === "ch01"
        ? { ...c, scenes: c.scenes.map((s) => (s.sid === "ch01s1" ? { ...s, povName: "林深" } : s)) }
        : c);
    WsCatalog.set(next);

    // 乐观值同步可见
    expect(WsCatalog.sceneById("ch01s1").scene.povName).toBe("林深");
    // diff 只发 pov_character_name（后端按名 find-or-create），命中后端 scene_id
    await vi.waitFor(() =>
      expect(client.apiPatch).toHaveBeenCalledWith(
        "/api/v2/projects/tide/catalog/scenes/s1",
        { pov_character_name: "林深" }
      ), T);
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

describe("WsCatalog.adoptOutline（雪花大纲→目录：物化主路径，QA3 fix(snow-sync)）", () => {
  // 装好目录 + 真实 SnowSync，并把 snowflake-workspace 的 ready 闸门置为指定值。
  // 物化路径是「服务端权威 + reset 重拉」，无乐观写可回滚——失败契约是"诚实上抛"，
  // 由调用方（ws-snow.jsx）兜 alert；故这里断言上抛而非本地回滚。
  async function loadWithSnow(ready) {
    const client = await import("./lib/client.js");
    installApiRouter(client, { snowflakeWorkspace: { ready_to_materialize: ready, steps: [] } });
    const mod = await import("./ws-catalog.jsx");
    const snow = await import("./ws-snow-sync.jsx");
    await settleActive();
    await vi.waitFor(() => expect(mod.WsCatalog.get().length).toBeGreaterThan(0), T);
    await snow.SnowSync.refetch("tide"); // 同步 snowReadyFlags["tide"]
    return { mod, client, snow };
  }

  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
    try { delete window.SnowSync; } catch (e) {}
  });
  afterEach(() => vi.restoreAllMocks());

  it("闸门满足 → 走 materialize 两步并回传后端真实 created_chapter_count", async () => {
    const { mod, client } = await loadWithSnow(true);
    expect(window.SnowSync.readyToMaterialize("tide")).toBe(true);

    const calls = [];
    client.apiPost.mockImplementation((url) => {
      calls.push(url);
      // /materialize 只建 pending 大纲、不带章节数；真实章节数来自第二步 approve
      if (url.endsWith("/outline/approve")) return Promise.resolve({ created_chapter_count: 7 });
      return Promise.resolve({});
    });

    const n = await mod.WsCatalog.adoptOutline([{ title: "应被忽略的本地章", act: 1 }]);

    // 章节数取自 approve 响应，而非入参 list 长度（=1）或 materialize 响应（无该字段）
    expect(n).toBe(7);
    // 两步都走且顺序固定：materialize → outline/approve
    expect(calls).toEqual([
      "/api/v2/projects/tide/snowflake-workspace/materialize",
      "/api/v2/projects/tide/snowflake-workspace/outline/approve",
    ]);
  });

  it("闸门满足但 materialize 失败 → adoptOutline 诚实上抛（不静默吞成 0）", async () => {
    const { mod, client } = await loadWithSnow(true);

    const calls = [];
    client.apiPost.mockImplementation((url) => {
      calls.push(url);
      if (url.endsWith("/materialize")) return Promise.reject(new Error("materialize boom"));
      return Promise.resolve({ created_chapter_count: 7 });
    });

    await expect(mod.WsCatalog.adoptOutline([{ title: "x", act: 1 }]))
      .rejects.toThrow("materialize boom");
    // 第一步即崩，不应继续走 approve
    expect(calls).toEqual(["/api/v2/projects/tide/snowflake-workspace/materialize"]);
  });

  it("闸门未满足 → 回退 __adoptByDiff 本地建章，绝不触发物化 POST", async () => {
    const { mod, client } = await loadWithSnow(false);
    expect(window.SnowSync.readyToMaterialize("tide")).toBe(false);
    client.apiPost.mockClear();

    const before = mod.WsCatalog.get().length;
    const n = await mod.WsCatalog.adoptOutline([{ title: "新采用的章", act: 1, summary: "概要" }]);

    expect(n).toBe(1);                                   // 本地新增一章
    expect(mod.WsCatalog.get().length).toBe(before + 1);
    expect(mod.WsCatalog.get().some((c) => c.title === "新采用的章")).toBe(true);
    // 闸门未过时绝不调物化端点
    expect(client.apiPost).not.toHaveBeenCalledWith(
      "/api/v2/projects/tide/snowflake-workspace/materialize", expect.anything());
  });
});
