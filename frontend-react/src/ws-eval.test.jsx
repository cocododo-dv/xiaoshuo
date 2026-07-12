// WsEval store 层单测（Wave 5 §6.2）：盲化消费（只读 pair_id+左右文本、只回传 choice+耗时）
// + 乐观推进 + 投票失败回滚告警。视图不依赖 active project（端点按 experimentId），无需 settleActive。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

async function loadStore() {
  const client = await import("./lib/client.js");
  return { client, mod: await import("./ws-eval.jsx") };
}

describe("WsEval store（匿名盲评）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("evStart 拉 next-pair，只消费 pair_id + 左右纯文本（不带入映射/元数据）", async () => {
    const { client, mod } = await loadStore();
    // 后端故意多回一个隐藏键——store 不得带入。
    client.apiGet.mockResolvedValueOnce({
      pair_id: "p1", left_text: "左稿", right_text: "右稿",
      treatment_slot: "left", scene_snapshot_hash: "h1",
    });
    await mod.evStart("exp1", "u1");

    expect(client.apiGet).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/evaluation-experiments/exp1/next-pair")
    );
    expect(client.apiGet).toHaveBeenCalledWith(expect.stringContaining("reviewer_ref=u1"));
    const cur = mod.evSnapshot().current;
    expect(Object.keys(cur).sort()).toEqual(["left_text", "pair_id", "right_text"]);
    expect(cur.treatment_slot).toBeUndefined();
    expect(cur.scene_snapshot_hash).toBeUndefined();
  });

  it("evVote 乐观推进：POST vote(choice+耗时) 后拉下一对", async () => {
    const { client, mod } = await loadStore();
    client.apiGet
      .mockResolvedValueOnce({ pair_id: "p1", left_text: "L1", right_text: "R1" })
      .mockResolvedValueOnce({ pair_id: "p2", left_text: "L2", right_text: "R2" });
    client.apiPost.mockResolvedValueOnce({ vote_id: "v1", pair_id: "p1", choice: "left" });
    await mod.evStart("exp1", "u1");

    await mod.evVote("left");

    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/evaluation-pairs/p1/vote",
      expect.objectContaining({ choice: "left", reviewer_ref: "u1" })
    );
    const body = client.apiPost.mock.calls[0][1];
    expect(typeof body.duration_ms).toBe("number");
    expect(body).not.toHaveProperty("treatment_slot");
    await vi.waitFor(() => expect(mod.evSnapshot().current.pair_id).toBe("p2"), T);
  });

  it("evVote 失败：回滚恢复当前对 + 告警（不吞票）", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce({ pair_id: "p1", left_text: "L1", right_text: "R1" });
    client.apiPost.mockRejectedValueOnce(new Error("网络错误"));
    await mod.evStart("exp1", "u1");

    await mod.evVote("right");

    expect(window.alert).toHaveBeenCalled();
    expect(mod.evSnapshot().current.pair_id).toBe("p1");   // 回滚：当前对恢复
    expect(mod.evSnapshot().error).toBeTruthy();
  });

  it("evStart 投完（next-pair 返回 null）→ done", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce(null);
    await mod.evStart("exp1", "u1");
    expect(mod.evSnapshot().done).toBe(true);
    expect(mod.evSnapshot().current).toBeNull();
  });

  it("evLoadReport 拉报告并入 store", async () => {
    const { client, mod } = await loadStore();
    client.apiGet
      .mockResolvedValueOnce(null)                                                  // evStart 的 next-pair
      .mockResolvedValueOnce({ decision: "keep_optional", preference_rate: 0.5, non_tie_n: 30 });  // report
    await mod.evStart("exp1", "u1");
    const rep = await mod.evLoadReport();
    expect(rep.decision).toBe("keep_optional");
    expect(mod.evSnapshot().report.decision).toBe("keep_optional");
    expect(client.apiGet).toHaveBeenLastCalledWith("/api/v1/evaluation-experiments/exp1/report");
  });
});
