// WsCost store 层单测（Wave 6 §5.8/§10）：读 cost-summary 成形；scene/chapter 下钻；
// 空/失败降级不抛。只读——不发写请求。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

async function loadStore() {
  const client = await import("./lib/client.js");
  return { client, mod: await import("./ws-cost.jsx") };
}

describe("WsCost store（成本看板）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("costLoad 项目级：拉 project 成本并入 store", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce({
      level: "project",
      summary: { total_cost: 1.23, currency: "USD", call_count: 3, is_estimate: true,
                 phase_breakdown: { candidate_generation: { cost: 1, share: 0.8 } },
                 judge_independence: { correlated_judge: false } },
    });
    await mod.costLoad("P1");
    expect(client.apiGet).toHaveBeenCalledWith("/api/v2/projects/P1/cost-summary");
    expect(mod.csSnapshot().level).toBe("project");
    expect(mod.csSnapshot().summary.total_cost).toBe(1.23);
  });

  it("costLoad 场景下钻：带 scene_id 查询串", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce({ level: "scene", summary: { scene_id: "S1", total_cost: 0.5 } });
    await mod.costLoad("P1", { sceneId: "S1" });
    expect(client.apiGet).toHaveBeenCalledWith(expect.stringContaining("scene_id=S1"));
    expect(mod.csSnapshot().level).toBe("scene");
  });

  it("costLoad 章节下钻：带 chapter_id 查询串", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce({ level: "chapter", summary: { chapter_id: "C1" } });
    await mod.costLoad("P1", { chapterId: "C1" });
    expect(client.apiGet).toHaveBeenCalledWith(expect.stringContaining("chapter_id=C1"));
    expect(mod.csSnapshot().level).toBe("chapter");
  });

  it("costLoad 失败：降级为 error，不抛", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockRejectedValueOnce(new Error("网络错误"));
    const r = await mod.costLoad("P1");
    expect(r).toBeNull();
    expect(mod.csSnapshot().error).toBeTruthy();
    expect(mod.csSnapshot().loading).toBe(false);
  });

  it("costLoad 只读：不发任何写请求", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce({ level: "project", summary: { total_cost: 0 } });
    await mod.costLoad("P1");
    expect(client.apiPost).not.toHaveBeenCalled();
    expect(client.apiPatch).not.toHaveBeenCalled();
    expect(client.apiDelete).not.toHaveBeenCalled();
  });
});
