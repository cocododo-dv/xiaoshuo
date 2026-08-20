// @vitest-environment jsdom
//
// PR-5 — stores/referenceLearning.js 关键路径测试 + useWriterPathProgress
// 5 字段契约保留断言(loaded / books / profiles / pendingDecisionCount / actionId)。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

vi.mock("../src/lib/api/styleReference", () => ({
  listStyleReferenceBooks: vi.fn(),
  fetchStyleReferenceBook: vi.fn(),
  deleteStyleReferenceBook: vi.fn(),
  reclassifyStyleReferenceBook: vi.fn(),
  importStyleReferenceBookPath: vi.fn(),
  importStyleReferenceBookUpload: vi.fn(),
  startStyleReferenceRun: vi.fn(),
  fetchStyleReferenceRun: vi.fn(),
  cancelStyleReferenceRun: vi.fn(),
  listStyleReferenceRunFindings: vi.fn(),
  reviewStyleReferenceFinding: vi.fn(),
  synthesizeStyleReferenceProfile: vi.fn(),
  listStyleReferenceProfiles: vi.fn(),
  fetchStyleReferenceProfile: vi.fn(),
  previewStyleReferenceProfile: vi.fn(),
  applyStyleReferenceProfile: vi.fn(),
  listStyleReferenceBindings: vi.fn(),
  deleteStyleReferenceBinding: vi.fn(),
}));

import * as api from "../src/lib/api/styleReference";
import { useReferenceLearningStore } from "../src/stores/referenceLearning";

