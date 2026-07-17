// WsCost store 层单测（结果闭环治理 §5.8/§10）：
// 项目级读 cost-dashboard（趋势/构成/明细一读聚合）；chapter/scene 走 cost-summary 下钻；
// costBack 用缓存就地还原不重发请求；空/失败降级不抛。只读——不发写请求。
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

const DASH = {
  project_id: "P1",
  summary: {
    total_cost: 1.23, currency: "USD", call_count: 3, is_estimate: true,
    total_tokens: 900, cross_provider: false,
    phase_breakdown: { candidate_generation: { cost: 1, share: 0.8, call_count: 2 } },
    judge_independence: { correlated_judge: false },
  },
  trend: {
    days: 30, series: [{ date: "2026-07-16", cost: 0.5, tokens: 300, call_count: 1 }],
    window_cost: 0.5, window_tokens: 300, window_call_count: 1,
  },
  by_model: [{ provider: "openai_compatible", model: "gpt-5", cost: 1.2, tokens: 900, call_count: 3, is_estimate: true }],
  by_node: { top: [{ node_id: "style_draft", phase: "candidate_generation", cost: 1, tokens: 600, call_count: 2 }], remainder: null },
  by_chapter: [{ chapter_id: "C1", cost: 1.2, tokens: 900, call_count: 3, scene_count: 2 }],
  top_calls: [{ llm_call_id: "c1", cost: 0.6, total_tokens: 300, phase: "candidate_generation" }],
  quota: { daily_tokens: { used: 100, limit: 1000 }, period_timezone: "UTC" },
};

describe("WsCost store（成本看板）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });
  afterEach(() => vi.restoreAllMocks());

  it("costLoad 项目级：拉 cost-dashboard（默认近 30 天）并入 store", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce(DASH);
    await mod.costLoad("P1");
    expect(client.apiGet).toHaveBeenCalledWith("/api/v2/projects/P1/cost-dashboard?days=30");
    const st = mod.csSnapshot();
    expect(st.level).toBe("project");
    expect(st.dashboard.trend.window_cost).toBe(0.5);
    expect(st.summary.total_cost).toBe(1.23);
    expect(st.quota.daily_tokens.limit).toBe(1000);
  });

  it("costLoad 支持 days 窗口并记住选择", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValue(DASH);
    await mod.costLoad("P1", { days: 7 });
    expect(client.apiGet).toHaveBeenLastCalledWith("/api/v2/projects/P1/cost-dashboard?days=7");
    expect(mod.csSnapshot().days).toBe(7);
    // 后续不带 days 沿用上次窗口
    await mod.costLoad("P1");
    expect(client.apiGet).toHaveBeenLastCalledWith("/api/v2/projects/P1/cost-dashboard?days=7");
  });

  it("costLoad 场景下钻：走 cost-summary?scene_id，保留 dashboard 缓存", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce(DASH);
    await mod.costLoad("P1");
    client.apiGet.mockResolvedValueOnce({ level: "scene", summary: { scene_id: "S1", total_cost: 0.5 } });
    await mod.costLoad("P1", { sceneId: "S1" });
    expect(client.apiGet).toHaveBeenLastCalledWith(expect.stringContaining("cost-summary?scene_id=S1"));
    expect(mod.csSnapshot().level).toBe("scene");
    expect(mod.csSnapshot().summary.scene_id).toBe("S1");
    expect(mod.csSnapshot().dashboard.summary.total_cost).toBe(1.23);
  });

  it("costLoad 章节下钻：走 cost-summary?chapter_id；下钻响应无 quota 时保留旧额度", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce(DASH);
    await mod.costLoad("P1");
    client.apiGet.mockResolvedValueOnce({ level: "chapter", summary: { chapter_id: "C1" } });
    await mod.costLoad("P1", { chapterId: "C1" });
    expect(client.apiGet).toHaveBeenLastCalledWith(expect.stringContaining("cost-summary?chapter_id=C1"));
    expect(mod.csSnapshot().level).toBe("chapter");
    expect(mod.csSnapshot().quota.daily_tokens.limit).toBe(1000);
  });

  it("costBack：有 dashboard 缓存时就地还原项目层，不重发请求", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce(DASH);
    await mod.costLoad("P1");
    client.apiGet.mockResolvedValueOnce({ level: "chapter", summary: { chapter_id: "C1" } });
    await mod.costLoad("P1", { chapterId: "C1" });
    const callsBefore = client.apiGet.mock.calls.length;
    mod.costBack();
    expect(client.apiGet.mock.calls.length).toBe(callsBefore);
    expect(mod.csSnapshot().level).toBe("project");
    expect(mod.csSnapshot().summary.total_cost).toBe(1.23);
  });

  it("costBack：无缓存时回退为重新加载项目级", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockRejectedValueOnce(new Error("boom"));
    await mod.costLoad("P1"); // 失败，dashboard 仍为空
    client.apiGet.mockResolvedValueOnce(DASH);
    mod.costBack();
    await vi.waitFor(() => expect(mod.csSnapshot().dashboard).toBeTruthy());
    expect(client.apiGet).toHaveBeenLastCalledWith(expect.stringContaining("cost-dashboard"));
  });

  it("costLoad 失败：降级为 error，不抛；下次成功后清除 error", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockRejectedValueOnce(new Error("网络错误"));
    const r = await mod.costLoad("P1");
    expect(r).toBeNull();
    expect(mod.csSnapshot().error).toBeTruthy();
    expect(mod.csSnapshot().loading).toBe(false);
    client.apiGet.mockResolvedValueOnce(DASH);
    await mod.costLoad("P1");
    expect(mod.csSnapshot().error).toBeNull();
    expect(mod.csSnapshot().dashboard).toBeTruthy();
  });

  it("costLoad 只读：不发任何写请求", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValue(DASH);
    await mod.costLoad("P1");
    await mod.costLoad("P1", { chapterId: "C1" });
    expect(client.apiPost).not.toHaveBeenCalled();
    expect(client.apiPatch).not.toHaveBeenCalled();
    expect(client.apiDelete).not.toHaveBeenCalled();
  });

  it("costLoad 无 projectId：直接返回 null 不发请求", async () => {
    const { client, mod } = await loadStore();
    const r = await mod.costLoad("");
    expect(r).toBeNull();
    expect(client.apiGet).not.toHaveBeenCalled();
  });
});
