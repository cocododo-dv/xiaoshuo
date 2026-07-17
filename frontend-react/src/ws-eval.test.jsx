// WsEval store 层单测（结果闭环治理 §6.2）：盲化消费（pair 只读三键、进度只读纯计数、
// 只回传 choice+耗时）+ 乐观推进 + 投票失败回滚（行内错误，不弹 alert）+ 实验清单/建实验/
// 加对/冻结管理动作。视图不依赖 active project（端点按 experimentId），无需 settleActive。
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

function wrapPair(pair, progress) {
  return {
    pair,
    done: !pair,
    progress: progress || { total_pairs: 3, voted_pairs: 0, remaining_pairs: 3 },
  };
}

describe("WsEval store（匿名盲评）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("evStart 拉 next-pair：pair 只消费三键、进度只消费纯计数（隐藏键不带入）", async () => {
    const { client, mod } = await loadStore();
    // 后端故意多回隐藏键——store 不得带入。
    client.apiGet.mockResolvedValueOnce({
      pair: { pair_id: "p1", left_text: "左稿", right_text: "右稿", treatment_slot: "left", scene_snapshot_hash: "h1" },
      done: false,
      progress: { total_pairs: 3, voted_pairs: 1, remaining_pairs: 2, token_cost: { treatment: 9 } },
    });
    await mod.evStart("exp1", "u1");

    expect(client.apiGet).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/evaluation-experiments/exp1/next-pair")
    );
    expect(client.apiGet).toHaveBeenCalledWith(expect.stringContaining("reviewer_ref=u1"));
    const st = mod.evSnapshot();
    expect(Object.keys(st.current).sort()).toEqual(["left_text", "pair_id", "right_text"]);
    expect(st.current.treatment_slot).toBeUndefined();
    expect(st.current.scene_snapshot_hash).toBeUndefined();
    expect(st.progress).toEqual({ total_pairs: 3, voted_pairs: 1, remaining_pairs: 2 });
    expect(st.view).toBe("arena");
  });

  it("evVote 乐观推进：POST vote(choice+耗时) 后拉下一对", async () => {
    const { client, mod } = await loadStore();
    client.apiGet
      .mockResolvedValueOnce(wrapPair({ pair_id: "p1", left_text: "L1", right_text: "R1" }))
      .mockResolvedValueOnce(wrapPair({ pair_id: "p2", left_text: "L2", right_text: "R2" },
        { total_pairs: 3, voted_pairs: 1, remaining_pairs: 2 }));
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
    expect(mod.evSnapshot().progress.voted_pairs).toBe(1);
  });

  it("evVote 失败：回滚恢复当前对 + 行内错误（不吞票、不弹 alert）", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce(wrapPair({ pair_id: "p1", left_text: "L1", right_text: "R1" }));
    client.apiPost.mockRejectedValueOnce(new Error("网络错误"));
    await mod.evStart("exp1", "u1");

    await mod.evVote("right");

    expect(mod.evSnapshot().current.pair_id).toBe("p1");   // 回滚：当前对恢复
    expect(mod.evSnapshot().voting).toBe(false);
    expect(mod.evSnapshot().error).toMatch(/重试/);
    expect(window.alert).not.toHaveBeenCalled();
  });

  it("evStart 投完（pair=null, done=true）→ done + 进度保留", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce(wrapPair(null, { total_pairs: 3, voted_pairs: 3, remaining_pairs: 0 }));
    await mod.evStart("exp1", "u1");
    const st = mod.evSnapshot();
    expect(st.done).toBe(true);
    expect(st.current).toBeNull();
    expect(st.progress.remaining_pairs).toBe(0);
  });

  it("evLoadExperiments 拉实验清单入 store", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce([
      { experiment_id: "exp1", name: "BoN", status: "collecting", total_pairs: 2, voted_pairs: 1 },
    ]);
    const rows = await mod.evLoadExperiments();
    expect(client.apiGet).toHaveBeenCalledWith("/api/v1/evaluation-experiments");
    expect(rows).toHaveLength(1);
    expect(mod.evSnapshot().experiments[0].experiment_id).toBe("exp1");
  });

  it("evLoadExperiments 失败：error 落 store、listLoading 复位", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockRejectedValueOnce(new Error("后端未启动"));
    const rows = await mod.evLoadExperiments();
    expect(rows).toBeNull();
    expect(mod.evSnapshot().listLoading).toBe(false);
    expect(mod.evSnapshot().error).toMatch(/后端未启动/);
  });

  it("evOpenReport 拉报告并切到报告视图", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockResolvedValueOnce({ decision: "keep_optional", preference_rate: 0.5, non_tie_n: 30 });
    const rep = await mod.evOpenReport("exp1");
    expect(rep.decision).toBe("keep_optional");
    expect(client.apiGet).toHaveBeenLastCalledWith("/api/v1/evaluation-experiments/exp1/report");
    const st = mod.evSnapshot();
    expect(st.view).toBe("report");
    expect(st.report.decision).toBe("keep_optional");
    expect(st.reportFor).toBe("exp1");
  });

  it("evCreateExperiment：POST 建实验成功后刷新清单", async () => {
    const { client, mod } = await loadStore();
    client.apiPost.mockResolvedValueOnce({ experiment_id: "exp_new", name: "新实验" });
    client.apiGet.mockResolvedValueOnce([{ experiment_id: "exp_new", name: "新实验", status: "collecting" }]);
    const created = await mod.evCreateExperiment({ name: "新实验", evidence_provenance: "human" });
    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/evaluation-experiments",
      expect.objectContaining({ name: "新实验", evidence_provenance: "human" })
    );
    expect(created.experiment_id).toBe("exp_new");
    expect(mod.evSnapshot().experiments[0].experiment_id).toBe("exp_new");
    expect(mod.evSnapshot().notice).toMatch(/新实验/);
  });

  it("evCreateExperiment 失败：error 落 store、busy 复位、不刷清单", async () => {
    const { client, mod } = await loadStore();
    client.apiPost.mockRejectedValueOnce(new Error("VALIDATION"));
    const created = await mod.evCreateExperiment({ name: "x" });
    expect(created).toBeNull();
    expect(mod.evSnapshot().busy).toBe(false);
    expect(mod.evSnapshot().error).toMatch(/VALIDATION/);
    expect(client.apiGet).not.toHaveBeenCalled();
  });

  it("evAddPair：POST 盲化入库（透传 genre/scene_function/token_cost）后刷新清单", async () => {
    const { client, mod } = await loadStore();
    client.apiPost.mockResolvedValueOnce({ pair_id: "p9", no_contrast: 0 });
    client.apiGet.mockResolvedValueOnce([]);
    const added = await mod.evAddPair("exp1", {
      scene_snapshot_hash: "h9", treatment_text: "T", control_text: "C",
      genre: "悬疑", scene_function: "reveal", token_cost: { treatment: 5000, control: 1000 },
    });
    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/evaluation-experiments/exp1/pairs",
      expect.objectContaining({ scene_function: "reveal", genre: "悬疑" })
    );
    expect(added.pair_id).toBe("p9");
  });

  it("evFreeze：POST 冻结题包后刷新清单", async () => {
    const { client, mod } = await loadStore();
    client.apiPost.mockResolvedValueOnce({ experiment_id: "exp1", status: "frozen" });
    client.apiGet.mockResolvedValueOnce([{ experiment_id: "exp1", status: "frozen" }]);
    const frozen = await mod.evFreeze("exp1");
    expect(client.apiPost).toHaveBeenCalledWith("/api/v1/evaluation-experiments/exp1/freeze", {});
    expect(frozen.status).toBe("frozen");
    expect(mod.evSnapshot().experiments[0].status).toBe("frozen");
  });
});
