// WsQuality store 层单测：巡检 overview 的 URL/参数 + summary/items 映射；
// 临时文本扫描 analyze 的端点/载荷；失败路径 error/alert（可证伪）。
// 视图不依赖 active project（端点不收 project_id），故无需 installApiRouter/settleActive。
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("./lib/client.js", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

const T = { timeout: 5000, interval: 25 };

function overviewPayload() {
  return {
    filters: {},
    summary: {
      object_count: 3, mean_score: 0.62, high_risk_count: 1,
      model_voice_count: 2, risk_cluster_count: 1, cross_scene_reuse_count: 0,
    },
    items: [
      {
        object_type: "scene", object_id: "s1", chapter_id: "c1", scene_id: "s1",
        text_layer: "author_draft_preferred", source_ref: "scene:s1", score: 0.55,
        signals: { model_voice: { risk: true, score: 0.3, evidence: "腔" }, valid_ambiguity: { risk: false, score: 0.9, evidence: "" } },
        findings: [{ dimension: "model_voice", severity: "revision", issue: "模型腔重", evidence_excerpt: "他笑了笑", recommendation: "去套话" }],
        fingerprint: {},
        recommended_next_action: { action: "open_deepdesk_patch", label: "去深改" },
      },
    ],
    risk_clusters: [], fingerprints: [], cross_scene_reuse: [],
    recommended_next_action: { action: "none", label: "暂无动作" },
  };
}

async function loadStore() {
  const client = await import("./lib/client.js");
  return { client, mod: await import("./ws-quality.jsx") };
}

describe("WsQuality store（overview 巡检）", () => {
  beforeEach(() => { vi.resetModules(); window.localStorage.clear(); vi.spyOn(window, "alert").mockImplementation(() => {}); });
  afterEach(() => vi.restoreAllMocks());

  it("qLoadOverview 以含 text_layer/min_severity 的正确 URL 调 apiGet，并映射 summary/items", async () => {
    const { client, mod } = await loadStore();
    // 按 URL 路由：overview 返回 payload；其余（boot 期 /api/v2/projects 等）给空对象
    client.apiGet.mockImplementation((u) => {
      if (String(u).includes("/literary-quality/overview")) return Promise.resolve(overviewPayload());
      return Promise.resolve({});
    });

    const data = await mod.qLoadOverview({ text_layer: "author_draft_preferred", min_severity: "revision", chapter_id: "", risk_type: "" });

    // 在所有 apiGet 调用里找 overview 那次（boot 期还有 /api/v2/projects 调用）
    const ovCall = client.apiGet.mock.calls.find((c) => String(c[0]).includes("/api/v1/literary-quality/overview"));
    expect(ovCall).toBeTruthy();
    const url = ovCall[0];
    expect(url).toContain("/api/v1/literary-quality/overview?");
    expect(url).toContain("text_layer=author_draft_preferred");
    expect(url).toContain("min_severity=revision");
    // 空串参数被丢弃（可证伪：若不过滤空值，会出现 chapter_id=）
    expect(url).not.toContain("chapter_id=");
    expect(data.summary.object_count).toBe(3);
    expect(mod.qSnapshot().overview.items[0].object_id).toBe("s1");
    expect(mod.qSnapshot().error).toBeNull();
  });

  it("qLoadOverview 失败时置 error 且返回 null（不抛）", async () => {
    const { client, mod } = await loadStore();
    client.apiGet.mockRejectedValueOnce(new Error("overview boom"));

    const data = await mod.qLoadOverview({ text_layer: "runtime_final_scene" });

    expect(data).toBeNull();
    expect(mod.qSnapshot().error).toContain("overview boom");
  });
});

describe("WsQuality store（临时文本扫描 analyze）", () => {
  beforeEach(() => { vi.resetModules(); window.localStorage.clear(); vi.spyOn(window, "alert").mockImplementation(() => {}); });
  afterEach(() => vi.restoreAllMocks());

  it("qAnalyzeText 以 {content} 打到 analyze-text 端点并存入 analyze", async () => {
    const { client, mod } = await loadStore();
    client.apiPost.mockResolvedValueOnce({ score: 0.4, span_findings: [{ dimension: "summary_ending", severity: "taste", start: 0, end: 3, evidence: "于是" }], signals: {} });

    const data = await mod.qAnalyzeText("  一段要体检的文字  ");

    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/literary-quality/analyze-text",
      { content: "一段要体检的文字" } // 去除首尾空白
    );
    expect(data.span_findings.length).toBe(1);
    expect(mod.qSnapshot().analyze.score).toBe(0.4);
  });

  it("空白文本不发请求", async () => {
    const { client, mod } = await loadStore();
    const data = await mod.qAnalyzeText("   ");
    expect(data).toBeNull();
    expect(client.apiPost).not.toHaveBeenCalled(); // 可证伪：若不守卫空串则会发请求
  });

  it("analyze 失败时触发 alert 且置 error（可证伪）", async () => {
    const { client, mod } = await loadStore();
    client.apiPost.mockRejectedValueOnce(new Error("analyze boom"));

    await mod.qAnalyzeText("会失败的文字");

    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T);
    expect(mod.qSnapshot().error).toContain("analyze boom");
  });
});

