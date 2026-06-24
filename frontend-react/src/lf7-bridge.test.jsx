// Lf7Bridge store 层单测：设定裁决（乐观锁定 + adjudicate 端点）/ 失败回滚刷新。
// 断言取向同 ws-catalog.test.jsx：失败回滚断「isRuled 翻回 open（服务端覆盖）」+ alert，
// 而非被 lf7Fetch 去重吃掉的「又拉了一次 audit」；waitFor 给足超时耐负载。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { installApiRouter, DEFAULT_FINDING } from "./test-helpers.js";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

async function settleActive() {
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("tide"), T);
}

async function loadBridge(opts) {
  const client = await import("./lib/client.js");
  installApiRouter(client, { findings: [DEFAULT_FINDING], ...(opts || {}) });
  const mod = await import("./lf7-bridge.jsx");
  await settleActive();
  // 等审计清单从后端装载（work-changed 级联触发 lf7Fetch("tide")）
  await vi.waitFor(
    () => expect(mod.Lf7Bridge.extraCanon().some((c) => c.id === "f1")).toBe(true), T);
  return { mod, client };
}

describe("Lf7Bridge（设定裁决乐观锁定 + 失败回滚）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("ruleCanon 同步置为已裁决并 POST adjudicate", async () => {
    const { mod, client } = await loadBridge();
    const { Lf7Bridge } = mod;
    expect(Lf7Bridge.isRuled("f1")).toBe(false); // 装载态：open
    client.apiPost.mockClear();

    Lf7Bridge.ruleCanon("f1", "统一为黄铜");

    // 乐观：本地缓存立即锁定
    expect(Lf7Bridge.isRuled("f1")).toBe(true);

    // adjudicate 的 apiPost 不参与 fetch 去重
    await vi.waitFor(() =>
      expect(client.apiPost).toHaveBeenCalledWith(
        "/api/v2/projects/tide/longform/audit/f1/adjudicate",
        { decision: "accept_fix", note: "统一为黄铜" }
      ), T);
  });

  it("adjudicate 失败时告警并以服务端为准回滚乐观锁定", async () => {
    const { mod, client } = await loadBridge();
    const { Lf7Bridge } = mod;
    client.apiPost.mockRejectedValueOnce(new Error("adjudicate failed"));

    Lf7Bridge.ruleCanon("f1", "统一为黄铜");
    expect(Lf7Bridge.isRuled("f1")).toBe(true); // 乐观先锁

    // 失败 → catch 调 window.alert（强可证伪）
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T);
    // 且重拉后服务端 open 态覆盖乐观锁定——回滚到位
    await vi.waitFor(() => expect(Lf7Bridge.isRuled("f1")).toBe(false), T);
  });
});
