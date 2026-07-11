// WsManuStore store 层单测（Wave 1 · 结果闭环治理 §5.2）：
// 成稿中心正文换源——唯一正文来源是后端章节聚合（chapter-manuscripts，
// FinalScene 为源），localStorage 的 wr-doc 缓存不再作为章节正文来源。
// 完成门可复算证明：「缓存清除不丢稿」= 清空 localStorage 后正文仍完整来自 API。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { installApiRouter } from "./test-helpers.js";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

const DETAIL_URL = /^\/api\/v1\/chapter-manuscripts\/([^/?]+)$/;

const ARCHIVED_DETAIL = {
  chapter: { chapter_id: "c1", title: "盐场的早班" },
  completion_status: "complete",
  assembled: {
    content: "潮水退去，她看清了闸门上的名字。",
    char_count: 16,
    scene_count: 1,
    generated_scene_count: 1,
    missing_scene_ids: [],
  },
  aggregate: null,
  scenes: [
    {
      scene_id: "s1",
      scene_seq: 1,
      final_scene: {
        row_id: "final_s1_v1",
        content: "潮水退去，她看清了闸门上的名字。",
        char_count: 16,
        created_at: "2026-07-11",
      },
    },
  ],
};

const EMPTY_DETAIL = {
  chapter: { chapter_id: "c1", title: "盐场的早班" },
  completion_status: "empty",
  assembled: { content: "", char_count: 0, scene_count: 1, generated_scene_count: 0, missing_scene_ids: ["s1"] },
  aggregate: null,
  scenes: [{ scene_id: "s1", scene_seq: 1, final_scene: null }],
};

function routeDetail(client, detailByChapter) {
  const base = client.apiGet.getMockImplementation();
  client.apiGet.mockImplementation((url) => {
    const hit = DETAIL_URL.exec(url);
    if (hit) {
      const detail = detailByChapter[hit[1]];
      return detail ? Promise.resolve(detail) : Promise.reject(new Error("not found"));
    }
    return base(url);
  });
}

async function loadStore(detailByChapter = { c1: ARCHIVED_DETAIL }) {
  const client = await import("./lib/client.js");
  installApiRouter(client);
  routeDetail(client, detailByChapter);
  // 键是后端 chapter_id，store 不依赖 WsWorks/目录——直接可用
  const mod = await import("./ws-manuscripts-store.jsx");
  return { mod, client };
}

describe("WsManuStore（成稿中心正文换源到后端聚合）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("refresh 拉后端 detail；body 给出逐场归档正文（来源=FinalScene，非 wr-doc）", async () => {
    const { mod, client } = await loadStore();
    await mod.WsManuStore.refresh("c1");
    expect(client.apiGet).toHaveBeenCalledWith("/api/v1/chapter-manuscripts/c1");

    const body = mod.WsManuStore.body("c1");
    expect(body).not.toBeNull();
    expect(body.completion).toBe("complete");
    expect(body.scenes.length).toBe(1);
    expect(body.scenes[0].sceneId).toBe("s1");
    expect(body.scenes[0].paras).toEqual(["潮水退去，她看清了闸门上的名字。"]);
    expect(body.scenes[0].live).toBe(true);
  });

  it("完成门：清空 localStorage 后正文仍完整来自 API（缓存清除不丢稿）", async () => {
    const { mod } = await loadStore();
    await mod.WsManuStore.refresh("c1");
    // 模拟「清缓存」：清空 localStorage 后 store 的正文不受影响
    window.localStorage.clear();
    const body = mod.WsManuStore.body("c1");
    expect(body.scenes[0].paras).toEqual(["潮水退去，她看清了闸门上的名字。"]);
    // 强断言：store 从不把 wr-doc 缓存当正文来源
    expect(Object.keys(window.localStorage).filter((k) => k.includes("wr-doc"))).toEqual([]);
  });

  it("无归档正文的章 → 场景无稿（live=false、无段落），不再拿 wr-doc 假装成稿", async () => {
    const { mod } = await loadStore({ c1: EMPTY_DETAIL });
    // 就算 wr-doc 缓存里有内容，也不得作为成稿正文来源
    window.localStorage.setItem("ws:tide:wr-doc:ch01s1", "<p>缓存里的假成稿</p>");
    await mod.WsManuStore.refresh("c1");
    const body = mod.WsManuStore.body("c1");
    expect(body.completion).toBe("empty");
    expect(body.scenes[0].live).toBe(false);
    expect(body.scenes[0].paras).toEqual([]);
  });

  it("detail 拉取失败：body 返回 null（视图显示待生成，不炸）", async () => {
    const { mod } = await loadStore({});
    await mod.WsManuStore.refresh("c1");
    expect(mod.WsManuStore.body("c1")).toBeNull();
  });
});
