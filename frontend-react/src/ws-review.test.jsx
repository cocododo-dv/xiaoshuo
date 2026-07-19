// WsReview store 层单测：投递 / 处理（乐观移除 + resolve 端点）/ 处理失败告警。
// 断言取向同 ws-catalog.test.jsx：只断可观测结果 + 非去重写动词；waitFor 给足超时耐负载。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { installApiRouter, DEFAULT_REVIEW_CARD } from "./test-helpers.js";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

async function settleActive() {
  await vi.waitFor(() => expect(window.WsWorks && window.WsWorks.activeId()).toBe("prj-main"), T);
}

async function loadReview(opts) {
  const client = await import("./lib/client.js");
  installApiRouter(client, opts);
  const mod = await import("./ws-review.jsx");
  await settleActive(); // 投递/处理 payload 需要真实 project_id
  return { mod, client };
}

describe("WsReview（收件箱乐观处理 + 失败告警）", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.spyOn(window, "alert").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("rvPush 投递待办到后端 review-items 端点（带当前作品 id）", async () => {
    const { mod, client } = await loadReview();
    client.apiPost.mockClear();

    mod.rvPush({ title: "新批注：第 5 章节奏", kind: "note" });

    await vi.waitFor(() =>
      expect(client.apiPost).toHaveBeenCalledWith(
        "/api/v1/review-items",
        expect.objectContaining({ title: "新批注：第 5 章节奏", project_id: "prj-main" })
      ), T);
  });

  it("rvMarkResolved 乐观移除并 POST resolve", async () => {
    const { mod, client } = await loadReview({ reviewOpen: [DEFAULT_REVIEW_CARD] });
    // 等收件箱从后端装载（work-changed 去抖后拉取）
    await vi.waitFor(() => expect(mod.rvOpenItems().length).toBeGreaterThan(0), T);
    client.apiPost.mockClear();

    mod.rvMarkResolved(["rv1"]);

    // 乐观：立即从 open 列表移除
    expect(mod.rvOpenItems().some((i) => i.id === "rv1")).toBe(false);

    // resolve 的 apiPost 在循环里逐条发，不参与 fetch 去重
    await vi.waitFor(() =>
      expect(client.apiPost).toHaveBeenCalledWith(
        "/api/v1/review-items/rv1/resolve",
        expect.objectContaining({ project_id: "prj-main" })
      ), T);
  });

  it("resolve 端点失败时告警", async () => {
    const { mod, client } = await loadReview({ reviewOpen: [DEFAULT_REVIEW_CARD] });
    await vi.waitFor(() => expect(mod.rvOpenItems().length).toBeGreaterThan(0), T);
    client.apiPost.mockRejectedValueOnce(new Error("resolve failed"));

    mod.rvMarkResolved(["rv1"]);

    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T);
  });
});
