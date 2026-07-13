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
import * as styleReferenceApi from "../src/lib/api/styleReference";
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

  it.each(["path", "upload"])(
    "%s 非本地导入必须明确确认发送权",
    async (mode) => {
      const el = mount();
      await nextTick();
      await nextTick();
      if (mode === "upload") {
        el.querySelector('[data-testid="reference-import-toggle-upload"]').click();
        await nextTick();
      }

      const form = el.querySelector(".import-card .form");
      const policy = form.querySelector("select");
      const submit = form.querySelector(".base-btn");
      expect(form.querySelector('[data-testid="reference-import-rights"]')).toBeNull();
      expect(submit.disabled).toBe(false);

      policy.value = "segments_only";
      policy.dispatchEvent(new Event("change", { bubbles: true }));
      await nextTick();

      const rights = form.querySelector('[data-testid="reference-import-rights"]');
      expect(rights).not.toBeNull();
      expect(rights.checked).toBe(false);
      expect(submit.disabled).toBe(true);

      rights.click();
      await nextTick();
      expect(submit.disabled).toBe(false);

      policy.value = "local_only";
      policy.dispatchEvent(new Event("change", { bubbles: true }));
      await nextTick();
      expect(form.querySelector('[data-testid="reference-import-rights"]')).toBeNull();
    },
  );

  it("非布尔发送权不能使非本地导入就绪", () => {
    const store = useReferenceLearningStore();
    store.pathDraft.cloud_policy = "segments_only";
    store.pathDraft.rights_declaration.send_rights = "false";
    store.uploadDraft.cloud_policy = "allow_full_cloud";
    store.uploadDraft.rights_declaration.send_rights = 1;

    expect(store.pathImportRightsReady).toBe(false);
    expect(store.uploadImportRightsReady).toBe(false);
  });

  it("store 对 path/upload 透传相同声明，本地策略传 null", async () => {
    vi.clearAllMocks();
    const store = useReferenceLearningStore();
    const rightsDeclaration = {
      analysis_rights: true,
      send_rights: true,
      declared_by: "测试用户",
    };

    store.pathDraft = {
      file_path: "cloud-path.txt",
      title: "path",
      author_label: "author",
      cloud_policy: "segments_only",
      rights_declaration: { ...rightsDeclaration },
    };
    await store.importPath();
    expect(styleReferenceApi.importStyleReferenceBookPath).toHaveBeenLastCalledWith({
      file_path: "cloud-path.txt",
      title: "path",
      author_label: "author",
      cloud_policy: "segments_only",
      rights_declaration: rightsDeclaration,
    });

    const cloudFile = new File(["cloud"], "cloud.txt", { type: "text/plain" });
    store.uploadDraft = {
      file: cloudFile,
      title: "upload",
      author_label: "author",
      cloud_policy: "allow_full_cloud",
      rights_declaration: { ...rightsDeclaration },
    };
    await store.importUpload();
    expect(styleReferenceApi.importStyleReferenceBookUpload).toHaveBeenLastCalledWith({
      file: cloudFile,
      title: "upload",
      authorLabel: "author",
      cloudPolicy: "allow_full_cloud",
      rightsDeclaration,
    });

    store.pathDraft.file_path = "local-path.txt";
    await store.importPath();
    expect(styleReferenceApi.importStyleReferenceBookPath).toHaveBeenLastCalledWith(
      expect.objectContaining({ cloud_policy: "local_only", rights_declaration: null }),
    );

    const localFile = new File(["local"], "local.txt", { type: "text/plain" });
    store.uploadDraft.file = localFile;
    await store.importUpload();
    expect(styleReferenceApi.importStyleReferenceBookUpload).toHaveBeenLastCalledWith(
      expect.objectContaining({ cloudPolicy: "local_only", rightsDeclaration: null }),
    );
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
