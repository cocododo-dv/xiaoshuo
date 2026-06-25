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

  it("adjudicateDraft 把后端 violations 映射成 drifted（带真实 finding_id，block→rose/high）", async () => {
    const { mod, client } = await loadBridge();
    const { Lf7Bridge } = mod;
    await vi.waitFor(() => expect(window.WsCatalog.get().length).toBeGreaterThan(0), T);

    client.apiPost.mockImplementation((url) => {
      if (url.includes("/audit/adjudicate-draft")) {
        return Promise.resolve({
          skipped: false,
          findings_created: 1,
          violations: [
            {
              finding_id: "AUD_X", clause_ref: "1", kind: "drift", severity: "block",
              text: "档案室被写到三楼", evidence_sentence: "他们走上三楼。",
              at: "第 9 章", suggested_fix: "改回地下",
            },
          ],
        });
      }
      return Promise.resolve({});
    });

    const adj = await Lf7Bridge.adjudicateDraft(1);
    expect(adj.skipped).toBe(false);
    expect(adj.findings_created).toBe(1);
    expect(adj.drifted).toHaveLength(1);
    const dr = adj.drifted[0];
    expect(dr.finding_id).toBe("AUD_X");   // 真实 finding_id 透传，fixDrift 据此走 ruleCanon
    expect(dr.real).toBe(true);
    expect(dr.tone).toBe("rose");          // block → rose / high
    expect(dr.sev).toBe("high");
    expect(dr.what).toBe("档案室被写到三楼");
    expect(dr.line).toBe("他们走上三楼。");
    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v2/projects/tide/longform/chapters/c1/audit/adjudicate-draft", {});
  });

  it("adjudicateDraft 在 LLM 未配置时诚实降级（skipped + author_action，drifted 空、不机器判违约）", async () => {
    const { mod, client } = await loadBridge();
    const { Lf7Bridge } = mod;
    await vi.waitFor(() => expect(window.WsCatalog.get().length).toBeGreaterThan(0), T);

    client.apiPost.mockImplementation((url) => {
      if (url.includes("/audit/adjudicate-draft")) {
        return Promise.resolve({
          skipped: true, reason: "llm_disabled", violations: [],
          author_action: { target_view: "system-config", title: "未配置 LLM" },
        });
      }
      return Promise.resolve({});
    });

    const adj = await Lf7Bridge.adjudicateDraft(1);
    expect(adj.skipped).toBe(true);
    expect(adj.reason).toBe("llm_disabled");
    expect(adj.drifted).toEqual([]);
    expect(adj.author_action.target_view).toBe("system-config");
  });
});
