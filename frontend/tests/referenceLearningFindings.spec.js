// @vitest-environment jsdom
//
// PR-12 — ReferenceLearningView findings 区 ProgressiveList 虚拟化。

import { createApp, h, nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

vi.mock("../src/lib/api/styleReference", () => ({
  listStyleReferenceBooks: vi.fn().mockResolvedValue({ books: [] }),
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
  listStyleReferenceProfiles: vi.fn().mockResolvedValue({ profiles: [] }),
  fetchStyleReferenceProfile: vi.fn(),
  previewStyleReferenceProfile: vi.fn(),
  applyStyleReferenceProfile: vi.fn(),
  listStyleReferenceBindings: vi.fn(),
  deleteStyleReferenceBinding: vi.fn(),
}));

const FAKE_VIEW_META = {
  id: "reference", label: "风格参考", stepLabel: "学习风格", description: "...",
  stage: "inform", icon: "GraduationCap", nextViews: [], writerGoal: "x",
  writerDoneSignal: "y", writerLabel: "学风格", writerMotivation: "z",
};

vi.mock("../src/router", () => ({
  useShellRouter: () => ({
    navigate: vi.fn(),
    activeViewId: { value: "reference" },
    viewMeta: (viewId) => (viewId === "reference" ? FAKE_VIEW_META : { id: viewId, label: viewId, stepLabel: viewId, stage: "inform", nextViews: [] }),
  }),
  workflowGroups: [{ id: "inform", label: "Inform", stepLabel: "了解" }],
  viewMeta: (viewId) => (viewId === "reference" ? FAKE_VIEW_META : { id: viewId, label: viewId, stepLabel: viewId, stage: "inform", nextViews: [] }),
}));

import ReferenceLearningView from "../src/views/ReferenceLearningView.vue";
import { useReferenceLearningStore } from "../src/stores/referenceLearning";

let activeApp = null;

function createAnimationFrameController() {
  let queue = [];
  let nextId = 1;
  return {
    request(callback) {
      const id = nextId++;
      queue.push({ id, callback });
      return id;
    },
    cancel(id) {
      queue = queue.filter((e) => e.id !== id);
    },
    async flushAll() {
      while (queue.length) {
        const current = queue;
        queue = [];
        current.forEach((e) => e.callback(0));
        await nextTick();
      }
    },
  };
}

function makeFinding(i, kind = "observation") {
  return {
    finding_id: `sr_find_${kind}_${i}`,
    finding_kind: kind,
    statement: `${kind} statement ${i}`,
    confidence: "medium",
    status: "pending",
    sub_dimension: "language.vocabulary",
  };
}

function emptyBuckets() {
  return {
    "language.sentence_structure": { observations: [], forbidden_patterns: [] },
    "language.vocabulary": { observations: [], forbidden_patterns: [] },
  };
}

async function mountWithFindings(bucketOverride) {
  if (activeApp) activeApp.unmount();
  const pinia = createPinia();
  setActivePinia(pinia);
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(ReferenceLearningView) });
  app.use(pinia);
  app.mount(el);
  activeApp = app;
  await nextTick();

  const store = useReferenceLearningStore();
  store.currentBook = {
    book_id: "sr_book_1", title: "测试书", author_label: "x", total_chars: 5000,
    status: "ready", cloud_policy: "local_only", stats_json: {},
  };
  store.selectedBookId = "sr_book_1";
  store.currentRun = { run_id: "sr_run_xxxxxxxxxxxx", status: "done", coverage_json: {} };
  store.findings = { ...emptyBuckets(), ...bucketOverride };
  await nextTick();
  await nextTick();
  return { el, store };
}

let animationFrames;

beforeEach(() => {
  animationFrames = createAnimationFrameController();
  vi.stubGlobal("requestAnimationFrame", vi.fn((cb) => animationFrames.request(cb)));
  vi.stubGlobal("cancelAnimationFrame", vi.fn((id) => animationFrames.cancel(id)));
  setActivePinia(createPinia());
});

afterEach(() => {
  if (activeApp) { activeApp.unmount(); activeApp = null; }
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("ReferenceLearningView findings 虚拟化", () => {
  it("小数据集(<12)首帧全渲染,不启用渐进", async () => {
    const observations = Array.from({ length: 5 }, (_, i) => makeFinding(i));
    const { el } = await mountWithFindings({
      "language.vocabulary": { observations, forbidden_patterns: [] },
    });
    // ProgressiveList threshold=12,5 < 12 → 直接全渲染
    const cards = el.querySelectorAll('article[data-testid^="reference-finding-"]');
    expect(cards.length).toBe(5);
  });

  it("大数据集(>12)首帧只渲染 initial-count,rAF flush 后补全", async () => {
    const observations = Array.from({ length: 15 }, (_, i) => makeFinding(i));
    const { el } = await mountWithFindings({
      "language.vocabulary": { observations, forbidden_patterns: [] },
    });
    // 首帧 initial-count=8
    const firstFrame = el.querySelectorAll('article[data-testid^="reference-finding-"]');
    expect(firstFrame.length).toBe(8);
    // flush rAF → 全部 15 个补全
    await animationFrames.flushAll();
    const allRendered = el.querySelectorAll('article[data-testid^="reference-finding-"]');
    expect(allRendered.length).toBe(15);
  });

  it("observations 在 forbidden_patterns 之前(合并顺序)", async () => {
    const observations = [makeFinding(0, "observation"), makeFinding(1, "observation")];
    const forbidden = [makeFinding(0, "forbidden_pattern"), makeFinding(1, "forbidden_pattern")];
    const { el } = await mountWithFindings({
      "language.vocabulary": { observations, forbidden_patterns: forbidden },
    });
    const cards = [...el.querySelectorAll('article[data-testid^="reference-finding-"]')];
    expect(cards.length).toBe(4);
    // 前 2 个 testid 应是 observation
    expect(cards[0].getAttribute("data-testid")).toContain("observation");
    expect(cards[1].getAttribute("data-testid")).toContain("observation");
    expect(cards[2].getAttribute("data-testid")).toContain("forbidden_pattern");
    expect(cards[3].getAttribute("data-testid")).toContain("forbidden_pattern");
  });

  it("FindingCard 的 approve/reject testid 透传到 DOM", async () => {
    const observations = [makeFinding(0)];
    const { el } = await mountWithFindings({
      "language.vocabulary": { observations, forbidden_patterns: [] },
    });
    expect(el.querySelector('[data-testid="reference-finding-sr_find_observation_0"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="reference-approve-sr_find_observation_0"]')).not.toBeNull();
    expect(el.querySelector('[data-testid="reference-reject-sr_find_observation_0"]')).not.toBeNull();
  });
});
