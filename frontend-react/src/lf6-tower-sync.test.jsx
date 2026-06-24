import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

/* 缺口A 回归：长篇控制塔 v6 原先把 LF2_LOOPS/LF2_CANON 在 useState 初始化器里
   一次性深拷贝静态种子、之后不消费后端同步。修复让 Lf6Tower 订阅 lf2:tower-synced
   重置 state。本测试守住塔台所依赖的「数据契约」：lf2SyncFromTower 把后端锚点按 kind
   投影到 LF2_*，派发 lf2:tower-synced，且 lf2Derive 能从同步后的锚点算出失控派生量。
   （断言走 window.LF2_*，因 lf2PushGlobals 在重写后 Object.assign 到 window，确定性强。） */

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

function anchorsResponse() {
  return {
    project_id: "tide",
    anchors: [
      // 悬念债：payoff(6) < now(8) → 逾期 overdue
      { anchor_id: "a-l6", kind: "promise", status: "pinned",
        note: JSON.stringify({ fe: { id: "l6", title: "楼梯间的第二组脚印", setup: 2, payoff: 6, state: "open", pri: "high", pinned: false } }) },
      // 设定锚点：status=conflict & drift=true → 漂移冲突 driftConflicts
      { anchor_id: "a-c1", kind: "fact", status: "pinned",
        note: JSON.stringify({ fe: { id: "c1", subject: "林岑 · 年龄", value: "28 岁", source: 1, status: "conflict", drift: true, conflictCh: 5, critical: true, pinned: true } }) },
      // 故事线 thread
      { anchor_id: "a-main", kind: "thread", status: "pinned",
        note: JSON.stringify({ fe: { id: "main", name: "主线 · 父亲的真相", short: "主线", color: "crimson", segs: [[1, 8]] } }) },
      // faded 锚点 → 进入记忆预算可检索池，不应混进 LF2_LOOPS
      { anchor_id: "a-rv", kind: "fact", status: "faded",
        note: JSON.stringify({ fe: { id: "rv1", pool: "retrieve", text: "走廊钟摆声 · 环境母题", ch: 2, tone: "slate", reason: "氛围" } }) },
    ],
  };
}

function routeApi(client) {
  client.apiGet.mockImplementation((url) => {
    if (url === "/api/v2/projects") return Promise.resolve({ items: [{ project_id: "tide", title: "潮汐档案", genre: "悬疑 · 长篇" }] });
    if (/\/longform\/anchors$/.test(url)) return Promise.resolve(anchorsResponse());
    if (/\/longform\/audit$/.test(url)) return Promise.resolve({ findings: [] });
    return Promise.resolve({});
  });
  client.apiPost.mockResolvedValue({});
  client.apiPatch.mockResolvedValue({});
  client.apiDelete.mockResolvedValue({});
}

async function load() {
  const client = await import("./lib/client.js");
  routeApi(client);
  await import("./ws-works.jsx");
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("tide"), T);
  const mod = await import("./lf2-data.jsx");
  return { client, mod };
}

describe("缺口A · lf2SyncFromTower 投影后端锚点 + 派发 lf2:tower-synced", () => {
  beforeEach(() => { vi.resetModules(); window.localStorage.clear(); });
  afterEach(() => vi.restoreAllMocks());

  it("anchors 按 kind 投影到 LF2_LOOPS/LF2_CANON/LF2_THREADS，faded 不混入 loops，并派发同步事件", async () => {
    await load();
    const seen = vi.fn();
    window.addEventListener("lf2:tower-synced", seen);
    await window.lf2SyncFromTower();

    expect(window.LF2_LOOPS.map(l => l.id)).toContain("l6");
    expect(window.LF2_CANON.map(c => c.id)).toContain("c1");
    expect(window.LF2_THREADS.map(t => t.id)).toContain("main");
    // 可证伪：若 faded 分流被破坏，rv1 会错误进入 loops
    expect(window.LF2_LOOPS.map(l => l.id)).not.toContain("rv1");
    // 可证伪：若 lf2SyncFromTower 不派发事件，组件 reseat 永远收不到
    expect(seen).toHaveBeenCalled();

    window.removeEventListener("lf2:tower-synced", seen);
  });

  it("lf2Derive 从同步后的锚点算出 overdue / driftConflicts（塔台消费的失控派生量为真）", async () => {
    const { mod } = await load();
    await window.lf2SyncFromTower();

    const d = mod.lf2Derive(window.LF2_LOOPS, window.LF2_CANON);
    // l6 payoff=6 < now=8 → 逾期
    expect(d.overdue.map(l => l.id)).toContain("l6");
    // c1 conflict + drift → 漂移冲突
    expect(d.driftConflicts.map(c => c.id)).toContain("c1");
  });
});