describe("WsQuality 维度标签完整性", () => {
  beforeEach(() => { vi.resetModules(); });
  afterEach(() => vi.restoreAllMocks());

  it("21 维齐全且含蓝图 v2 新增三维中文标签", async () => {
    const { mod } = await loadStore();
    expect(mod.QUALITY_DIM_KEYS.length).toBe(21);
    expect(mod.QUALITY_DIMS.perception_filter).toBe("感知过滤");
    expect(mod.QUALITY_DIMS.self_repetition).toBe("自我重复");
    expect(mod.QUALITY_DIMS.conflict_too_clean).toBe("冲突过净");
    // 无 undefined 标签
    expect(mod.QUALITY_DIM_KEYS.every((k) => typeof mod.QUALITY_DIMS[k] === "string")).toBe(true);
  });
});

describe("WsQuality store（章组复审 chapter-set-review）", () => {
  beforeEach(() => { vi.resetModules(); window.localStorage.clear(); vi.spyOn(window, "alert").mockImplementation(() => {}); });
  afterEach(() => vi.restoreAllMocks());

  it("qChapterSetReview 以 {chapter_ids,protected_terms,text_layer} 打到 chapter-set-review 端点，并丢弃空值", async () => {
    const { client, mod } = await loadStore();
    client.apiPost.mockResolvedValueOnce({
      chapter_ids: ["c1"],
      summary: { chapter_count: 1, scene_count: 2, mean_score: 0.6, high_risk_count: 1, repeated_pattern_count: 0, reference_safety_finding_count: 0 },
      scores: { literary_quality: 0.6, cross_chapter_arc: 0.5, reference_safety: 1 },
      chapters: [], scenes: [], risk_clusters: [], repeated_patterns: [], reference_safety_findings: [],
      recommended_next_action: { action: "none" },
    });

    const data = await mod.qChapterSetReview({ chapter_ids: ["c1", ""], protected_terms: ["盐钟", ""], text_layer: "chapter_assembled" });

    // 可证伪：若不过滤空值，body 会含空串 chapter_id / protected_term
    expect(client.apiPost).toHaveBeenCalledWith(
      "/api/v1/literary-quality/chapter-set-review",
      { chapter_ids: ["c1"], protected_terms: ["盐钟"], text_layer: "chapter_assembled" }
    );
    expect(data.summary.chapter_count).toBe(1);
    expect(mod.qSnapshot().review.scores.reference_safety).toBe(1);
  });

  it("无 chapter_ids 时不发请求（可证伪）", async () => {
    const { client, mod } = await loadStore();
    const data = await mod.qChapterSetReview({ chapter_ids: [] });
    expect(data).toBeNull();
    expect(client.apiPost).not.toHaveBeenCalled();
  });

  it("章组复审失败时触发 alert 且置 error（可证伪）", async () => {
    const { client, mod } = await loadStore();
    client.apiPost.mockRejectedValueOnce(new Error("review boom"));
    await mod.qChapterSetReview({ chapter_ids: ["c1"] });
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalled(), T);
    expect(mod.qSnapshot().error).toContain("review boom");
  });
});
