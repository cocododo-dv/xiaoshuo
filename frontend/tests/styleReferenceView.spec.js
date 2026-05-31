// @vitest-environment jsdom
//
// PR-5 — ReferenceLearningView 关键渲染路径(渲染骨架 + store mock)。

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
  id: "reference",
  label: "风格参考",
  stepLabel: "学习风格",
  description: "...",
  stage: "inform",
  icon: "GraduationCap",
  nextViews: [],
  writerGoal: "x",
  writerDoneSignal: "y",
  writerLabel: "学风格",
  writerMotivation: "z",
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

function mount() {
  if (activeApp) activeApp.unmount();
  const pinia = createPinia();
  setActivePinia(pinia);
  const el = document.createElement("div");
  document.body.appendChild(el);
  const app = createApp({ render: () => h(ReferenceLearningView) });
  app.use(pinia);
  app.mount(el);
  activeApp = app;
  return el;
}

beforeEach(() => {
  setActivePinia(createPinia());
});

afterEach(() => {
  if (activeApp) {
    activeApp.unmount();
    activeApp = null;
  }
  vi.restoreAllMocks();
});

describe("ReferenceLearningView", () => {
  it("初始渲染:WorkflowPageHeader + 导入卡 + 空 books 列表", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const el = mount();
    await nextTick();
    await nextTick();
    expect(el.querySelector(".style-reference-view")).not.toBeNull();
    expect(el.querySelector(".import-card")).not.toBeNull();
    expect(el.querySelector(".books-list-card")).not.toBeNull();
    // 主区右侧应显示"尚未选择参考书" empty state
    expect(el.querySelector(".main-side .base-empty")).not.toBeNull();
    expect(warn).not.toHaveBeenCalledWith(expect.stringContaining("Invalid prop"));
  });

  it("import-tabs 默认选中 path,可切换 upload", async () => {
    const el = mount();
    await nextTick();
    const tabs = el.querySelectorAll(".import-tabs .tab");
    expect(tabs[0].classList.contains("tab-active")).toBe(true);
    tabs[1].click();
    await nextTick();
    expect(tabs[1].classList.contains("tab-active")).toBe(true);
    // upload 表单含 file input
    const fileInput = el.querySelector('input[type="file"]');
    expect(fileInput).not.toBeNull();
  });

  it("当 store 有 currentBook 时,主区渲染 stats / 启动 run 按钮", async () => {
    const el = mount();
    await nextTick();
    const store = useReferenceLearningStore();
    store.currentBook = {
      book_id: "sr_book_1",
      title: "测试书",
      author_label: "测试",
      total_chars: 5000,
      status: "ready",
      cloud_policy: "local_only",
      stats_json: { input_assessment: { language: "low" } },
    };
    store.selectedBookId = "sr_book_1";
    await nextTick();
    expect(el.querySelector(".book-stats-head")).not.toBeNull();
    // 启动 run 按钮(在 empty-run section)
    const emptyRun = el.querySelector(".empty-run");
    expect(emptyRun).not.toBeNull();
    expect(emptyRun.textContent).toContain("启动抽取");
  });
});