beforeEach(() => {
  setActivePinia(createPinia());
  Object.values(api).forEach((fn) => fn.mockReset?.());
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("referenceLearning store — useWriterPathProgress 契约", () => {
  it("保留 loaded / books / profiles / pendingDecisionCount / actionId 5 字段", () => {
    const store = useReferenceLearningStore();
    expect(store.loaded).toBe(false);
    expect(store.books).toEqual([]);
    expect(store.profiles).toEqual([]);
    expect(store.pendingDecisionCount).toBe(0);
    expect(store.actionId).toBeNull();
  });

  it("findings 按 16 sub_dim 分桶(PR-6 全盘)", () => {
    const store = useReferenceLearningStore();
    expect(Object.keys(store.findings).sort()).toEqual([
      "language.punctuation",
      "language.rhetoric",
      "language.sentence_structure",
      "language.vocabulary",
      "narrative.information_density",
      "narrative.pacing",
      "narrative.perspective",
      "narrative.time_handling",
      "scene.character_portrayal",
      "scene.dialogue",
      "scene.environment",
      "scene.sensory_priority",
      "theme.emotional_tone",
      "theme.motifs",
      "theme.narrative_philosophy",
      "theme.values",
    ]);
  });
});

describe("referenceLearning store — initialize + loadBooks", () => {
  it("initialize 调用 listStyleReferenceBooks 并设置 loaded=true", async () => {
    api.listStyleReferenceBooks.mockResolvedValue({ books: [{ book_id: "sr_book_1", title: "x" }] });
    const store = useReferenceLearningStore();
    await store.initialize();
    expect(api.listStyleReferenceBooks).toHaveBeenCalled();
    expect(store.loaded).toBe(true);
    expect(store.books).toHaveLength(1);
  });

  it("initialize 第二次调用(已 loaded 且 fresh)跳过 API 调用", async () => {
    api.listStyleReferenceBooks.mockResolvedValue({ books: [] });
    const store = useReferenceLearningStore();
    await store.initialize();
    api.listStyleReferenceBooks.mockClear();
    await store.initialize();
    expect(api.listStyleReferenceBooks).not.toHaveBeenCalled();
  });
});

describe("referenceLearning store — selectBook", () => {
  it("selectBook 串联 fetchBook + listProfiles 并设置 currentBook / profiles", async () => {
    api.fetchStyleReferenceBook.mockResolvedValue({ book: { book_id: "sr_book_1", title: "t" } });
    api.listStyleReferenceProfiles.mockResolvedValue({ profiles: [{ profile_id: "p1", status: "active" }] });
    const store = useReferenceLearningStore();
    await store.selectBook("sr_book_1");
    expect(store.selectedBookId).toBe("sr_book_1");
    expect(store.currentBook?.title).toBe("t");
    expect(store.profiles).toHaveLength(1);
    expect(store.currentProfile?.profile_id).toBe("p1");
  });
});

describe("referenceLearning store — startRun 默认层(P0-1)", () => {
  it("startRun() 无参时,调用 api 的 payload 不含 layers 键(默认值收敛到后端单点)", async () => {
    api.startStyleReferenceRun.mockResolvedValue({ run_id: null });
    const store = useReferenceLearningStore();
    store.selectedBookId = "sr_book_1";
    await store.startRun();
    expect(api.startStyleReferenceRun).toHaveBeenCalledWith("sr_book_1", {});
    expect(api.startStyleReferenceRun.mock.calls[0][1]).not.toHaveProperty("layers");
  });

  it("startRun(layers) 显式传层时透传 layers", async () => {
    api.startStyleReferenceRun.mockResolvedValue({ run_id: null });
    const store = useReferenceLearningStore();
    store.selectedBookId = "sr_book_1";
    await store.startRun(["language"]);
    expect(api.startStyleReferenceRun).toHaveBeenCalledWith("sr_book_1", { layers: ["language"] });
  });
});

describe("referenceLearning store — loadRunFindings + pendingDecisionCount", () => {
  it("findings 按 sub_dim + kind 正确分桶,pendingDecisionCount 更新", async () => {
    api.listStyleReferenceRunFindings.mockResolvedValue({
      findings: [
        { finding_id: "f1", sub_dimension: "language.rhetoric", finding_kind: "observation", status: "pending" },
        { finding_id: "f2", sub_dimension: "language.rhetoric", finding_kind: "forbidden_pattern", status: "approved" },
        { finding_id: "f3", sub_dimension: "narrative.pacing", finding_kind: "observation", status: "pending" },
      ],
    });
    const store = useReferenceLearningStore();
    await store.loadRunFindings("sr_run_1");
    expect(store.findings["language.rhetoric"].observations).toHaveLength(1);
    expect(store.findings["language.rhetoric"].forbidden_patterns).toHaveLength(1);
    expect(store.findings["narrative.pacing"].observations).toHaveLength(1);
    expect(store.pendingDecisionCount).toBe(2);  // f1 + f3 pending
  });

  it("loadRunFindings 默认携带 include=evidence,finding.evidence 数组保留(P0-2)", async () => {
    api.listStyleReferenceRunFindings.mockResolvedValue({
      findings: [
        {
          finding_id: "f1",
          sub_dimension: "language.rhetoric",
          finding_kind: "observation",
          status: "pending",
          evidence: [
            { evidence_id: "ev1", anchor_kind: "paragraph_quote", quote_text: "引文甲", is_synthetic: 0 },
            { evidence_id: "ev2", anchor_kind: "author_avoidance", quote_text: "引文乙", is_synthetic: 0 },
          ],
        },
      ],
    });
    const store = useReferenceLearningStore();
    await store.loadRunFindings("sr_run_1");
    expect(api.listStyleReferenceRunFindings).toHaveBeenCalledWith(
      "sr_run_1",
      expect.objectContaining({ include: "evidence" }),
    );
    expect(store.findings["language.rhetoric"].observations[0].evidence).toHaveLength(2);
  });
});

describe("referenceLearning store — reviewFinding 更新本地状态", () => {
  it("approve 后 finding.status=approved + pendingDecisionCount 减少", async () => {
    api.listStyleReferenceRunFindings.mockResolvedValue({
      findings: [
        { finding_id: "f1", sub_dimension: "language.rhetoric", finding_kind: "observation", status: "pending" },
      ],
    });
    api.reviewStyleReferenceFinding.mockResolvedValue({ review_id: "review_style_ref_finding_f1", decision: "approved" });
    const store = useReferenceLearningStore();
    await store.loadRunFindings("sr_run_1");
    expect(store.pendingDecisionCount).toBe(1);
    await store.reviewFinding("f1", "approved");
    expect(store.findings["language.rhetoric"].observations[0].status).toBe("approved");
    expect(store.pendingDecisionCount).toBe(0);
  });
});

describe("referenceLearning store — applyProfile 后载入 bindings", () => {
  it("场景生成默认启用 MIXED 与量化锚点", () => {
    const store = useReferenceLearningStore();
    expect(store.applyDraft.strategy).toBe("mixed");
    expect(store.applyDraft.include_metric).toBe(true);
  });

  it("applyProfile 调 applyStyleReferenceProfile + loadBindings", async () => {
    api.applyStyleReferenceProfile.mockResolvedValue({
      profile_id: "p1",
      binding_id: "sr_bind_1",
      review_ids: ["review_style_ref_apply_x"],
    });
    api.listStyleReferenceBindings.mockResolvedValue({
      bindings: [{ binding_id: "sr_bind_1", profile_id: "p1", scope: "project", status: "active" }],
    });
    const store = useReferenceLearningStore();
    store.currentProfile = { profile_id: "p1" };
    store.applyDraft = {
      scope: "project",
      scope_ref_id: "",
      task_type: "scene_generation",
      strategy: "mixed",
      intensity: 80,
      sub_dimensions: ["language.punctuation"],
      include_positive: true,
      include_forbidden: true,
      include_metric: true,
    };
    await store.applyProfile("p1");
    expect(api.applyStyleReferenceProfile).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({
        scope: "project",
        taskType: "scene_generation",
        strategy: "mixed",
        intensity: 80,
        subDimensions: ["language.punctuation"],
        includeMetric: true,
      }),
    );
    expect(store.bindings).toHaveLength(1);
  });
});
