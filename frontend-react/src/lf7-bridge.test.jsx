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

  it("auditReceipt 把后端确定性回执还原成 LF3_AUDIT 形状（命中→honored、未检出/到期→introduced、drifted 恒空）", async () => {
    const { mod, client } = await loadBridge();
    const { Lf7Bridge } = mod;
    await vi.waitFor(() => expect(window.WsCatalog.get().length).toBeGreaterThan(0), T);

    client.apiGet.mockImplementation((url) => {
      if (url.includes("/audit-receipt")) {
        return Promise.resolve({
          has_text: true, chapter_no: 1, words_total: 1500, contract: { status: "ready" },
          anchor_hits: [{ id: "h1", subject: "林岑 · 年龄", value: "28 岁", evidence: "她在年龄栏写下 28", at: "场1·段3" }],
          anchor_misses: [{ id: "m1", subject: "周岚 · 办公室", value: "地下档案室" }],
          pending: [{ id: "p1", title: "第二组脚印回收" }],
        });
      }
      return Promise.resolve({});
    });

    const r = await Lf7Bridge.auditReceipt(1);
    expect(r.real).toBe(true);
    expect(r.ch).toBe(1);
    expect(r.honored).toHaveLength(1);
    expect(r.honored[0].text).toContain("28 岁");
    expect(r.honored[0].evidence).toBe("她在年龄栏写下 28");
    // 可证伪：违约判定属 D13，确定性回执的 drifted 必须恒空
    expect(r.drifted).toEqual([]);
    // 1 未检出 + 1 到期承诺 → introduced 待人工核对
    expect(r.introduced).toHaveLength(2);
    expect(r.introduced.map((x) => x.kind)).toEqual(["未检出", "到期承诺"]);
  });

  it("auditReceipt 在本章无正文时返回 null（lf6 回落静态演示，不冒充真实回执）", async () => {
    const { mod, client } = await loadBridge();
    const { Lf7Bridge } = mod;
    await vi.waitFor(() => expect(window.WsCatalog.get().length).toBeGreaterThan(0), T);

    client.apiGet.mockImplementation((url) =>
      url.includes("/audit-receipt") ? Promise.resolve({ has_text: false }) : Promise.resolve({}));

    expect(await Lf7Bridge.auditReceipt(1)).toBe(null);
  });
});
